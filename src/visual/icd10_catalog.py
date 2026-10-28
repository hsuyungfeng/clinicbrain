"""臺灣基層診所 ICD-10-CM 高頻疾病目錄：載入、驗證與種子寫入 (Phase 35)。

設計原則：
1. 單一來源：36 筆疾病條目由 `data/icd10/primary_care_36_catalog.json` 定義，本模組只負責載入與驗證。
2. 唯一寫入路徑：視覺卡走 `src.visual.writer.upsert_assets`，衛教 FAQ 走 `src.pageindex.faq_writer.upsert_faqs`。
3. 一般醫學共用（`clinic_id IS NULL`）；視覺卡預設 `pending`，FAQ 以 `llm_generated` 寫入（恆為 `pending`，
   依 AGENTS.md 2.12 「一般衛教內容須經醫師審核後始得入庫」）。
4. 零阿拉伯數字：所有可見文字（不含 `topic_key` 與 metadata 代碼）不得含 0-9。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from src.ingestion.generate_faq import validate_single_faq
from src.visual.icd10_enrichment import (
    CONNECTORS_BASE,
    LEFT_MODES_BASE,
    RIGHT_MODES_BASE,
    SYSTEM_BY_SPECIALTY,
    validate_summary,
)
from src.visual.ir import validate_ir
from src.visual.review import set_review_status
from src.visual.writer import upsert_assets
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.db_writer import upsert_trees

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "data" / "icd10" / "primary_care_36_catalog.json"

# 6 大專科與各專科目標筆數（總計 36）
SPECIALTY_TARGETS: dict[str, int] = {
    "ent_peds_fm": 8,
    "internal_chronic": 6,
    "gi_hepatobiliary": 6,
    "dermatology": 7,
    "ortho_rehab": 5,
    "uro_obgyn": 4,
}

# 一般衛教 FAQ 寫入來源：llm_generated 會使列為 pending（Fail-Closed），需醫師以 review_faq approve 核准
FAQ_SOURCE_TYPE = "llm_generated"
VISUAL_SOURCE_TYPE = "manual"
ORIGIN_TAG = "icd10_primary_care_catalog"

_ARABIC_DIGIT_RE = re.compile(r"\d")


def load_icd10_catalog(path: Optional[Path | str] = None) -> list[dict[str, Any]]:
    """載入 ICD-10 目錄 JSON（不做驗證，驗證請呼叫 validate_catalog_entry）。"""
    target = Path(path) if path is not None else DEFAULT_CATALOG_PATH
    with target.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("ICD-10 目錄須為陣列")
    return data


def _iter_visible_strings(obj: Any) -> Iterable[str]:
    """遞迴產生 IR 中所有可見文字（略過 topic_key 這類機器識別碼）。"""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if key == "topic_key":
                continue
            yield from _iter_visible_strings(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_visible_strings(item)


def validate_catalog_entry(entry: dict[str, Any]) -> tuple[bool, str]:
    """驗證單筆 ICD-10 條目：IR、零阿拉伯數字、禁用 surgical_action、FAQ 合規。

    回傳 (ok, code)；code 為固定英文代碼，不回傳原文。
    """
    if not isinstance(entry, dict):
        return False, "schema_error"
    for key in ("icd10_code", "specialty", "topic_key", "ir", "faqs", "clinical_summary"):
        if key not in entry:
            return False, "schema_error"
    if entry["specialty"] not in SPECIALTY_TARGETS:
        return False, "unknown_specialty"

    s_ok, s_code = validate_summary(entry["clinical_summary"])
    if not s_ok:
        return False, s_code

    ir = entry["ir"]
    if not isinstance(ir, dict) or ir.get("topic_key") != entry["topic_key"]:
        return False, "schema_error"

    ok, code = validate_ir(ir)
    if not ok:
        return False, code

    for text in _iter_visible_strings(ir):
        if _ARABIC_DIGIT_RE.search(text):
            return False, "arabic_digit"

    for scene in ir["scenes"]:
        if scene["blueprint"] == "surgical_action":
            return False, "surgical_action_forbidden"

    # Phase 35-02：Scene 1 必須為 pathology_mechanism，且器官系統與專科一一對應
    scene1 = ir["scenes"][0]
    if scene1["blueprint"] != "pathology_mechanism":
        return False, "scene1_blueprint"
    if scene1["params"].get("organ_system") != SYSTEM_BY_SPECIALTY[entry["specialty"]]:
        return False, "organ_system_mismatch"

    # Phase 35-03：場景 2 必須為基層誘因對照模式，場景 3 必須為基層病程模式
    scene2 = ir["scenes"][1]
    if scene2["blueprint"] != "contrast":
        return False, "scene2_blueprint"
    if scene2["params"]["left"]["mode"] not in LEFT_MODES_BASE:
        return False, "scene2_left_mode"
    if scene2["params"]["right"]["mode"] not in RIGHT_MODES_BASE:
        return False, "scene2_right_mode"
    scene3 = ir["scenes"][2]
    if scene3["blueprint"] != "timeline" or scene3["params"]["connectors"] not in CONNECTORS_BASE:
        return False, "scene3_connectors"

    faqs = entry["faqs"]
    if not isinstance(faqs, list) or len(faqs) != 2:
        return False, "faq_count"
    for item in faqs:
        f_ok, _reason = validate_single_faq(item, check_dosage=True, require_doctor_warning=True)
        if not f_ok:
            return False, "faq_invalid"

    return True, "ok"


def entry_to_page_index_tree(entry: dict[str, Any]) -> dict[str, Any]:
    """將單筆 ICD-10 條目轉為 page_index_trees 一般醫學共用樹（純函式，不寫入資料庫）。

    四段式對應：clinical_presentation→pre_op、pathophysiology→procedure、
    management_care→post_op_short、red_flags_prevention→maintenance。醫師註記一律留空（None）。
    """
    ir_title = entry["ir"]["title"]
    summary = entry["clinical_summary"]
    keywords = " ".join(entry["ir"]["keywords"])
    return {
        "doc_id": entry["topic_key"],
        "clinic_id": None,
        "category": "general",
        "title": ir_title,
        "pre_op": summary["clinical_presentation"],
        "pre_op_physician_notes": None,
        "procedure": summary["pathophysiology"],
        "procedure_physician_notes": None,
        "post_op_short": summary["management_care"],
        "post_op_short_physician_notes": None,
        "maintenance": summary["red_flags_prevention"],
        "maintenance_physician_notes": None,
        "summary_text": f"{ir_title}（{entry['icd10_code']}）：{keywords}。{summary['pathophysiology']}",
    }


def seed_icd10_catalog(
    conn: sqlite3.Connection,
    catalog: Optional[list[dict[str, Any]]] = None,
    *,
    approve_visuals: bool = False,
    seed_trees: bool = True,
    approve_trees: bool = False,
    commit: bool = True,
) -> dict[str, Any]:
    """將 ICD-10 目錄寫入視覺卡、一般衛教 FAQ 與（選填）一般醫學推理樹（皆 clinic_id IS NULL）。

    任一條目驗證失敗即整批拒絕，不寫入任何資料。
    seed_trees: 是否寫入 36 棵 general 推理樹（經 upsert_trees 唯一寫入路徑）。
    approve_trees: False（預設）寫為 llm_generated／pending；True 寫為 clinic_upload／approved。
    所有寫入共用同一交易（commit=False 時由呼叫端統一提交）。
    回傳摘要：visuals、approved、faqs、trees（皆為 (inserted, updated, unchanged) 或數字）。
    """
    entries = catalog if catalog is not None else load_icd10_catalog()

    for entry in entries:
        ok, code = validate_catalog_entry(entry)
        if not ok:
            raise ValueError(f"ICD-10 條目驗證失敗（{entry.get('topic_key', '?')}）：{code}")

    assets = []
    faqs: list[dict[str, Any]] = []
    for entry in entries:
        meta = {
            "icd10_code": entry["icd10_code"],
            "icd10_alt": entry.get("icd10_alt", []),
            "specialty": entry["specialty"],
            "origin": ORIGIN_TAG,
        }
        assets.append({
            "topic_key": entry["topic_key"],
            "title": entry["ir"]["title"],
            "keywords": entry["ir"]["keywords"],
            "ir": entry["ir"],
            "metadata": meta,
        })
        for item in entry["faqs"]:
            faqs.append({
                "question": item["question"],
                "answer": item["answer"],
                "category": "general",
                "clinic_id": None,
                "topic_key": entry["topic_key"],
                "metadata": json.dumps(meta, ensure_ascii=False),
            })

    visual_counts = upsert_assets(conn, assets, source_type=VISUAL_SOURCE_TYPE, commit=False)

    approved = 0
    if approve_visuals:
        for asset in assets:
            set_review_status(conn, asset["topic_key"], "approved", commit=False, clinic_id=None)
            approved += 1

    faq_counts = upsert_faqs(conn, faqs, source_type=FAQ_SOURCE_TYPE, commit=False)

    tree_counts = (0, 0, 0)
    if seed_trees:
        status = "approved" if approve_trees else "pending"
        tree_source = "clinic_upload" if approve_trees else FAQ_SOURCE_TYPE
        trees = [{**entry_to_page_index_tree(e), "review_status": status} for e in entries]
        tree_counts = upsert_trees(conn, trees, source_type=tree_source, commit=False)

    if commit:
        conn.commit()

    return {
        "visuals": visual_counts,
        "approved": approved,
        "faqs": faq_counts,
        "trees": tree_counts,
    }
