"""共用的價格遮蔽工具模組（零業務依賴，避免循環匯入）。"""

from __future__ import annotations

import re
from typing import Any

# 絕對禁止出現的價格格式：數字+元/塊，或 NT$/$ 開頭的金額
_PRICE_PATTERN = re.compile(r"\d+\s*[元塊]|NT\$\s*\d+|\$\d+")
_PRICE_MASK = "[請致電診所確認]"


def mask_prices(text: str) -> str:
    """把任何形式的價格資訊替換成統一的引導文字。這是 CONSTRAINT 的最後
    一道防線，任何要回傳給使用者的文字都應該先經過這裡。"""
    if not text:
        return text
    return _PRICE_PATTERN.sub(_PRICE_MASK, text)


def deep_mask_prices(obj: Any) -> Any:
    """遞迴對所有巢狀資料結構（字串、字典、串列）執行價格遮蔽。
    這是在 API 序列化回傳前的二次安全防禦層，保證任何深層文字無金額數字洩漏。
    """
    if isinstance(obj, str):
        return mask_prices(obj)
    if isinstance(obj, dict):
        return {k: deep_mask_prices(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_mask_prices(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(deep_mask_prices(item) for item in obj)
    return obj
