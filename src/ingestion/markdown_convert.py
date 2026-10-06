#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 檔案轉 Markdown 前處理器 (markdown_convert)

以 Microsoft markitdown 把 docx / xlsx / pdf / pptx 轉成保留表格與清單結構的 Markdown，
供文件擷取管線後續切塊與 FAQ 生成使用（補強 extract_text.py：新增 pdf/pptx、表格保留為 Markdown 表格）。

使用順序（重要）：
    convert_to_markdown → convert_chinese.to_traditional（簡轉繁）→ 價格屏蔽／去識別化 → 切塊 → generate_faq
本模組只負責第一步，不做簡繁轉換、不做價格屏蔽。

純本地推理限制（AGENTS.md）：
- 只接受本機檔案路徑；拒絕 http(s)/file/data URI。
- 不啟用 markitdown 外掛，不傳入任何 LLM／雲端 Document Intelligence 客戶端
  （圖片描述、音訊轉錄皆需外部服務，一律不使用）。
- 內嵌圖片（base64 data URI）一律濾除，不得進入提示詞。
- 僅含文字層的 PDF 可轉換；掃描檔會得到空內容並拋出 MarkdownConvertError（本模組無 OCR）。

markitdown 為選用依賴：
    uv pip install "markitdown[docx,xlsx,pdf,pptx]"
"""

from pathlib import Path
import re
import zipfile
from typing import Union

SUPPORTED_SUFFIXES = frozenset({".docx", ".xlsx", ".pdf", ".pptx"})
_URI_PREFIXES = ("http:", "https:", "file:", "data:", "ftp:")
_EMBEDDED_IMAGE = re.compile(r"!\[[^\]]*\]\(data:[^)]*\)")


class MarkdownConvertError(Exception):
    """檔案轉 Markdown 失敗（不含檔案內容，避免洩漏病患或診所資料）。"""


def _looks_like_declared_format(file_path: Path) -> bool:
    """檢查檔頭是否與副檔名相符。

    markitdown 對格式不符的檔案會退回「純文字」模式並回傳亂碼內容而不報錯
    （例如 Word 暫存鎖檔 ~$xxx.docx 只有 162 位元組），必須先擋下。
    """
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        with open(file_path, "rb") as f:
            return f.read(5) == b"%PDF-"
    return zipfile.is_zipfile(file_path)  # docx / xlsx / pptx 皆為 zip 容器


def strip_embedded_images(markdown: str) -> str:
    """移除內嵌 base64 圖片，並收斂過多空行。"""
    text = _EMBEDDED_IMAGE.sub("", markdown)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def convert_to_markdown(path: Union[str, Path]) -> str:
    """把本機 docx/xlsx/pdf/pptx 轉成 Markdown 字串。

    例外一律包成 MarkdownConvertError（訊息不含檔案內容）。
    """
    if isinstance(path, str) and path.strip().lower().startswith(_URI_PREFIXES):
        raise MarkdownConvertError("僅允許本機檔案路徑，不接受網址或 data URI")

    file_path = Path(path)
    if not file_path.is_file():
        raise MarkdownConvertError(f"找不到檔案: {file_path.name}")
    if file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise MarkdownConvertError(
            f"不支援的檔案格式: {file_path.suffix or '(無副檔名)'}，僅支援 {sorted(SUPPORTED_SUFFIXES)}"
        )

    if not _looks_like_declared_format(file_path):
        raise MarkdownConvertError(f"檔案內容與副檔名不符或已損毀 ({file_path.name})，可能是 Office 暫存鎖檔")

    try:
        import markitdown
    except ImportError as e:
        raise MarkdownConvertError(
            'markitdown 未安裝，請執行: uv pip install "markitdown[docx,xlsx,pdf,pptx]"'
        ) from e

    try:
        converter = markitdown.MarkItDown(enable_plugins=False)
        raw = converter.convert(str(file_path)).text_content
    except Exception as e:  # markitdown 底層例外種類繁多，統一包裝且不回顯內容
        raise MarkdownConvertError(f"轉換失敗 ({file_path.name}): {type(e).__name__}") from e

    text = strip_embedded_images(raw or "")
    if not text:
        raise MarkdownConvertError(
            f"未擷取到文字內容 ({file_path.name})：可能是無文字層的掃描檔或空白文件，本模組不提供 OCR"
        )
    return text
