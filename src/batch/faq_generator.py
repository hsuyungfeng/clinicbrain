"""
Taiwan Clinic Medical PageIndex RAG System - FAQ 夜間批次預生成引擎 (faq_generator)
Phase 09 Nightly Batch Maintenance: Task 1

設計原則：
- 僅回答人寫的種子問題：嚴格比對 question 是否逐字符合種子清單，杜絕 LLM 改寫或發明問題。
- 四層合規檢查：重用 generate_faq.parse_and_validate_faq 驗證器，任何違規項目拒絕入庫。
- 隱私承諾：剔除項目一律映射至固定代碼 (REJECT_CODES)，絕不記錄或回顯含敏感詞之原始錯誤訊息或模型原文。
- 單一寫入途徑：一律呼叫 faq_writer.upsert_faqs(source_type='llm_generated')，新列預設為 pending。
"""

from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any, Callable, NamedTuple, Optional, Sequence, Union

from src.batch.topic_sources import SeedTopic
from src.ingestion.generate_faq import parse_and_validate_faq
from src.pageindex.faq_writer import upsert_faqs
from src.query.router import mask_prices


class WriteResult(NamedTuple):
    """write_topic_faqs 回傳之三元組（相容 tuple 解包與屬性存取）。"""
    inserted: int
    updated: int
    unchanged: int

MIN_ANSWER_CHARS = 15
TREE_REFERENCE_MAX_CHARS = 800

REJECT_CODES = frozenset([
    "price_leak",
    "simplified",
    "political",
    "forbidden",
    "dosage_prescription",
    "missing_doctor_warning",
    "json_invalid",
    "malformed_item",
    "question_not_in_seed",
    "answer_too_short",
    "duplicate_question",
    "other",
])

FAQ_SEED_PROMPT_TEMPLATE = """你是台灣緻妍外科診所的專業醫療文案編輯。請針對以下主題與指定問題，提供嚴格遵守醫療法規之繁體中文衛教問答。

【主題】：{title}
【參考背景資料】：
{reference_context}

【待回答問題清單】：
{questions_text}

【生成規則】：
1. 繁體中文專用：輸出必須全為台灣正體中文，嚴禁使用簡體字。
2. 嚴格價格屏蔽：不得輸出任何具體金額數字或促銷組合；若涉及費用一律回答「請致電診所確認」。
3. 立場中立：保持客觀專業醫學視角，不得提及任何爭議政治立場。
4. 醫療責任分工：不得誇大或保證療效，不做個別化診斷；需要就醫評估的情況請明確建議就醫。
5. 題目一致性：輸出的 question 欄位必須與上述「待回答問題清單」中的問題逐字完全相同，嚴禁自行改寫或增加問題。
6. 解答長度：每題 answer 字數介於 15 至 300 字。{extra_rules}
7. 輸出格式：僅輸出合法 JSON 陣列，不帶任何 markdown 標記，格式如下：
[
  {{
    "question": "問題原文",
    "answer": "繁體中文衛教解答"
  }}
]
"""


def classify_reject_reason(reason: str) -> str:
    """將驗證器之詳細錯誤訊息映射為固定安全代碼，杜絕敏感字串洩漏至日誌。"""
    r = reason or ""
    if "具體金額" in r or "價格" in r or "金額" in r:
        return "price_leak"
    if "簡體" in r:
        return "simplified"
    if "政治立場" in r:
        return "political"
    if "違規禁詞" in r or "保證療效" in r or "誇大" in r:
        return "forbidden"
    if "用藥劑量" in r or "處方建議" in r:
        return "dosage_prescription"
    if "何時該就醫" in r:
        return "missing_doctor_warning"
    if "為空或非字串" in r or "非 dict" in r or "缺少" in r:
        return "malformed_item"
    if "JSONDecodeError" in r or "頂層結構非陣列" in r or "json" in r.lower():
        return "json_invalid"
    return "other"


def build_seed_faq_prompt(
    title: str,
    questions: Sequence[str],
    reference_context: Optional[str],
    *,
    require_doctor_warning: bool = False,
) -> str:
    """組裝送入 LLM 之種子問答生成 Prompt。"""
    ref_text = (
        reference_context.strip()
        if reference_context and reference_context.strip()
        else "無額外參考資料，請依一般醫學衛教常識回答並保持保守。"
    )
    q_lines = "\n".join(f"- {q}" for q in questions)

    rules = [
        "\n8. 用藥安全原則：禁止輸出具體用藥劑量、藥物處方或建議服用/使用何種藥物；用藥一律回答『請由醫師或藥師評估』。"
    ]
    if require_doctor_warning:
        rules.append(
            "\n9. 何時該就醫警訊收尾：每題 answer 必須以一句『若出現〔具體症狀或數值條件，如胸痛、呼吸困難、體溫超過38.5度且持續3天〕，請〔就醫動作，如立即前往急診或儘速就醫〕』收尾。"
        )
    extra_rules = "".join(rules)

    return FAQ_SEED_PROMPT_TEMPLATE.format(
        title=title,
        reference_context=ref_text,
        questions_text=q_lines,
        extra_rules=extra_rules,
    )


def existing_questions(
    conn: sqlite3.Connection,
    clinic_id: Optional[str],
    topic_key: str,
    *,
    exclude_regen_marked: bool = False,
) -> set[str]:
    """
    查詢 faq_cache 中指定主題下已存在的全部問題（不論審核狀態與資料來源）。
    當 exclude_regen_marked=True 且具備審核欄位時，
    排除 needs_regeneration = 1 AND source_type = 'llm_generated' AND review_status = 'rejected' 的列，
    允許被標記重生成的問題重新進入生成候選。
    """
    from src.pageindex.faq_review import has_review_status

    cur = conn.cursor()
    if exclude_regen_marked and has_review_status(conn):
        cur.execute(
            """
            SELECT question
            FROM faq_cache
            WHERE clinic_id IS ? AND topic_key IS ?
              AND NOT (needs_regeneration = 1 AND source_type = 'llm_generated' AND review_status = 'rejected')
            """,
            (clinic_id, topic_key),
        )
    else:
        cur.execute(
            """
            SELECT question
            FROM faq_cache
            WHERE clinic_id IS ? AND topic_key IS ?
            """,
            (clinic_id, topic_key),
        )
    return {row[0].strip() for row in cur.fetchall()}


def reference_from_tree(
    conn: sqlite3.Connection,
    tree_doc_id: Optional[str],
) -> Optional[str]:
    """自對應之 PageIndex 臨床推理樹取得已屏蔽價格之 summary_text 作為參考上下文。"""
    if not tree_doc_id:
        return None
    cur = conn.cursor()
    cur.execute(
        "SELECT summary_text FROM page_index_trees WHERE doc_id = ?",
        (tree_doc_id,),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return None
    cleaned_summary = mask_prices(str(row[0]))
    return cleaned_summary[:TREE_REFERENCE_MAX_CHARS]


@dataclass
class TopicGenResult:
    """單一主題 FAQ 批次生成結果。"""
    topic_key: str
    requested: int
    skipped_existing: int
    valid: list[dict]
    rejected: list[dict] = field(default_factory=list)
    called_llm: bool = False
    regen_questions: list[str] = field(default_factory=list)


def _query_regen_marked_questions(
    conn: sqlite3.Connection,
    clinic_id: Optional[str],
    topic_key: str,
) -> set[str]:
    """查詢當前主題下被標記重生成之 rejected llm_generated 問題清單。"""
    from src.pageindex.faq_review import has_review_status

    if not has_review_status(conn):
        return set()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT question
        FROM faq_cache
        WHERE clinic_id IS ? AND topic_key IS ?
          AND needs_regeneration = 1
          AND source_type = 'llm_generated'
          AND review_status = 'rejected'
        """,
        (clinic_id, topic_key),
    )
    return {row[0].strip() for row in cur.fetchall()}


def generate_topic_faqs(
    conn: sqlite3.Connection,
    topic: SeedTopic,
    llm_call: Callable[[str], str],
) -> TopicGenResult:
    """
    針對指定主題執行 FAQ 預生成。
    純生成函式，不執行資料庫寫入操作。
    """
    # 1. 過濾已存在的題目（排除被標記重生成者，使其進入待回答清單）
    exist_set = existing_questions(conn, topic.clinic_id, topic.topic_key, exclude_regen_marked=True)
    pending_questions = [q for q in topic.questions if q.strip() not in exist_set]
    skipped_count = len(topic.questions) - len(pending_questions)

    # 查明本批待生成問題中有哪些是「被標記重生成」者
    regen_marked_set = _query_regen_marked_questions(conn, topic.clinic_id, topic.topic_key)
    batch_regen_questions = [q for q in pending_questions if q.strip() in regen_marked_set]

    if not pending_questions:
        return TopicGenResult(
            topic_key=topic.topic_key,
            requested=len(topic.questions),
            skipped_existing=skipped_count,
            valid=[],
            rejected=[],
            called_llm=False,
            regen_questions=batch_regen_questions,
        )

    # 2. 構建 Prompt 並呼叫 LLM
    ref_context = reference_from_tree(conn, topic.tree_doc_id)
    is_general = (topic.category == "general")
    prompt = build_seed_faq_prompt(
        topic.title,
        pending_questions,
        ref_context,
        require_doctor_warning=is_general,
    )
    raw_output = llm_call(prompt)

    # 3. 執行醫療法規合規檢查（LLM 生成路徑一律啟用劑量處方檢測，general 另要求就醫警訊）
    valid_items, rejected_raw = parse_and_validate_faq(
        raw_output,
        return_rejected=True,
        check_dosage=True,
        require_doctor_warning=is_general,
    )

    rejected_clean: list[dict] = []
    for rej in rejected_raw:
        if "error" in rej:
            rejected_clean.append({"code": "json_invalid"})
        else:
            reason_str = rej.get("reason", "")
            code = classify_reject_reason(reason_str)
            item_record = {"code": code}
            if "index" in rej:
                item_record["index"] = rej["index"]
            rejected_clean.append(item_record)

    # 4. 針對合格項目進行種子一致性與長度檢查
    final_valid: list[dict] = []
    seen_in_batch: set[str] = set()
    pending_set = {q.strip() for q in pending_questions}

    for idx, item in enumerate(valid_items):
        q = (item.get("question") or "").strip()
        a = (item.get("answer") or "").strip()

        if not a:
            rejected_clean.append({"code": "malformed_item", "index": idx})
            continue

        if q not in pending_set:
            rejected_clean.append({"code": "question_not_in_seed", "index": idx})
            continue

        if len(a) < MIN_ANSWER_CHARS:
            rejected_clean.append({"code": "answer_too_short", "index": idx})
            continue

        if q in seen_in_batch:
            rejected_clean.append({"code": "duplicate_question", "index": idx})
            continue

        seen_in_batch.add(q)
        final_valid.append(
            {
                "question": q,
                "answer": a,
                "category": topic.category,
                "clinic_id": topic.clinic_id,
                "topic_key": topic.topic_key,
            }
        )

    return TopicGenResult(
        topic_key=topic.topic_key,
        requested=len(topic.questions),
        skipped_existing=skipped_count,
        valid=final_valid,
        rejected=rejected_clean,
        called_llm=True,
        regen_questions=batch_regen_questions,
    )


def write_topic_faqs(
    conn: sqlite3.Connection,
    topic_or_faqs: Union[SeedTopic, list[dict]],
    result: Optional[TopicGenResult] = None,
) -> WriteResult:
    """
    將生成的合格 FAQ 寫入資料庫，強制標記 source_type='llm_generated'。
    支援兩種呼叫簽名：
    - write_topic_faqs(conn, faqs: list[dict])
    - write_topic_faqs(conn, topic: SeedTopic, result: TopicGenResult)
    回傳相容 NamedTuple / 3-tuple (inserted, updated, unchanged)。
    """
    if result is not None:
        faqs = result.valid
    elif isinstance(topic_or_faqs, list):
        faqs = topic_or_faqs
    else:
        faqs = []

    if not faqs:
        return WriteResult(0, 0, 0)
    ins, upd, unc = upsert_faqs(conn, faqs, source_type="llm_generated")
    return WriteResult(ins, upd, unc)


def settle_regen_flags(
    conn: sqlite3.Connection,
    topic: SeedTopic,
    result: TopicGenResult,
    details: Optional[dict[str, list[int]]] = None,
) -> dict[str, int]:
    """
    依「一次標記，一次嘗試」原則清算本次重生成旗標。
    對 regen_questions 逐題檢查：
    - 若 needs_regeneration 已為 0（faq_writer 因答案變更已更新）：計 regenerated
    - 若 needs_regeneration 仍為 1：
      呼叫 clear_regeneration_flag 清除旗標。
      若該題在 result.valid 中（代表答案相同 unchanged）：計 unchanged
      若不在 result.valid 中（被合規檢查拒絕或遺漏）：計 failed
    回傳: {"regenerated": int, "unchanged": int, "failed": int}
    若傳入 details，會填入 "unchanged_ids"／"failed_ids"（列 id，非敏感資訊，供日誌追蹤）。
    """
    from src.pageindex.faq_review import clear_regeneration_flag, has_review_status

    if not result.regen_questions or not has_review_status(conn):
        return {"regenerated": 0, "unchanged": 0, "failed": 0}

    cur = conn.cursor()
    regenerated = 0
    unchanged = 0
    failed = 0

    valid_questions = {item.get("question", "").strip() for item in result.valid}
    unchanged_ids: list[int] = []
    failed_ids: list[int] = []

    for q in result.regen_questions:
        cur.execute(
            """
            SELECT id, needs_regeneration
            FROM faq_cache
            WHERE clinic_id IS ? AND topic_key IS ? AND question = ?
            """,
            (topic.clinic_id, topic.topic_key, q.strip()),
        )
        row = cur.fetchone()
        if not row:
            failed += 1
            continue

        faq_id, needs_reg = row
        if needs_reg == 0:
            regenerated += 1
        else:
            # 旗標仍為 1，必須清除以避免每晚白跑
            clear_regeneration_flag(conn, [faq_id])
            if q.strip() in valid_questions:
                unchanged += 1
                unchanged_ids.append(faq_id)
            else:
                failed += 1
                failed_ids.append(faq_id)

    if details is not None:
        details["unchanged_ids"] = unchanged_ids
        details["failed_ids"] = failed_ids

    return {"regenerated": regenerated, "unchanged": unchanged, "failed": failed}
