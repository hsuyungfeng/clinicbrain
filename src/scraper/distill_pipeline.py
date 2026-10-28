"""Phase 38 Step 3：站點內文 → 本地 LLM 提煉 FAQ 與四段式推理樹（全部寫入 pending）。

流程（固定順序）：
1. 防禦性清洗：opencc 台灣正體 → deep_mask_prices 價格遮蔽（即使上游已清洗，入口仍再做一次）。
2. FAQ 提煉：單次呼叫本地 LLM 要求 5～10 筆 JSON 問答；逐筆經 validate_single_faq（劑量／價格／
   簡體／禁詞／就醫警訊）與 text_harness.score_faq_answer_alignment（passed_threshold）驗證；
   缺就醫警訊收尾句者強制補上標準收尾句後再驗證。
3. 推理樹提煉：對前 max_trees 段內容呼叫 tree_distiller.distill_tree_from_text（內含 k 候選的
   score_tree_distillation_alignment 選優與 validate_tree_segment 合規檢驗）。
4. 寫入：FAQ 經 faq_writer.upsert_faqs(source_type='llm_generated')；推理樹經 db_writer.upsert_trees
   （透過 distill_tree_from_text）。兩者皆強制 review_status='pending'，絕不自動核准。

LLM 可注入（llm_call）；未注入時使用本地 llama-server（local_llm_call）。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.ingestion.convert_chinese import to_traditional
from src.ingestion.generate_faq import validate_single_faq
from src.ingestion.medical_safety import has_doctor_warning
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.text_harness import (
    TEXT_ALIGNMENT_THRESHOLD,
    score_faq_answer_alignment,
)
from src.pageindex.tree_distiller import TreeConflictError, TreeValidationError, distill_tree_from_text
from src.scraper.site_crawler import deep_mask_prices

MAX_SOURCE_CHARS = 3500
TREE_CHUNK_CHARS = 1500
FAQ_MIN_CHARS = 100
FAQ_MAX_CHARS = 600
MAX_FAQ_ITEMS = 10
WARNING_SENTENCE = "若出現持續高燒不退、呼吸困難或胸痛等情形，請立即就醫或前往急診評估。"

FAQ_PROMPT_TEMPLATE = """思考過程請保持簡潔（不超過 100 字），直接輸出 JSON。
你是台灣{clinic_name}的衛教內容編輯。請閱讀下列診所網站內文，提煉 5 至 10 筆民眾常見問題與衛教回答。

# 網站內文
{text}

# 規則（必須全部遵守）
1. 只輸出 JSON 陣列，每項為 {{"question": "……？", "answer": "……"}}，不要任何其他文字或 Markdown。
2. 全文使用台灣正體中文，嚴禁簡體字。
3. 答案 150 至 300 字，至少三句，內容僅限一般性衛教，不下診斷、不開處方。
4. 嚴禁任何金額、價格、折扣、促銷字樣；嚴禁具體藥品名稱與劑量。
5. 嚴禁「保證」「根治」「百分之百」「一定有效」等療效保證用語。
6. 每則答案最後必須包含就醫警訊（具體症狀加就醫動作）。
"""

TREE_TITLE_TEMPLATE = "{clinic_name}核心療程{index}"


@dataclass
class DistillationResult:
    faq_candidates: int = 0
    faq_accepted: int = 0
    faq_rejected: list[str] = field(default_factory=list)
    faq_written: tuple[int, int, int] = (0, 0, 0)
    trees_attempted: int = 0
    trees_written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _digest(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]


def _split_chunks(text: str, size: int) -> list[str]:
    """依段落切分為約 size 字的區塊（不切斷段落；單段超長時硬切）。"""
    chunks: list[str] = []
    buf = ""
    for para in text.split("\n"):
        while len(para) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(para[:size])
            para = para[size:]
        if len(buf) + len(para) + 1 > size and buf:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf.strip():
        chunks.append(buf)
    return [c for c in chunks if c.strip()]


def _parse_faq_items(raw: str) -> list[dict[str, str]]:
    """自模型輸出擷取 JSON 陣列；格式不符的項目略過（不拋例外）。"""
    text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL | re.IGNORECASE).strip()
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return []
    items: list[dict[str, str]] = []
    for entry in data if isinstance(data, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("question"), str) and isinstance(entry.get("answer"), str):
            items.append({"question": entry["question"].strip(), "answer": entry["answer"].strip()})
    return items[:MAX_FAQ_ITEMS]


def _default_llm(prompt: str) -> str:
    from src.pageindex.llm_client import local_llm_call

    return local_llm_call(prompt, timeout=420)


def _sanitize(text: str) -> str:
    cleaned = deep_mask_prices(to_traditional(text))
    return cleaned if isinstance(cleaned, str) else str(cleaned)


def _accept_faq(question: str, answer: str, clinic_name: str) -> tuple[Optional[tuple[str, str, float]], str]:
    """回傳 ((問題, 答案, 分數), "ok") 或 (None, 拒絕原因代碼)。"""
    q = _sanitize(question)
    a = _sanitize(answer)
    if not has_doctor_warning(a):
        a = f"{a} {WARNING_SENTENCE}"
    if not (FAQ_MIN_CHARS <= len(a) <= FAQ_MAX_CHARS):
        return None, "length"
    ok, _reason = validate_single_faq({"question": q, "answer": a}, check_dosage=True, require_doctor_warning=True)
    if not ok:
        return None, "compliance"
    # 主題僅以問題本身計分：診所名稱不是症狀答案會重述的詞彙，不應拉低相關度
    report = score_faq_answer_alignment(q, "", a)
    if not report["passed_threshold"]:
        return None, "alignment"
    return (q, a, report["score"]), "ok"


def distill_site_content(
    site_text: str,
    clinic_id: str,
    clinic_name: str,
    *,
    conn: Optional[sqlite3.Connection] = None,
    llm_call: Optional[Callable[[str], str]] = None,
    max_trees: int = 2,
    source_url: str = "",
) -> DistillationResult:
    """提煉站點內文為 FAQ 草稿與推理樹草稿；conn 為 None 時僅提煉不寫入（乾跑）。"""
    if not site_text or not site_text.strip():
        raise ValueError("site_text 不可為空")
    if not clinic_id or not clinic_name:
        raise ValueError("clinic_id 與 clinic_name 為必填")

    llm = llm_call or _default_llm
    text = _sanitize(site_text)
    condensed = text[:MAX_SOURCE_CHARS]
    result = DistillationResult()
    digest = _digest(clinic_id, clinic_name)

    # 1. FAQ 提煉與驗證
    try:
        raw = llm(FAQ_PROMPT_TEMPLATE.format(clinic_name=clinic_name, text=condensed))
    except Exception as exc:  # noqa: BLE001 — LLM 離線不應使整段管線崩潰；記錄後仍嘗試推理樹
        result.errors.append(f"faq_llm:{type(exc).__name__}")
        raw = ""
    items = _parse_faq_items(raw)
    result.faq_candidates = len(items)
    accepted: list[tuple[str, str, float]] = []
    for item in items:
        got, code = _accept_faq(item["question"], item["answer"], clinic_name)
        if got is None:
            result.faq_rejected.append(code)
        else:
            accepted.append(got)
    result.faq_accepted = len(accepted)

    if conn is not None and accepted:
        rows = [
            {
                "question": q,
                "answer": a,
                "category": "special",
                "clinic_id": clinic_id,
                "topic_key": f"site-{digest}",
                "metadata": json.dumps(
                    {"origin": "site_distill", "source_url": source_url, "harness_score": score},
                    ensure_ascii=False,
                ),
            }
            for q, a, score in accepted
        ]
        result.faq_written = upsert_faqs(conn, rows, source_type="llm_generated", commit=True)

    # 2. 四段式推理樹提煉（distill_tree_from_text 內含 k 候選對齊評分與合規檢驗，寫入 pending）
    if conn is not None and max_trees > 0:
        for index, chunk in enumerate(_split_chunks(text, TREE_CHUNK_CHARS)[:max_trees], start=1):
            result.trees_attempted += 1
            doc_id = f"site-{digest}-{index}"
            title = TREE_TITLE_TEMPLATE.format(clinic_name=clinic_name, index=index)[:30]
            try:
                row = distill_tree_from_text(
                    conn,
                    title=title,
                    text=chunk,
                    clinic_id=clinic_id,
                    doc_id=doc_id,
                    llm_call=llm,
                    category="special",
                    source_type="web_upload",
                    k_candidates=3,
                    recursion_mode="sequential",
                )
                result.trees_written.append(row["doc_id"])
            except TreeConflictError:
                result.errors.append(f"tree_exists:{doc_id}")
            except TreeValidationError as exc:
                result.errors.append(f"tree_invalid:{doc_id}:{str(exc)[:80]}")
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"tree_error:{doc_id}:{type(exc).__name__}")
    return result
