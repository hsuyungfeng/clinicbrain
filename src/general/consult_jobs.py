"""病人端非同步諮詢作業登錄與管理模組 (consult_jobs)。

設計原則（P28-ASYNC）：
1. 快速響應：非紅旗問句送出後立即取得不可預測的 job_id，由前端輪詢結果，避免長時間掛住 HTTP 連線。
2. 紅旗同步回傳：急重症問句於提交當下立即同步回傳就醫指示，不建立 job、不呼叫模型。
3. 嚴格隱私：作業狀態與結果存於記憶體，問句僅作為 worker 參數傳遞，絕不存入 registry、全域變數或日誌。
4. 限時限量：結果單次讀取即刪除，未讀取最長保留 5 分鐘 (RESULT_TTL_SECONDS = 300)；上限 MAX_JOBS = 20、MAX_RUNNING = 4。
5. 模型序列化：由 patient_consult 內的 GENERATION_LOCK 負責，registry 不以「同時僅一個 job」誤擋不需模型的快速路徑。
6. 唯讀輪詢：GET 輪詢端點純讀取記憶體 registry，絕不連線資料庫。
"""

from __future__ import annotations

import re
import secrets
import sqlite3
import threading
import time
from typing import Any, Callable, Optional

from src.api.routes.query import deep_mask_prices
from src.general.disclaimer import RED_FLAG_DISCLAIMER_TEXT, message_for_red_flag
from src.general.patient_clinic import resolve_patient_clinic
from src.general.patient_consult import (
    BOOKING_URL,
    BUSY_TEXT,
    LLM_DISCLAIMER,
    NO_DATA_TEXT,
    default_patient_compose_llm,
    default_patient_llm,
    patient_consult,
)
from src.general.red_flags import detect_red_flag

RESULT_TTL_SECONDS = 300
MAX_JOBS = 20
MAX_RUNNING = 4

_JOB_ID_REGEX = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_running_count: int = 0


def _now() -> float:
    """可由測試替換之時鐘來源（預設單調時鐘）。"""
    return time.monotonic()


def _sweep_expired_locked() -> int:
    """清理超過 TTL 之過期作業（呼叫端須持有 _lock）。"""
    now = _now()
    to_delete = [
        jid for jid, item in _jobs.items()
        if now - item.get("created_at", 0) > RESULT_TTL_SECONDS
    ]
    for jid in to_delete:
        del _jobs[jid]
    return len(to_delete)


def sweep_expired() -> int:
    """清理超過 TTL 之過期作業。"""
    with _lock:
        return _sweep_expired_locked()


def submit_job(
    db_path: str,
    query: str,
    patient_llm: Optional[Callable[[str], str]] = None,
    compose_llm: Optional[Callable[[str], str]] = None,
    configured_clinic_id: Optional[str] = None,
) -> dict[str, Any]:
    """提交諮詢問句至背景作業佇列。

    - 紅旗問句：立即同步回傳就醫指示，不建立 job。
    - 超過 worker 上限或 registry 上限：回傳 busy 結果，不排隊。
    - 正常情況：產生 cryptographically secure job_id，啟動背景 worker 處理。
    """
    # 1. 急重症紅旗問句：同步回傳，不建立 job、不呼叫模型
    rf = detect_red_flag(query)
    if rf is not None:
        return {
            "status": "red_flag",
            "message": message_for_red_flag(rf.level, rf.rule_id),
            "disclaimer": RED_FLAG_DISCLAIMER_TEXT,
            "label": None,
            "booking_url": BOOKING_URL,
        }

    global _running_count

    with _lock:
        _sweep_expired_locked()

        # 2. 檢查容量上限（worker 數達 4 或總 job 數達 20）
        if _running_count >= MAX_RUNNING or len(_jobs) >= MAX_JOBS:
            return {
                "status": "busy",
                "message": BUSY_TEXT,
                "disclaimer": LLM_DISCLAIMER,
                "label": None,
                "booking_url": BOOKING_URL,
            }

        job_id = secrets.token_urlsafe(16)
        _jobs[job_id] = {
            "state": "pending",
            "result": None,
            "created_at": _now(),
        }
        _running_count += 1

    # 3. 啟動背景執行緒（問句僅作參數傳遞，絕不進入 registry）
    worker_thread = threading.Thread(
        target=_worker,
        args=(job_id, db_path, query, patient_llm, compose_llm, configured_clinic_id),
        daemon=True,
    )
    worker_thread.start()

    return {"status": "pending", "job_id": job_id}


def _worker(
    job_id: str,
    db_path: str,
    query: str,
    patient_llm: Optional[Callable[[str], str]],
    compose_llm: Optional[Callable[[str], str]],
    configured_clinic_id: Optional[str] = None,
) -> None:
    """背景執行緒：連線資料庫並呼叫 patient_consult，結果寫入 registry。"""
    global _running_count
    res_dict: Optional[dict[str, Any]] = None

    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            act_patient_llm = patient_llm or default_patient_llm
            act_compose_llm = compose_llm or default_patient_compose_llm
            resolved_clinic = resolve_patient_clinic(conn, configured_clinic_id)
            res = patient_consult(
                conn,
                query,
                act_patient_llm,
                compose_llm_call=act_compose_llm,
                clinic_id=resolved_clinic,
            )
            raw_res = {
                "status": res.status,
                "message": res.message,
                "label": res.label,
                "disclaimer": res.disclaimer,
                "booking_url": res.booking_url,
            }
            res_dict = deep_mask_prices(raw_res)
        finally:
            conn.close()
    except Exception:
        res_dict = {
            "status": "no_match",
            "message": NO_DATA_TEXT,
            "disclaimer": LLM_DISCLAIMER,
            "label": None,
            "booking_url": BOOKING_URL,
        }
    finally:
        with _lock:
            if job_id in _jobs:
                _jobs[job_id]["state"] = "done"
                _jobs[job_id]["result"] = res_dict
            _running_count = max(0, _running_count - 1)


def get_job_result(job_id: str) -> Optional[dict[str, Any]]:
    """輪詢取得作業結果（純記憶體讀取，不連線資料庫）。

    - 格式不符、不存在或已過期：回傳 None。
    - pending：回傳 {"status": "pending"}。
    - done：回傳結果 dict 並自 registry 刪除（單次讀取即刪除）。
    """
    if not job_id or not _JOB_ID_REGEX.match(job_id):
        return None

    with _lock:
        _sweep_expired_locked()
        if job_id not in _jobs:
            return None

        entry = _jobs[job_id]
        if entry["state"] == "pending":
            return {"status": "pending"}

        res = entry.get("result")
        del _jobs[job_id]
        return res


def wait_idle(timeout: float = 10.0) -> bool:
    """測試輔助函式：等待所有背景 worker 執行完畢。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _lock:
            if _running_count == 0:
                return True
        time.sleep(0.02)
    return False


def reset_for_tests() -> None:
    """測試輔助函式：清空 registry 與計數。"""
    global _running_count
    with _lock:
        _jobs.clear()
        _running_count = 0


def snapshot() -> dict[str, Any]:
    """測試輔助函式：取得 registry 狀態快照（驗證不含問句原文）。"""
    with _lock:
        return {
            "total": len(_jobs),
            "running": _running_count,
            "jobs": {
                k: {"state": v["state"], "created_at": v.get("created_at")}
                for k, v in _jobs.items()
            },
        }
