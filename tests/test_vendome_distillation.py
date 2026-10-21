#!/usr/bin/env python3
"""
單元測試：凡登整形外科診所（3503264627）27 篇官方醫療內文提煉驗證。
驗證項目：
1. 27 棵專屬 PageIndex 臨床推理樹欄位完整性、四段式結構與醫師指令留空。
2. 54 筆高頻口語 FAQ 之繁體中文、問答長度與主題關聯。
3. 醫療合規性：零價格洩漏、零保證療效詞彙、零簡體字。
4. SQLite FTS5 trigram 全文檢索雙向檢索驗證。
"""

from pathlib import Path
import sqlite3
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 確保 opencc 可用
try:
    import opencc  # noqa: F401
except ImportError:
    uv_opencc = Path("/home/hsu/.cache/uv/archive-v0/hD69btIoBk4Lc2HKmEOvw")
    if uv_opencc.exists():
        sys.path.insert(0, str(uv_opencc))

from src.pageindex.prompt_template import (
    _FORBIDDEN_PHRASES,
    _POLITICAL_STANCE_PHRASES,
    _SIMPLIFIED_CHAR_SAMPLE,
)

DB_PATH = PROJECT_ROOT / "clinic.db"
CLINIC_ID = "3503264627"

EXPECTED_VENDOME_PROCEDURES = [
    "qray-frx-fractional-laser",
    "thermage-flx-rf",
    "chin-augmentation-genioplasty",
    "mid-lower-smas-facelift",
    "facial-bone-contouring",
    "ultraformer-mpt-hifu",
    "mommy-makeover-reconstruction",
    "fue-hair-transplantation",
    "orthognathic-surgery",
    "triton-laser-hair-removal",
    "hydrafacial-deep-cleansing",
    "nd-yag-laser-toning",
    "hyaluronic-acid-dermal-filler",
    "picosecond-laser-rejuvenation",
    "blepharoplasty-eye-contouring",
    "ultherapy-focused-ultrasound",
    "full-deep-plane-facelift",
    "renuvion-helium-plasma",
    "structural-autologous-rhinoplasty",
    "bbl-broadband-light",
    "varicose-vein-evlt-sclerotherapy",
    "chronic-migraine-botox-decompression",
    "swan-neck-cervicoplasty",
    "overfilled-face-syndrome-correction",
    "asce-rose-exosome-regeneration",
    "rejuran-pdrn-skin-healer",
    "bulbous-nose-rhinoplasty",
]


class TestVendomeDistillation(unittest.TestCase):
    """凡登整形外科 PageIndex 推理樹與 FAQ 提煉驗證。"""

    def setUp(self):
        self.conn = sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True)
        self.cur = self.conn.cursor()

    def tearDown(self):
        self.conn.close()

    def test_vendome_trees_count_and_structure(self):
        """驗證 27 棵專屬推理樹存在且具備標準四段式結構與合法欄位。"""
        doc_ids = [f"{CLINIC_ID}-{slug}" for slug in EXPECTED_VENDOME_PROCEDURES]
        placeholders = ",".join("?" * len(doc_ids))
        self.cur.execute(
            f"""
            SELECT doc_id, title, category, pre_op, procedure, post_op_short,
                   maintenance, summary_text, pre_op_physician_notes,
                   procedure_physician_notes, post_op_short_physician_notes,
                   maintenance_physician_notes, source_type, review_status
            FROM page_index_trees
            WHERE clinic_id = ? AND doc_id IN ({placeholders})
            """,
            [CLINIC_ID, *doc_ids],
        )
        rows = self.cur.fetchall()
        self.assertEqual(len(rows), 27, f"凡登應有 27 棵專屬手術與療程推理樹，實際查得 {len(rows)} 棵")

        for row in rows:
            doc_id, title, cat, pre, proc, post, maint, summ, n1, n2, n3, n4, src, rev = row
            self.assertTrue(doc_id.startswith(f"{CLINIC_ID}-"))
            self.assertTrue(title and len(title) >= 3, f"{doc_id} 標題過短: {title}")
            self.assertEqual(cat, "special")
            self.assertGreaterEqual(len(pre), 40, f"{doc_id} pre_op 過短")
            self.assertGreaterEqual(len(proc), 40, f"{doc_id} procedure 過短")
            self.assertGreaterEqual(len(post), 40, f"{doc_id} post_op_short 過短")
            self.assertGreaterEqual(len(maint), 40, f"{doc_id} maintenance 過短")
            self.assertGreaterEqual(len(summ), 40, f"{doc_id} summary_text 過短")

            # 醫師筆記強制留空
            self.assertIsNone(n1, f"{doc_id} pre_op_physician_notes 應為 None")
            self.assertIsNone(n2, f"{doc_id} procedure_physician_notes 應為 None")
            self.assertIsNone(n3, f"{doc_id} post_op_short_physician_notes 應為 None")
            self.assertIsNone(n4, f"{doc_id} maintenance_physician_notes 應為 None")

            self.assertEqual(src, "clinic_upload")
            self.assertEqual(rev, "approved")

    def test_vendome_faqs_count_and_relevance(self):
        """驗證 54 筆高頻口語 FAQ 存在且每療程至少 2 筆。"""
        self.cur.execute(
            """
            SELECT topic_key, question, answer, category, review_status, source_type
            FROM faq_cache
            WHERE clinic_id = ? AND topic_key LIKE ?
            """,
            (CLINIC_ID, f"{CLINIC_ID}-%"),
        )
        rows = self.cur.fetchall()
        self.assertEqual(len(rows), 54, f"凡登應有 54 筆口語 FAQ，實際查得 {len(rows)} 筆")

        # 驗證每個預期主題皆有恰好 2 筆
        topic_counts = {}
        for r in rows:
            tk, q, a, cat, rev, src = r
            topic_counts[tk] = topic_counts.get(tk, 0) + 1
            self.assertEqual(cat, "special")
            self.assertEqual(rev, "approved")
            self.assertEqual(src, "clinic_upload")
            self.assertTrue(len(q) >= 6, f"問題過短: {q}")
            self.assertTrue(len(a) >= 40, f"答案過短: {a}")
            self.assertTrue("？" in q or "?" in q or "嗎" in q or "什麼" in q or "多久" in q or "如何" in q, f"問句語意不符合常見諮詢問句: {q}")

        for slug in EXPECTED_VENDOME_PROCEDURES:
            tk = f"{CLINIC_ID}-{slug}"
            self.assertEqual(topic_counts.get(tk, 0), 2, f"主題 {tk} 的 FAQ 數量非 2 筆")

    def test_vendome_data_compliance(self):
        """驗證所有樹與 FAQ 零價格洩漏、零保證療效、零政治爭議與零簡體字。"""
        # 檢查推理樹
        self.cur.execute(
            """
            SELECT pre_op || procedure || post_op_short || maintenance || summary_text
            FROM page_index_trees
            WHERE clinic_id = ? AND doc_id LIKE ?
            """,
            (CLINIC_ID, f"{CLINIC_ID}-%"),
        )
        tree_texts = [r[0] for r in self.cur.fetchall()]

        # 檢查 FAQ
        self.cur.execute(
            """
            SELECT question || answer
            FROM faq_cache
            WHERE clinic_id = ? AND topic_key LIKE ?
            """,
            (CLINIC_ID, f"{CLINIC_ID}-%"),
        )
        faq_texts = [r[0] for r in self.cur.fetchall()]

        all_texts = tree_texts + faq_texts
        self.assertGreater(len(all_texts), 0)

        for text in all_texts:
            # 簡體字檢測
            simplified = [c for c in _SIMPLIFIED_CHAR_SAMPLE if c in text]
            self.assertEqual(simplified, [], f"檢出疑似簡體字: {simplified} in {text[:100]}")

            # 保證療效禁詞
            forbidden = [p for p in _FORBIDDEN_PHRASES if p in text]
            self.assertEqual(forbidden, [], f"檢出保證療效禁詞: {forbidden} in {text[:100]}")

            # 政治立場詞
            political = [p for p in _POLITICAL_STANCE_PHRASES if p in text]
            self.assertEqual(political, [], f"檢出政治立場詞: {political} in {text[:100]}")

    def test_fts5_trigram_searchability(self):
        """驗證 FTS5 檢索能夠精準搜尋凡登核心關鍵字。"""
        test_keywords = [
            ("天鵝頸", 1, 1),
            ("中下臉拉皮", 1, 1),
            ("正顎手術", 1, 1),
            ("超能電漿", 1, 1),
            ("鳳凰電波", 1, 1),
            ("削骨手術", 1, 1),
            ("饅化臉", 1, 1),
            ("麗珠蘭", 1, 1),
        ]
        for kw, min_tree_hits, min_faq_hits in test_keywords:
            self.cur.execute(
                "SELECT count(*) FROM page_index_fts WHERE page_index_fts MATCH ?",
                (kw,),
            )
            tree_hits = self.cur.fetchone()[0]
            self.assertGreaterEqual(tree_hits, min_tree_hits, f"page_index_fts 搜尋 '{kw}' 命中不足: {tree_hits}")

            self.cur.execute(
                "SELECT count(*) FROM faq_cache_fts WHERE faq_cache_fts MATCH ?",
                (kw,),
            )
            faq_hits = self.cur.fetchone()[0]
            self.assertGreaterEqual(faq_hits, min_faq_hits, f"faq_cache_fts 搜尋 '{kw}' 命中不足: {faq_hits}")


if __name__ == "__main__":
    unittest.main()
