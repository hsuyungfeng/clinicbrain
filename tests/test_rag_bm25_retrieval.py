#!/usr/bin/env python3
"""
tests/test_rag_bm25_retrieval.py
Phase 22 Plan 22-01: FTS5 BM25 相關度排序與多詞交集評分單元測試
"""

import sqlite3
import pytest

from src.query.search import (
    search_text,
    search_drugs,
    search_service_items,
    search_page_index_trees,
    search_faq_cache,
    SearchHit,
)
from src.query.router import (
    _search_terms_merged,
    extract_search_terms,
    handle_query,
    _gather_faq_hits,
)


@pytest.fixture
def memory_db():
    """建立包含 trigram FTS5 的純記憶體測試資料庫"""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()

    # 建立 faq_cache 與 faq_cache_fts
    cur.execute(
        """
        CREATE TABLE faq_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id TEXT,
            topic_key TEXT,
            category TEXT,
            question TEXT,
            answer TEXT,
            source_type TEXT DEFAULT 'clinic_upload',
            review_status TEXT DEFAULT 'approved',
            content_version INTEGER DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE VIRTUAL TABLE faq_cache_fts USING fts5(
            question,
            answer,
            content='faq_cache',
            content_rowid='id',
            tokenize='trigram'
        )
        """
    )
    cur.execute(
        """
        CREATE TRIGGER faq_cache_ai AFTER INSERT ON faq_cache BEGIN
            INSERT INTO faq_cache_fts(rowid, question, answer)
            VALUES (new.id, new.question, new.answer);
        END;
        """
    )

    # 建立 page_index_trees 與 page_index_fts
    cur.execute(
        """
        CREATE TABLE page_index_trees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT UNIQUE,
            clinic_id TEXT,
            category TEXT,
            pre_op TEXT,
            procedure TEXT,
            post_op_short TEXT,
            maintenance TEXT,
            summary_text TEXT,
            source_type TEXT DEFAULT 'manual',
            review_status TEXT DEFAULT 'approved'
        )
        """
    )
    cur.execute(
        """
        CREATE VIRTUAL TABLE page_index_fts USING fts5(
            summary_text,
            pre_op,
            procedure,
            post_op_short,
            maintenance,
            content='page_index_trees',
            content_rowid='id',
            tokenize='trigram'
        )
        """
    )
    cur.execute(
        """
        CREATE TRIGGER page_index_ai AFTER INSERT ON page_index_trees BEGIN
            INSERT INTO page_index_fts(rowid, summary_text, pre_op, procedure, post_op_short, maintenance)
            VALUES (new.id, new.summary_text, new.pre_op, new.procedure, new.post_op_short, new.maintenance);
        END;
        """
    )

    # 建立 drugs 與 drugs_fts
    cur.execute(
        """
        CREATE TABLE drugs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            chinese_name TEXT,
            english_name TEXT,
            ingredient TEXT,
            otc_name_chinese TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE VIRTUAL TABLE drugs_fts USING fts5(
            chinese_name,
            ingredient,
            otc_name_chinese,
            content='drugs',
            content_rowid='id',
            tokenize='trigram'
        )
        """
    )
    cur.execute(
        """
        CREATE TRIGGER drugs_ai AFTER INSERT ON drugs BEGIN
            INSERT INTO drugs_fts(rowid, chinese_name, ingredient, otc_name_chinese)
            VALUES (new.id, new.chinese_name, new.ingredient, new.otc_name_chinese);
        END;
        """
    )

    # 建立 service_items 與 service_items_fts
    cur.execute(
        """
        CREATE TABLE service_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            chinese_name TEXT,
            english_name TEXT,
            points INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE VIRTUAL TABLE service_items_fts USING fts5(
            chinese_name,
            content='service_items',
            content_rowid='id',
            tokenize='trigram'
        )
        """
    )
    cur.execute(
        """
        CREATE TRIGGER service_items_ai AFTER INSERT ON service_items BEGIN
            INSERT INTO service_items_fts(rowid, chinese_name)
            VALUES (new.id, new.chinese_name);
        END;
        """
    )

    conn.commit()
    return conn


def test_bm25_ranking_prefers_higher_relevance(memory_db):
    """驗證 BM25 排序生效：高相關度（高詞頻）之問答排在早期建立的低相關度問答前面。"""
    cur = memory_db.cursor()

    # 早期插入 low_rel (id=1)，僅出現一次「甲溝炎」
    cur.execute(
        """
        INSERT INTO faq_cache (id, clinic_id, category, question, answer)
        VALUES (1, '3503190424', 'special', '一般指甲問題諮詢', '本診所有處理各類指甲發炎，包括甲溝炎等常見問題。')
        """
    )
    # 後期插入 high_rel (id=2)，高密度出現「甲溝炎」
    cur.execute(
        """
        INSERT INTO faq_cache (id, clinic_id, category, question, answer)
        VALUES (2, '3503190424', 'special', '甲溝炎治療方式', '甲溝炎是常見指甲周圍發炎。甲溝炎處置包括甲溝炎藥物與甲溝炎手術。')
        """
    )
    memory_db.commit()

    hits = search_faq_cache(memory_db, "甲溝炎", limit=10, clinic_id="3503190424")
    assert len(hits) == 2
    # 驗證 id=2 (high relevance) 排在 id=1 前面，而非依據主表 rowid 升冪
    assert hits[0].row_id == 2
    assert hits[1].row_id == 1


def test_bm25_with_extra_where_clauses(memory_db):
    """驗證 BM25 JOIN 語法在各類 extra_where (clinic_id, category, review_status) 下正確無歧義執行。"""
    cur = memory_db.cursor()
    cur.execute(
        """
        INSERT INTO faq_cache (clinic_id, category, question, answer, source_type, review_status)
        VALUES 
            ('3503190424', 'special', '甲溝炎門診處理', '甲溝炎清創與護理', 'clinic_upload', 'approved'),
            ('9999999999', 'special', '甲溝炎門診處理', '其他診所甲溝炎', 'clinic_upload', 'approved'),
            ('3503190424', 'general', '甲溝炎日常衛教', '一般常識說明', 'clinic_upload', 'approved'),
            ('3503190424', 'special', '甲溝炎草稿審查', '未核准草稿', 'llm_generated', 'pending')
        """
    )
    memory_db.commit()

    # 僅查詢特定 clinic_id + category='special'
    hits = search_faq_cache(
        memory_db, "甲溝炎", limit=10, clinic_id="3503190424", category="special"
    )
    # pending 應被 visible_faq_sql 隔離，其他診所應被 clinic_id 隔離
    assert len(hits) == 1
    assert hits[0].fields["question"] == "甲溝炎門診處理"
    assert hits[0].fields["clinic_id"] == "3503190424"


def test_multi_term_intersection_boost_logic(memory_db):
    """驗證多詞交集加權：同時命中多個檢索詞的問答排在最前列。"""
    cur = memory_db.cursor()

    # A: 僅命中「甲溝炎」
    cur.execute(
        """
        INSERT INTO faq_cache (id, clinic_id, category, question, answer)
        VALUES (10, '3503190424', 'special', '甲溝炎門診處理有哪些？', '包含門診局部切除與清創。')
        """
    )
    # B: 僅命中「照護」
    cur.execute(
        """
        INSERT INTO faq_cache (id, clinic_id, category, question, answer)
        VALUES (20, '3503190424', 'special', '一般傷口照護須知', '保持清潔乾燥，按時回診換藥照護。')
        """
    )
    # C: 同時命中「甲溝炎」與「照護」（多詞交集）
    cur.execute(
        """
        INSERT INTO faq_cache (id, clinic_id, category, question, answer)
        VALUES (30, '3503190424', 'special', '甲溝炎居家照護指南', '甲溝炎發炎時應注意日常清潔，做好指甲周圍照護。')
        """
    )
    memory_db.commit()

    terms = ["甲溝炎", "照護"]
    hits = _search_terms_merged(search_faq_cache, memory_db, terms, limit=5, clinic_id="3503190424")

    assert len(hits) == 3
    # ID 30 同時命中甲溝炎與照護，必須享有最高優先權排在第 1 筆
    assert hits[0].row_id == 30
    assert "甲溝炎居家照護" in hits[0].fields["question"]


def test_real_db_paronychia_care_retrieval():
    """在真實 clinic.db 上驗證「甲溝炎要怎麼照護？」檢索：
    居家自我護理與照護問答（如 ID 497 等）必須被精準加權排進 Top 5。
    """
    try:
        conn = sqlite3.connect("file:clinic.db?mode=ro", uri=True)
    except Exception:
        pytest.skip("clinic.db 無法以唯讀模式開啟")

    query = "甲溝炎要怎麼照護？"
    terms = extract_search_terms(query)
    assert "甲溝炎" in terms
    assert "照護" in terms

    hits = _gather_faq_hits(conn, terms, limit=5, clinic_id="3503190424", route="special")
    assert len(hits) >= 1

    hit_ids = [h.row_id for h in hits]
    # ID 497 (甲溝炎在家能做哪些自我護理與家庭治療？) 應進入 Top 5
    assert 497 in hit_ids, f"預期 ID 497 在 Top 5 中，實際命中 ID 為 {hit_ids}"

    # Top 5 中應包含「自我護理」或「照護」之問答
    has_care_faq = any("護理" in h.fields["question"] or "照護" in h.fields.get("answer", "") for h in hits)
    assert has_care_faq, "Top 5 中未見護理或照護相關問答"


def test_all_search_entities_compatibility(memory_db):
    """驗證 search_drugs, search_service_items, search_page_index_trees 皆正常支援 BM25 與 LIKE 分流。"""
    cur = memory_db.cursor()

    # 插入藥品
    cur.execute(
        """
        INSERT INTO drugs (id, code, chinese_name, english_name, ingredient, otc_name_chinese)
        VALUES 
            (1, 'D001', '普拿疼止痛藥', 'Panadol', 'Acetaminophen', '乙醯胺酚止痛'),
            (2, 'D002', '安莫西林膠囊', 'Amoxicillin', 'Amoxicillin', '抗生素')
        """
    )

    # 插入給付項目
    cur.execute(
        """
        INSERT INTO service_items (id, code, chinese_name, english_name, points)
        VALUES 
            (1, 'S001', '傷口清創處置', 'Debridement', 350),
            (2, 'S002', '指甲部分拔除手術', 'Partial Nail Avulsion', 800)
        """
    )

    # 插入推理樹
    cur.execute(
        """
        INSERT INTO page_index_trees (id, doc_id, clinic_id, category, pre_op, procedure, post_op_short, maintenance, summary_text)
        VALUES (
            1, 'paronychia-care', '3503190424', 'special',
            '評估局部紅腫', '局部麻醉微創切除', '每日換藥', '直向修剪指甲',
            '甲溝炎微創處理與術後照護決策樹'
        )
        """
    )
    memory_db.commit()

    # 測試 search_drugs: 3+ 字走 FTS5 BM25，<3字走 LIKE
    drug_hits_fts = search_drugs(memory_db, "普拿疼", limit=5)
    assert len(drug_hits_fts) == 1
    assert drug_hits_fts[0].fields["code"] == "D001"

    drug_hits_like = search_drugs(memory_db, "膠囊", limit=5)
    assert len(drug_hits_like) == 1
    assert drug_hits_like[0].fields["code"] == "D002"

    # 測試 search_service_items:
    srv_hits = search_service_items(memory_db, "拔除手術", limit=5)
    assert len(srv_hits) == 1
    assert srv_hits[0].fields["code"] == "S002"

    # 測試 search_page_index_trees:
    tree_hits = search_page_index_trees(memory_db, "甲溝炎", limit=5, clinic_id="3503190424")
    assert len(tree_hits) == 1
    assert tree_hits[0].fields["doc_id"] == "paronychia-care"


def test_edge_cases_empty_and_zero_limits(memory_db):
    """驗證邊界條件：空字串、純空白、limit <= 0 均能優雅處理。"""
    assert search_text(memory_db, "faq_cache", "faq_cache_fts", "", ("id",), ("question",)) == []
    assert search_text(memory_db, "faq_cache", "faq_cache_fts", "   ", ("id",), ("question",)) == []
    assert _search_terms_merged(search_faq_cache, memory_db, [], limit=5) == []
    assert _search_terms_merged(search_faq_cache, memory_db, ["甲溝炎"], limit=0) == []
    assert _search_terms_merged(search_faq_cache, memory_db, ["甲溝炎"], limit=-1) == []
