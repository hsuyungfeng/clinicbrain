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
    """驗證 FTS5 中文關鍵字 MATCH 查詢能真實命中中文內容。

    2026-09-22 修正：clinic.db 現在已有 40 筆真實 Phase 03 Stage 1 生成的
    FAQ（含「甲溝炎」等常見醫療用語），舊版測試直接用 MATCH 命中數斷言會被
    真實資料污染（isolated_conn 複製的是正式 clinic.db，不是空白資料庫）。
    改用 JOIN 回 faq_cache 並以本測試專屬的 topic_key 過濾，確保只驗證本
    測試自己寫入的那一列，不受資料庫既有內容影響——比照 test_multi_clinic.py
    用 "test-*" 前綴避免碰撞既有資料的既有慣例。
    """
    faqs = [
        {
            "clinic_id": "3503190424",
            "topic_key": "test-fts-cjk-match-unique-marker",
            "question": "甲溝炎手術需要注意什麼？",
            "answer": "術前需由醫師評估甲床狀況，若有急性蜂窩性組織炎需先消炎。",
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faqs, source_type="clinic_upload")

    cursor = isolated_conn.cursor()
    # 測試 3 字以上關鍵字 MATCH，並限定只看本測試寫入的 topic_key
    cursor.execute(
        """
        SELECT fts.rowid FROM faq_cache_fts fts
        JOIN faq_cache f ON f.id = fts.rowid
        WHERE fts.faq_cache_fts MATCH '甲溝炎' AND f.topic_key = 'test-fts-cjk-match-unique-marker'
        """
    )
    hits = cursor.fetchall()
    assert len(hits) == 1, "甲溝炎關鍵字未於 FTS 命中本測試寫入的列"

    cursor.execute(
        """
        SELECT fts.rowid FROM faq_cache_fts fts
        JOIN faq_cache f ON f.id = fts.rowid
        WHERE fts.faq_cache_fts MATCH '組織炎' AND f.topic_key = 'test-fts-cjk-match-unique-marker'
        """
    )
    hits = cursor.fetchall()
    assert len(hits) == 1, "答案中之組織炎關鍵字未於 FTS 命中本測試寫入的列"


def test_faq_cache_triggers_sync(isolated_conn: sqlite3.Connection):
    """驗證 INSERT/UPDATE/DELETE 觸發器能否正確同步 faq_cache_fts。

    2026-09-22 修正：同上，改用本測試專屬的 topic_key 過濾，避免被
    clinic.db 既有真實資料（如同樣提及「矽膠」的其他 FAQ 列）誤判。
    """
    topic_key = "test-triggers-sync-unique-marker"
    faqs = [
        {
            "clinic_id": "3503190424",
            "topic_key": topic_key,
            "question": "蟹足腫疤痕如何治療？",
            "answer": "可透過局部消疤針或矽膠貼片撫平組織。",
            "category": "special",
        }
    ]
    upsert_faqs(isolated_conn, faqs, source_type="clinic_upload")

    def _match_this_topic(match_term: str) -> list:
        cursor = isolated_conn.cursor()
        cursor.execute(
            """
            SELECT fts.rowid FROM faq_cache_fts fts
            JOIN faq_cache f ON f.id = fts.rowid
            WHERE fts.faq_cache_fts MATCH ? AND f.topic_key = ?
            """,
            (match_term, topic_key),
        )
        return cursor.fetchall()

    assert len(_match_this_topic("蟹足腫")) == 1

    # UPDATE 答案內容
    faqs[0]["answer"] = "可透過類固醇注射或雷射治療撫平組織。"
    upsert_faqs(isolated_conn, faqs, source_type="clinic_upload")

    assert len(_match_this_topic("類固醇")) == 1
    assert len(_match_this_topic("矽膠貼")) == 0, "舊內容應自 FTS 索引移除"

    # DELETE
    cursor = isolated_conn.cursor()
    cursor.execute("DELETE FROM faq_cache WHERE topic_key = ?", (topic_key,))
    isolated_conn.commit()
    assert len(_match_this_topic("類固醇")) == 0, "刪除後 FTS 應無結果"


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
