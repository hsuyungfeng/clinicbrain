"""Phase 48-01 單元測試：ICD-10 診斷碼擷取、高頻排行與 nhi_catalog_1_400 對齊。"""

import json
import sqlite3

from src.soap.icd10_stats import (
    align_icd10_with_nhi_catalog,
    extract_icd10_codes,
    get_top_clinic_diseases,
    rank_icd10_from_aggregated,
    rank_icd10_from_soap,
)


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE soap_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id TEXT NOT NULL,
            subjective TEXT,
            objective TEXT,
            assessment TEXT,
            plan TEXT,
            raw_text TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE nhi_catalog_1_400 (
            index_no INTEGER PRIMARY KEY,
            id TEXT,
            system TEXT,
            category TEXT,
            name TEXT,
            icd10 TEXT,
            alias TEXT,
            keywords TEXT,
            clinical_feature TEXT,
            topic_key TEXT,
            visual_available INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE nhi_catalog_fts USING fts5(
            index_no UNINDEXED,
            name,
            alias,
            keywords,
            clinical_feature,
            tokenize='trigram'
        )
        """
    )
    catalog_rows = [
        (
            89,
            "w001",
            "western",
            "呼吸道",
            "急性上呼吸道感染（感冒）",
            "J06.9",
            json.dumps(["感冒", "URI"], ensure_ascii=False),
            json.dumps(["流鼻水", "咳嗽", "喉嚨痛"], ensure_ascii=False),
            "常見病毒性上呼吸道發炎",
            "nhi-w001-j06-9",
            1,
        ),
        (
            93,
            "w005",
            "western",
            "呼吸道",
            "流行性感冒（流感）",
            "J11.1",
            json.dumps(["流感"], ensure_ascii=False),
            json.dumps(["高燒", "肌肉痠痛"], ensure_ascii=False),
            "急性發燒與全身痠痛",
            "nhi-w005-j11-1",
            1,
        ),
        (
            120,
            "w032",
            "western",
            "皮膚",
            "異位性皮膚炎",
            "L20.9",
            json.dumps(["濕疹"], ensure_ascii=False),
            json.dumps(["搔癢", "乾燥"], ensure_ascii=False),
            "慢性反覆發作搔癢性皮膚炎",
            "nhi-w032-l20-9",
            0,
        ),
    ]
    conn.executemany(
        """
        INSERT INTO nhi_catalog_1_400
        (index_no, id, system, category, name, icd10, alias, keywords, clinical_feature, topic_key, visual_available)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        catalog_rows,
    )
    for r in catalog_rows:
        conn.execute(
            "INSERT INTO nhi_catalog_fts (index_no, name, alias, keywords, clinical_feature) VALUES (?, ?, ?, ?, ?)",
            (r[0], r[4], r[6], r[7], r[8]),
        )
    conn.commit()
    return conn


def test_extract_icd10_codes_normalizes_and_deduplicates():
    text = "A: j06.9 Acute URI, also J06.9 and E11.9 DM, plus L20.9. Take B12."
    codes = extract_icd10_codes(text)
    assert codes == ["J06.9", "E11.9", "L20.9"]
    assert extract_icd10_codes("") == []


def test_rank_icd10_from_soap_and_missing_table():
    empty_conn = sqlite3.connect(":memory:")
    assert rank_icd10_from_soap(empty_conn) == []

    conn = _make_db()
    conn.executemany(
        "INSERT INTO soap_records (clinic_id, assessment, raw_text) VALUES (?, ?, ?)",
        [
            ("3503190424", "J06.9 感冒", "J06.9"),
            ("3503190424", "J06.9, L20.9", ""),
            ("3503190424", "J11.1 流感", ""),
            ("9999999999", "J11.1", ""),
        ],
    )
    conn.commit()

    ranked = rank_icd10_from_soap(conn, clinic_id="3503190424")
    assert ranked[0]["icd10"] == "J06.9"
    assert ranked[0]["count"] == 2
    assert {r["icd10"] for r in ranked} == {"J06.9", "J11.1", "L20.9"}


def test_rank_icd10_from_aggregated_merges_and_filters():
    items = [
        {"icd10": "j06.9", "count": 10, "label": "感冒"},
        {"icd10": "J06.9", "count": 5},
        {"icd10": "INVALID", "count": 99},
        {"icd10": "L20.9", "count": -1},
        {"icd10": "J11.1", "count": 7},
    ]
    ranked = rank_icd10_from_aggregated(items)
    assert ranked == [
        {"icd10": "J06.9", "count": 15, "label": "感冒", "source": "aggregated"},
        {"icd10": "J11.1", "count": 7, "label": None, "source": "aggregated"},
    ]


def test_align_icd10_exact_prefix_and_label_fallback():
    conn = _make_db()
    ranked = [
        {"icd10": "J06.9", "count": 20, "source": "soap_records"},
        {"icd10": "J06.0", "count": 10, "source": "aggregated"},  # 3碼大類 J06 fallback
        {"icd10": "R50.9", "count": 5, "label": "異位性皮膚炎", "source": "aggregated"},  # label fallback
        {"icd10": "Z99.9", "count": 2, "label": "不明原因", "source": "aggregated"},  # unmatched
    ]
    aligned = align_icd10_with_nhi_catalog(conn, ranked)
    assert aligned[0]["catalog_matched"] is True
    assert aligned[0]["topic_key"] == "nhi-w001-j06-9"
    assert aligned[0]["clinic_rank"] == 1

    assert aligned[1]["catalog_matched"] is True
    assert aligned[1]["topic_key"] == "nhi-w001-j06-9"

    assert aligned[2]["catalog_matched"] is True
    assert aligned[2]["topic_key"] == "nhi-w032-l20-9"

    assert aligned[3]["catalog_matched"] is False
    assert aligned[3]["topic_key"] == "icd10-z99-9"
    assert aligned[3]["disease_name"] == "不明原因"


def test_get_top_clinic_diseases_combines_sources():
    conn = _make_db()
    conn.execute(
        "INSERT INTO soap_records (clinic_id, assessment) VALUES (?, ?)",
        ("3503190424", "J06.9"),
    )
    conn.commit()
    res = get_top_clinic_diseases(
        conn,
        clinic_id="3503190424",
        aggregated_counts=[{"icd10": "J06.9", "count": 4}, {"icd10": "J11.1", "count": 3}],
    )
    assert res[0]["icd10"] == "J06.9"
    assert res[0]["count"] == 5
    assert res[0]["source"] == "mixed"
    assert res[1]["icd10"] == "J11.1"
