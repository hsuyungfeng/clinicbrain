"""
Taiwan Clinic Medical PageIndex RAG System - FAQ 審核管理模組 (faq_review)
Phase 09 Nightly Batch & Physician Review Gate: Task 2
Phase 12 General Content Generation: DEBT-03 (人工標記重生成與審核增強)

功能：
- 唯一權威的審核狀態寫入介面 (set_review_status)
- 審核前執行多層醫療合規驗證（價格、簡體字、政治立場、保證療效、用藥劑量與就醫警訊）
- 可見性改變時自動遞增 content_version 並刷新 updated_at，確保同步契約正確匯出
- 提供檢索端共用的可見性查詢片段 visible_faq_sql
- 人工重生成標記入口 (mark_for_regeneration)，旗標清除由 faq_writer（內容變更）與 clear_regeneration_flag
"""

from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any, Optional

REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"
REVIEW_STATUSES = frozenset([REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED])


@dataclass
class ReviewResult:
    """審核操作回傳結果。"""
    changed: list[int] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)


def has_review_status(conn: sqlite3.Connection) -> bool:
    """檢查 faq_cache 資料表是否已具備 review_status 與 reviewed_at 兩欄。"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(faq_cache)")
    cols = {row[1] for row in cur.fetchall()}
    return ("review_status" in cols) and ("reviewed_at" in cols)


def has_metadata_column(conn: sqlite3.Connection) -> bool:
    """檢查 faq_cache 是否有 metadata 欄位。"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(faq_cache)")
    cols = {row[1] for row in cur.fetchall()}
    return "metadata" in cols


# 受審核閘門控管的來源：未經醫師核准（review_status='approved'）前對外完全隱蔽。
# web_upload = 診所人員經 Web 管理介面上傳文件擷取之草稿（Phase 18）。
# 注意：sync 匯入與 CLI 擷取使用的 clinic_upload 視為院所權威來源，恆為可見。
REVIEW_GATED_SOURCES = ("llm_generated", "soap_distilled", "web_upload")
_GATED_SQL_LIST = ", ".join(f"'{s}'" for s in REVIEW_GATED_SOURCES)


def visible_faq_sql(conn: sqlite3.Connection) -> str:
    """產生供 faq_cache 查詢 WHERE 子句共用的可見性 SQL 片段。"""
    if has_review_status(conn):
        return f"(source_type IS NULL OR source_type NOT IN ({_GATED_SQL_LIST}) OR review_status = 'approved')"
    return f"(source_type IS NULL OR source_type NOT IN ({_GATED_SQL_LIST}))"


def count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    """統計各 review_status 的資料筆數。若未遷移則回傳空字典。"""
    if not has_review_status(conn):
        return {}
    cur = conn.cursor()
    cur.execute("SELECT review_status, COUNT(*) FROM faq_cache GROUP BY review_status")
    return dict(cur.fetchall())


def list_faqs(
    conn: sqlite3.Connection,
    status: str = REVIEW_PENDING,
    limit: int = 50,
    offset: int = 0,
    *,
    topic_key: Optional[str] = None,
    source_type: Optional[str] = None,
    category: Optional[str] = None,
) -> list[dict[str, Any]]:
    """列出指定審核狀態的 FAQ 列表（依 id 升冪排列）。可選 topic_key, source_type, category 篩選。"""
    if not has_review_status(conn):
        return []
    cur = conn.cursor()
    where_clauses = ["review_status = ?"]
    params: list[Any] = [status]
    if source_type is not None:
        where_clauses.append("source_type = ?")
        params.append(source_type)
    else:
        where_clauses.append(f"source_type IN ({_GATED_SQL_LIST})")

    if topic_key is not None:
        where_clauses.append("topic_key = ?")
        params.append(topic_key)

    if category is not None:
        where_clauses.append("category = ?")
        params.append(category)

    where_sql = " AND ".join(where_clauses)
    params.extend([limit, offset])

    has_meta = has_metadata_column(conn)
    select_meta = ", metadata" if has_meta else ""
    columns = [
        "id", "clinic_id", "topic_key", "question", "answer", "category",
        "source_type", "content_version", "needs_regeneration",
        "review_status", "reviewed_at", "created_at", "updated_at",
    ]
    if has_meta:
        columns.append("metadata")

    cur.execute(
        f"""
        SELECT id, clinic_id, topic_key, question, answer, category,
               source_type, content_version, needs_regeneration,
               review_status, reviewed_at, created_at, updated_at{select_meta}
        FROM faq_cache
        WHERE {where_sql}
        ORDER BY id ASC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    )
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def validation_report(faq: dict[str, Any]) -> dict[str, Any]:
    """
    對指定 FAQ 執行多層醫療合規驗證並回傳報告字典。
    回傳格式: {"ok": bool, "reason": Optional[str]}
    旗標: check_dosage=True, require_doctor_warning=(category == 'general')
    """
    from src.ingestion.generate_faq import validate_single_faq

    category = faq.get("category")
    is_valid, reason = validate_single_faq(
        {"question": faq.get("question", ""), "answer": faq.get("answer", "")},
        check_dosage=True,
        require_doctor_warning=(category == "general"),
    )
    return {"ok": is_valid, "reason": reason if not is_valid else None}


def get_faq(conn: sqlite3.Connection, faq_id: int) -> Optional[dict[str, Any]]:
    """取得指定 ID 之 FAQ 詳細資訊。"""
    has_review = has_review_status(conn)
    has_meta = has_metadata_column(conn)
    cur = conn.cursor()
    select_meta = ", metadata" if has_meta else ""

    if has_review:
        columns = [
            "id", "clinic_id", "topic_key", "question", "answer", "category",
            "source_type", "content_version", "needs_regeneration",
            "review_status", "reviewed_at", "created_at", "updated_at",
        ]
        if has_meta:
            columns.append("metadata")
        cur.execute(
            f"""
            SELECT id, clinic_id, topic_key, question, answer, category,
                   source_type, content_version, needs_regeneration,
                   review_status, reviewed_at, created_at, updated_at{select_meta}
            FROM faq_cache
            WHERE id = ?
            """,
            (faq_id,),
        )
    else:
        columns = [
            "id", "clinic_id", "topic_key", "question", "answer", "category",
            "source_type", "content_version", "needs_regeneration",
            "created_at", "updated_at",
        ]
        if has_meta:
            columns.append("metadata")
        cur.execute(
            f"""
            SELECT id, clinic_id, topic_key, question, answer, category,
                   source_type, content_version, needs_regeneration,
                   created_at, updated_at{select_meta}
            FROM faq_cache
            WHERE id = ?
            """,
            (faq_id,),
        )
    row = cur.fetchone()
    return dict(zip(columns, row)) if row else None


def mark_for_regeneration(
    conn: sqlite3.Connection,
    faq_ids: list[int],
    seed_questions: Optional[set[tuple[Optional[str], str, str]]] = None,
) -> ReviewResult:
    """
    手動標記指定被駁回之 LLM 生成 FAQ 為待重新生成 (needs_regeneration = 1)。

    規則：
    - 未遷移審核欄位時拋出 RuntimeError
    - 僅允許標記 source_type='llm_generated' 且 review_status='rejected' 的列
    - 若已經被標記 (needs_regeneration == 1)，回報 skipped ('already_marked')
    - 標記操作不變更 content_version，亦不變更 review_status
    - 若提供 seed_questions（(clinic_id, topic_key, question) 集合，來自人寫種子清單），
      不在其中的列回報 skipped ('not_in_seed')：夜間批次只重生成種子內題目，種子外的旗標會永遠殘留
    """
    if not has_review_status(conn):
        raise RuntimeError(
            "資料庫尚未建立審核欄位，請先執行 scripts/migrate_faq_review_status.py 遷移腳本！"
        )

    changed: list[int] = []
    skipped: list[tuple[int, str]] = []

    cur = conn.cursor()
    for faq_id in faq_ids:
        cur.execute(
            """
            SELECT id, source_type, review_status, needs_regeneration,
                   clinic_id, topic_key, question
            FROM faq_cache
            WHERE id = ?
            """,
            (faq_id,),
        )
        row = cur.fetchone()
        if row is None:
            skipped.append((faq_id, "not_found"))
            continue

        _, src_type, status, needs_reg, row_clinic, row_topic, row_question = row
        if src_type != "llm_generated":
            skipped.append((faq_id, "not_llm_generated"))
            continue

        if status != REVIEW_REJECTED:
            skipped.append((faq_id, "not_rejected"))
            continue

        if needs_reg == 1:
            skipped.append((faq_id, "already_marked"))
            continue

        if seed_questions is not None and (row_clinic, row_topic, (row_question or "").strip()) not in seed_questions:
            skipped.append((faq_id, "not_in_seed"))
            continue

        cur.execute(
            "UPDATE faq_cache SET needs_regeneration = 1 WHERE id = ?",
            (faq_id,),
        )
        changed.append(faq_id)

    conn.commit()
    return ReviewResult(changed=changed, skipped=skipped)


def clear_regeneration_flag(
    conn: sqlite3.Connection,
    faq_ids: list[int],
) -> int:
    """
    清除指定 FAQ 之重新生成旗標 (needs_regeneration = 0)。
    僅對 source_type='llm_generated' AND review_status='rejected' AND needs_regeneration=1 之列生效。
    回傳實際清除旗標之筆數。
    """
    if not has_review_status(conn) or not faq_ids:
        return 0

    placeholders = ",".join("?" for _ in faq_ids)
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE faq_cache
        SET needs_regeneration = 0
        WHERE id IN ({placeholders})
          AND source_type = 'llm_generated'
          AND review_status = 'rejected'
          AND needs_regeneration = 1
        """,
        faq_ids,
    )
    affected = cur.rowcount
    conn.commit()
    return affected


def regen_marked_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    查詢目前所有被標記重生成且處於 rejected 之 LLM 生成 FAQ 列表。
    若資料庫尚未建立審核欄位則回傳空列表。
    """
    if not has_review_status(conn):
        return []

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, clinic_id, topic_key, question
        FROM faq_cache
        WHERE source_type = 'llm_generated'
          AND review_status = 'rejected'
          AND needs_regeneration = 1
        ORDER BY id ASC
        """
    )
    return [
        {"id": row[0], "clinic_id": row[1], "topic_key": row[2], "question": row[3]}
        for row in cur.fetchall()
    ]


def set_review_status(
    conn: sqlite3.Connection,
    faq_ids: list[int],
    new_status: str,
    *,
    enforce_general_warning: bool = False,
) -> ReviewResult:
    """
    修改指定 FAQ 之審核狀態。
    本函式為 faq_cache.review_status 之唯一寫入途徑。

    規則：
    - new_status 必須屬於 REVIEW_STATUSES
    - 僅允許審核 source_type='llm_generated' 的記錄（手寫與診所上傳恆為可見）
    - 核准前重跑醫療合規驗證（含價格、簡體字、政治立場、保證療效、用藥劑量與可選的 general 就醫警訊檢查），違規者拒絕核准
    - 當可見性改變時（approved 與非 approved 之間轉換），遞增 content_version 並更新 updated_at
    """
    if new_status not in REVIEW_STATUSES:
        raise ValueError(
            f"無效的審核狀態: '{new_status}'，合法值為 {sorted(REVIEW_STATUSES)}"
        )

    if not has_review_status(conn):
        raise RuntimeError(
            "資料庫尚未建立審核欄位，請先執行 scripts/migrate_faq_review_status.py 遷移腳本！"
        )

    changed: list[int] = []
    skipped: list[tuple[int, str]] = []

    cur = conn.cursor()
    for faq_id in faq_ids:
        cur.execute(
            """
            SELECT id, source_type, review_status, question, answer, content_version, category
            FROM faq_cache
            WHERE id = ?
            """,
            (faq_id,),
        )
        row = cur.fetchone()
        if row is None:
            skipped.append((faq_id, "not_found"))
            continue

        _, src_type, old_status, question, answer, _, category = row
        if src_type not in REVIEW_GATED_SOURCES:
            skipped.append((faq_id, "not_reviewable"))
            continue

        if old_status == new_status:
            skipped.append((faq_id, "no_change"))
            continue

        # 核准前重跑醫療合規驗證
        if new_status == REVIEW_APPROVED:
            from src.ingestion.generate_faq import validate_single_faq
            require_warning = bool(enforce_general_warning and category == "general")
            is_valid, reason = validate_single_faq(
                {"question": question, "answer": answer},
                check_dosage=True,
                require_doctor_warning=require_warning,
            )
            if not is_valid:
                skipped.append((faq_id, f"validation_failed: {reason}"))
                continue

        # 判定是否造成可見性改變
        was_visible = (old_status == REVIEW_APPROVED)
        will_be_visible = (new_status == REVIEW_APPROVED)
        visibility_changed = (was_visible != will_be_visible)

        if visibility_changed:
            if new_status == REVIEW_PENDING:
                cur.execute(
                    """
                    UPDATE faq_cache
                    SET review_status = ?,
                        reviewed_at = NULL,
                        content_version = content_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_status, faq_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE faq_cache
                    SET review_status = ?,
                        reviewed_at = CURRENT_TIMESTAMP,
                        content_version = content_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_status, faq_id),
                )
        else:
            if new_status == REVIEW_PENDING:
                cur.execute(
                    """
                    UPDATE faq_cache
                    SET review_status = ?,
                        reviewed_at = NULL
                    WHERE id = ?
                    """,
                    (new_status, faq_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE faq_cache
                    SET review_status = ?,
                        reviewed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_status, faq_id),
                )

        changed.append(faq_id)

    conn.commit()
    return ReviewResult(changed=changed, skipped=skipped)


# ---------------------------------------------------------------------------
# Phase 19：批量簽核與內聯修訂
# ---------------------------------------------------------------------------
MAX_BATCH_SIZE = 100
MAX_QUESTION_CHARS = 200
MAX_ANSWER_CHARS = 3000


def sanitize_faq_text(text: str) -> str:
    """去識別化＋價格屏蔽（寫入前的二次防線）。"""
    from src.api.routes.query import deep_mask_prices
    from src.soap.deid import deidentify_text

    cleaned = deep_mask_prices(deidentify_text(text or ""))
    return cleaned if isinstance(cleaned, str) else str(cleaned)


def batch_review_faqs(conn: sqlite3.Connection, faq_ids: list[int], action: str) -> dict:
    """批量核准／駁回：單一交易、單一權威路徑（set_review_status）。

    - action 僅限 approve／reject；ID 去重後最多 MAX_BATCH_SIZE 筆（呼叫端另做型別驗證）。
    - 逐筆合規檢驗失敗者略過並回報原因，其餘於同一次 commit 生效；
      任何非預期例外一律 rollback，不留下半提交狀態。
    """
    if action not in ("approve", "reject"):
        raise ValueError("action 僅限 approve 或 reject")
    ids = list(dict.fromkeys(int(i) for i in faq_ids))
    if not ids:
        raise ValueError("faq_ids 不可為空")
    if len(ids) > MAX_BATCH_SIZE:
        raise ValueError(f"單次批次最多 {MAX_BATCH_SIZE} 筆")
    new_status = REVIEW_APPROVED if action == "approve" else REVIEW_REJECTED
    try:
        res = set_review_status(conn, ids, new_status, enforce_general_warning=True)
    except Exception:
        conn.rollback()
        raise
    return {
        "success_count": len(res.changed),
        "failed_count": len(res.skipped),
        "processed_ids": res.changed,
        "failed_ids": [i for i, _ in res.skipped],
        "failed_reasons": {str(i): r for i, r in res.skipped},
    }


def update_faq_content(
    conn: sqlite3.Connection,
    faq_id: int,
    question: Optional[str] = None,
    answer: Optional[str] = None,
) -> bool:
    """內聯修訂待審草稿的題目／答案。

    - 僅限待審來源（REVIEW_GATED_SOURCES）且非 approved 的列；已核准項目不得靜默改寫對外內容。
    - 文字先去識別化＋價格屏蔽，再過四層驗證（含劑量）；失敗拋 ValueError，不寫入。
    - 修訂後狀態一律回到 pending（被駁回的草稿修訂後重新進入待審）。
    - 找不到回 LookupError；不可編輯回 PermissionError；題目重複回 ValueError。
    """
    from src.ingestion.generate_faq import validate_single_faq

    if question is None and answer is None:
        raise ValueError("至少需提供 question 或 answer")
    if not has_review_status(conn):
        raise RuntimeError("資料庫尚未建立審核欄位")

    row = conn.execute(
        "SELECT question, answer, source_type, review_status, category FROM faq_cache WHERE id = ?",
        (faq_id,),
    ).fetchone()
    if row is None:
        raise LookupError("找不到指定的 FAQ")
    old_q, old_a, src, status_, category = tuple(row)
    if src not in REVIEW_GATED_SOURCES:
        raise PermissionError("僅限待審來源草稿可編輯")
    if status_ == REVIEW_APPROVED:
        raise PermissionError("已核准項目不可直接編輯，請先退回待審")

    new_q = sanitize_faq_text(question).strip() if question is not None else old_q
    new_a = sanitize_faq_text(answer).strip() if answer is not None else old_a
    if not new_q or not new_a:
        raise ValueError("題目與答案不可為空")
    if len(new_q) > MAX_QUESTION_CHARS or len(new_a) > MAX_ANSWER_CHARS:
        raise ValueError("題目或答案超過長度上限")
    ok, reason = validate_single_faq(
        {"question": new_q, "answer": new_a},
        check_dosage=True,
        require_doctor_warning=(category == "general"),
    )
    if not ok:
        raise ValueError(f"未通過合規檢驗：{reason}")

    meta_sql, meta_params = "", []
    if has_metadata_column(conn):
        old = conn.execute("SELECT metadata FROM faq_cache WHERE id = ?", (faq_id,)).fetchone()[0]
        try:
            meta = json.loads(old) if old else {}
            if not isinstance(meta, dict):
                meta = {}
        except (TypeError, ValueError):
            meta = {}
        meta["answer_source"] = "manual_edit"
        meta_sql, meta_params = ", metadata = ?", [json.dumps(meta, ensure_ascii=False)]

    try:
        conn.execute(
            f"""
            UPDATE faq_cache
            SET question = ?, answer = ?, review_status = 'pending', reviewed_at = NULL,
                content_version = content_version + 1, updated_at = CURRENT_TIMESTAMP{meta_sql}
            WHERE id = ?
            """,
            [new_q, new_a, *meta_params, faq_id],
        )
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise ValueError("同診所同主題已有相同題目") from e
    conn.commit()
    return True
