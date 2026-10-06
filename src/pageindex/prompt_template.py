#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - LLM 臨床推理樹生成 Prompt
Phase 01 Task 4: Build clinical reasoning tree LLM prompt

設計目標：
- 給定一個療程名稱（及可選的院內既有描述、service_items/drugs 參考資料），
  生成一份符合 page_index_trees schema 的臨床推理樹（pre_op/procedure/
  post_op_short/maintenance + summary_text）。
- 品質基準：src/pageindex/seed_trees.py 的 6 筆手寫範本（few-shot 範例）。
- 這個模組本身不綁定任何特定 LLM provider（本地或雲端皆可）。呼叫方式是
  傳入一個 `llm_call: Callable[[str], str]` 函式，接收 prompt 字串、回傳
  模型原始輸出字串。Phase 02 的本地 LLM 推理層完成後，只需實作一個符合
  這個介面的 llm_call，不需要更動這裡的 prompt/驗證邏輯。

CONSTRAINT 遵循（強制寫入 prompt 本文，並在輸出端再次驗證）：
- 全篇繁體中文，不含任何簡體字
- 絕對禁止出現原始價格數字；不確定給付/收費一律使用「請致電診所確認」
- physician_notes 欄位一律留空（LLM 不得生成醫師專屬醫囑內容）
"""

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    from .seed_trees import TREES as SEED_TREES
except ImportError:
    from seed_trees import TREES as SEED_TREES

# ---------------------------------------------------------------------------
# Few-shot 範例：從既有 6 筆手寫範本中挑 2 筆，涵蓋不同麻醉/恢復期特性
# （侵入性注射 vs 非侵入性能量儀器），讓 LLM 看到結構差異但格式一致。
# ---------------------------------------------------------------------------

_FEW_SHOT_DOC_IDS = ("botox-injection",)

_OUTPUT_FIELDS = ("pre_op", "procedure", "post_op_short", "maintenance", "summary_text")


def _few_shot_examples() -> str:
    examples = []
    for tree in SEED_TREES:
        if tree["doc_id"] not in _FEW_SHOT_DOC_IDS:
            continue
        procedure_name = tree["doc_id"]
        example = {
            "procedure_name": procedure_name,
            **{field_name: tree[field_name] for field_name in _OUTPUT_FIELDS},
        }
        examples.append(json.dumps(example, ensure_ascii=False, indent=2))
    return "\n\n".join(examples)


PROMPT_TEMPLATE = """你是台灣醫美診所的臨床衛教文案編輯，任務是為指定療程生成一份結構化的
「臨床推理樹」，供病患查詢療程資訊時使用。

# 嚴格規則（違反任何一條視為輸出無效）

1. 全篇僅使用繁體中文。禁止簡體字、禁止非必要的英文（藥品學名、國際通用醫療術語除外）。
2. 絕對禁止出現任何具體價格、金額、收費數字（例如 "1500元"、"NT$500"、"打三次八折"）。
   若內容原本會提及費用，一律替換為「請致電診所確認」。
3. 只生成以下五個欄位：pre_op（術前須知，30-80字）、procedure（療程步驟與原理，30-80字）、
   post_op_short（術後短期照護，30-80字）、maintenance（長期維持保養，30-80字）、summary_text
   （前四段的精簡摘要，供全文檢索使用，50-100字為佳）。
4. **不要生成 physician_notes 相關欄位**——這些欄位保留給醫師人工審核填寫，
   由你生成內容會違反醫療責任分工，一律不得輸出。
5. 內容必須是衛教性質的一般性說明，不得包含具體診斷建議或保證療效的字句
   （如「保證有效」「一定能消除」），改用「因人而異」「多數情況下」等措辭。
6. 若你不確定某個步驟的醫學細節，寧可用較保守、通用的描述，也不要編造
   具體數據（如恢復天數、儀器參數）。
7. 嚴格遵守立場中立原則：禁止輸出任何政治、主權、國家定位、意識形態相關的立場表述，僅專注於醫療衛教內容本身；若生成過程中意外偏離療程主題，應該完全略過該離題內容，不得附和、重複或延伸任何政治性敘述。
8. 思考簡潔：思考過程請保持精簡專注，思考完畢後立即輸出 JSON 物件。

# 輸出格式

僅輸出一個 JSON 物件，不要有任何前綴或後綴文字、不要用 markdown code fence 包裹。
欄位：{{"pre_op": "...", "procedure": "...", "post_op_short": "...", "maintenance": "...", "summary_text": "..."}}

# 範例（品質與格式基準，內容取材自其他療程，僅供參考結構）

{few_shot_examples}

# 你的任務

療程名稱：{procedure_name}
{reference_context}

請依照上述規則與範例格式，為此療程生成臨床推理樹的 JSON 輸出。
"""


@dataclass
class GeneratedTree:
    pre_op: str
    procedure: str
    post_op_short: str
    maintenance: str
    summary_text: str
    warnings: list = field(default_factory=list)


class TreeValidationError(Exception):
    """LLM 輸出未通過 CONSTRAINT 驗證。"""


_PRICE_PATTERN = re.compile(r"\d+\s*[元塊]|NT\$\s*\d+|\$\d+")
# 常見簡體字樣本（僅作快速篩檢，非完整簡繁對照表）
_SIMPLIFIED_CHAR_SAMPLE = set("这个国实现们来对进为产时问题号线还没会说")
_FORBIDDEN_PHRASES = ("physician_notes", "保證有效", "一定能消除", "保證消除", "保證")
_POLITICAL_STANCE_PHRASES = (
    "不可分割的一部分",
    "一個中國",
    "中國台灣",
    "台灣地區",
)


def build_prompt(procedure_name: str, reference_context: Optional[str] = None) -> str:
    """組裝完整 prompt。reference_context 可放 service_items/drugs 的相關
    參考資料（例如既有給付規定文字、成分說明），幫助 LLM 生成更貼合實際
    療程的內容；留空則純靠 LLM 既有知識生成通用衛教內容。"""
    context_block = f"參考資料：\n{reference_context}" if reference_context else "（無額外參考資料，請依一般醫學衛教常識生成）"
    return PROMPT_TEMPLATE.format(
        few_shot_examples=_few_shot_examples(),
        procedure_name=procedure_name,
        reference_context=context_block,
    )


def parse_and_validate(raw_output: str) -> GeneratedTree:
    """解析 LLM 原始輸出並驗證 CONSTRAINT。任何違規直接拋出
    TreeValidationError，呼叫方不應該把未通過驗證的內容寫入資料庫。"""
    raw_output = raw_output.strip()
    # 容錯：部分模型仍會用 code fence 包裹，即使 prompt 已要求不要
    if raw_output.startswith("```"):
        raw_output = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_output.strip(), flags=re.MULTILINE)

    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError as e:
        raise TreeValidationError(f"LLM 輸出不是合法 JSON：{e}") from e

    missing = [f for f in _OUTPUT_FIELDS if f not in data or not str(data[f]).strip()]
    if missing:
        raise TreeValidationError(f"輸出缺少必要欄位：{missing}")

    full_text = " ".join(str(data[f]) for f in _OUTPUT_FIELDS)

    price_hits = _PRICE_PATTERN.findall(full_text)
    if price_hits:
        raise TreeValidationError(f"偵測到價格資訊洩漏，違反 CONSTRAINT：{price_hits}")

    simplified_hits = [c for c in _SIMPLIFIED_CHAR_SAMPLE if c in full_text]
    if simplified_hits:
        raise TreeValidationError(f"偵測到疑似簡體字，違反繁體中文專用 CONSTRAINT：{simplified_hits}")

    forbidden_hits = [p for p in _FORBIDDEN_PHRASES if p in full_text]
    if forbidden_hits:
        raise TreeValidationError(f"偵測到禁用詞彙（保證療效用語或誤植欄位名）：{forbidden_hits}")

    political_hits = [p for p in _POLITICAL_STANCE_PHRASES if p in full_text]
    if political_hits:
        raise TreeValidationError(f"偵測到政治立場相關表述，違反立場中立 CONSTRAINT：{political_hits}")

    warnings = []
    for field_name in _OUTPUT_FIELDS:
        if len(str(data[field_name])) < 10:
            warnings.append(f"{field_name} 內容過短（少於10字），品質可能不足，建議人工複核")

    return GeneratedTree(
        pre_op=data["pre_op"],
        procedure=data["procedure"],
        post_op_short=data["post_op_short"],
        maintenance=data["maintenance"],
        summary_text=data["summary_text"],
        warnings=warnings,
    )


def generate_tree(
    procedure_name: str,
    llm_call: Callable[[str], str],
    reference_context: Optional[str] = None,
) -> GeneratedTree:
    """生成單一療程的臨床推理樹。

    llm_call：接收組好的 prompt 字串，回傳模型的原始文字輸出。呼叫方負責
    決定要接本地或雲端 LLM（Phase 02 待建），這裡不處理任何推理細節，
    只負責 prompt 組裝與輸出驗證，保持與底層 LLM provider 解耦。

    驗證失敗時拋出 TreeValidationError，呼叫方應該記錄失敗原因、不寫入
    資料庫，並可視情況重試或交由人工處理——絕不能把未通過驗證的內容
    直接存入 page_index_trees。
    """
    prompt = build_prompt(procedure_name, reference_context)
    raw_output = llm_call(prompt)
    return parse_and_validate(raw_output)


def to_upsert_row(doc_id: str, clinic_id: str, category: str, tree: GeneratedTree) -> dict:
    """把 GeneratedTree 轉成符合 db_writer.py CONTENT_FIELDS 格式的 dict，
    可直接餵給 db_writer.upsert_trees() 的增量 upsert 邏輯（呼叫時傳入
    source_type='llm_generated'；physician_notes 欄位一律 None，交由
    醫師事後審核填入）。"""
    return {
        "doc_id": doc_id,
        "clinic_id": clinic_id,
        "category": category,
        "pre_op": tree.pre_op,
        "pre_op_physician_notes": None,
        "procedure": tree.procedure,
        "procedure_physician_notes": None,
        "post_op_short": tree.post_op_short,
        "post_op_short_physician_notes": None,
        "maintenance": tree.maintenance,
        "maintenance_physician_notes": None,
        "summary_text": tree.summary_text,
    }
