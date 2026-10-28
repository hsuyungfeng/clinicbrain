"""醫師改寫覆寫（physician overrides）：只替換來源頁中完全相符的句子。

規則（fail-closed）：
- 覆寫檔不存在 → 視為沒有覆寫。
- 覆寫檔格式錯誤 → 拋出 OverrideError，呼叫端回報 drift，不略過。
- 覆寫的 find 必須在來源說明中完全相符；找不到即回報 missing，不靜默略過。
- 覆寫不繞過任何合規檢查：替換後的文字仍須通過草稿建置的所有規則（DX、禁詞、價格等）。
- 每筆覆寫需附 review_ref（醫師審核依據，如日期或審核單號），供追溯。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

DEFAULT_OVERRIDES_PATH = Path(__file__).resolve().parents[2] / "data" / "scraper" / "physician_overrides.json"


class OverrideError(ValueError):
    """覆寫檔格式錯誤。"""


def load_physician_overrides(path: Union[str, Path]) -> dict[str, list[dict[str, str]]]:
    """載入覆寫檔，依 URL 路徑分組。檔案不存在回傳空字典。"""
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise OverrideError("覆寫檔無法解析") from e
    entries = data.get("overrides") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise OverrideError("覆寫檔必須包含 overrides 清單")

    grouped: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise OverrideError("覆寫項目格式錯誤")
        path_key = entry.get("path")
        find = entry.get("find")
        replace = entry.get("replace")
        review_ref = entry.get("review_ref")
        if not all(isinstance(v, str) and v.strip() for v in (path_key, find, replace, review_ref)):
            raise OverrideError("覆寫項目缺少 path／find／replace／review_ref")
        if not path_key.startswith("/service-detail/"):
            raise OverrideError("覆寫僅適用於服務詳細頁路徑")
        grouped.setdefault(path_key, []).append({"find": find, "replace": replace})
    return grouped


def apply_overrides(description: str, overrides: list[dict[str, str]]) -> tuple[str, list[str]]:
    """套用覆寫，回傳 (新說明, 找不到的 find 清單)。"""
    text = description
    missing: list[str] = []
    for item in overrides:
        if item["find"] in text:
            text = text.replace(item["find"], item["replace"], 1)
        else:
            missing.append(item["find"])
    return text, missing
