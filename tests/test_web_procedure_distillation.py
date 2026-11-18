"""Phase 50 單元與整合測試：診所官網療程原理與手術步驟提煉（去診所名稱化）。"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_web_research_batch import _is_valid_clinic_url, extract_procedure_links
from src.pageindex.tree_distiller import NoProcedureContentError, validate_tree_segment
from src.pageindex.prompt_template import TreeValidationError
from src.scraper.distill_pipeline import distill_site_content


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE clinic_info (
            clinic_id TEXT PRIMARY KEY,
            clinic_name TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE page_index_trees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT UNIQUE,
            clinic_id TEXT REFERENCES clinic_info(clinic_id),
            category TEXT NOT NULL,
            title TEXT,
            pre_op TEXT,
            pre_op_physician_notes TEXT,
            procedure TEXT,
            procedure_physician_notes TEXT,
            post_op_short TEXT,
            post_op_short_physician_notes TEXT,
            maintenance TEXT,
            maintenance_physician_notes TEXT,
            summary_text TEXT,
            version TEXT DEFAULT '2.0',
            source_type TEXT DEFAULT 'manual',
            content_version INTEGER NOT NULL DEFAULT 1,
            needs_regeneration BOOLEAN NOT NULL DEFAULT 0,
            review_status TEXT NOT NULL DEFAULT 'approved',
            reviewed_at TIMESTAMP,
            reviewed_by TEXT,
            indexed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE faq_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id TEXT REFERENCES clinic_info(clinic_id),
            topic_key TEXT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            category TEXT NOT NULL,
            source_type TEXT DEFAULT 'manual',
            content_version INTEGER NOT NULL DEFAULT 1,
            needs_regeneration BOOLEAN NOT NULL DEFAULT 0,
            review_status TEXT NOT NULL DEFAULT 'approved',
            reviewed_at TIMESTAMP,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(clinic_id, topic_key, question)
        )
        """
    )
    return conn


def test_directory_urls_excluded():
    assert _is_valid_clinic_url("https://kb.commonhealth.com.tw/hospitals/21234.html") is False
    assert _is_valid_clinic_url("https://health.udn.com/health/story/123") is False
    assert _is_valid_clinic_url("https://www.example-clinic.tw/treatments") is True


def test_extract_procedure_links_prefers_same_host_treatment_pages():
    raw_html = """
    <html><body>
      <a href="/about">關於我們</a>
      <a href="/treatments/ingrown-nail">甲溝炎微創手術介紹</a>
      <a href="https://other.com/treatments/x">外部網站</a>
      <a href="/faq.html">常見衛教問題</a>
      <a href="/files/brochure.pdf">PDF</a>
    </body></html>
    """
    links = extract_procedure_links("https://example-clinic.tw/", raw_html, max_links=2)
    assert links == [
        "https://example-clinic.tw/treatments/ingrown-nail",
        "https://example-clinic.tw/faq.html",
    ]


def test_empty_directory_page_skips_tree_creation():
    conn = _make_db()
    directory_text = (
        "慶瑞堂中醫診所位於嘉義市東區公明路，看診科別為中醫一般科，"
        "門診時間為週一至週六上午九點至十二點，營業項目為門診診療。"
    )

    def stub_llm(prompt: str) -> str:
        if "has_procedure" in prompt:
            return json.dumps({"has_procedure": False, "procedure_title": ""})
        return "[]"

    res = distill_site_content(
        directory_text,
        clinic_id=None,
        clinic_name="慶瑞堂中醫診所",
        conn=conn,
        llm_call=stub_llm,
        max_trees=1,
        category="general",
        source_url="https://example-clinic.tw/",
    )
    assert res.trees_written == []
    assert "skipped_no_procedure" in res.errors
    assert conn.execute("SELECT COUNT(*) FROM page_index_trees").fetchone()[0] == 0


def test_validate_tree_segment_rejects_empty_shell_and_clinic_name():
    with pytest.raises(NoProcedureContentError):
        validate_tree_segment("procedure", "本頁未提供任何實際醫療療程或手術操作之原理與步驟。")
    with pytest.raises(TreeValidationError):
        validate_tree_segment(
            "summary_text",
            "慶瑞堂提供微創手術照護說明。",
            forbidden_terms=("慶瑞堂中醫診所", "慶瑞堂"),
        )


def test_general_distill_uses_pure_procedure_title_and_excludes_clinic_name():
    conn = _make_db()
    site_text = (
        "仁愛外科診所提供微創甲溝炎矯正手術：術前先評估甲床發炎程度與凝血功能，"
        "療程以局部麻醉下切除嵌甲邊緣並進行甲床母細胞電燒或化學燒灼抑制再生，"
        "術後每日以生理食鹽水清潔換藥並保持乾燥，避免穿過緊包鞋。"
    )

    def stub_llm(prompt: str) -> str:
        if "has_procedure" in prompt:
            return json.dumps({"has_procedure": True, "procedure_title": "微創甲溝炎矯正術"}, ensure_ascii=False)
        if "JSON 陣列" in prompt:
            return json.dumps(
                [
                    {
                        "question": "微創甲溝炎矯正術的操作原理與步驟為何？",
                        "answer": (
                            "微創甲溝炎矯正術會在局部麻醉下修除刺入甲溝軟組織的嵌甲邊緣，"
                            "並針對過度增生的甲床母細胞進行局部燒灼或化學處理以降低復發率。"
                            "術後需保持傷口乾燥清潔，每日以無菌生理食鹽水沖洗並塗抹抗菌藥膏，"
                            "穿著寬楦透氣鞋襪減少壓迫；若出現持續紅腫化膿或劇痛，請立即就醫評估。"
                        ),
                    }
                ],
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "pre_op": "評估患部甲溝紅腫化膿程度、糖尿病史與凝血功能，急性感染期需先控制發炎再行手術。",
                "procedure": "於局部神經阻斷麻醉下，沿嵌甲側緣縱向修除嵌入甲片並清除肉芽組織，再處理甲床母細胞防止側緣再生。",
                "post_op_short": "術後二十四小時內減少走動與抬高患肢，每日以無菌生理食鹽水清潔並塗抹抗菌藥膏包紮。",
                "maintenance": "日後修剪趾甲應平剪勿修剪過深呈圓弧狀，穿著寬楦透氣鞋襪以減少腳趾側緣壓迫復發。",
                "summary_text": "微創甲溝炎矯正術透過局部麻醉修除嵌甲並處理甲床母細胞，搭配術後清潔換藥與平剪趾甲保養預防復發。",
            },
            ensure_ascii=False,
        )

    res = distill_site_content(
        site_text,
        clinic_id=None,
        clinic_name="仁愛外科診所",
        conn=conn,
        llm_call=stub_llm,
        max_trees=1,
        category="general",
        source_url="https://example-clinic.tw/ingrown-nail",
    )
    assert len(res.trees_written) == 1
    row = conn.execute(
        "SELECT title, category, clinic_id, review_status, summary_text, procedure FROM page_index_trees"
    ).fetchone()
    assert row[0] == "微創甲溝炎矯正術"
    assert row[1] == "general"
    assert row[2] is None
    assert row[3] == "pending"
    for field_val in (row[0], row[4], row[5]):
        assert "仁愛" not in field_val
    faq = conn.execute("SELECT question, answer, category FROM faq_cache").fetchone()
    assert faq is not None
    assert faq[2] == "general"
    assert "仁愛" not in faq[0] and "仁愛" not in faq[1]
