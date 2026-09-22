#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 簡繁中文轉換模組 (convert_chinese)
Phase 03 Document Ingestion Stage 1: TASK-02

規範：
- 使用 opencc 的 's2twp' 配置（簡體到台灣正體，含台灣本地醫療與生活慣用詞轉換，如「软件」→「軟體」）。
- 嚴格遵守 AGENTS.md 繁體中文鐵則。
"""

from typing import Optional
import opencc

# 快取 OpenCC 物件，避免重複初始化負載
_CONVERTER: Optional[opencc.OpenCC] = None


def _get_converter() -> opencc.OpenCC:
    global _CONVERTER
    if _CONVERTER is None:
        _CONVERTER = opencc.OpenCC("s2twp")
    return _CONVERTER


def to_traditional(text: str) -> str:
    """將簡體中文字串轉換為台灣正體（繁體中文），並套用台灣慣用語對照。

    參數:
        text: 待轉換文字
    回傳:
        轉換後之繁體中文字串；若輸入為空則回傳原字串。
    """
    if not text:
        return text
    converter = _get_converter()
    return converter.convert(text)
