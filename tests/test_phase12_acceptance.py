"""
tests/test_phase12_acceptance.py - Phase 12 一般疾病內容生成與審核 端到端驗收測試

涵蓋：
1. 種子主題預檢（簽核確認，4 個 general 主題、17 題）
2. 批次生成 → 審核前隱藏 → 醫師 CLI 核准 → 自然語言與匿名衛教命中＋免責宣告
3. 拒絕原因碼檢驗（dosage_prescription 與 missing_doctor_warning）
4. DEBT-03 駁回重生成完整生命週期（標記重生成 → 成功更新回到 pending；相同答案清除旗標）
5. 雲端同步匯出閘門（審核通過前不匯出 general FAQ，通過後匯出）
6. 正式資料庫完整性保證（clinic.db 雜湊全程完全未變）
"""

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
import urllib.request
import pytest

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.config import config
from src.batch.faq_generator import generate_topic_faqs
from src.batch.run_log import RunLogger
from src.batch.runner import BatchConfig, run_batch
from src.batch.topic_sources import SeedTopic, load_seed_file
from src.general.consult import consult_general
from src.general.disclaimer import DISCLAIMER_TEXT
from src.pageindex.faq_review import (
    REVIEW_APPROVED,
    REVIEW_REJECTED,
    get_faq,
    set_review_status,
)
from src.query.router import handle_query
import scripts.review_faq as review_cli

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"
PROD_SHA256_FILE = PROJECT_ROOT / ".planning/phases/12-general-content-generation/prod.sha256"

# 17 題正式種子之高品質合格示範解答（逐字對照 reference/seed_mock_answers.py）
MOCK_ANSWERS: dict[str, str] = {
    "什麼是感冒？": "感冒是由病毒感染上呼吸道所引起的常見疾病，多數人會在一週左右自行恢復。若出現呼吸困難或胸痛，請立即前往急診就醫。",
    "感冒常見症狀有哪些？": "常見症狀包括流鼻水、鼻塞、喉嚨痛、咳嗽與輕微發燒，通常會逐漸改善。若體溫超過39度且持續3天，請盡速就醫。",
    "感冒什麼時候需要就醫？": "若出現呼吸困難、胸痛或意識不清，請立即前往急診；若體溫超過38.5度且持續3天，或症狀超過10天仍未改善，請至門診就診。",
    "感冒時在家要如何照護與休息？": "請充分休息、多補充溫開水，並保持室內空氣流通與適當濕度。若出現呼吸急促或持續嘔吐，請儘速就醫。",
    "感冒時需要多喝水嗎？": "感冒時發燒與流汗容易流失水分，建議少量多次補充溫開水。若出現尿量明顯減少或口乾，請儘速就醫。",
    "什麼是流感？": "流感是由流行性感冒病毒引起的急性呼吸道傳染病，傳染力強，可能出現高燒與全身痠痛。若出現呼吸困難或意識不清，請立即前往急診。",
    "流感常見症狀有哪些？": "常見症狀有突然發燒、頭痛、肌肉痠痛、咳嗽與極度疲倦。若發燒超過72小時仍未退，請至門診就診。",
    "流感什麼時候需要就醫？": "若出現呼吸急促、胸痛、意識不清或抽搐，請立即撥打119或前往急診；嬰幼兒或長者出現高燒不退，也應儘速就醫。",
    "流感患者在家要如何照護？": "請在家休息、避免外出以降低傳染，並補充足夠水分與清淡飲食。若出現呼吸困難或嘴唇發紫，請立即前往急診。",
    "什麼是急性腸胃炎？": "急性腸胃炎是腸胃道受到病毒或細菌感染所造成的發炎，常見腹瀉與嘔吐，多數數天內改善。若腹瀉超過6次或有血便，請立即就醫。",
    "急性腸胃炎常見症狀有哪些？": "常見症狀包括腹瀉、嘔吐、腹痛、噁心與輕度發燒。若一天內嘔吐超過三次或嘔吐不止，應儘速就醫。",
    "急性腸胃炎什麼時候需要就醫？": "若出現血便、黑便、嘔吐不止或脫水徵象如尿量明顯減少，請立即就醫；嬰幼兒或長者出現精神萎靡，也應儘速前往急診。",
    "急性腸胃炎患者在家要如何照護？": "請少量多次補充水分與電解質飲品，飲食由清淡易消化的食物開始，並充分休息。若一天內腹瀉超過三次且無法進食，請就醫。",
    "什麼是過敏性鼻炎？": "過敏性鼻炎是鼻黏膜對塵蟎、花粉等過敏原產生的慢性發炎反應，常反覆發作。若出現呼吸困難或喘鳴，請立即前往急診。",
    "過敏性鼻炎常見症狀有哪些？": "常見症狀有連續打噴嚏、流清水鼻涕、鼻塞與鼻子眼睛發癢，常在早晚或換季時加重。若症狀超過兩週仍未緩解，建議就診。",
    "過敏性鼻炎什麼時候需要就醫？": "若出現呼吸困難、喘鳴或臉部腫脹，請立即前往急診；若症狀持續超過兩週影響睡眠，請至門診就診評估。",
    "過敏性鼻炎患者在家要如何照護？": "請盡量避免接觸塵蟎、花粉與菸味，定期清洗寢具並保持室內清潔。若出現呼吸困難或喘鳴，請立即前往急診。",
}


@pytest.fixture(autouse=True)
def _block_external_network(monkeypatch):
    """防禦性 fixture：保證驗收期間絕對不發起任何真實外部網路請求。"""
    def _fail_urlopen(*args, **kwargs):
        raise AssertionError("測試期間禁止呼叫 urllib.request.urlopen 發起真實網路連線！")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_urlopen)


def _get_file_sha256(path: Path) -> str:
    """計算指定檔案之 SHA-256 雜湊值（分塊讀取）。"""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _assert_prod_db_intact():
    """驗證正式 clinic.db 檔案雜湊完全未變。"""
    if not PROD_SHA256_FILE.exists():
        pytest.fail("正式庫基準雜湊檔 prod.sha256 不存在！")
    baseline = PROD_SHA256_FILE.read_text(encoding="utf-8").split()[0].strip()
    current = _get_file_sha256(PROD_DB_PATH)
    assert current == baseline, f"正式 clinic.db 雜湊改變！基準: {baseline}, 現有: {current}"


def _make_mock_llm(answers_map: dict[str, str] = MOCK_ANSWERS):
    """建立根據 Prompt 問題行回傳對應答案之 Mock LLM 函式。"""
    def _mock_llm(prompt: str) -> str:
        items = []
        for line in prompt.splitlines():
            line_str = line.strip()
            if line_str.startswith("- "):
                q = line_str[2:].strip()
                ans = answers_map.get(q, f"針對【{q}】之合格衛教說明。若症狀持續加重，請儘速就醫。")
                items.append({"question": q, "answer": ans})
        return json.dumps(items, ensure_ascii=False)

    return _mock_llm


def test_01_preflight_seed_topics():
    """驗收 1: 前置檢核 faq_seeds.json 必須至少包含 4 個 general 主題與 17 題問題。"""
    _assert_prod_db_intact()
    seed_path = PROJECT_ROOT / "data/batch/faq_seeds.json"
    seeds = load_seed_file(seed_path)

    gen_topics = [t for t in seeds.topics if t.category == "general"]
    if len(gen_topics) < 4:
        pytest.fail(f"預期至少 4 個 general 主題，實際 {len(gen_topics)} 個")

    total_q = sum(len(t.questions) for t in gen_topics)
    if total_q < 17:
        pytest.fail(f"預期至少 17 題 general 問題，實際 {total_q} 題")

    _assert_prod_db_intact()


def test_02_e2e_generation_approval_and_consultation(
    isolated_db_path: Path,
    isolated_conn: sqlite3.Connection,
    tmp_path: Path,
):
    """
    驗收 2: 端到端主流程：
    批次生成 17 筆 pending → 審核前不可見 → CLI 核准 → 自然語言與一般諮詢命中＋免責宣告。
    """
    _assert_prod_db_intact()
    seed_path = PROJECT_ROOT / "data/batch/faq_seeds.json"
    logger = RunLogger(tmp_path / "logs", echo=False)

    cfg = BatchConfig(
        seed_path=seed_path,
        snapshot_dir=tmp_path / "snapshots",
        skip_trees=True,
        max_faq_topics=10,
    )

    # 1. 執行批次生成
    summary = run_batch(
        isolated_conn,
        cfg,
        llm_call=_make_mock_llm(MOCK_ANSWERS),
        health_check=lambda: None,
        logger=logger,
    )

    assert summary.status == "completed"
    assert summary.faq_inserted == 17
    assert summary.errors == 0

    # 驗證資料庫寫入狀態
    cur = isolated_conn.cursor()
    cur.execute(
        """
        SELECT id, question, category, source_type, review_status, clinic_id
        FROM faq_cache
        WHERE category = 'general'
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()
    assert len(rows) == 17
    inserted_ids = [r[0] for r in rows]
    for r in rows:
        assert r[2] == "general"
        assert r[3] == "llm_generated"
        assert r[4] == "pending"
        assert r[5] is None

    # 2. 審核前不可見檢驗
    target_q = "感冒時在家要如何照護與休息？"
    gen_res_before = consult_general(isolated_conn, target_q)
    assert gen_res_before.status == "no_match"

    hq_res_before = handle_query(isolated_conn, target_q)
    assert hq_res_before.source == "pageindex"

    # 3. 醫師 CLI 核准
    cmd_args = ["--db", str(isolated_db_path), "approve"] + [str(i) for i in inserted_ids]
    code = review_cli.main(cmd_args)
    assert code == 0

    # 4. 審核後命中與免責宣告驗證
    # 4.1 consult_general 命中
    gen_res_after = consult_general(isolated_conn, target_q)
    assert gen_res_after.status == "answered"
    assert len(gen_res_after.faq_hits) > 0
    assert gen_res_after.faq_hits[0]["question"] == target_q

    # 4.2 handle_query 不帶 clinic_id 命中快取短路且帶 disclaimer
    hq_after_no_cid = handle_query(isolated_conn, target_q)
    assert hq_after_no_cid.source == "cache"
    assert hq_after_no_cid.data_level == "general"
    assert hq_after_no_cid.disclaimer == DISCLAIMER_TEXT

    # 4.3 handle_query 帶 clinic_id='3503190424' 實測確定斷言
    hq_after_with_cid = handle_query(isolated_conn, target_q, clinic_id="3503190424")
    assert hq_after_with_cid.source == "cache"
    assert hq_after_with_cid.data_level == "general"
    assert hq_after_with_cid.disclaimer == DISCLAIMER_TEXT

    # 4.4 反例斷言（記錄「感冒照護」不可用於驗收）
    res_counter = consult_general(isolated_conn, "感冒照護")
    assert res_counter.status == "no_match"

    _assert_prod_db_intact()


def test_03_rejection_codes(isolated_conn: sqlite3.Connection):
    """驗收 3: 驗證違規項目的具體拒絕原因碼為 dosage_prescription 與 missing_doctor_warning。"""
    _assert_prod_db_intact()

    topic = SeedTopic(
        topic_key="influenza-basics",
        title="流感基本衛教",
        category="general",
        clinic_id=None,
        keywords=(),
        always=True,
        tree_doc_id=None,
        questions=("什麼是流感？", "流感常見症狀有哪些？"),
    )

    bad_answers = {
        "什麼是流感？": "流感是病毒感染，建議吃止痛藥緩解症狀。若高燒請就醫。",
        "流感常見症狀有哪些？": "常見症狀有發燒頭痛肌肉痠痛咳嗽疲倦，通常一週內改善。",
    }

    # 透過 generate_topic_faqs 直接檢測拒絕碼
    res = generate_topic_faqs(isolated_conn, topic, _make_mock_llm(bad_answers))
    assert len(res.rejected) == 2
    rej_codes = [r["code"] for r in res.rejected]
    assert "dosage_prescription" in rej_codes
    assert "missing_doctor_warning" in rej_codes

    _assert_prod_db_intact()


def test_04_regeneration_lifecycle_debt03(
    isolated_db_path: Path,
    isolated_conn: sqlite3.Connection,
    tmp_path: Path,
):
    """
    驗收 4: DEBT-03 駁回重生成完整生命週期：
    核准 → 駁回 → mark-regen → 批次重生成更新（回到 pending）→ 再次駁回＋mark-regen → 答案相同清除旗標。
    """
    _assert_prod_db_intact()
    seed_path = PROJECT_ROOT / "data/batch/faq_seeds.json"
    logger = RunLogger(tmp_path / "logs", echo=False)

    cfg = BatchConfig(
        seed_path=seed_path,
        snapshot_dir=tmp_path / "snapshots",
        skip_trees=True,
        max_faq_topics=10,
    )

    # 1. 首次批次生成 17 筆
    run_batch(
        isolated_conn,
        cfg,
        llm_call=_make_mock_llm(MOCK_ANSWERS),
        health_check=lambda: None,
        logger=logger,
    )

    cur = isolated_conn.cursor()
    cur.execute("SELECT id, question, answer FROM faq_cache WHERE category = 'general' LIMIT 1")
    target_row = cur.fetchone()
    target_id, target_q, original_ans = target_row

    # 核准
    set_review_status(isolated_conn, [target_id], REVIEW_APPROVED)
    item_approved = get_faq(isolated_conn, target_id)
    assert item_approved["review_status"] == REVIEW_APPROVED
    ver_approved = item_approved["content_version"]

    # 2. 醫師駁回該題
    set_review_status(isolated_conn, [target_id], REVIEW_REJECTED)
    item_rej = get_faq(isolated_conn, target_id)
    assert item_rej["review_status"] == REVIEW_REJECTED
    ver_rejected = item_rej["content_version"]

    # 3. CLI mark-regen
    code_mr = review_cli.main(["--db", str(isolated_db_path), "mark-regen", str(target_id)])
    assert code_mr == 0
    item_marked = get_faq(isolated_conn, target_id)
    assert item_marked["needs_regeneration"] == 1

    # 4. 再次跑批次（Mock 回應全新合格答案）
    new_answers = dict(MOCK_ANSWERS)
    new_ans_text = original_ans + "（更新修訂版衛教說明：請保持充分水分。若發燒超過39度，請儘速就醫。）"
    new_answers[target_q] = new_ans_text

    summary2 = run_batch(
        isolated_conn,
        cfg,
        llm_call=_make_mock_llm(new_answers),
        health_check=lambda: None,
        logger=logger,
    )
    assert summary2.faq_regen_regenerated == 1
    assert summary2.faq_regen_unchanged == 0

    item_regenerated = get_faq(isolated_conn, target_id)
    assert item_regenerated["review_status"] == "pending"
    assert item_regenerated["needs_regeneration"] == 0
    assert item_regenerated["content_version"] == ver_rejected + 1
    assert item_regenerated["answer"] == new_ans_text

    # 5. 再次駁回並 mark-regen，但這次 Mock 回傳相同答案
    set_review_status(isolated_conn, [target_id], REVIEW_REJECTED)
    review_cli.main(["--db", str(isolated_db_path), "mark-regen", str(target_id)])

    summary3 = run_batch(
        isolated_conn,
        cfg,
        llm_call=_make_mock_llm(new_answers),  # 回傳相同 new_ans_text
        health_check=lambda: None,
        logger=logger,
    )
    assert summary3.faq_regen_unchanged == 1
    assert summary3.faq_regen_regenerated == 0

    item_same = get_faq(isolated_conn, target_id)
    assert item_same["review_status"] == REVIEW_REJECTED
    assert item_same["needs_regeneration"] == 0  # 旗標已被清除

    # 6. 第三次批次（不應再被選入重生成隊列）
    called_questions = []
    def spy_llm(prompt: str) -> str:
        for line in prompt.splitlines():
            if line.strip().startswith("- "):
                called_questions.append(line.strip()[2:].strip())
        return json.dumps([], ensure_ascii=False)

    run_batch(
        isolated_conn,
        cfg,
        llm_call=spy_llm,
        health_check=lambda: None,
        logger=logger,
    )
    assert target_q not in called_questions

    _assert_prod_db_intact()


def test_05_sync_export_gate(
    isolated_db_path: Path,
    isolated_conn: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch,
):
    """驗收 5: 雲端同步匯出閘門（審核通過前不匯出 general FAQ，通過後匯出）。"""
    _assert_prod_db_intact()

    # 批次寫入 17 題 pending
    seed_path = PROJECT_ROOT / "data/batch/faq_seeds.json"
    logger = RunLogger(tmp_path / "logs", echo=False)
    cfg = BatchConfig(
        seed_path=seed_path,
        snapshot_dir=tmp_path / "snapshots",
        skip_trees=True,
        max_faq_topics=10,
    )
    run_batch(
        isolated_conn,
        cfg,
        llm_call=_make_mock_llm(MOCK_ANSWERS),
        health_check=lambda: None,
        logger=logger,
    )

    # 建立 TestClient
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "admin_api_key", None)
    app = create_app()

    with TestClient(app) as client:
        # 1. 審核前匯出：不含 general 項目
        resp_before = client.post(
            "/api/v1/sync/export",
            json={"clinic_id": "3503190424", "since_version": 0, "entities": ["faqs"]},
        )
        assert resp_before.status_code == 200
        faqs_before = resp_before.json()["data"]["faqs"]
        gen_before = [f for f in faqs_before if f["category"] == "general"]
        assert len(gen_before) == 0

        # 2. 醫師核准全量 17 筆
        cur = isolated_conn.cursor()
        cur.execute("SELECT id FROM faq_cache WHERE category = 'general'")
        ids = [r[0] for r in cur.fetchall()]
        review_cli.main(["--db", str(isolated_db_path), "approve", *[str(i) for i in ids]])

        # 3. 審核後匯出：包含 17 筆 general 項目
        resp_after = client.post(
            "/api/v1/sync/export",
            json={"clinic_id": "3503190424", "since_version": 0, "entities": ["faqs"]},
        )
        assert resp_after.status_code == 200
        faqs_after = resp_after.json()["data"]["faqs"]
        gen_after = [f for f in faqs_after if f["category"] == "general"]
        assert len(gen_after) == 17

    _assert_prod_db_intact()
