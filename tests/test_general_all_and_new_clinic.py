"""測試所有既有對話/MP4/QA 歸類為一般醫學常識後的跨診所查詢、公開 MP4 下載，以及新付費會員診所註冊與 PageIndex 隔離。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from scripts.generalize_all_knowledge import generalize_all
from src.api.app import app
from src.api.dependencies import get_read_db, get_write_db
from src.pageindex.db_writer import upsert_trees
from src.pageindex.faq_writer import upsert_faqs
from src.visual.writer import upsert_assets


def _make_clean_db(tmp_path: Path) -> Path:
    """建立含完整 schema（無預先資料干擾）的隔離 SQLite 測試資料庫。"""
    db_path = tmp_path / "test_general_all.db"
    conn = sqlite3.connect(str(db_path))
    schema_sql = Path("src/db/clinic_schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)

    # 補齊遷移欄位（review_status, title, visual_assets）
    for stmt in (
        "ALTER TABLE faq_cache ADD COLUMN review_status TEXT NOT NULL DEFAULT 'approved'",
        "ALTER TABLE faq_cache ADD COLUMN reviewed_at TIMESTAMP",
        "ALTER TABLE faq_cache ADD COLUMN metadata TEXT",
        "ALTER TABLE page_index_trees ADD COLUMN title TEXT",
        "ALTER TABLE page_index_trees ADD COLUMN review_status TEXT NOT NULL DEFAULT 'approved'",
        "ALTER TABLE page_index_trees ADD COLUMN reviewed_at TIMESTAMP",
        "ALTER TABLE page_index_trees ADD COLUMN reviewed_by TEXT",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS visual_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id TEXT REFERENCES clinic_info(clinic_id),
            topic_key TEXT NOT NULL,
            title TEXT NOT NULL,
            keywords TEXT NOT NULL,
            ir_json TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK(source_type IN ('manual', 'llm_generated')),
            review_status TEXT NOT NULL DEFAULT 'pending' CHECK(review_status IN ('pending', 'approved', 'rejected')),
            reviewed_at TEXT,
            content_version INTEGER NOT NULL DEFAULT 1,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            template_override TEXT,
            UNIQUE(clinic_id, topic_key)
        )
        """
    )

    conn.execute(
        "INSERT INTO clinic_info (clinic_id, name, clinic_type) VALUES ('3503190424', '緻妍外科診所', '外科')"
    )
    conn.execute(
        "INSERT INTO clinic_info (clinic_id, name, clinic_type) VALUES ('3503264627', '凡登整形外科診所', '整形外科')"
    )
    conn.commit()
    conn.close()
    return db_path


def _sample_ir(topic_key: str, title: str, keywords: list[str]) -> dict:
    return {
        "topic_key": topic_key,
        "title": title,
        "keywords": keywords,
        "scenes": [
            {
                "blueprint": "process_diagram",
                "title": "治療原理",
                "caption": "透過能量作用於目標組織，協助醫師評估後安全施作。",
                "labels": [{"text": "專業評估", "tone": "neutral"}],
            },
            {
                "blueprint": "timeline",
                "title": "術後恢復",
                "caption": "依醫囑照護並留意異常紅腫熱痛，必要時回診。",
                "labels": [{"text": "定期追蹤", "tone": "neutral"}],
            },
            {
                "blueprint": "contrast",
                "title": "日常保養",
                "caption": "維持防曬保濕並避免刺激性產品，效果因人而異。",
                "labels": [{"text": "溫和照護", "tone": "neutral"}],
            },
        ],
    }


def test_generalize_all_script_migrates_and_dedups_idempotently(tmp_path: Path):
    db_path = _make_clean_db(tmp_path)
    conn = sqlite3.connect(str(db_path))

    # 插入診所專屬 FAQ、重複 FAQ、診所專屬樹與視覺資產
    upsert_faqs(
        conn,
        [
            {
                "clinic_id": "3503190424",
                "topic_key": "botox",
                "category": "special",
                "question": "肉毒施打後多久有效？",
                "answer": "通常約 3 至 7 天開始見效，請依醫師評估為準。",
            },
            {
                "clinic_id": None,
                "topic_key": "botox",
                "category": "general",
                "question": "肉毒施打後多久有效？",
                "answer": "舊版一般答案。",
            },
            {
                "clinic_id": "3503264627",
                "topic_key": "rhinoplasty",
                "category": "special",
                "question": "隆鼻術後腫脹何時消退？",
                "answer": "多數於一至兩週內逐漸消腫，若持續劇痛請立即回診。",
            },
        ],
        source_type="clinic_upload",
    )
    upsert_trees(
        conn,
        [
            {
                "doc_id": "3503264627-rhinoplasty",
                "clinic_id": "3503264627",
                "title": "結構式隆鼻",
                "category": "special",
                "pre_op": "術前避免抗凝血藥物與吸菸。",
                "pre_op_physician_notes": "",
                "procedure": "依鼻部結構進行軟骨支撐調整。",
                "procedure_physician_notes": "",
                "post_op_short": "術後前三天冰敷並保持傷口清潔。",
                "post_op_short_physician_notes": "",
                "maintenance": "避免劇烈碰撞鼻部。",
                "maintenance_physician_notes": "",
                "summary_text": "結構式隆鼻術前術後完整衛教。",
            }
        ],
        source_type="clinic_upload",
    )
    upsert_assets(
        conn,
        [
            {
                "clinic_id": "3503264627",
                "topic_key": "tree-3503264627-rhinoplasty",
                "title": "結構式隆鼻衛教動畫",
                "keywords": ["隆鼻", "結構式隆鼻"],
                "ir": _sample_ir("tree-3503264627-rhinoplasty", "結構式隆鼻衛教動畫", ["隆鼻", "結構式隆鼻"]),
            }
        ],
        source_type="llm_generated",
    )
    conn.commit()

    report1 = generalize_all(conn)
    conn.commit()

    assert report1["faq_cache"]["scanned"] == 2
    assert report1["faq_cache"]["deduped"] == 1
    assert report1["faq_cache"]["updated"] == 1
    assert report1["page_index_trees"]["updated"] == 1
    assert report1["visual_assets"]["updated"] == 1

    # 確認全部皆已成為 clinic_id IS NULL 與 category='general'
    assert conn.execute("SELECT COUNT(*) FROM faq_cache WHERE clinic_id IS NOT NULL OR category != 'general'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM page_index_trees WHERE clinic_id IS NOT NULL OR category != 'general'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM visual_assets WHERE clinic_id IS NOT NULL").fetchone()[0] == 0

    # 第二次執行具冪等性
    report2 = generalize_all(conn)
    assert sum(report2["faq_cache"].values()) == 0
    assert sum(report2["page_index_trees"].values()) == 0
    assert sum(report2["visual_assets"].values()) == 0
    conn.close()


def test_all_patients_can_query_general_knowledge_and_new_paid_clinic_isolates_own_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db_path = _make_clean_db(tmp_path)
    video_dir = tmp_path / "videos"
    video_dir.mkdir()

    # 準備假 MP4 檔案
    mp4_file = video_dir / "tree-hifu-lifting_landscape.mp4"
    mp4_file.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    (video_dir / "tree-hifu-lifting_landscape.meta.json").write_text(
        json.dumps({"duration_sec": 24, "fps": 24}), encoding="utf-8"
    )

    monkeypatch.setattr("src.visual.video_queue.DEFAULT_VIDEO_DIR", video_dir)
    monkeypatch.setattr("src.api.routes.visual.DEFAULT_VIDEO_DIR", video_dir)

    conn = sqlite3.connect(str(db_path))
    # 寫入一般醫學常識：FAQ + PageIndex 樹 + 已核准視覺動畫
    upsert_faqs(
        conn,
        [
            {
                "clinic_id": None,
                "topic_key": "hifu-lifting",
                "category": "general",
                "question": "音波拉提術後要注意什麼？",
                "answer": "音波拉提術後請加強保濕與防曬，一週內避免高溫三溫暖。若出現嚴重紅腫水泡請立即就醫。",
            }
        ],
        source_type="clinic_upload",
    )
    upsert_trees(
        conn,
        [
            {
                "doc_id": "hifu-lifting",
                "clinic_id": None,
                "title": "音波拉提衛教",
                "category": "general",
                "pre_op": "術前評估皮膚狀況。",
                "pre_op_physician_notes": "",
                "procedure": "聚焦超音波能量作用於筋膜層。",
                "procedure_physician_notes": "",
                "post_op_short": "術後加強保濕防曬。",
                "post_op_short_physician_notes": "",
                "maintenance": "維持良好作息。",
                "maintenance_physician_notes": "",
                "summary_text": "音波拉提術前術後衛教與注意事項。",
            }
        ],
        source_type="clinic_upload",
    )
    upsert_assets(
        conn,
        [
            {
                "clinic_id": None,
                "topic_key": "tree-hifu-lifting",
                "title": "音波拉提動畫解說",
                "keywords": ["音波拉提", "音波"],
                "ir": _sample_ir("tree-hifu-lifting", "音波拉提動畫解說", ["音波拉提", "音波"]),
            }
        ],
        source_type="llm_generated",
    )
    conn.execute("UPDATE visual_assets SET review_status = 'approved' WHERE topic_key = 'tree-hifu-lifting'")

    # 模擬未來新付費會員診所（9999990001）登錄自己的診所資料與專屬 PageIndex
    conn.execute(
        "INSERT INTO clinic_info (clinic_id, name, clinic_type) VALUES ('9999990001', '新會員旗艦診所', '皮膚科')"
    )
    upsert_trees(
        conn,
        [
            {
                "doc_id": "9999990001-custom-laser",
                "clinic_id": "9999990001",
                "title": "新會員專屬蜂巢療程",
                "category": "special",
                "pre_op": "新會員診所術前須簽署專屬同意書。",
                "pre_op_physician_notes": "",
                "procedure": "雙波長脈衝施打。",
                "procedure_physician_notes": "",
                "post_op_short": "術後於本院敷臉修護。",
                "post_op_short_physician_notes": "",
                "maintenance": "每月回院追蹤一次。",
                "maintenance_physician_notes": "",
                "summary_text": "新會員診所專屬蜂巢雷射療程與術後照護。",
            }
        ],
        source_type="clinic_upload",
    )
    conn.commit()
    conn.close()

    def _override_read():
        c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    def _override_write():
        c = sqlite3.connect(str(db_path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_read_db] = _override_read
    app.dependency_overrides[get_write_db] = _override_write
    try:
        client = TestClient(app)

        # 1. 不帶 clinic_id 查詢療程問題（過去會因 clinic_custom_notes 誤報 400，現在應成功回傳一般醫學常識 + MP4）
        r_no_clinic = client.post("/api/v1/query", json={"query": "音波拉提術後要注意什麼？"})
        assert r_no_clinic.status_code == 200
        d1 = r_no_clinic.json()
        assert d1["source"] == "cache"
        assert "保濕" in d1["cache_answer"]
        assert d1["visual"]["topic_key"] == "tree-hifu-lifting"
        assert d1["videos"]["landscape"]["available"] is True
        assert d1["videos"]["landscape"]["download_url"] == "/api/v1/visual/videos/tree-hifu-lifting/download?aspect=landscape"

        # 2. 帶入舊診所 (3503190424) 或新付費會員診所 (9999990001) 皆可查到一般醫學常識（含 PageIndex 樹 + FAQ + MP4）
        r_old_clinic = client.post("/api/v1/clinics/3503190424/query", json={"query": "音波拉提"})
        assert r_old_clinic.status_code == 200
        d2 = r_old_clinic.json()
        assert any(h["fields"]["doc_id"] == "hifu-lifting" for h in d2["page_index_hits"])
        assert d2["videos"]["landscape"]["available"] is True

        # 3. 新付費會員診所 (9999990001) 可同時查到自己專屬的 PageIndex 樹 + 所有一般醫學常識
        r_new_own = client.post("/api/v1/clinics/9999990001/query", json={"query": "蜂巢雷射療程"})
        assert r_new_own.status_code == 200
        assert any(h["fields"]["doc_id"] == "9999990001-custom-laser" for h in r_new_own.json()["page_index_hits"])

        r_new_gen = client.post("/api/v1/clinics/9999990001/query", json={"query": "音波拉提"})
        assert r_new_gen.status_code == 200
        assert any(h["fields"]["doc_id"] == "hifu-lifting" for h in r_new_gen.json()["page_index_hits"])

        # 4. 跨診所隔離：他院 (3503190424) 或無診所入口不可查到 9999990001 的專屬資料
        r_cross = client.post("/api/v1/clinics/3503190424/query", json={"query": "蜂巢雷射療程"})
        assert r_cross.status_code == 200
        assert not any(h["fields"]["doc_id"] == "9999990001-custom-laser" for h in r_cross.json()["page_index_hits"])

        # 5. 一般諮詢 /api/v1/general/query 可查到一般 FAQ 與 PageIndex 樹
        r_gen = client.post("/api/v1/general/query", json={"query": "音波拉提術後要注意什麼？"})
        assert r_gen.status_code == 200
        assert r_gen.json()["status"] == "answered"

        # 6. 公開視覺搜尋與 MP4 下載端點正常運作
        r_vs = client.get("/api/v1/visual/search", params={"query": "音波拉提"})
        assert r_vs.status_code == 200
        assert r_vs.json()["total"] == 1
        assert r_vs.json()["items"][0]["videos"]["landscape"]["available"] is True

        r_vmeta = client.get("/api/v1/visual/videos/tree-hifu-lifting")
        assert r_vmeta.status_code == 200
        assert r_vmeta.json()["landscape"]["available"] is True

        r_vdl = client.get("/api/v1/visual/videos/tree-hifu-lifting/download", params={"aspect": "landscape"})
        assert r_vdl.status_code == 200
        assert r_vdl.headers["content-type"] == "video/mp4"
        assert r_vdl.content.startswith(b"\x00\x00\x00\x18ftypmp42")

        # 不存在或路徑穿越應被擋下
        assert client.get("/api/v1/visual/videos/nonexistent/download").status_code == 404
        assert client.get("/api/v1/visual/videos/..secret/download").status_code == 400
    finally:
        app.dependency_overrides.clear()
