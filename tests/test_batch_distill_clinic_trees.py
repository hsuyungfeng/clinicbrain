#!/usr/bin/env python3
"""
單元測試：門診 8 大核心手術臨床推理樹與動畫草稿批次提煉驗證。
"""

import json
from pathlib import Path
import sqlite3
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 確保 opencc-python-reimplemented 可用
try:
    import opencc  # noqa: F401
except ImportError:
    uv_opencc = Path("/home/hsu/.cache/uv/archive-v0/hD69btIoBk4Lc2HKmEOvw")
    if uv_opencc.exists():
        sys.path.insert(0, str(uv_opencc))

from src.visual.autodraft import infer_scene1_blueprint
from src.visual.ir import validate_ir

DB_PATH = PROJECT_ROOT / "clinic.db"
CLINIC_ID = "3503190424"

TARGET_DOC_IDS = [
    "epidermal-cyst-excision",
    "paronychia-matrixectomy",
    "bromhidrosis-rotary-cutter",
    "endolift-laser",
    "microneedle-rf",
    "scar-subcision",
    "lipoma-aspiration",
    "plasma-pen-electrocautery",
]

PRESERVED_DOC_IDS = [
    "botox-injection",
    "electrowave-facelift",
    "fractional-laser",
    "hifu-lifting",
    "hyaluronic-acid-filler",
    "laser-skin-resurfacing",
]

FORBIDDEN_MEDICAL_CLAIMS = [
    "保證有效",
    "保證根除",
    "保證痊癒",
    "百分之百有效",
    "永久不復發",
    "零風險",
    "絕不復發",
]


class TestBatchDistillClinicTrees(unittest.TestCase):
    """驗證 8 大核心門診手術 PageIndex 推理樹與視覺解說卡草稿。"""

    def setUp(self):
        self.conn = sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True)
        self.cur = self.conn.cursor()

    def tearDown(self):
        self.conn.close()

    def test_page_index_trees_count_and_preserved(self):
        """驗證推理樹總數至少 14 筆（緻妍 14 筆且涵蓋其他診所通用樹），且既有 6 筆醫美樹完好無損。"""
        self.cur.execute("SELECT count(*) FROM page_index_trees")
        total = self.cur.fetchone()[0]
        self.assertGreaterEqual(total, 14, f"預期至少有 14 筆推理樹，實際為 {total}")

        self.cur.execute("SELECT count(*) FROM page_index_trees WHERE clinic_id = ?", (CLINIC_ID,))
        zhiyan_total = self.cur.fetchone()[0]
        self.assertEqual(zhiyan_total, 14, f"預期緻妍共有 14 筆推理樹，實際為 {zhiyan_total}")

        # 檢查既有 6 筆醫美樹
        self.cur.execute("SELECT doc_id FROM page_index_trees WHERE doc_id IN ({})".format(
            ",".join("?" * len(PRESERVED_DOC_IDS))
        ), PRESERVED_DOC_IDS)
        found_preserved = {r[0] for r in self.cur.fetchall()}
        self.assertEqual(found_preserved, set(PRESERVED_DOC_IDS))

    def test_distilled_trees_fields_and_compliance(self):
        """驗證 8 筆核心手術推理樹欄位完整且符合醫療法規規範。"""
        self.cur.execute(
            """
            SELECT doc_id, clinic_id, title, category, pre_op, procedure, post_op_short,
                   maintenance, summary_text, review_status, source_type
            FROM page_index_trees
            WHERE doc_id IN ({})
            """.format(",".join("?" * len(TARGET_DOC_IDS))),
            TARGET_DOC_IDS,
        )
        rows = self.cur.fetchall()
        self.assertEqual(len(rows), 8, "應有 8 筆新產生的外科手術推理樹")

        for r in rows:
            doc_id, clinic_id, title, category, pre_op, proc, post_op, maint, summary, status, src = r
            self.assertEqual(clinic_id, CLINIC_ID, f"{doc_id} 的 clinic_id 應為 {CLINIC_ID}")
            self.assertEqual(category, "special", f"{doc_id} 的 category 應為 special")
            self.assertEqual(status, "approved", f"{doc_id} 的 review_status 應為 approved")
            self.assertEqual(src, "clinic_upload", f"{doc_id} 的 source_type 應為 clinic_upload")
            self.assertTrue(bool(title and title.strip()), f"{doc_id} 缺少 title")
            self.assertTrue(bool(pre_op and pre_op.strip()), f"{doc_id} 缺少 pre_op")
            self.assertTrue(bool(proc and proc.strip()), f"{doc_id} 缺少 procedure")
            self.assertTrue(bool(post_op and post_op.strip()), f"{doc_id} 缺少 post_op_short")
            self.assertTrue(bool(maint and maint.strip()), f"{doc_id} 缺少 maintenance")
            self.assertTrue(bool(summary and summary.strip()), f"{doc_id} 缺少 summary_text")

            # 醫療法規檢核：無誇大宣稱
            combined_text = f"{title} {pre_op} {proc} {post_op} {maint} {summary}"
            for claim in FORBIDDEN_MEDICAL_CLAIMS:
                self.assertNotIn(claim, combined_text, f"{doc_id} 包含違法醫療誇大宣稱：'{claim}'")

    def test_visual_assets_presence_and_status(self):
        """驗證 8 筆核心手術動畫草稿在 visual_assets 中存在，且狀態為 pending。"""
        expected_keys = [f"tree-{doc_id}" for doc_id in TARGET_DOC_IDS]
        self.cur.execute(
            """
            SELECT topic_key, clinic_id, title, keywords, ir_json, source_type, review_status
            FROM visual_assets
            WHERE topic_key IN ({})
            """.format(",".join("?" * len(expected_keys))),
            expected_keys,
        )
        rows = self.cur.fetchall()
        self.assertEqual(len(rows), 8, "應有 8 筆新產生的視覺解說卡草稿")

        for r in rows:
            topic_key, clinic_id, title, keywords_raw, ir_raw, src, status = r
            self.assertTrue(clinic_id is None or clinic_id == CLINIC_ID, f"{topic_key} 的 clinic_id 應為 None 或 {CLINIC_ID}")
            self.assertIn(status, ("pending", "approved", "rejected"), f"{topic_key} 的 review_status 應為有效狀態")
            self.assertEqual(src, "llm_generated", f"{topic_key} 的 source_type 應為 llm_generated")

            ir = json.loads(ir_raw)
            ok, code = validate_ir(ir)
            self.assertTrue(ok, f"{topic_key} IR 驗證未通過，錯誤代碼={code}")

    def test_infer_scene1_blueprint_coverage(self):
        """驗證 infer_scene1_blueprint 支援 8 大手術主題機轉推斷。"""
        for doc_id in TARGET_DOC_IDS:
            self.cur.execute(
                "SELECT doc_id, title, summary_text FROM page_index_trees WHERE doc_id = ?",
                (doc_id,),
            )
            tree = dict(zip(["doc_id", "title", "summary_text"], self.cur.fetchone()))
            bp, info = infer_scene1_blueprint(tree)
            self.assertIn(
                bp,
                ("cyst_excision", "nail_matrix", "subdermal_curettage", "skin_energy", "laser_action", "process_diagram"),
                f"{doc_id} 推斷出的 blueprint 異常: {bp}",
            )
            self.assertTrue(bool(info.get("title")), f"{doc_id} 的 blueprint 資訊缺少 title")
            self.assertTrue(bool(info.get("params_template")), f"{doc_id} 的 blueprint 資訊缺少 params_template")

    def test_polymorphic_scene2_and_scene3(self):
        """驗證場景 2 與場景 3 具備多型態幾何，不再全體固定為 mass/layered/none。"""
        expected_keys = [f"tree-{doc_id}" for doc_id in TARGET_DOC_IDS]
        self.cur.execute(
            """
            SELECT topic_key, ir_json
            FROM visual_assets
            WHERE topic_key IN ({})
            """.format(",".join("?" * len(expected_keys))),
            expected_keys,
        )
        rows = self.cur.fetchall()
        self.assertEqual(len(rows), 8)

        contrast_modes = set()
        timeline_connectors = set()

        for topic_key, ir_raw in rows:
            ir = json.loads(ir_raw)
            sc2 = ir["scenes"][1]
            sc3 = ir["scenes"][2]

            contrast_modes.add(sc2["params"]["left"]["mode"])
            contrast_modes.add(sc2["params"]["right"]["mode"])
            timeline_connectors.add(sc3["params"]["connectors"])

        # 斷言包含手術與光電的多型態模式
        self.assertIn("wide_incision", contrast_modes)
        self.assertIn("minimal_incision", contrast_modes)
        self.assertIn("thermal_spread", contrast_modes)
        self.assertIn("targeted_energy", contrast_modes)
        self.assertIn("wound_healing", timeline_connectors)
        self.assertIn("collagen_remodeling", timeline_connectors)


if __name__ == "__main__":
    unittest.main()
