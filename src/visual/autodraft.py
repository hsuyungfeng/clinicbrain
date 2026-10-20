"""
由已核准 PageIndex 臨床推理樹自動生成「原理與手術過程」視覺解說卡草稿模組 (autodraft)。
Phase 31: P31-AUTODRAFT

設計原則：
1. 輸入嚴格隔離：僅限對外可見（已核准）之臨床決策推理樹（符合 visible_tree_sql），
   未核准或駁回之樹一律拒絕生成。
2. 範圍嚴格約束：僅說明「原理與手術／處置過程」，絕不產生用藥劑量、價格數字、
   促銷方案或個人化診斷。
3. 零預設文字污染：所有場景 params 的文字欄位必須由模型針對主題明確生成，
   絕不退回寫死之預設文字。
4. 結構鎖定：固定產生 3 個場景（process_diagram -> contrast -> timeline），
   且皆附帶合法之 params。
5. 永不自動核准：生成結果寫入 visual_assets 狀態恆為 pending，source_type='llm_generated'，
   需經執業醫師審核簽核後方可對外提供。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Optional, Tuple

from src.pageindex.llm_client import (
    LLMEmptyOutputError,
    LLMTruncatedError,
    LocalLLMUnavailableError,
    VISUAL_SAMPLING,
    local_llm_call,
)
from src.pageindex.llm_lock import GENERATION_LOCK, nightly_batch_running
from src.pageindex.tree_review import visible_tree_sql
from .blueprints import BLUEPRINTS, PALETTE_TOKENS, validate_params
from .ir import (
    VISUAL_EXTRA_FORBIDDEN,
    validate_ir,
    validate_visual_text,
)
from .writer import upsert_assets

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_DIGIT_RE = re.compile(r"\d")

# 場景 3 必須包含之專業收尾語意（至少命中其一）
_TIMELINE_CLOSING_PHRASES = (
    "因人而異",
    "個人體質",
    "醫師評估",
    "醫師當面評估",
    "個別評估",
    "臨床評估",
    "視個人狀況",
    "專業評估",
)

# 非自體脂肪主題不得殘留之引擎預設脂肪移植字面值（防止模型照抄預設值污染非脂肪主題）
_FAT_GRAFT_DEFAULT_LITERALS = (
    "抽取之脂肪組織",
    "油脂層（捨棄）",
    "純化脂肪顆粒（保留）",
    "血水雜質（捨棄）",
    "中心缺血",
    "單團塊中心不易獲取充足養分",
    "微細脂肪球與周圍組織充分接觸",
    "新生血管長入",
)


def normalize_tree_topic_key(doc_id: str) -> str:
    """將 doc_id 正規化為 visual_assets 的 topic_key。

    規則：小寫英數連字號，前綴 tree-，長度 3..64。
    """
    if not isinstance(doc_id, str):
        raise ValueError("schema_error")
    cleaned = doc_id.strip().lower()
    if not cleaned.startswith("tree-"):
        normalized = f"tree-{cleaned}"
    else:
        normalized = cleaned

    if not re.match(r"^[a-z0-9-]{3,64}$", normalized):
        raise ValueError("schema_error")
    return normalized


def fetch_eligible_trees(
    conn: sqlite3.Connection,
    *,
    tree_id: Optional[int] = None,
    doc_id: Optional[str] = None,
    clinic_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """查詢符合自動生成視覺解說卡資格（已核准）之臨床決策推理樹。"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(page_index_trees)")
    cols = [row[1] for row in cur.fetchall()]
    if not cols:
        return []

    vis_sql = visible_tree_sql(conn)
    where_parts = [vis_sql]
    if "review_status" in cols:
        where_parts.append("review_status = 'approved'")
    params: list[Any] = []

    if tree_id is not None:
        where_parts.append("id = ?")
        params.append(tree_id)

    if doc_id is not None:
        where_parts.append("doc_id = ?")
        params.append(doc_id)

    if clinic_id is not None:
        where_parts.append("clinic_id = ?")
        params.append(clinic_id)

    where_clause = " AND ".join(where_parts)
    col_str = "id, clinic_id, doc_id, title, summary_text, pre_op, procedure, post_op_short, maintenance, source_type, content_version"
    # 若表中有 review_status 也取出
    if "review_status" in cols:
        col_str += ", review_status"

    cur.execute(f"SELECT {col_str} FROM page_index_trees WHERE {where_clause} ORDER BY id ASC", tuple(params))
    rows = cur.fetchall()

    result = []
    select_cols = [c.strip() for c in col_str.split(",")]
    for r in rows:
        item = dict(zip(select_cols, r))
        result.append(item)
    return result


def build_tree_visual_prompt(tree: dict[str, Any]) -> str:
    """依據推理樹內容組裝自動生成 3 場景視覺解說卡 Typed IR 的 LLM 提示詞。"""
    title = tree.get("title") or tree.get("doc_id") or "醫療療程"
    summary = tree.get("summary_text") or ""
    pre_op = tree.get("pre_op") or ""
    procedure = tree.get("procedure") or ""
    post_op = tree.get("post_op_short") or ""
    maintenance = tree.get("maintenance") or ""

    forbidden_list = "、".join(VISUAL_EXTRA_FORBIDDEN)
    palette_list = ", ".join(PALETTE_TOKENS)

    return f"""你是一位專業的台灣整形外科與醫學美容臨床決策解說設計師。
請根據以下已通過醫師審核的「臨床推理樹」醫學內容，為病患設計一套符合台灣醫療法規的「原理與處置過程」3 場景視覺解說卡 JSON 規格。

【推理樹資料】
主題標題：{title}
臨床摘要：{summary}
術前評估：{pre_op}
手術／處置過程：{procedure}
術後初期照護：{post_op}
長期維持照護：{maintenance}

【重要合規規範（違者整批拒絕）】
1. 純一般醫學原理與衛教：僅解說「原理、機轉與標準處置過程」，絕不提及任何療效保證、個人化診斷或特定診所促銷。
2. 零數字原則：嚴禁出現任何阿拉伯數字（0-9）或具體用藥劑量、百分比、金額、天數數字。請改以「微量」、「數層」、「適當時間」、「一段時間」、「少許」等中文字詞表達。
3. 嚴禁詞彙：絕對禁止出現以下詞彙：{forbidden_list}。
4. 語言規範：必須全篇使用台灣正體中文（不得出現簡體字）。
5. 第三場景（timeline）的 caption 說明文字末尾必須包含「因人而異」或「由醫師當面評估」等合規收尾語意。
6. 調色盤限制：所有顏色填色屬性（fill, unit_fill）僅限使用以下安全代號之一：[{palette_list}]。

【輸出結構要求】
請僅輸出單一合法 JSON 物件（不得包含額外說明文字或 markdown 解釋）：
{{
  "title": "{title}原理圖解",
  "keywords": ["關鍵字一", "關鍵字二", "關鍵字三"],
  "scenes": [
    {{
      "blueprint": "process_diagram",
      "title": "處置或純化步驟",
      "caption": "20到120字的說明文字，清楚解釋處置機轉，不含任何數字。",
      "labels": [
        {{"text": "重要標籤一", "tone": "neutral"}},
        {{"text": "重要標籤二", "tone": "optimal"}}
      ],
      "params": {{
        "source": {{"label": "來源組織或材料(8字內)", "fill": "skin"}},
        "particles": 6,
        "container_layers": [
          {{"label": "上層層次", "fill": "pale", "weight": 2, "keep": false}},
          {{"label": "目標核心層", "fill": "accent", "weight": 3, "keep": true}},
          {{"label": "下層基底", "fill": "neutral", "weight": 2, "keep": false}}
        ],
        "step_labels": ["第一階段步驟", "第二階段步驟", "第三階段步驟"]
      }}
    }},
    {{
      "blueprint": "contrast",
      "title": "方式對比說明",
      "caption": "20到120字的說明文字，清楚對比不佳作法與建議作法，不含任何數字。",
      "labels": [
        {{"text": "單點集中", "tone": "warning"}},
        {{"text": "分層分散", "tone": "optimal"}}
      ],
      "params": {{
        "left": {{
          "title": "單點過量",
          "note": "集中不易吸收",
          "mode": "mass",
          "core_effect": "dim",
          "core_label": "中心循環差",
          "footnote": "單點過量容易造成組織營養不良",
          "unit_fill": "accent"
        }},
        "right": {{
          "title": "分層少量",
          "note": "均勻接觸組織",
          "mode": "layered",
          "rows": 3,
          "per_row": 5,
          "footnote": "多點分散有助組織建立良好接觸",
          "unit_fill": "accent"
        }}
      }}
    }},
    {{
      "blueprint": "timeline",
      "title": "照護與穩定進程",
      "caption": "20到120字的說明文字，說明恢復進程，結尾必須註明恢復程度因人而異需由醫師當面評估。",
      "labels": [
        {{"text": "初期狀態", "tone": "neutral"}},
        {{"text": "逐漸穩定", "tone": "optimal"}}
      ],
      "params": {{
        "milestones": ["初期反應", "逐漸融入", "長期穩定"],
        "unit_effect": "mature",
        "connectors": "vessels",
        "units": 3,
        "unit_fill": "accent"
      }}
    }}
  ]
}}
"""


def _check_no_digits_recursive(data: Any) -> bool:
    """遞迴檢查結構內所有字串皆不含阿拉伯數字。"""
    if isinstance(data, str):
        return not bool(_DIGIT_RE.search(data))
    if isinstance(data, dict):
        return all(_check_no_digits_recursive(k) and _check_no_digits_recursive(v) for k, v in data.items())
    if isinstance(data, list):
        return all(_check_no_digits_recursive(item) for item in data)
    return True


def parse_and_build_tree_ir(
    raw: str,
    topic_key: str,
    fallback_title: str,
) -> Tuple[Optional[dict[str, Any]], str]:
    """解析模型輸出之 JSON 並嚴格檢驗其文字、零污染 params 與 Typed IR 結構。

    回傳：
        (ir, "ok") 或 (None, error_code)
    """
    if not raw or not isinstance(raw, str):
        return None, "empty_output"

    cleaned = _THINK_BLOCK_RE.sub("", raw)
    cleaned = _THINK_OPEN_RE.sub("", cleaned).strip()

    # 嘗試擷取 JSON 字串
    json_str = None
    m = _CODE_BLOCK_RE.search(cleaned)
    if m:
        json_str = m.group(1).strip()
    else:
        # 尋找最外層的 { ... }
        s_idx = cleaned.find("{")
        e_idx = cleaned.rfind("}")
        if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
            json_str = cleaned[s_idx : e_idx + 1].strip()

    if not json_str:
        return None, "schema_error"

    try:
        data = json.loads(json_str)
    except Exception:
        return None, "schema_error"

    if not isinstance(data, dict):
        return None, "schema_error"

    # 檢查頂層欄位
    title = data.get("title") or fallback_title
    if not isinstance(title, str) or not (1 <= len(title) <= 30):
        return None, "schema_error"

    keywords = data.get("keywords")
    if not isinstance(keywords, list) or not (1 <= len(keywords) <= 8):
        return None, "schema_error"

    scenes = data.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 3:
        return None, "schema_error"

    # 嚴格檢查各場景之 blueprint 順序
    expected_blueprints = ["process_diagram", "contrast", "timeline"]
    shaped_scenes = []

    for idx, (expected_bp, sc) in enumerate(zip(expected_blueprints, scenes)):
        if not isinstance(sc, dict):
            return None, "schema_error"
        if sc.get("blueprint") != expected_bp:
            return None, "unknown_blueprint"

        sc_title = sc.get("title")
        if not isinstance(sc_title, str) or not (1 <= len(sc_title) <= 16):
            return None, "schema_error"

        caption = sc.get("caption")
        if not isinstance(caption, str) or not (20 <= len(caption) <= 120):
            return None, "schema_error"

        # 場景 3 必須包含合規收尾語意
        if expected_bp == "timeline":
            if not any(phrase in caption for phrase in _TIMELINE_CLOSING_PHRASES):
                return None, "forbidden_phrase"

        labels = sc.get("labels")
        if not isinstance(labels, list) or not (0 <= len(labels) <= 4):
            return None, "schema_error"
        for lb in labels:
            if not isinstance(lb, dict) or "text" not in lb or "tone" not in lb:
                return None, "schema_error"
            if not (1 <= len(str(lb["text"])) <= 12) or lb["tone"] not in ("neutral", "warning", "optimal"):
                return None, "schema_error"

        # 檢查 params 零預設文字污染（模型必須明確提供所有中文字串）
        raw_params = sc.get("params")
        if not isinstance(raw_params, dict):
            return None, "schema_error"

        if expected_bp == "process_diagram":
            src = raw_params.get("source")
            if not isinstance(src, dict) or not isinstance(src.get("label"), str) or not src["label"].strip():
                return None, "schema_error"
            layers = raw_params.get("container_layers")
            if not isinstance(layers, list) or not (2 <= len(layers) <= 4):
                return None, "schema_error"
            for layer in layers:
                if not isinstance(layer, dict) or not isinstance(layer.get("label"), str) or not layer["label"].strip():
                    return None, "schema_error"
            step_lbls = raw_params.get("step_labels")
            if not isinstance(step_lbls, list) or len(step_lbls) != 3:
                return None, "schema_error"
            for sl in step_lbls:
                if not isinstance(sl, str) or not sl.strip():
                    return None, "schema_error"
            particles = raw_params.get("particles", 6)
            if not isinstance(particles, int) or isinstance(particles, bool) or not (4 <= particles <= 12):
                particles = 6
            shaped_params = {
                "source": {"label": src["label"].strip(), "fill": src.get("fill", "skin")},
                "particles": particles,
                "container_layers": [
                    {
                        "label": l["label"].strip(),
                        "fill": l.get("fill", "accent"),
                        "weight": int(l.get("weight", 2)),
                        "keep": bool(l.get("keep", False)),
                    }
                    for l in layers
                ],
                "step_labels": [s.strip() for s in step_lbls],
            }

        elif expected_bp == "contrast":
            left = raw_params.get("left")
            right = raw_params.get("right")
            if not isinstance(left, dict) or not isinstance(right, dict):
                return None, "schema_error"
            left_req = ["title", "note", "core_label", "footnote"]
            right_req = ["title", "note", "footnote"]
            for req_k in left_req:
                if not isinstance(left.get(req_k), str) or not left[req_k].strip():
                    return None, "schema_error"
            for req_k in right_req:
                if not isinstance(right.get(req_k), str) or not right[req_k].strip():
                    return None, "schema_error"

            rows = right.get("rows", raw_params.get("rows", 3))
            per_row = right.get("per_row", raw_params.get("per_row", 5))
            shaped_params = {
                "left": {
                    "title": left["title"].strip(),
                    "note": left["note"].strip(),
                    "mode": left.get("mode", "mass"),
                    "core_effect": left.get("core_effect", "dim"),
                    "core_label": left["core_label"].strip(),
                    "footnote": left["footnote"].strip(),
                    "unit_fill": left.get("unit_fill", "accent"),
                },
                "right": {
                    "title": right["title"].strip(),
                    "note": right["note"].strip(),
                    "mode": right.get("mode", "layered"),
                    "rows": int(rows) if isinstance(rows, int) and not isinstance(rows, bool) and 1 <= rows <= 4 else 3,
                    "per_row": int(per_row) if isinstance(per_row, int) and not isinstance(per_row, bool) and 3 <= per_row <= 8 else 5,
                    "footnote": right["footnote"].strip(),
                    "unit_fill": right.get("unit_fill", "accent"),
                },
            }

        elif expected_bp == "timeline":
            milestones = raw_params.get("milestones")
            if not isinstance(milestones, list) or len(milestones) != 3:
                return None, "schema_error"
            for m_item in milestones:
                if not isinstance(m_item, str) or not m_item.strip():
                    return None, "schema_error"
            units = raw_params.get("units", 3)
            shaped_params = {
                "milestones": [m_item.strip() for m_item in milestones],
                "unit_effect": raw_params.get("unit_effect", "mature"),
                "connectors": raw_params.get("connectors", "vessels"),
                "units": int(units) if isinstance(units, int) and not isinstance(units, bool) and 2 <= units <= 5 else 3,
                "unit_fill": raw_params.get("unit_fill", "accent"),
            }

        # 檢驗 params 是否符合 Blueprint 規格
        p_ok, p_code = validate_params(expected_bp, shaped_params)
        if not p_ok:
            return None, p_code

        shaped_scenes.append({
            "blueprint": expected_bp,
            "title": sc_title.strip(),
            "caption": caption.strip(),
            "labels": [{"text": lb["text"].strip(), "tone": lb["tone"]} for lb in labels],
            "params": shaped_params,
            "duration_sec": sc.get("duration_sec", 8) if isinstance(sc.get("duration_sec"), int) and 4 <= sc.get("duration_sec", 8) <= 12 else 8,
        })

    candidate_ir = {
        "topic_key": topic_key,
        "title": title.strip(),
        "keywords": [str(k).strip() for k in keywords],
        "scenes": shaped_scenes,
    }

    # 檢查全文字結構（不含 topic_key 識別碼）不含任何阿拉伯數字
    text_Check_payload = {
        "title": candidate_ir["title"],
        "keywords": candidate_ir["keywords"],
        "scenes": candidate_ir["scenes"],
    }
    if not _check_no_digits_recursive(text_Check_payload):
        return None, "forbidden_phrase"

    # 若非自體脂肪主題，嚴禁殘留引擎預設之脂肪移植字面值
    is_fat_topic = ("脂肪" in fallback_title) or ("脂肪" in candidate_ir["title"]) or ("fat" in topic_key)
    if not is_fat_topic:
        scenes_dump = json.dumps(candidate_ir["scenes"], ensure_ascii=False)
        if any(lit in scenes_dump for lit in _FAT_GRAFT_DEFAULT_LITERALS):
            return None, "forbidden_phrase"

    # 完整執行 validate_ir
    ok, code = validate_ir(candidate_ir)
    if not ok:
        return None, code

    return candidate_ir, "ok"


def _default_visual_llm(prompt: str) -> str:
    """預設本地 LLM 呼叫包裝。"""
    return local_llm_call(prompt, timeout=180, sampling=dict(VISUAL_SAMPLING))


def autodraft_from_tree(
    conn: sqlite3.Connection,
    tree_id_or_dict: int | dict[str, Any],
    llm_call: Optional[Callable[[str], str]] = None,
    *,
    max_attempts: int = 2,
    db_path: Any = None,
    commit: bool = True,
) -> dict[str, Any]:
    """由已核准的 PageIndex 推理樹自動生成視覺解說卡草稿並寫入 visual_assets。

    回傳：
        {"status": "ok", "topic_key": ..., "clinic_id": ..., "review_status": "pending", "ir": ...}
        或 {"status": "error"|"busy"|"not_found", "code": ...}
    """
    if isinstance(tree_id_or_dict, int):
        trees = fetch_eligible_trees(conn, tree_id=tree_id_or_dict)
        if not trees:
            # 檢查是否存在但未核准
            cur = conn.cursor()
            cur.execute("SELECT id FROM page_index_trees WHERE id = ?", (tree_id_or_dict,))
            if cur.fetchone() is None:
                return {"status": "not_found", "code": "tree_not_found"}
            return {"status": "error", "code": "tree_not_approved"}
        tree = trees[0]
    elif isinstance(tree_id_or_dict, dict):
        tree = tree_id_or_dict
        # 驗證傳入之 dict 是否符合核准樹條件
        if "id" in tree:
            eligible = fetch_eligible_trees(conn, tree_id=tree["id"])
            if not eligible:
                return {"status": "error", "code": "tree_not_approved"}
    else:
        return {"status": "error", "code": "invalid_argument"}

    doc_id = tree.get("doc_id") or ""
    try:
        topic_key = normalize_tree_topic_key(doc_id)
    except ValueError:
        return {"status": "error", "code": "schema_error"}

    # 排程互斥：確認非夜間批次與行程內鎖
    if nightly_batch_running(db_path):
        return {"status": "busy", "code": "busy"}

    if not GENERATION_LOCK.acquire(blocking=False):
        return {"status": "busy", "code": "busy"}

    act_llm = llm_call or _default_visual_llm
    prompt = build_tree_visual_prompt(tree)
    fallback_title = tree.get("title") or f"{doc_id}手術原理"

    try:
        last_code = "parse_error"
        for _ in range(max(1, max_attempts)):
            try:
                raw_out = act_llm(prompt)
            except LocalLLMUnavailableError:
                return {"status": "error", "code": "llm_unavailable"}
            except LLMTruncatedError:
                last_code = "truncated"
                continue
            except (LLMEmptyOutputError, Exception):
                last_code = "parse_error"
                continue

            ir, code = parse_and_build_tree_ir(raw_out, topic_key=topic_key, fallback_title=fallback_title)
            if ir is None:
                last_code = code
                continue

            # 生成成功，組裝資產資料
            asset = {
                "clinic_id": tree.get("clinic_id"),
                "topic_key": topic_key,
                "title": ir["title"],
                "keywords": ir["keywords"],
                "ir": ir,
                "metadata": {
                    "origin": "pageindex_tree",
                    "tree_id": tree.get("id"),
                    "doc_id": doc_id,
                    "tree_version": tree.get("content_version", 1),
                },
            }

            upsert_res = upsert_assets(conn, [asset], source_type="llm_generated", commit=commit)
            return {
                "status": "ok",
                "topic_key": topic_key,
                "clinic_id": tree.get("clinic_id"),
                "review_status": "pending",
                "ir": ir,
                **upsert_res,
            }

        return {"status": "error", "code": last_code}
    finally:
        GENERATION_LOCK.release()
