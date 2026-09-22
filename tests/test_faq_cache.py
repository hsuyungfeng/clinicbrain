#!/usr/bin/env python3
"""
FAQ Cache 資料表與唯一寫入路徑 (faq_writer) 單元與整合測試
Phase 03 Document Ingestion Stage 1: TASK-00
"""

import sqlite3
import pytest
from src.pageindex.faq_writer import upsert_faqs


def test_faq_cache_fts_trigram_configuration(isolated_conn: sqlite3.Connection):
    """驗證 faq_cache_fts 虛擬表必須明確指定 tokenize='trigram'。"""
    cursor = isolated_conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE name = 'faq_cache_fts'")
    row = cursor.fetchone()
    assert row is not None, "faq_cache_fts 虛擬表不存在"
    sql = row[0].lower()
    assert "tokenize='trigram'" in sql or 'tokenize="trigram"' in sql, (
        f"faq_cache_fts 未指定 trigram 分詞器: {sql}"
    )


def test_faq_cache_fts_cjk_match(isolated_conn: sqlite3.Connection):
    """驗證 FTS5 中文關鍵字 MATCH 查詢能真實命中中文內容。"""
    faqs = [
        {
            "clinic_id": "3503190424",
            "topic_key": "paronychia",
            "question": "甲溝炎手術需要注意什麼？",
            "answer": "術前需由醫師評估甲床狀況，若有急性蜂窩性組織炎需先消炎。",
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faqs, source_type="clinic_upload")

    cursor = isolated_conn.cursor()
    # 測試 3 字以上關鍵字 MATCH
    cursor.execute("SELECT rowid FROM faq_cache_fts WHERE faq_cache_fts MATCH '甲溝炎'")
    hits = cursor.fetchall()
    assert len(hits) == 1, "甲溝炎關鍵字未於 FTS 命中"

    cursor.execute("SELECT rowid FROM faq_cache_fts WHERE faq_cache_fts MATCH '組織炎'")
    hits = cursor.fetchall()
    assert len(hits) == 1, "答案中之組織炎關鍵字未於 FTS 命中"


def test_faq_cache_triggers_sync(isolated_conn: sqlite3.Connection):
    """驗證 INSERT/UPDATE/DELETE 觸發器能否正確同步 faq_cache_fts。"""
    faqs = [
        {
            "clinic_id": "3503190424",
            "topic_key": "scar-care",
            "question": "蟹足腫疤痕如何治療？",
            "answer": "可透過局部消疤針或矽膠貼片撫平組織。",
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faqs, source_type="clinic_upload")

    cursor = isolated_conn.cursor()
    cursor.execute("SELECT rowid FROM faq_cache_fts WHERE faq_cache_fts MATCH '蟹足腫'")
    assert len(cursor.fetchall()) == 1

    # UPDATE 答案內容
    faqs[0]["answer"] = "可透過類固醇注射或雷射治療撫平組織。"
    upsert_faqs(isolated_conn, faqs, source_type="clinic_upload")

    cursor.execute("SELECT rowid FROM faq_cache_fts WHERE faq_cache_fts MATCH '類固醇'")
    assert len(cursor.fetchall()) == 1
    cursor.execute("SELECT rowid FROM faq_cache_fts WHERE faq_cache_fts MATCH '矽膠貼'")
    assert len(cursor.fetchall()) == 0, "舊內容應自 FTS 索引移除"

    # DELETE
    cursor.execute("DELETE FROM faq_cache WHERE topic_key = 'scar-care'")
    isolated_conn.commit()
    cursor.execute("SELECT rowid FROM faq_cache_fts WHERE faq_cache_fts MATCH '類固醇'")
    assert len(cursor.fetchall()) == 0, "刪除後 FTS 應無結果"


def test_upsert_faqs_validation_rules(isolated_conn: sqlite3.Connection):
    """驗證 upsert_faqs 的防禦性欄位檢核。"""
    # 1. 無效 source_type
    with pytest.raises(ValueError, match="無效的 source_type"):
        upsert_faqs(isolated_conn, [], source_type="unknown_source")

    # 2. 缺少 question
    with pytest.raises(ValueError, match="缺少必填欄位 'question'"):
        upsert_faqs(isolated_conn, [{"question": "", "answer": "有答案", "category": "general"}], source_type="manual")

    # 3. 缺少 answer
    with pytest.raises(ValueError, match="缺少必填欄位 'answer'"):
        upsert_faqs(isolated_conn, [{"question": "有問題", "answer": "", "category": "general"}], source_type="manual")

    # 4. 無效 category
    with pytest.raises(ValueError, match="無效，必須為"):
        upsert_faqs(isolated_conn, [{"question": "問", "answer": "答", "category": "other"}], source_type="manual")

    # 5. category='special' 卻缺少 clinic_id
    with pytest.raises(ValueError, match="必須包含非空之 'clinic_id'"):
        upsert_faqs(
            isolated_conn,
            [{"question": "問", "answer": "答", "category": "special", "clinic_id": None}],
            source_type="clinic_upload",
        )


def test_upsert_faqs_incremental_behavior(isolated_conn: sqlite3.Connection):
    """驗證增量寫入：新增 content_version=1，相同跳過，變更遞增版號。"""
    item = {
        "clinic_id": "3503190424",
        "topic_key": "mole-removal",
        "question": "點痣後可以洗臉嗎？",
        "answer": "術後24小時內傷口貼人工皮，洗臉時輕柔避開即可。",
        "category": "special",
    }

    # 第一次寫入：INSERT
    ins, upd, unc = upsert_faqs(isolated_conn, [item], source_type="clinic_upload")
    assert (ins, upd, unc) == (1, 0, 0)

    cursor = isolated_conn.cursor()
    cursor.execute("SELECT content_version, source_type, created_at, updated_at FROM faq_cache WHERE topic_key='mole-removal'")
    row = cursor.fetchone()
    assert row[0] == 1
    assert row[1] == "clinic_upload"
    created_at = row[2]

    # 相同內容再次寫入：UNCHANGED
    ins, upd, unc = upsert_faqs(isolated_conn, [item], source_type="clinic_upload")
    assert (ins, upd, unc) == (0, 0, 1)

    cursor.execute("SELECT content_version, created_at FROM faq_cache WHERE topic_key='mole-removal'")
    row = cursor.fetchone()
    assert row[0] == 1, "內容未變版號不可遞增"
    assert row[1] == created_at, "建立時間不可重置"

    # 內容修改：UPDATE 且 content_version 遞增
    item["answer"] = "術後需貼人工皮保護，防水防曬，可正常淋巴輕柔清潔。"
    ins, upd, unc = upsert_faqs(isolated_conn, [item], source_type="llm_generated")
    assert (ins, upd, unc) == (0, 1, 0)

    cursor.execute("SELECT content_version, source_type, answer FROM faq_cache WHERE topic_key='mole-removal'")
    row = cursor.fetchone()
    assert row[0] == 2, "內容更新後版號應遞增為 2"
    assert row[1] == "llm_generated"
    assert "防水防曬" in row[2]
