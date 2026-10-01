"""
Taiwan Clinic Medical PageIndex RAG System - PageIndex 臨床推理樹夜間批次重建引擎 (tree_rebuild)
Phase 09 Nightly Batch Maintenance: Task 2

設計原則與審核取捨（見 AGENTS.md 2.2 與 Phase 09 Objective）：
1. 僅重建人工標記（needs_regeneration=1）之臨床推理樹，不自行推論過期時間。
2. 絕對保護醫師權威指令：to_upsert_row 會預設將 physician_notes 清為 None，本引擎在寫入前
   強制以既有列原值覆寫，寫入後立即進行逐欄位後置校驗；若偵測到不一致自動執行快照還原。
3. 快照保護：重建寫庫前必須落盤 JSON 快照檔，支援人工稽核與版本回滾。
4. 樹重建結果不走 review_status 閘門（人工標記已為明確意圖，且觸碰面最小化），以 source_type='llm_generated' 誠實標記。
"""

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Optional

from src.pageindex.db_writer import (
    CONTENT_FIELDS,
    set_needs_regeneration,
    upsert_trees,
)
from src.pageindex.llm_client import LocalLLMUnavailableError
from src.pageindex.prompt_template import (
    TreeValidationError,
    generate_tree,
    to_upsert_row,
)

PHYSICIAN_NOTE_FIELDS = (
    "pre_op_physician_notes",
    "procedure_physician_notes",
    "post_op_short_physician_notes",
    "maintenance_physician_notes",
)

TREE_TEXT_FIELDS = (
    "pre_op",
    "procedure",
    "post_op_short",
    "maintenance",
    "summary_text",
)

TREE_REASON_CODES = frozenset([
    "json_invalid",
    "missing_fields",
    "price_leak",
    "simplified",
    "forbidden",
    "political",
    "other",
    "not_found",
    "no_clinic_id",
    "snapshot_failed",
    "physician_notes_mismatch_restored",
    "physician_notes_restore_failed",
    "rebuild_error",
])


def classify_tree_error(message: str) -> str:
    """將 TreeValidationError 之錯誤訊息映射為固定代碼，防範原始字串洩漏至日誌。"""
    msg = message or ""
    if "不是合法 JSON" in msg or "json" in msg.lower():
        return "json_invalid"
    if "缺少必要欄位" in msg or "缺少" in msg:
        return "missing_fields"
    if "價格" in msg or "金額" in msg:
        return "price_leak"
    if "簡體" in msg:
        return "simplified"
    if "禁用詞彙" in msg or "保證" in msg:
        return "forbidden"
    if "政治立場" in msg:
        return "political"
    return "other"


@dataclass
class TreeRebuildResult:
    """單一臨床推理樹重建結果。"""
    doc_id: str
    status: str  # 'rebuilt' | 'unchanged' | 'skipped' | 'rejected' | 'error'
    reason: Optional[str] = None
    changed_fields: list[str] = field(default_factory=list)
    snapshot_path: Optional[str] = None
    previous_source_type: Optional[str] = None


def find_marked_trees(
    conn: sqlite3.Connection,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """查詢當前被標記為待重建 (needs_regeneration=1) 的樹清單。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT doc_id, clinic_id, category
        FROM page_index_trees
        WHERE needs_regeneration = 1
        ORDER BY updated_at ASC, id ASC
        LIMIT ?
        """,
        (limit,),
    )
    cols = ["doc_id", "clinic_id", "category"]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def rebuild_tree(
    conn: sqlite3.Connection,
    doc_id: str,
    procedure_name: str,
    llm_call: Callable[[str], str],
    snapshot_dir: Path,
) -> TreeRebuildResult:
    """
    針對指定 doc_id 之 PageIndex 樹進行批次重建。

    流程：
    1. 讀取並備份既有列之完整內容與 4 個 physician_notes。
    2. 呼叫 generate_tree 產生新版臨床推理樹並通過四層合規驗證。
    3. 將新版樹結構轉為 upsert 格式，並以備份值覆寫 4 個 physician_notes 欄位。
    4. 比對新舊內容，若內容一致則直接清除標記並回傳 'unchanged'。
    5. 建立 JSON 快照記錄舊與新之內容。
    6. 呼叫 upsert_trees 寫入資料庫（更新內容、source_type 改為 llm_generated、清空標記）。
    7. 重新讀取 physician_notes 進行一致性檢查；若有不符則自動執行快照還原。
    """
    if snapshot_dir is None:
        raise ValueError("snapshot_dir 為必填參數，不得為 None")

    cur = conn.cursor()
    fields_to_select = ["clinic_id", "category", "source_type"] + list(CONTENT_FIELDS)
    cur.execute(
        f"SELECT {', '.join(fields_to_select)} FROM page_index_trees WHERE doc_id = ?",
        (doc_id,),
    )
    row = cur.fetchone()
    if not row:
        return TreeRebuildResult(doc_id=doc_id, status="skipped", reason="not_found")

    existing_row = dict(zip(fields_to_select, row))
    existing_clinic_id = existing_row["clinic_id"]
    existing_category = existing_row["category"]
    prev_source_type = existing_row["source_type"]

    if not existing_clinic_id:
        return TreeRebuildResult(
            doc_id=doc_id,
            status="skipped",
            reason="no_clinic_id",
            previous_source_type=prev_source_type,
        )

    # 1. 呼叫生成引擎
    try:
        generated_tree = generate_tree(procedure_name, llm_call)
    except TreeValidationError as e:
        return TreeRebuildResult(
            doc_id=doc_id,
            status="rejected",
            reason=classify_tree_error(str(e)),
            previous_source_type=prev_source_type,
        )
    except LocalLLMUnavailableError:
        raise
    except Exception:
        return TreeRebuildResult(
            doc_id=doc_id,
            status="error",
            reason="rebuild_error",
            previous_source_type=prev_source_type,
        )

    # 2. 轉換為 upsert 列並強制保留 physician_notes 原始指令
    upsert_row = to_upsert_row(
        doc_id=doc_id,
        clinic_id=existing_clinic_id,
        category=existing_category,
        tree=generated_tree,
    )
    # 重要保護：to_upsert_row 預設將 physician_notes 清為 None，必須以既有列原值覆寫
    for field_name in PHYSICIAN_NOTE_FIELDS:
        upsert_row[field_name] = existing_row[field_name]

    # 3. 檢查內容是否確實變更
    changed_fields = [
        f for f in TREE_TEXT_FIELDS
        if existing_row.get(f) != upsert_row.get(f)
    ]
    if not changed_fields:
        set_needs_regeneration(conn, [doc_id], False)
        return TreeRebuildResult(
            doc_id=doc_id,
            status="unchanged",
            previous_source_type=prev_source_type,
        )

    # 4. 落盤快照檔案
    try:
        snap_path_obj = Path(snapshot_dir)
        if snap_path_obj.is_file():
            return TreeRebuildResult(
                doc_id=doc_id,
                status="error",
                reason="snapshot_failed",
                previous_source_type=prev_source_type,
            )
        snap_path_obj.mkdir(parents=True, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d-%H%M%S")
        snap_file = snap_path_obj / f"{doc_id}-{timestamp_str}.json"
        snapshot_content = {
            "doc_id": doc_id,
            "created_at": datetime.now().isoformat(),
            "old": {f: existing_row[f] for f in (TREE_TEXT_FIELDS + PHYSICIAN_NOTE_FIELDS)},
            "new": {f: upsert_row[f] for f in TREE_TEXT_FIELDS},
        }
        snap_file.write_text(json.dumps(snapshot_content, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshot_path_str = str(snap_file)
    except Exception:
        return TreeRebuildResult(
            doc_id=doc_id,
            status="error",
            reason="snapshot_failed",
            previous_source_type=prev_source_type,
        )

    # 5. 寫入資料庫
    upsert_trees(conn, [upsert_row], source_type="llm_generated")

    # 6. 後置校驗 physician_notes 欄位完整性
    cur.execute(
        f"SELECT {', '.join(PHYSICIAN_NOTE_FIELDS)} FROM page_index_trees WHERE doc_id = ?",
        (doc_id,),
    )
    notes_after = cur.fetchone()
    notes_before = tuple(existing_row[f] for f in PHYSICIAN_NOTE_FIELDS)

    if notes_after != notes_before:
        # 異常損壞，啟動自動還原機制
        restore_row = {
            "doc_id": doc_id,
            "clinic_id": existing_clinic_id,
            **{f: existing_row[f] for f in CONTENT_FIELDS},
        }
        upsert_trees(conn, [restore_row], source_type=prev_source_type)

        cur.execute(
            f"SELECT {', '.join(PHYSICIAN_NOTE_FIELDS)} FROM page_index_trees WHERE doc_id = ?",
            (doc_id,),
        )
        notes_restored = cur.fetchone()
        if notes_restored == notes_before:
            return TreeRebuildResult(
                doc_id=doc_id,
                status="error",
                reason="physician_notes_mismatch_restored",
                snapshot_path=snapshot_path_str,
                previous_source_type=prev_source_type,
            )
        else:
            return TreeRebuildResult(
                doc_id=doc_id,
                status="error",
                reason="physician_notes_restore_failed",
                snapshot_path=snapshot_path_str,
                previous_source_type=prev_source_type,
            )

    return TreeRebuildResult(
        doc_id=doc_id,
        status="rebuilt",
        changed_fields=changed_fields,
        snapshot_path=snapshot_path_str,
        previous_source_type=prev_source_type,
    )
