"""
視覺解說卡本地 LLM 預生成器模組 (generator)。
Phase 29: P29-GEN

設計原則：
1. 結構鎖死（Typed IR）：blueprint、場景標題、labels、keywords、topic_key 全由人工撰寫之骨架檔決定，
   LLM 僅負責填寫各場景的 caption 純文字，模型輸出無法改變任何結構欄位。
2. 禁詞常數同步：提示詞中的禁用詞清單直接由 ir.VISUAL_EXTRA_FORBIDDEN 動態組裝，單一來源不重複維護。
3. 嚴格驗證與重試上限：模型輸出組成 IR 後經 validate_ir（及無數字檢核）全數通過才回傳；最多嘗試 2 次。
4. 排程互斥：生成前非阻塞取得 GENERATION_LOCK 且確認 nightly_batch_running 為 False，絕不並行爭搶 GPU。
5. 零原文外洩：失敗回傳固定英文代碼，不回傳、不記錄模型輸出原文。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
from typing import Any, Callable, Optional, Tuple

from src.pageindex.llm_client import (
    LLMEmptyOutputError,
    LLMTruncatedError,
    LocalLLMUnavailableError,
)
from src.pageindex.llm_lock import GENERATION_LOCK, nightly_batch_running
from .ir import (
    VALID_BLUEPRINTS,
    VALID_TONES,
    VISUAL_EXTRA_FORBIDDEN,
    validate_ir,
    validate_visual_text,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SKELETON_DIR = PROJECT_ROOT / "data" / "visual" / "skeletons"

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
_SCENE_LINE_RE = re.compile(r"^\s*場景\s*(\d+)\s*[:：]\s*(.+?)\s*$")
_DIGIT_RE = re.compile(r"\d")


def _validate_skeleton_text(text: str) -> Tuple[bool, str]:
    """檢驗骨架與場景文字：除 validate_visual_text 外，額外禁止任何阿拉伯數字。"""
    ok, code = validate_visual_text(text)
    if not ok:
        return False, code
    if _DIGIT_RE.search(text):
        return False, "forbidden_phrase"
    return True, "ok"


def load_skeleton(path: Path | str) -> dict[str, Any]:
    """載入並嚴格驗證視覺解說卡骨架檔。

    不通過時拋出 ValueError（只帶代碼，不洩漏原文）。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"找不到骨架檔案：{p}")

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError("骨架 JSON 解析失敗: schema_error") from e

    if not isinstance(data, dict):
        raise ValueError("骨架格式錯誤: schema_error")

    required_keys = {"topic_key", "title", "keywords", "scenes", "reference"}
    if set(data.keys()) != required_keys:
        raise ValueError("骨架欄位集合不符: schema_error")

    topic_key = data.get("topic_key")
    if not isinstance(topic_key, str) or not re.match(r"^[a-z0-9-]{3,64}$", topic_key):
        raise ValueError("骨架 topic_key 不合規: schema_error")

    title = data.get("title")
    if not isinstance(title, str) or not (1 <= len(title) <= 30):
        raise ValueError("骨架 title 長度不符: schema_error")
    ok, code = _validate_skeleton_text(title)
    if not ok:
        raise ValueError(f"骨架 title 驗證失敗: {code}")

    keywords = data.get("keywords")
    if not isinstance(keywords, list) or not (1 <= len(keywords) <= 8):
        raise ValueError("骨架 keywords 數量不符: schema_error")
    for kw in keywords:
        if not isinstance(kw, str) or not (2 <= len(kw) <= 12):
            raise ValueError("骨架 keyword 長度不符: schema_error")
        ok, code = _validate_skeleton_text(kw)
        if not ok:
            raise ValueError(f"骨架 keyword 驗證失敗: {code}")

    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not (3 <= len(scenes) <= 5):
        raise ValueError("骨架 scenes 數量不符: schema_error")

    scene_required_keys = {"blueprint", "title", "labels"}
    scene_allowed_optional = {"params", "duration_sec"}

    for sc in scenes:
        if not isinstance(sc, dict):
            raise ValueError("骨架 scene 欄位不符: schema_error")
        sc_keys = set(sc.keys())
        if not scene_required_keys.issubset(sc_keys) or not sc_keys.issubset(scene_required_keys | scene_allowed_optional):
            raise ValueError("骨架 scene 欄位不符: schema_error")
        if sc["blueprint"] not in VALID_BLUEPRINTS:
            raise ValueError("骨架 blueprint 不合規: unknown_blueprint")

        if "duration_sec" in sc:
            dur = sc["duration_sec"]
            if not isinstance(dur, int) or isinstance(dur, bool) or not (4 <= dur <= 12):
                raise ValueError("骨架 scene duration_sec 不合規: param_error")

        if "params" in sc:
            from src.visual.blueprints import validate_params

            p_ok, p_code = validate_params(sc["blueprint"], sc["params"])
            if not p_ok:
                raise ValueError(f"骨架 scene params 驗證失敗: {p_code}")

        stitle = sc["title"]
        if not isinstance(stitle, str) or not (1 <= len(stitle) <= 16):
            raise ValueError("骨架 scene title 長度不符: schema_error")
        ok, code = _validate_skeleton_text(stitle)
        if not ok:
            raise ValueError(f"骨架 scene title 驗證失敗: {code}")

        labels = sc["labels"]
        if not isinstance(labels, list) or not (0 <= len(labels) <= 4):
            raise ValueError("骨架 labels 數量不符: schema_error")
        for lb in labels:
            if not isinstance(lb, dict) or set(lb.keys()) != {"text", "tone"}:
                raise ValueError("骨架 label 欄位不符: schema_error")
            if lb["tone"] not in VALID_TONES:
                raise ValueError("骨架 label tone 不合規: schema_error")
            ltext = lb["text"]
            if not isinstance(ltext, str) or not (1 <= len(ltext) <= 12):
                raise ValueError("骨架 label text 長度不符: schema_error")
            ok, code = _validate_skeleton_text(ltext)
            if not ok:
                raise ValueError(f"骨架 label text 驗證失敗: {code}")

    reference = data.get("reference")
    if not isinstance(reference, list) or not (4 <= len(reference) <= 6):
        raise ValueError("骨架 reference 數量不符（須為 4～6 條）: schema_error")
    for ref_line in reference:
        if not isinstance(ref_line, str) or not ref_line.strip():
            raise ValueError("骨架 reference 內容為空: schema_error")
        ok, code = _validate_skeleton_text(ref_line)
        if not ok:
            raise ValueError(f"骨架 reference 驗證失敗: {code}")

    return data


def build_prompt(skeleton: dict[str, Any]) -> str:
    """根據骨架組裝 LLM 提示詞，禁用詞表直接由 VISUAL_EXTRA_FORBIDDEN 同步組出。"""
    scenes = skeleton["scenes"]
    n_scenes = len(scenes)
    ref_text = "\n".join(f"- {r}" for r in skeleton["reference"])
    forbidden_joined = "、".join(VISUAL_EXTRA_FORBIDDEN)

    scene_specs = []
    for idx, sc in enumerate(scenes, 1):
        lbl_str = "／".join(lb["text"] for lb in sc.get("labels", []))
        scene_specs.append(f"場景{idx}（標題：{sc['title']}；關鍵標籤：{lbl_str}）")
    scene_list_text = "\n".join(scene_specs)

    format_lines = "\n".join(f"場景{i}：（請填寫 20 至 120 字之繁體中文說明）" for i in range(1, n_scenes + 1))

    return f"""你是台灣專業醫療衛教編輯。請根據以下【參考概念要點】，為「{skeleton['title']}」視覺解說卡的 {n_scenes} 個場景撰寫簡短說明文字。

【參考概念要點】：
{ref_text}

【待撰寫場景】：
{scene_list_text}

【嚴格生成規則】：
1. 只輸出 {n_scenes} 行純文字，每行固定以「場景1：」「場景2：」…開頭，不要輸出 JSON、不要標題、不要前言或結語。
2. 每個場景的說明文字長度必須介於 20 至 120 字之間，使用台灣繁體中文，語氣為一般醫學衛教說明、非個人化診斷。
3. 說明內容只能依據上方【參考概念要點】，不得憑空捏造。
4. 嚴格禁用詞彙（出現任一詞即整份作廢）：{forbidden_joined}。
5. 嚴格禁止出現任何阿拉伯數字、百分比符號（%或％）、具體金額或價格、網址、HTML 標籤或用藥劑量。
6. 替代用語指引：涉及效果或留存請以「因人而異」「實際狀況由醫師評估」表達；涉及恢復或時間請以「一段時間」「逐步適應」表達。

【輸出格式】：
{format_lines}
"""


def parse_output(raw: str, n_scenes: int) -> Optional[list[str]]:
    """清理 think 標籤並解析模型輸出的各場景說明行。

    若數量不符、缺行或夾帶多餘場景編號，回傳 None。
    """
    if not raw or not isinstance(raw, str) or n_scenes <= 0:
        return None

    cleaned = _THINK_BLOCK_RE.sub("", raw)
    cleaned = _THINK_OPEN_RE.sub("", cleaned).strip()
    if not cleaned:
        return None

    found: dict[int, str] = {}
    for line in cleaned.splitlines():
        line_s = line.strip()
        if not line_s:
            continue
        m = _SCENE_LINE_RE.match(line_s)
        if m:
            idx = int(m.group(1))
            text = m.group(2).strip()
            # 若出現超出範圍的場景編號或重複編號，視為格式不合規拒絕
            if idx < 1 or idx > n_scenes or idx in found:
                return None
            found[idx] = text

    if len(found) != n_scenes:
        return None

    return [found[i] for i in range(1, n_scenes + 1)]


def generate_ir(
    skeleton: dict[str, Any],
    llm_call: Callable[[str], str],
    max_attempts: int = 2,
    db_path: Any = None,
) -> Tuple[Optional[dict[str, Any]], str]:
    """以骨架搭配本地 LLM 產出完整 Typed IR 並通過 validate_ir 驗證。

    回傳：
        (ir, "ok") 或 (None, error_code)
    """
    if max_attempts < 1:
        max_attempts = 1

    # 排程互斥：檢查夜間批次檔案鎖與行程內 GENERATION_LOCK
    if nightly_batch_running(db_path):
        return None, "busy"

    if not GENERATION_LOCK.acquire(blocking=False):
        return None, "busy"

    try:
        prompt = build_prompt(skeleton)
        n_scenes = len(skeleton["scenes"])
        last_code = "parse_error"

        for _ in range(max_attempts):
            try:
                raw = llm_call(prompt)
            except LocalLLMUnavailableError:
                return None, "llm_unavailable"
            except LLMTruncatedError:
                last_code = "truncated"
                continue
            except (LLMEmptyOutputError, Exception):
                last_code = "parse_error"
                continue

            captions = parse_output(raw, n_scenes)
            if captions is None:
                last_code = "parse_error"
                continue

            # 組裝 IR：結構欄位 100% 複製自骨架，模型只能填入 caption
            ir_scenes = []
            for sc_skel, cap in zip(skeleton["scenes"], captions):
                scene_dict = {
                    "blueprint": sc_skel["blueprint"],
                    "title": sc_skel["title"],
                    "caption": cap,
                    "labels": copy.deepcopy(sc_skel["labels"]),
                }
                if "duration_sec" in sc_skel:
                    scene_dict["duration_sec"] = sc_skel["duration_sec"]
                if "params" in sc_skel:
                    scene_dict["params"] = copy.deepcopy(sc_skel["params"])
                ir_scenes.append(scene_dict)

            candidate_ir = {
                "topic_key": skeleton["topic_key"],
                "title": skeleton["title"],
                "keywords": list(skeleton["keywords"]),
                "scenes": ir_scenes,
            }

            ok, code = validate_ir(candidate_ir)
            if not ok:
                last_code = code
                continue

            # 額外檢查 caption 不得含任何阿拉伯數字
            if any(_DIGIT_RE.search(c) for c in captions):
                last_code = "forbidden_phrase"
                continue

            return candidate_ir, "ok"

        return None, last_code
    finally:
        GENERATION_LOCK.release()
