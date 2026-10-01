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
from typing import Any, Callable, Optional, Sequence

from src.batch.topic_sources import SeedTopic
from src.ingestion.generate_faq import parse_and_validate_faq
from src.pageindex.faq_writer import upsert_faqs
from src.query.router import mask_prices

MIN_ANSWER_CHARS = 15
TREE_REFERENCE_MAX_CHARS = 800

REJECT_CODES = frozenset([
    "price_leak",
    "simplified",
    "political",
    "forbidden",
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
6. 解答長度：每題 answer 字數介於 15 至 300 字。
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
    if "為空或非字串" in r or "非 dict" in r or "缺少" in r:
        return "malformed_item"
    if "JSONDecodeError" in r or "頂層結構非陣列" in r or "json" in r.lower():
        return "json_invalid"
    return "other"


def build_seed_faq_prompt(
    title: str,
    questions: Sequence[str],
    reference_context: Optional[str],
) -> str:
    """組裝送入 LLM 之種子問答生成 Prompt。"""
    ref_text = (
        reference_context.strip()
        if reference_context and reference_context.strip()
        else "無額外參考資料，請依一般醫學衛教常識回答並保持保守。"
    )
    q_lines = "\n".join(f"- {q}" for q in questions)
    return FAQ_SEED_PROMPT_TEMPLATE.format(
        title=title,
        reference_context=ref_text,
        questions_text=q_lines,
    )


def existing_questions(
    conn: sqlite3.Connection,
    clinic_id: Optional[str],
    topic_key: str,
) -> set[str]:
    """查詢 faq_cache 中指定主題下已存在的全部問題（不論審核狀態與資料來源）。"""
    cur = conn.cursor()
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


def generate_topic_faqs(
    conn: sqlite3.Connection,
    topic: SeedTopic,
    llm_call: Callable[[str], str],
) -> TopicGenResult:
    """
    針對指定主題執行 FAQ 預生成。
    純生成函式，不執行資料庫寫入操作。
    """
    # 1. 過濾已存在的題目
    exist_set = existing_questions(conn, topic.clinic_id, topic.topic_key)
    pending_questions = [q for q in topic.questions if q.strip() not in exist_set]
    skipped_count = len(topic.questions) - len(pending_questions)

    if not pending_questions:
        return TopicGenResult(
            topic_key=topic.topic_key,
            requested=len(topic.questions),
            skipped_existing=skipped_count,
            valid=[],
            rejected=[],
            called_llm=False,
        )

    # 2. 構建 Prompt 並呼叫 LLM
    ref_context = reference_from_tree(conn, topic.tree_doc_id)
    prompt = build_seed_faq_prompt(topic.title, pending_questions, ref_context)
    raw_output = llm_call(prompt)

    # 3. 執行四層醫療法規合規檢查
    valid_items, rejected_raw = parse_and_validate_faq(raw_output, return_rejected=True)

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
    )


def write_topic_faqs(
    conn: sqlite3.Connection,
    faqs: list[dict],
) -> tuple[int, int, int]:
    """將生成的合格 FAQ 寫入資料庫，強制標記 source_type='llm_generated'。"""
    if not faqs:
        return (0, 0, 0)
    return upsert_faqs(conn, faqs, source_type="llm_generated")
