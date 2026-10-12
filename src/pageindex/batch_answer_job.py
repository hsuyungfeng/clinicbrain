"""
Taiwan Clinic Medical PageIndex RAG System - 待審草稿「批次補齊答案」背景作業
Phase 21: 先讓本機 LLM 批次補齊答案，最後再由醫師一起審核。

- 伺服器背景執行緒逐題處理（單題 1～3 分鐘，不能綁在一個 HTTP 請求上）；同時只允許一個作業。
- 每題各自開連線、各自 commit：作業中斷或服務重啟時，已完成的題目不會遺失。
- 每題的合規把關完全沿用 generate_answer_for_faq（價格屏蔽／四層／劑量／就醫警訊），
  生成結果一律 pending，絕不核准任何項目。
- 本機 LLM 離線時整批中止（不空轉剩餘題目）；使用者可隨時取消，取消在題目之間生效。
"""

import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .answer_generator import GenerationError, generate_answer_for_faq, is_answer_thin
from .faq_review import REVIEW_GATED_SOURCES
from ..batch import db_lock

MAX_JOB_IDS = 100

_state_lock = threading.Lock()
_state: Optional[dict] = None
_cancel = threading.Event()
_thread: Optional[threading.Thread] = None
_db_lock_fd: Optional[int] = None   # 持有夜間批次共用的跨行程鎖（作業期間）


def get_pending_unanswered_ids(
    conn: sqlite3.Connection,
    clinic_id: Optional[str] = None,
    limit: int = 100,
) -> list[int]:
    """待補齊答案的待審草稿 ID（依 id 升冪，最多 limit 筆）。

    判斷標準與 Web 介面「⚠️ 答案待補齊」完全相同（answer_generator.is_answer_thin 為唯一來源）：
    review_status='pending'、來源為審核閘門來源，且 is_answer_thin 為真
    （答案過短，或佔位題下僅為問題清單／小標題）。已核准、已駁回與手寫來源一律排除。
    """
    where_clauses = [
        "review_status = 'pending'",
        "source_type IN (" + ", ".join(f"'{s}'" for s in REVIEW_GATED_SOURCES) + ")",
    ]
    params: list = []
    if clinic_id and str(clinic_id).strip():
        where_clauses.append("clinic_id = ?")
        params.append(str(clinic_id).strip())
    cur = conn.cursor()
    cur.execute(
        f"SELECT id, question, answer FROM faq_cache WHERE {' AND '.join(where_clauses)} ORDER BY id ASC",
        tuple(params),
    )
    out: list[int] = []
    for fid, question, answer in cur.fetchall():
        if is_answer_thin(question or "", answer or ""):
            out.append(fid)
            if len(out) >= int(limit):
                break
    return out


def _fresh(ids: list[int]) -> dict:
    return {
        "state": "running", "total": len(ids), "processed": 0, "ok": 0, "skipped": 0,
        "failed": [], "ok_ids": [], "current_id": None,
        "started_at": time.time(), "finished_at": None, "message": "",
    }


def snapshot() -> dict:
    with _state_lock:
        if _state is None:
            return {"state": "idle"}
        snap = dict(_state)
        snap["failed"] = list(_state["failed"])
        snap["ok_ids"] = list(_state["ok_ids"])
        return snap


def is_running() -> bool:
    with _state_lock:
        return _state is not None and _state["state"] == "running"


def cancel() -> bool:
    with _state_lock:
        running = _state is not None and _state["state"] == "running"
    if running:
        _cancel.set()
    return running


def _record(**kw) -> None:
    with _state_lock:
        if _state is not None:
            _state.update(kw)


def _worker(db_path: str, ids: list[int], llm_call, grounded_call, gen_lock: threading.Lock) -> None:
    from .llm_client import LocalLLMUnavailableError

    global _db_lock_fd
    try:
        _run_items(db_path, ids, llm_call, grounded_call, gen_lock)
    finally:
        with _state_lock:
            fd, _db_lock_fd = _db_lock_fd, None
        db_lock.release(fd)


def _run_items(db_path: str, ids: list[int], llm_call, grounded_call, gen_lock: threading.Lock) -> None:
    from .llm_client import LocalLLMUnavailableError

    final = "done"
    for fid in ids:
        if _cancel.is_set():
            final = "cancelled"
            break
        # 與單題生成／提問共用本機模型鎖；等待期間仍可被取消
        while not gen_lock.acquire(timeout=2):
            if _cancel.is_set():
                break
        else:
            conn = None
            try:
                _record(current_id=fid)
                conn = sqlite3.connect(db_path, timeout=30)
                conn.execute("PRAGMA foreign_keys = ON;")
                generate_answer_for_faq(conn, fid, llm_call, grounded_llm_call=grounded_call)
                with _state_lock:
                    _state["ok"] += 1
                    _state["ok_ids"].append(fid)
            except GenerationError as e:
                with _state_lock:
                    if e.skippable:                # 已完整／已核准／非待審來源：不是錯誤，視為略過
                        _state["skipped"] += 1
                    else:
                        _state["failed"].append({"id": fid, "reason": str(e)})
            except LocalLLMUnavailableError:
                with _state_lock:
                    _state["failed"].append({"id": fid, "reason": "本機 LLM 無法使用"})
                final = "aborted"
            except Exception as e:             # 單題的非預期錯誤不拖垮整批
                with _state_lock:
                    _state["failed"].append({"id": fid, "reason": f"非預期錯誤（{type(e).__name__}）"})
            finally:
                gen_lock.release()
                if conn is not None:
                    conn.close()
                with _state_lock:
                    _state["processed"] += 1
                    _state["current_id"] = None
            if final == "aborted":
                break
            continue
        final = "cancelled"   # 等鎖期間被取消
        break
    with _state_lock:
        _state["state"] = final
        _state["finished_at"] = time.time()
        if final == "aborted":
            _state["message"] = "本機 LLM 無法使用，已中止剩餘題目"


def start(db_path: str | Path, ids: list[int], llm_call: Callable[[str], str],
          grounded_call: Optional[Callable[[str], str]], gen_lock: threading.Lock) -> dict:
    """啟動背景作業；已有作業進行中時拋 RuntimeError。"""
    global _state, _thread, _db_lock_fd
    ids = list(dict.fromkeys(int(i) for i in ids))
    if not ids:
        raise ValueError("faq_ids 不可為空")
    if len(ids) > MAX_JOB_IDS:
        raise ValueError(f"單次最多 {MAX_JOB_IDS} 筆")
    with _state_lock:
        if _state is not None and _state["state"] == "running":
            raise RuntimeError("已有批次補齊作業進行中")
        # 上一作業已寫入最終狀態但尚未釋放鎖（收尾中）：拒絕，避免誤報為「資料庫被占用」
        if _db_lock_fd is not None:
            raise RuntimeError("上一批次補齊作業尚在收尾，請稍後再試")
        # 跨行程：夜間批次持鎖時拒絕啟動，避免兩個行程同時打本機 llama-server
        fd = db_lock.try_acquire(db_path)
        if fd is None:
            raise RuntimeError("夜間批次或其他作業正在使用資料庫，請稍後再試")
        _db_lock_fd = fd
        _cancel.clear()
        _state = _fresh(ids)
    try:
        _thread = threading.Thread(
            target=_worker, args=(str(db_path), ids, llm_call, grounded_call, gen_lock),
            name="batch-answer-job", daemon=True,
        )
        _thread.start()
    except Exception:
        with _state_lock:
            fd, _db_lock_fd = _db_lock_fd, None
            _state = None
        db_lock.release(fd)
        _thread = None
        raise
    return snapshot()


def wait(timeout: float = 30.0) -> None:
    """測試用：等待背景執行緒結束。"""
    t = _thread
    if t is not None and t.ident is not None:   # 尚未啟動的執行緒不可 join
        t.join(timeout)
