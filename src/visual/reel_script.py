"""Phase 56-01: Ornith-1.5-35B 結構化短影音腳本生成、醫療合規檢核與確定性降級。"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from typing import Any, Callable, List, Literal, Optional, Tuple

import httpx
from pydantic import BaseModel, Field

from src.api.routes.query import deep_mask_prices
from src.general.disclaimer import DISCLAIMER_TEXT
from src.ingestion.convert_chinese import to_traditional
from src.pageindex.prompt_template import _FORBIDDEN_PHRASES, _POLITICAL_STANCE_PHRASES

logger = logging.getLogger("clinicbrain.reel_script")

DEFAULT_ORNITH_URL = "http://127.0.0.1:8080/v1/chat/completions"
DEFAULT_REEL_DISCLAIMER = "本解說僅供衛教參考，實際療程與處置需由專科醫師親自評估"

_EXTRA_GUARANTEE_TERMS = (
    "保證",
    "根治",
    "根除",
    "永久",
    "永久有效",
    "絕對安全",
    "100%",
    "百分之百",
)
_PERCENT_RE = re.compile(r"(?:\d+(?:\.\d+)?\s*[%％]|百分之[一二三四五六七八九十百零兩\d]+)")
_PRICE_RE = re.compile(
    r"(?:NT\$|NTD|\$\s*\d+|\d[\d,]*\s*(?:元|塊)|新台幣\s*\d+|費用|價格|收費|價錢)",
    re.IGNORECASE,
)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


class ReelScript(BaseModel):
    """短影音結構化腳本（由 Ornith-1.5-35B 或確定性降級產出）。"""

    topic_key: str = Field(..., min_length=1)
    hook_title: str = Field(..., min_length=2, max_length=32)
    badge: str = Field(..., min_length=1, max_length=24)
    summary_points: List[str] = Field(..., min_length=1, max_length=4)
    narration_lines: List[str] = Field(..., min_length=1, max_length=5)
    cta_text: str = Field(default="門診諮詢預約", min_length=2, max_length=24)
    disclaimer: str = Field(default=DEFAULT_REEL_DISCLAIMER, min_length=10)
    source: Literal["ornith", "fallback"] = "fallback"


def _derive_badge(topic_key: str) -> str:
    if topic_key.startswith("icd-"):
        parts = topic_key.split("-")
        if len(parts) >= 2 and parts[1]:
            return f"ICD-10: {parts[1].upper()}"
    return "衛教精選"


def _sanitize_text(text: str) -> str:
    cleaned = to_traditional((text or "").strip())
    cleaned = deep_mask_prices(cleaned)
    cleaned = _PERCENT_RE.sub("部分比例", cleaned)
    for kw in _EXTRA_GUARANTEE_TERMS:
        if kw in cleaned:
            cleaned = cleaned.replace(kw, "")
    return re.sub(r"\s+", " ", cleaned).strip()


def validate_reel_script(script: ReelScript) -> Tuple[bool, List[str]]:
    """檢查 ReelScript 是否符合台灣醫療法規（零價格、零百分比、無保證療效、繁中與免責聲明）。"""
    errors: List[str] = []

    if not script.disclaimer or len(script.disclaimer.strip()) < 10:
        errors.append("缺少醫療免責聲明")
    elif "衛教" not in script.disclaimer and "醫師" not in script.disclaimer and DISCLAIMER_TEXT[:6] not in script.disclaimer:
        errors.append("免責聲明內容不完整")

    all_texts = [
        script.hook_title,
        script.badge,
        script.cta_text,
        script.disclaimer,
        *script.summary_points,
        *script.narration_lines,
    ]
    joined = "\n".join(t for t in all_texts if t)

    if _PERCENT_RE.search(joined):
        errors.append("含禁止之百分比或中文分數百分比描述")

    if _PRICE_RE.search(joined) or deep_mask_prices(joined) != joined:
        errors.append("含禁止之價格或收費資訊")

    forbidden = set(_FORBIDDEN_PHRASES) | set(_EXTRA_GUARANTEE_TERMS)
    for kw in forbidden:
        if kw and kw in joined:
            errors.append(f"含保證療效或禁止詞彙: {kw}")

    for kw in _POLITICAL_STANCE_PHRASES:
        if kw and kw in joined:
            errors.append(f"含政治敏感詞彙: {kw}")

    # 檢查是否有明顯簡體字殘留（以 to_traditional 轉換前後差異檢查常見簡體字元）
    if to_traditional(joined) != joined:
        # 排除常見台/臺異體字差異
        norm_src = joined.replace("台", "臺")
        norm_trad = to_traditional(joined).replace("台", "臺")
        if norm_src != norm_trad:
            errors.append("偵測到簡體字殘留，必須全繁體中文")

    return (len(errors) == 0, errors)


def _load_asset_row(conn: sqlite3.Connection, topic_key: str) -> Tuple[str, dict[str, Any], dict[str, Any]]:
    row = conn.execute(
        "SELECT title, ir_json, edu_json FROM visual_assets WHERE topic_key = ?",
        (topic_key,),
    ).fetchone()
    if not row:
        raise ValueError(f"clinic.db 找不到視覺資產: {topic_key}")
    title = row[0] or topic_key
    ir_data = json.loads(row[1]) if isinstance(row[1], str) and row[1].strip() else (row[1] or {})
    edu_data = json.loads(row[2]) if isinstance(row[2], str) and row[2].strip() else (row[2] or {})
    return title, ir_data, edu_data


def build_fallback_reel_script(conn: sqlite3.Connection, topic_key: str) -> ReelScript:
    """從 clinic.db 的 visual_assets.ir_json 與 edu_json 確定性組裝合規腳本。"""
    title, ir_data, edu_data = _load_asset_row(conn, topic_key)

    scenes = ir_data.get("scenes") if isinstance(ir_data, dict) else []
    captions: List[str] = []
    if isinstance(scenes, list):
        for sc in scenes[:3]:
            if isinstance(sc, dict):
                cap = _sanitize_text(str(sc.get("caption") or sc.get("title") or ""))
                if cap:
                    captions.append(cap[:80])

    # 嘗試從 edu_json.red_flags_takeaway.takeaway 或 scenes[2].params.takeaway 萃取重點
    takeaway = ""
    if isinstance(edu_data, dict):
        rft = edu_data.get("red_flags_takeaway")
        if isinstance(rft, dict) and rft.get("takeaway"):
            takeaway = _sanitize_text(str(rft["takeaway"]))
    if not takeaway and isinstance(scenes, list) and len(scenes) >= 3 and isinstance(scenes[2], dict):
        params = scenes[2].get("params") or {}
        if isinstance(params, dict) and params.get("takeaway"):
            takeaway = _sanitize_text(str(params["takeaway"]))

    if not captions:
        captions = [
            _sanitize_text(f"{title}之臨床機轉與常見成因說明"),
            _sanitize_text("病症程度差異與臨床處置重點對照"),
            takeaway or _sanitize_text("維持規律作息，若症狀持續請及早由專科醫師評估"),
        ]

    summary_points: List[str] = []
    if isinstance(scenes, list):
        for sc in scenes[:3]:
            if isinstance(sc, dict) and sc.get("title"):
                pt = _sanitize_text(str(sc["title"]))[:20]
                if pt:
                    summary_points.append(pt)
    if not summary_points:
        summary_points = [_sanitize_text(title)[:20], "由專科醫師親自評估"]

    hook_title = _sanitize_text(title)[:28] or "臨床衛教解說"
    return ReelScript(
        topic_key=topic_key,
        hook_title=hook_title,
        badge=_derive_badge(topic_key),
        summary_points=summary_points[:3],
        narration_lines=captions[:3],
        cta_text="門診諮詢預約",
        disclaimer=DEFAULT_REEL_DISCLAIMER,
        source="fallback",
    )


def _default_ornith_call(prompt: str, llm_url: str, timeout_sec: float) -> str:
    resp = httpx.post(
        llm_url,
        json={
            "model": "Ornith-1.5-35B",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是台灣診所醫學衛教短影音編劇。請僅輸出合法 JSON，全繁體中文，"
                        "嚴禁價格、百分比（含%與百分之）、保證療效或簡體字。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 1200,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _parse_ornith_json(raw: str, topic_key: str) -> ReelScript:
    text = (raw or "").strip()
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    text = _CODE_FENCE_RE.sub("", text).strip()
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        raise ValueError("Ornith 回傳內容未包含合法 JSON")
    data = json.loads(text[s : e + 1])

    hook_title = to_traditional(str(data.get("hook_title") or "")).strip()
    badge = to_traditional(str(data.get("badge") or _derive_badge(topic_key))).strip()
    summary_points = [to_traditional(str(x)).strip() for x in (data.get("summary_points") or []) if str(x).strip()]
    narration_lines = [to_traditional(str(x)).strip() for x in (data.get("narration_lines") or []) if str(x).strip()]
    cta_text = to_traditional(str(data.get("cta_text") or "門診諮詢預約")).strip()

    return ReelScript(
        topic_key=topic_key,
        hook_title=hook_title,
        badge=badge,
        summary_points=summary_points[:3],
        narration_lines=narration_lines[:3],
        cta_text=cta_text,
        disclaimer=DEFAULT_REEL_DISCLAIMER,
        source="ornith",
    )


def generate_reel_script(
    conn: sqlite3.Connection,
    topic_key: str,
    llm_url: str = DEFAULT_ORNITH_URL,
    timeout_sec: float = 45.0,
    use_llm: bool = True,
    llm_caller: Optional[Callable[[str], str]] = None,
) -> ReelScript:
    """呼叫 Ornith-1.5-35B 產出結構化 JSON 腳本，失敗或違規時重試 1 次或降級至確定性版本。"""
    if not use_llm:
        return build_fallback_reel_script(conn, topic_key)

    title, ir_data, edu_data = _load_asset_row(conn, topic_key)
    scenes_brief = [
        {"title": sc.get("title"), "caption": sc.get("caption")}
        for sc in (ir_data.get("scenes") or [])[:3]
        if isinstance(sc, dict)
    ]
    takeaway = ""
    if isinstance(edu_data, dict) and isinstance(edu_data.get("red_flags_takeaway"), dict):
        takeaway = str(edu_data["red_flags_takeaway"].get("takeaway") or "")

    base_prompt = (
        f"主題：{title}（{topic_key}）\n"
        f"3 幕醫學結構：{json.dumps(scenes_brief, ensure_ascii=False)}\n"
        f"衛教總結：{takeaway}\n\n"
        "請產出 JSON 物件，欄位：\n"
        '- "hook_title": 18字內繁體中文吸睛標題\n'
        '- "badge": 簡短標籤（如 ICD-10 代碼）\n'
        '- "summary_points": 3 個重點字串（每個 16 字內）\n'
        '- "narration_lines": 3 句口白（對應 3 幕，每句 25~45 字）\n'
        '- "cta_text": "門診諮詢預約"\n'
        "合規要求：全繁體中文、嚴禁價格數字、嚴禁百分比（%或百分之）、嚴禁保證/根治/永久等療效字眼。"
    )

    caller = llm_caller or (lambda p: _default_ornith_call(p, llm_url, timeout_sec))
    prompt = base_prompt

    for attempt in range(2):
        try:
            raw = caller(prompt)
            script = _parse_ornith_json(raw, topic_key)
            ok, errs = validate_reel_script(script)
            if ok:
                return script
            logger.warning("Ornith 腳本合規檢核未通過 (attempt=%d): %s", attempt + 1, errs)
            if attempt == 0:
                prompt = base_prompt + f"\n\n【修正要求】前次輸出違規：{'; '.join(errs)}，請修正後重新輸出純 JSON。"
        except Exception as exc:
            logger.warning("Ornith 呼叫或解析失敗 (attempt=%d): %s", attempt + 1, exc)
            break

    return build_fallback_reel_script(conn, topic_key)
