"""
Taiwan Clinic Medical PageIndex RAG System - 臨床決策推理樹提煉引擎 (tree_distiller)
Phase 21 Plan 21-01: 自長篇文件或醫療文字中，結構化提煉四段式臨床推理樹

核心安全準則：
1. 嚴格限制思考過程（不超過 100 字），直接輸出 JSON。
2. 醫師權威醫囑（*_physician_notes）強制留空 (None)，嚴禁 LLM 擅自生成。
3. 繁體中文、無保證療效、無政治立場、價格深度清洗 (deep_mask_prices)。
4. 預設以 review_status='pending' 寫入資料庫，維持 Fail-Closed 隔離。
"""

import json
import logging
import re
import sqlite3
from typing import Callable, Optional

try:
    from src.api.routes.query import deep_mask_prices
except Exception:
    try:
        from src.query.router import mask_prices
    except Exception:
        from ..query.router import mask_prices

    def deep_mask_prices(obj):
        if isinstance(obj, str):
            return mask_prices(obj)
        elif isinstance(obj, dict):
            return {k: deep_mask_prices(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [deep_mask_prices(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(deep_mask_prices(item) for item in obj)
        return obj
from .db_writer import upsert_trees
from .prompt_template import (
    _FORBIDDEN_PHRASES,
    _POLITICAL_STANCE_PHRASES,
    _PRICE_PATTERN,
    _SIMPLIFIED_CHAR_SAMPLE,
    TreeValidationError,
)

logger = logging.getLogger(__name__)

TREE_DISTILL_PROMPT_TEMPLATE = """思考過程請保持簡潔（不超過 100 字），直接輸出繁體中文 JSON 結果。
你是台灣專業醫美與外科診所的臨床決策系統專家。請分析以下醫療文件或療程內文，提煉結構化「四段式臨床決策推理樹」：

# 來源內容：
療程標題：{title}
文件內文：
{text}

# 嚴格臨床規範：
1. 輸出必須為標準 JSON 物件，包含以下 5 個鍵：
   - "pre_op"：術前評估、適應症、禁忌症與注意事項（50-120字）
   - "procedure"：療程原理、操作步驟、儀器或技術特色（50-120字）
   - "post_op_short"：術後立即照護、傷口或紅腫處理、初期回診提醒（50-120字）
   - "maintenance"：長期維持保養、預防復發、生活飲食建議（50-120字）
   - "summary_text"：精簡全文摘要，供全文檢索索引（60-120字）
2. 全篇必須使用台灣正體中文，嚴禁簡體字。
3. 嚴禁出現具體價格或收費數字（若有請寫「請致電診所確認」）。
4. 嚴禁任何保證療效詞彙（如「保證有效」、「徹底根除」、「100%」）。
5. 嚴禁生成 physician_notes 欄位（該欄位保留由主治醫師親自填寫）。
6. 請勿包含 markdown 程式碼區塊標記，直接輸出合法 JSON。
"""


MAX_SOURCE_CHARS = 3500          # 送入提示詞的來源文字上限（超出部分不會被提煉，呼叫端需告知）
TREE_TEXT_FIELDS = ("pre_op", "procedure", "post_op_short", "maintenance", "summary_text")


class TreeConflictError(Exception):
    """doc_id 已存在：提煉只能建立新草稿，絕不覆寫既有樹（尤其是醫師手寫之醫囑）。"""


def validate_tree_segment(field: str, text: str) -> str:
    """單一段落的合規檢驗（提煉、編輯、簽核共用同一份規則）。

    回傳價格遮蔽後的文字；簡體字、保證療效禁詞、政治立場詞一律拋 TreeValidationError。
    """
    val = deep_mask_prices(str(text).strip())
    if not isinstance(val, str):
        val = str(val)
    simplified = [c for c in _SIMPLIFIED_CHAR_SAMPLE if c in val]
    if simplified:
        raise TreeValidationError(f"段落 {field} 檢出疑似簡體字: {simplified}")
    forbidden = [p for p in _FORBIDDEN_PHRASES if p in val]
    if forbidden:
        raise TreeValidationError(f"段落 {field} 檢出保證療效禁用詞: {forbidden}")
    political = [p for p in _POLITICAL_STANCE_PHRASES if p in val]
    if political:
        raise TreeValidationError(f"段落 {field} 檢出政治爭議詞: {political}")
    return val


def _clean_json_output(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.MULTILINE).strip()
    # 移除 <think>...</think>
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL | re.IGNORECASE).strip()
    return s


def distill_tree_from_text(
    conn: sqlite3.Connection,
    title: str,
    text: str,
    clinic_id: str,
    doc_id: str,
    llm_call: Callable[[str], str],
    category: str = "special",
    source_type: str = "web_upload",
    k_candidates: int = 1,
    recursion_mode: str = "sequential",
) -> dict:
    """自給定長篇文字中提煉臨床推理樹，並以 pending 狀態寫入「新」草稿（不覆寫既有樹）。

    Phase 37 Harness²：自動注入命中之治理教訓；k_candidates > 1 時最多探索 k 個通過 JSON 解析與
    validate_tree_segment 的候選，依 score_tree_distillation_alignment 選最高分者寫入。
    sequential 於分數未達優異門檻時以批評提示續寫；parallel 每次皆由原始提示詞獨立生成。
    """
    if conn.execute("SELECT 1 FROM page_index_trees WHERE doc_id = ?", (doc_id,)).fetchone():
        raise TreeConflictError(f"doc_id '{doc_id}' 已存在，提煉僅能建立新草稿，請改用其他識別碼")
    if recursion_mode not in ("sequential", "parallel") or not isinstance(k_candidates, int) or k_candidates < 1:
        raise TreeValidationError("遞迴參數不合法（k_candidates 須為正整數，recursion_mode 須為 sequential 或 parallel）")
    from .tree_navigator import condense_long_document_by_toc
    from .text_harness import (
        EXCELLENT_THRESHOLD,
        build_tree_critique_prompt,
        format_text_lessons_for_prompt,
        score_tree_distillation_alignment,
        select_text_lessons,
    )

    condensed_text = condense_long_document_by_toc(text, MAX_SOURCE_CHARS)
    base_prompt = TREE_DISTILL_PROMPT_TEMPLATE.format(title=title, text=condensed_text)
    lessons_block = format_text_lessons_for_prompt(select_text_lessons(f"{title}\n{condensed_text}"))
    if lessons_block:
        base_prompt = f"{base_prompt}\n{lessons_block}\n"

    required_fields = list(TREE_TEXT_FIELDS)

    def _attempt(prompt: str) -> dict:
        """單一候選：呼叫模型、解析 JSON、四段齊全與合規檢驗；不合格拋 TreeValidationError。"""
        raw = llm_call(prompt)
        clean_json = _clean_json_output(raw)
        try:
            data = json.loads(clean_json)
        except json.JSONDecodeError as e:
            raise TreeValidationError(f"模型輸出無法解析為 JSON：{e} (原始輸出: {raw[:200]})") from e
        if not isinstance(data, dict):
            raise TreeValidationError("模型輸出必須為 JSON 物件")
        missing = [f for f in required_fields if f not in data or not str(data[f]).strip()]
        if missing:
            raise TreeValidationError(f"輸出缺少必要段落：{missing}")
        # 合規檢驗與清洗（與編輯／簽核共用同一規則）
        return {k: validate_tree_segment(k, data[k]) for k in required_fields}

    if k_candidates == 1:
        cleaned_data = _attempt(base_prompt)
        report = score_tree_distillation_alignment(title, condensed_text, cleaned_data)
    else:
        candidates: list[tuple[dict, dict]] = []
        last_err: Optional[TreeValidationError] = None
        prompt = base_prompt
        for _round in range(k_candidates):
            try:
                cand = _attempt(prompt)
            except TreeValidationError as e:
                last_err = e
                continue
            rep = score_tree_distillation_alignment(title, condensed_text, cand)
            candidates.append((cand, rep))
            if recursion_mode == "sequential":
                if rep["score"] >= EXCELLENT_THRESHOLD:
                    break
                prompt = build_tree_critique_prompt(base_prompt, cand, rep)
        if not candidates:
            raise last_err or TreeValidationError("沒有通過合規檢驗的候選推理樹")
        cleaned_data, report = max(candidates, key=lambda c: c[1]["score"])

    # 組裝寫入 row，醫師指令強制留空 None
    tree_row = {
        "doc_id": doc_id,
        "title": validate_tree_segment("title", title.strip()),
        "clinic_id": clinic_id,
        "category": category,
        "pre_op": cleaned_data["pre_op"],
        "pre_op_physician_notes": None,
        "procedure": cleaned_data["procedure"],
        "procedure_physician_notes": None,
        "post_op_short": cleaned_data["post_op_short"],
        "post_op_short_physician_notes": None,
        "maintenance": cleaned_data["maintenance"],
        "maintenance_physician_notes": None,
        "summary_text": cleaned_data["summary_text"],
        "review_status": "pending",
    }

    upsert_trees(conn, [tree_row], source_type=source_type, review_status="pending")
    return {
        **tree_row,
        "harness_score": report["score"],
        "harness_k": k_candidates,
        "harness_mode": recursion_mode,
    }
