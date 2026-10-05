"""
tests/test_faq_conflicts.py - 診所相近常見問答 (FAQ 衝突比對) 模組測試 (Phase 12 GC-04)

驗證：
1. faq_coverage 覆蓋率計算精確度（實測句對）
2. 同一定義保證（與 select_confident_faq 算出的 query_coverage 完全一致）
3. find_similar_clinic_faqs 檢索功能（正例檢出、負例為空、limit 上限）
4. CLINIC_RELATED_FLOOR 唯一來源引用
5. 可見性過濾保證（未核准之 llm_generated 不進入衝突清單）
6. 唯讀連線 (mode=ro) 執行保證
"""

import inspect
from pathlib import Path
import sqlite3
import pytest


def test_faq_coverage_measurements():
    """驗證 faq_coverage 純函式對實測句對之覆蓋率數值符合基準。"""
    from src.query.faq_shortcut import faq_coverage
    from src.query.router import STOPWORD_SPLIT_PATTERN

    # 句對 1：「術後傷口如何照護？」對「手術後傷口該如何照護？」
    cov1 = faq_coverage("術後傷口如何照護？", "手術後傷口該如何照護？", STOPWORD_SPLIT_PATTERN)
    assert cov1[0] == pytest.approx(0.857, abs=0.001)
    assert cov1[1] == pytest.approx(0.667, abs=0.001)

    # 句對 2：「手術後傷口要怎麼照顧？」對「手術後傷口該如何照護？」
    cov2 = faq_coverage("手術後傷口要怎麼照顧？", "手術後傷口該如何照護？", STOPWORD_SPLIT_PATTERN)
    assert cov2[0] == pytest.approx(0.571, abs=0.001)
    assert cov2[1] == pytest.approx(0.444, abs=0.001)


def test_faq_coverage_consistent_with_select_confident_faq():
    """驗證 faq_coverage 與 select_confident_faq 採用完全一致的覆蓋率定義。"""
    from src.query.faq_shortcut import faq_coverage, select_confident_faq
    from src.query.router import STOPWORD_SPLIT_PATTERN
    from src.query.search import SearchHit

    query = "術後傷口如何照護？"
    q_target = "手術後傷口該如何照護？"

    hit = SearchHit(
        table="faq_cache",
        row_id=1,
        fields={
            "id": 1,
            "question": q_target,
            "answer": "傷口請保持乾燥清潔。",
            "clinic_id": "3503190424",
            "topic_key": "post-op-care",
            "category": "special",
        },
    )

    cov = faq_coverage(query, q_target, STOPWORD_SPLIT_PATTERN)
    decision = select_confident_faq(
        query=query,
        faq_hits=[hit],
        route="special",
        clinic_id="3503190424",
        stopword_pattern=STOPWORD_SPLIT_PATTERN,
    )

    assert decision.query_coverage == pytest.approx(cov[0], abs=0.0001)


def test_find_similar_clinic_faqs_retrieval(isolated_conn: sqlite3.Connection):
    """驗證 find_similar_clinic_faqs 正例、負例與 limit 表現。"""
    from src.pageindex.faq_conflicts import find_similar_clinic_faqs
    from src.query.faq_shortcut import CLINIC_RELATED_FLOOR

    # 1. 正例：術後傷口照顧，應檢出診所「手術後傷口該如何照護？」
    similar = find_similar_clinic_faqs(isolated_conn, "術後傷口如何照護？")
    assert len(similar) >= 1
    top_hit = similar[0]
    assert top_hit["question"] == "手術後傷口該如何照護？"
    assert top_hit["query_coverage"] >= CLINIC_RELATED_FLOOR
    assert "answer" in top_hit

    # 2. 負例：感冒居家照護，與診所既有 FAQ 最高覆蓋率僅 ~0.25 (< 0.4)，回傳空清單
    similar_cold = find_similar_clinic_faqs(isolated_conn, "感冒時在家要如何照護與休息？")
    assert similar_cold == []

    # 3. limit 限制
    similar_limited = find_similar_clinic_faqs(isolated_conn, "術後傷口如何照護？", limit=1)
    assert len(similar_limited) == 1


def test_similar_faqs_floor_unique_and_no_literal():
    """驗證 floor 預設值為 CLINIC_RELATED_FLOOR 且模組原始碼不含字面 '0.4'。"""
    from src.pageindex.faq_conflicts import find_similar_clinic_faqs
    from src.query.faq_shortcut import CLINIC_RELATED_FLOOR

    sig = inspect.signature(find_similar_clinic_faqs)
    assert sig.parameters["floor"].default is CLINIC_RELATED_FLOOR

    conflicts_src = (Path(__file__).resolve().parent.parent / "src" / "pageindex" / "faq_conflicts.py").read_text(encoding="utf-8")
    assert "0.4" not in conflicts_src, "faq_conflicts.py 違規包含硬編碼數值 '0.4'，必須引用 CLINIC_RELATED_FLOOR"


def test_find_similar_clinic_faqs_visibility(isolated_conn: sqlite3.Connection):
    """驗證可見性：未核准（pending）之診所 llm_generated 項目不得列入衝突清單。"""
    from src.pageindex.faq_conflicts import find_similar_clinic_faqs
    from src.pageindex.faq_review import REVIEW_APPROVED, set_review_status
    from src.pageindex.faq_writer import upsert_faqs

    custom_q = "手術後特殊傷口該如何照護之全新題目？"
    upsert_faqs(
        isolated_conn,
        [
            {
                "clinic_id": "3503190424",
                "topic_key": "test-vis",
                "question": custom_q,
                "answer": "這是待核准之特殊傷口答案說明。",
                "category": "special",
            }
        ],
        source_type="llm_generated",
    )

    cur = isolated_conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE question = ?", (custom_q,))
    faq_id = cur.fetchone()[0]

    # 尚未核准時，查詢該題目本身，不應出現在衝突清單中
    res_pending = find_similar_clinic_faqs(isolated_conn, custom_q)
    assert faq_id not in [r["id"] for r in res_pending]

    # 核准後應出現在清單中
    set_review_status(isolated_conn, [faq_id], REVIEW_APPROVED)
    res_approved = find_similar_clinic_faqs(isolated_conn, custom_q)
    assert faq_id in [r["id"] for r in res_approved]


def test_find_similar_clinic_faqs_readonly(isolated_db_path: Path):
    """驗證 find_similar_clinic_faqs 可在 SQLite 唯讀模式 (mode=ro) 下正常執行。"""
    from src.pageindex.faq_conflicts import find_similar_clinic_faqs

    ro_conn = sqlite3.connect(f"file:{isolated_db_path}?mode=ro", uri=True)
    try:
        results = find_similar_clinic_faqs(ro_conn, "術後傷口如何照護？")
        assert isinstance(results, list)
    finally:
        ro_conn.close()
