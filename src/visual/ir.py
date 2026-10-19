"""
視覺解說卡 Typed IR 規格定義與醫療法規驗證模組 (Phase 29 P29-IR)。

設計原則：
1. 單一權威驗證：所有入庫、審核、展示的視覺 IR 皆呼叫 validate_ir。
2. 零原始文字洩漏：驗證失敗一律回傳結構化英文代碼，丟棄任何含原文的錯誤訊息。
3. 嚴格醫療合規：重用既有政治敏感、保證療效、用藥劑量、價格深度清洗規則，並增補視覺卡專屬禁詞與百分比符號過濾。
4. 自然語言防誤殺：避免單獨「一定」誤殺「一定程度」「不一定」「一定時間」等通用敘述。
"""

from __future__ import annotations

import re
from typing import Any, Tuple

from src.ingestion.generate_faq import validate_single_faq

# IR 規格列舉常數
VALID_BLUEPRINTS: tuple[str, ...] = ("process_diagram", "contrast", "timeline")
VALID_TONES: tuple[str, ...] = ("neutral", "warning", "optimal")

# 視覺解說卡專屬額外禁詞（不含單獨「一定」，防止誤殺「一定程度」「不一定」「一定時間」）
VISUAL_EXTRA_FORBIDDEN: tuple[str, ...] = (
    "永久",
    "終身",
    "一輩子",
    "成為身體一部分",
    "百分之",
    "存活率",
    "保證",
    "一定能",
    "一定會",
    "一定有效",
    "絕對",
    "完全不會",
    "零風險",
)

# 正則規則
_TOPIC_KEY_RE = re.compile(r"^[a-z0-9-]{3,64}$")
_PERCENT_RE = re.compile(r"\d+\s*[%％]")
_URL_RE = re.compile(r"(https?://|www\.|\b://\b)", re.IGNORECASE)
_HTML_RISK_RE = re.compile(r"[<>]")


def validate_visual_text(text: str) -> Tuple[bool, str]:
    """檢驗視覺解說卡中單一字串欄位的安全與合規性。

    回傳：
        (ok, code)，code 為固定英文代碼，不含任何原始輸入文字。
    """
    if not isinstance(text, str):
        return False, "schema_error"

    t = text.strip()
    if not t:
        return False, "schema_error"

    # 1. 禁字元與內容（HTML 標籤字元、網址、javascript）
    if _HTML_RISK_RE.search(t):
        return False, "text_unsafe"
    if _URL_RE.search(t):
        return False, "text_unsafe"
    if "javascript:" in t.lower():
        return False, "text_unsafe"

    # 2. 價格洩漏檢驗（延遲匯入避免與 src.api.__init__ 產生循環匯入）
    from src.api.routes.query import deep_mask_prices

    if deep_mask_prices(t) != t:
        return False, "price_leak"

    # 3. 視覺解說卡額外禁詞與百分比數字
    if _PERCENT_RE.search(t):
        return False, "forbidden_phrase"

    for phrase in VISUAL_EXTRA_FORBIDDEN:
        if phrase in t:
            return False, "forbidden_phrase"

    # 4. 重用既有 validate_single_faq 檢驗（劑量處方、簡體中文、政治立場、通用保證療效）
    val_ok, reason = validate_single_faq(
        {"question": "視覺解說文字檢驗", "answer": t},
        check_dosage=True,
        require_doctor_warning=False,
    )

    if not val_ok:
        # 解析 reason 並轉換為結構化代碼，徹底丟棄 reason 原文
        r_str = reason or ""
        if "具體金額或價格" in r_str:
            return False, "price_leak"
        elif "簡體中文" in r_str:
            return False, "simplified_chinese"
        elif "政治立場" in r_str or "違規禁詞" in r_str:
            return False, "forbidden_phrase"
        elif "用藥劑量或處方" in r_str:
            return False, "dosage_prescription"
        else:
            return False, "text_unsafe"

    return True, "ok"


def validate_ir(ir: Any) -> Tuple[bool, str]:
    """檢驗整份視覺解說卡 Typed IR 的結構完整性與內容合規性。

    回傳：
        (ok, code)，code 為固定列舉代碼：
        - 'ok': 完全合格
        - 'schema_error': 結構、鍵名、長度或型別不符
        - 'unknown_blueprint': 未知場景模板
        - 'text_unsafe': 含 HTML 標籤、網址或不安全腳本
        - 'forbidden_phrase': 含保證療效、政治爭議、存活率、百分比等禁詞
        - 'price_leak': 檢出具體金額或價格數字
        - 'simplified_chinese': 檢出簡體中文
        - 'dosage_prescription': 檢出用藥劑量或處方
        - 'param_error': 參數規格或時長不符
    """
    if not isinstance(ir, dict):
        return False, "schema_error"

    # 頂層鍵集合嚴格驗證（不允許任何額外欄位）
    if set(ir.keys()) != {"topic_key", "title", "keywords", "scenes"}:
        return False, "schema_error"

    # 1. topic_key
    topic_key = ir.get("topic_key")
    if not isinstance(topic_key, str) or not _TOPIC_KEY_RE.match(topic_key):
        return False, "schema_error"

    # 2. title
    title = ir.get("title")
    if not isinstance(title, str) or not (1 <= len(title) <= 30):
        return False, "schema_error"
    t_ok, t_code = validate_visual_text(title)
    if not t_ok:
        return False, t_code

    # 3. keywords
    keywords = ir.get("keywords")
    if not isinstance(keywords, list) or not (1 <= len(keywords) <= 8):
        return False, "schema_error"
    for kw in keywords:
        if not isinstance(kw, str) or not (2 <= len(kw) <= 12):
            return False, "schema_error"
        kw_ok, kw_code = validate_visual_text(kw)
        if not kw_ok:
            return False, kw_code

    # 4. scenes
    scenes = ir.get("scenes")
    if not isinstance(scenes, list) or not (3 <= len(scenes) <= 5):
        return False, "schema_error"

    required_keys = {"blueprint", "title", "caption", "labels"}
    allowed_optional = {"params", "duration_sec"}

    for scene in scenes:
        if not isinstance(scene, dict):
            return False, "schema_error"
        scene_keys = set(scene.keys())
        if not required_keys.issubset(scene_keys) or not scene_keys.issubset(required_keys | allowed_optional):
            return False, "schema_error"

        # blueprint
        blueprint = scene.get("blueprint")
        if not isinstance(blueprint, str) or blueprint not in VALID_BLUEPRINTS:
            return False, "unknown_blueprint"

        # duration_sec（選填，4..12 整數）
        if "duration_sec" in scene:
            dur = scene["duration_sec"]
            if not isinstance(dur, int) or isinstance(dur, bool) or not (4 <= dur <= 12):
                return False, "param_error"

        # params（選填，委派 blueprints.validate_params 檢驗）
        if "params" in scene:
            from src.visual.blueprints import validate_params

            p_ok, p_code = validate_params(blueprint, scene["params"])
            if not p_ok:
                return False, p_code

        # scene title
        stitle = scene.get("title")
        if not isinstance(stitle, str) or not (1 <= len(stitle) <= 16):
            return False, "schema_error"
        st_ok, st_code = validate_visual_text(stitle)
        if not st_ok:
            return False, st_code

        # scene caption
        caption = scene.get("caption")
        if not isinstance(caption, str) or not (20 <= len(caption) <= 120):
            return False, "schema_error"
        c_ok, c_code = validate_visual_text(caption)
        if not c_ok:
            return False, c_code

        # labels
        labels = scene.get("labels")
        if not isinstance(labels, list) or not (0 <= len(labels) <= 4):
            return False, "schema_error"

        for label in labels:
            if not isinstance(label, dict):
                return False, "schema_error"
            if set(label.keys()) != {"text", "tone"}:
                return False, "schema_error"

            tone = label.get("tone")
            if not isinstance(tone, str) or tone not in VALID_TONES:
                return False, "schema_error"

            ltext = label.get("text")
            if not isinstance(ltext, str) or not (1 <= len(ltext) <= 12):
                return False, "schema_error"
            lt_ok, lt_code = validate_visual_text(ltext)
            if not lt_ok:
                return False, lt_code

    return True, "ok"
