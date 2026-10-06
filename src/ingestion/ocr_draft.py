#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 手動 OCR 草稿模組 (ocr_draft)

用途：醫師／人員指定「一張」圖片，以本機 Tesseract (chi_tra+eng) 產出 OCR 草稿供人工參考。

規範（見 .planning/PROJECT.md 對圖片 OCR 之結案決策）：
- 草稿未經驗證（實測表格型、設計型圖片辨識品質差，常有亂碼），僅供人工謄寫時對照。
- 本模組與其 CLI 絕不寫入資料庫，也不 import 任何權威寫入路徑
  （db_writer / faq_writer / faq_review / custom_notes），由測試以 AST 掃描把關。
- 不使用任何外部 LLM／雲端服務。
- 草稿含疑似價格字樣時會警示；價格不得寫入資料庫（價格屏蔽規則）。
"""

from pathlib import Path
import re
import subprocess
from typing import Union

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"})
DEFAULT_LANG = "chi_tra+eng"

_CJK_GAP = re.compile(r"(?<=[一-鿿]) +(?=[一-鿿])")
_PRICE = re.compile(r"(?:NT\$?|\$)\s*\d|\d[\d,]*\s*元|[-—─]{3,}\s*\d{3,}")


class OcrDraftError(Exception):
    """OCR 草稿產生失敗。"""


def clean_ocr_text(raw: str) -> str:
    """整理 Tesseract 輸出：合併中文字間多餘空白、去除行尾空白與多餘空行。"""
    lines = [_CJK_GAP.sub("", ln).rstrip() for ln in raw.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def run_tesseract(image_path: Path, lang: str = DEFAULT_LANG, timeout: int = 120) -> str:
    """呼叫本機 tesseract，回傳原始辨識文字。"""
    try:
        proc = subprocess.run(
            ["tesseract", str(image_path), "-", "-l", lang, "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as e:
        raise OcrDraftError("找不到 tesseract，請先安裝（含 chi_tra 語言包）") from e
    except subprocess.TimeoutExpired as e:
        raise OcrDraftError(f"tesseract 逾時（{timeout} 秒）") from e
    if proc.returncode != 0:
        raise OcrDraftError(f"tesseract 執行失敗（結束碼 {proc.returncode}）")
    return proc.stdout


def build_draft(image_path: Path, text: str) -> str:
    """組裝草稿：固定警語標頭（只記檔名，不含本機路徑）＋整理後文字。"""
    header = [
        "【OCR 草稿】僅供人工參考，未經驗證，不得直接寫入資料庫或對外使用。",
        f"來源圖片：{Path(image_path).name}",
        "請對照原圖逐字確認；簡體字、亂碼與表格內容尤其容易出錯。",
    ]
    if _PRICE.search(text):
        header.append("⚠️ 內含疑似價格字樣：價格不得寫入資料庫，引用前請人工移除或改為「請致電診所確認」。")
    return "\n".join(header) + "\n" + "-" * 40 + "\n" + text + "\n"


def make_draft(image_path: Union[str, Path]) -> str:
    """對單張圖片產生 OCR 草稿字串。"""
    p = Path(image_path)
    if not p.is_file():
        raise OcrDraftError(f"找不到圖片: {p.name}")
    if p.suffix.lower() not in IMAGE_SUFFIXES:
        raise OcrDraftError(f"不支援的圖片格式: {p.suffix or '(無副檔名)'}，僅支援 {sorted(IMAGE_SUFFIXES)}")
    text = clean_ocr_text(run_tesseract(p))
    if not text:
        raise OcrDraftError("未辨識出任何文字（圖片可能不含文字或解析度不足）")
    return build_draft(p, text)
