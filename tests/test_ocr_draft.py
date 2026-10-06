"""
tests/test_ocr_draft.py - 手動 OCR 草稿工具測試

規範：僅輸出供人工參考之草稿，絕不寫入資料庫、不走任何 FAQ／樹寫入路徑。
"""

import ast
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts import ocr_draft as cli
from src.ingestion import ocr_draft as mod

ROOT = Path(__file__).resolve().parent.parent


def test_clean_ocr_text_joins_cjk_spaces():
    raw = "緻 妍 外 科 診 所 7 月 門診\n\n\n\n  預約 電話 :04-2395  \n"
    out = mod.clean_ocr_text(raw)
    assert "緻妍外科診所" in out
    assert "7 月" in out  # 數字與單位間空白不處理
    assert "\n\n\n" not in out
    assert out == out.strip()


def test_build_draft_has_warning_header(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    d = mod.build_draft(img, "門診公告")
    assert "OCR 草稿" in d and "僅供人工參考" in d and "不得直接" in d
    assert "a.png" in d and "門診公告" in d
    assert str(tmp_path) not in d  # 只記檔名，不洩漏本機路徑


def test_build_draft_flags_price_like_text(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    d = mod.build_draft(img, "玻尿酸 1CC ---- 8990 元\nNT$500")
    assert "疑似價格" in d
    d2 = mod.build_draft(img, "請多喝水")
    assert "疑似價格" not in d2


def test_make_draft_rejects_bad_input(tmp_path):
    with pytest.raises(mod.OcrDraftError, match="找不到"):
        mod.make_draft(tmp_path / "nope.png")
    f = tmp_path / "a.txt"
    f.write_text("x")
    with pytest.raises(mod.OcrDraftError, match="不支援"):
        mod.make_draft(f)


def test_make_draft_tesseract_missing(tmp_path, monkeypatch):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")

    def boom(*a, **k):
        raise FileNotFoundError("tesseract")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(mod.OcrDraftError, match="tesseract"):
        mod.make_draft(img)


def test_make_draft_empty_ocr_result(tmp_path, monkeypatch):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    monkeypatch.setattr(mod, "run_tesseract", lambda *a, **k: "  \n ")
    with pytest.raises(mod.OcrDraftError, match="未辨識"):
        mod.make_draft(img)


def test_cli_prints_to_stdout_and_writes_nothing_else(tmp_path, monkeypatch, capsys):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    monkeypatch.setattr(mod, "run_tesseract", lambda *a, **k: "營業 時間")
    before = sorted(p.name for p in tmp_path.iterdir())
    assert cli.main([str(img)]) == 0
    assert "營業時間" in capsys.readouterr().out
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_cli_out_file_and_no_overwrite(tmp_path, monkeypatch):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    monkeypatch.setattr(mod, "run_tesseract", lambda *a, **k: "營業時間")
    out = tmp_path / "draft.txt"
    assert cli.main([str(img), "--out", str(out)]) == 0
    assert "營業時間" in out.read_text(encoding="utf-8")
    assert cli.main([str(img), "--out", str(out)]) == 2  # 不覆蓋既有檔
    assert cli.main([str(img), "--out", str(out), "--force"]) == 0


def test_cli_error_exit_code(tmp_path, capsys):
    assert cli.main([str(tmp_path / "nope.png")]) == 2
    assert "找不到" in capsys.readouterr().err


def test_never_touches_database_or_writers():
    """草稿工具不得 import 任何資料庫或權威寫入路徑。"""
    banned = {"sqlite3", "db_writer", "faq_writer", "faq_review", "custom_notes"}
    for rel in ("src/ingestion/ocr_draft.py", "scripts/ocr_draft.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[-1] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                names |= {(n.module or "").split(".")[-1]} | {a.name for a in n.names}
        assert not (names & banned), (rel, names & banned)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="本機未安裝 tesseract")
def test_real_tesseract_english(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (600, 120), "white")
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48)
    except OSError:
        pytest.skip("無可用字型")
    ImageDraw.Draw(img).text((20, 30), "CLINIC OPEN", fill="black", font=font)
    p = tmp_path / "t.png"
    img.save(p)
    assert "CLINIC" in mod.make_draft(p)
