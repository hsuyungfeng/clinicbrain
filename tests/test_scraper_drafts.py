"""Phase 23 Task 2 & 3 單元測試：FAQ 草稿建置、合規檢驗與唯一寫入路徑。"""

import json
from pathlib import Path
import re
import sqlite3
import pytest

from src.ingestion.convert_chinese import to_traditional
from src.pageindex.faq_review import visible_faq_sql
from src.scraper.drafts import (
    GUARANTEE_PHRASES,
    DraftBuildResult,
    ScraperDraftError,
    build_faq_drafts,
    write_faq_drafts,
)
from src.scraper.extract import ExtractedClinicPage


@pytest.fixture
def sample_page() -> ExtractedClinicPage:
    return ExtractedClinicPage(
        institution_name="範例醫美診所",
        address="台北市中山區南京東路一段 100 號",
        phone="02-2500-1234",
        business_hours="週一至週五 09:00 - 18:00",
        services=[
            {
                "name": "極致皮秒蜂巢雷射",
                "description": "本療程採用專業先進光震波技術，有效改善肌膚暗沉並撫平細紋，使膚質細緻透亮，術後恢復期極短且提供完整護理衛教。",
            },
            {
                "name": "果酸煥膚角質調理",
                "description": "溫和代謝老化角質層，平衡油脂分泌並淨化毛孔，使肌膚重現光澤柔嫩與平滑觸感，適合粉刺及粗糙膚質之日常定期保養。",
            },
        ],
        doctors=[
            {"name": "王小明", "specialty": "微整形雕塑"},
        ],
        schema_drift=False,
    )


def test_build_faq_drafts_basic(sample_page):
    """Test 1, 2, 9: 產生合規草稿，包含題目、答案、安全 slug，不含 review_status/source_type。"""
    res = build_faq_drafts(
        sample_page,
        clinic_id="3503190424",
        source_url="https://www.nu-vendome.com/location-detail/Taichung/",
        fetched_at="2026-10-14T08:00:00Z",
    )
    assert len(res.drafts) == 2
    assert len(res.rejected) == 0

    first = res.drafts[0]
    assert first["clinic_id"] == "3503190424"
    assert first["category"] == "special"
    assert first["topic_key"].startswith("web-")
    assert first["question"] == "【極致皮秒蜂巢雷射】是什麼？"
    assert "本療程採用" in first["answer"]
    assert "review_status" not in first
    assert "source_type" not in first


def test_no_identity_leak_in_answer_or_question(sample_page):
    """Test 3: 草稿問答絕不包含機構名稱、地址與電話。"""
    res = build_faq_drafts(
        sample_page,
        clinic_id="3503190424",
        source_url="https://www.nu-vendome.com/location-detail/Taichung/",
        fetched_at="2026-10-14T08:00:00Z",
    )
    for draft in res.drafts:
        assert sample_page.institution_name not in draft["question"]
        assert sample_page.institution_name not in draft["answer"]
        assert sample_page.address not in draft["answer"]
        assert sample_page.phone not in draft["answer"]


def test_guarantee_phrase_rejection_independent_of_validate_single_faq(sample_page, monkeypatch):
    """Test 4: 服務含保證療效詞時在前置檢查即被剔除，不依賴 validate_single_faq。"""
    sample_page.services.append(
        {
            "name": "神奇消脂針",
            "description": "本療程採用高濃度萃取精華，保證根除局部頑固脂肪且百分之百有效，術後完全無需運動即可維持窈窕曲線。",
        }
    )

    import src.ingestion.generate_faq as gen_faq_mod

    # monkeypatch validate_single_faq 恆回 (True, None)
    monkeypatch.setattr(gen_faq_mod, "validate_single_faq", lambda item, **kwargs: (True, None))

    res = build_faq_drafts(
        sample_page,
        clinic_id="3503190424",
        source_url="https://www.nu-vendome.com/location-detail/Taichung/",
        fetched_at="2026-10-14T08:00:00Z",
    )
    assert len(res.drafts) == 2
    assert len(res.rejected) == 1
    assert res.rejected[0]["service"] == "神奇消脂針"
    assert res.rejected[0]["reason"] == "guarantee_phrase"


def test_simplified_chinese_conversion(sample_page, monkeypatch):
    """Test 5: 簡體字在 to_traditional 正常運作下可轉換通過；若轉後仍含簡體則剔除。"""
    sample_page.services[0]["description"] = "这是专业的光震波技术，有效改善暗沉并抚平细纹，使肤质细致透亮，术后恢复期极短且提供完整护理卫教。"
    res = build_faq_drafts(
        sample_page,
        clinic_id="3503190424",
        source_url="https://www.nu-vendome.com/location-detail/Taichung/",
        fetched_at="2026-10-14T08:00:00Z",
    )
    assert len(res.drafts) == 2

    # monkeypatch to_traditional 為恆等函式（模擬未轉換）
    import src.scraper.drafts as drafts_mod
    monkeypatch.setattr(drafts_mod, "to_traditional", lambda s: s)
    res_unconverted = build_faq_drafts(
        sample_page,
        clinic_id="3503190424",
        source_url="https://www.nu-vendome.com/location-detail/Taichung/",
        fetched_at="2026-10-14T08:00:00Z",
    )
    assert len(res_unconverted.rejected) >= 1


def test_schema_drift_raises():
    """Test 6: schema_drift 頁面拋出 ScraperDraftError('schema_drift')。"""
    drift_page = ExtractedClinicPage(schema_drift=True, drift_fields=["services"])
    with pytest.raises(ScraperDraftError) as exc:
        build_faq_drafts(
            drift_page,
            clinic_id="3503190424",
            source_url="https://www.nu-vendome.com/location-detail/Taichung/",
            fetched_at="2026-10-14T08:00:00Z",
        )
    assert exc.value.reason == "schema_drift"


def test_metadata_structure_and_doctor_exclusion(sample_page):
    """Test 7 & 8: metadata 僅含機構層級欄位，排除 doctors，且 source_url 經清洗無 query/fragment。"""
    res = build_faq_drafts(
        sample_page,
        clinic_id="3503190424",
        source_url="https://www.example.com/location-detail/x?token=abc#sec",
        fetched_at="2026-10-14T08:00:00Z",
    )
    meta_str = res.drafts[0]["metadata"]
    meta = json.loads(meta_str)
    assert meta["origin"] == "web_scrape"
    assert meta["source_url"] == "https://www.example.com/location-detail/x"
    assert "token" not in meta["source_url"]
    assert "doctors" not in meta["extracted"]
    assert "王小明" not in meta_str
    assert "微整形" not in meta_str
    assert not re.search(r"09\d{2}[-\s]?\d{3}[-\s]?\d{3}", meta_str)
    assert "0912" not in meta_str
    assert "@" not in meta_str


def test_price_pattern_rejection(sample_page):
    """Test 10: 含有價格字樣的服務會被二次過濾剔除。"""
    sample_page.services.append(
        {
            "name": "優惠電波拉提",
            "description": "單次特惠價格 NT$ 999 元整，提供全方位緊緻肌膚保養處置與術後日常追蹤服務完整說明。",
        }
    )
    res = build_faq_drafts(
        sample_page,
        clinic_id="3503190424",
        source_url="https://www.nu-vendome.com/location-detail/Taichung/",
        fetched_at="2026-10-14T08:00:00Z",
    )
    assert len(res.drafts) == 2
    assert any(rej["reason"] == "price_pattern" for rej in res.rejected)


def test_bad_clinic_id(sample_page):
    """Test 11: 非 10 碼數字 clinic_id 拋 ScraperDraftError('bad_clinic_id')。"""
    with pytest.raises(ScraperDraftError) as exc:
        build_faq_drafts(sample_page, clinic_id="abc", source_url="https://x.com/a", fetched_at="now")
    assert exc.value.reason == "bad_clinic_id"

    with pytest.raises(ScraperDraftError) as exc:
        build_faq_drafts(sample_page, clinic_id="350319042", source_url="https://x.com/a", fetched_at="now")
    assert exc.value.reason == "bad_clinic_id"


def test_guarantee_phrases_completeness():
    """Test 12: GUARANTEE_PHRASES 涵蓋 AGENTS §2.5 與 sync.py 完整條目。"""
    from src.api.routes.sync import _FORBIDDEN_PHRASES as SYNC_PHRASES

    for p in ("保證有效", "保證根除", "百分之百有效", "徹底根除", "一定有效"):
        assert p in GUARANTEE_PHRASES

    for sp in SYNC_PHRASES:
        if sp != "physician_notes":
            assert sp in GUARANTEE_PHRASES or to_traditional(sp) in GUARANTEE_PHRASES


def test_identity_leak_doctor_name(sample_page):
    """Test 13: 服務描述或名稱含醫師姓名（含簡體）立即以 identity_leak 剔除。"""
    sample_page.services.append(
        {
            "name": "王小明醫師特約拉提",
            "description": "提供專業輪廓線條微調拉提與緊緻處置，術後恢復期極短且提供完整護理衛教說明事項。",
        }
    )
    sample_page.services.append(
        {
            "name": "極限玻尿酸注射",
            "description": "由王小明医师亲自操作微整形注射，提供完整輪廓線條微調處置，術後恢復期極短且提供完整衛教。",
        }
    )
    res = build_faq_drafts(
        sample_page,
        clinic_id="3503190424",
        source_url="https://www.nu-vendome.com/location-detail/Taichung/",
        fetched_at="2026-10-14T08:00:00Z",
    )
    assert len(res.drafts) == 2
    leak_rejections = [r for r in res.rejected if r["reason"] == "identity_leak"]
    assert len(leak_rejections) == 2


def test_identity_leak_institution_info(sample_page):
    """Test 14: 服務描述或名稱含機構名稱、地址或電話以 identity_leak 剔除。"""
    sample_page.services.append(
        {
            "name": "範例醫美診所專屬保養",
            "description": "提供專業客製化保養處置與術後日常追蹤服務完整說明事項，恢復期極短且提供日常護理諮詢。",
        }
    )
    sample_page.services.append(
        {
            "name": "南京東路分院美白針",
            "description": "歡迎至台北市中山區南京東路一段 100 號預約或電洽 02-2500-1234 進行專業諮詢與日常護理。",
        }
    )
    res = build_faq_drafts(
        sample_page,
        clinic_id="3503190424",
        source_url="https://www.nu-vendome.com/location-detail/Taichung/",
        fetched_at="2026-10-14T08:00:00Z",
    )
    assert len(res.drafts) == 2
    leak_rejections = [r for r in res.rejected if r["reason"] == "identity_leak"]
    assert len(leak_rejections) == 2


def test_inspection_order_guarantee_before_identity(sample_page):
    """Test 15: 同時含保證療效與醫師姓名時，原因判定必須為 guarantee_phrase。"""
    sample_page.services.append(
        {
            "name": "王小明醫師保證有效除皺",
            "description": "由王小明親自操作，保證根除所有面部細紋，恢復青春容顏且效果持久非常顯著完善。",
        }
    )
    res = build_faq_drafts(
        sample_page,
        clinic_id="3503190424",
        source_url="https://www.nu-vendome.com/location-detail/Taichung/",
        fetched_at="2026-10-14T08:00:00Z",
    )
    rejected = [r for r in res.rejected if r["service"] == "王小明醫師保證有效除皺"]
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "guarantee_phrase"


# =========================================================================
# Task 3 測試：write_faq_drafts 唯一寫入路徑
# =========================================================================

def test_write_faq_drafts_lifecycle(isolated_conn, sample_page):
    """Test 1-4, 9: write_faq_drafts 增量寫入、審核前隱蔽、冪等、變更重審與不自動 commit。"""
    res = build_faq_drafts(
        sample_page,
        clinic_id="3503190424",
        source_url="https://www.nu-vendome.com/location-detail/Taichung/",
        fetched_at="2026-10-14T08:00:00Z",
    )

    # 1. 寫入草稿
    ins, upd, unch = write_faq_drafts(isolated_conn, res.drafts)
    assert ins == 2
    assert upd == 0
    assert unch == 0

    # 斷言尚未自動 commit
    assert isolated_conn.in_transaction

    isolated_conn.commit()

    # 查證草稿屬性
    rows = isolated_conn.execute(
        "SELECT source_type, review_status, metadata FROM faq_cache WHERE topic_key LIKE 'web-%' AND metadata NOT LIKE '%service-detail%'"
    ).fetchall()
    assert len(rows) == 2
    for r in rows:
        assert r[0] == "web_upload"
        assert r[1] == "pending"
        meta = json.loads(r[2])
        assert meta["origin"] == "web_scrape"

    # 2. 審核前隱蔽
    vis_sql = visible_faq_sql(isolated_conn)
    visible_rows = isolated_conn.execute(
        f"SELECT COUNT(*) FROM faq_cache WHERE topic_key LIKE 'web-%' AND metadata NOT LIKE '%service-detail%' AND ({vis_sql})"
    ).fetchone()[0]
    assert visible_rows == 0

    # 3. 冪等重跑
    ins2, upd2, unch2 = write_faq_drafts(isolated_conn, res.drafts)
    isolated_conn.commit()
    assert ins2 == 0
    assert upd2 == 0
    assert unch2 == 2

    # 4. 內容變更重審
    res.drafts[0]["answer"] = "修改後的皮秒雷射衛教說明，提供詳細術後保養指南與日常注意事項處置完整指引。"
    ins3, upd3, unch3 = write_faq_drafts(isolated_conn, res.drafts)
    isolated_conn.commit()
    assert ins3 == 0
    assert upd3 == 1
    assert unch3 == 1


def test_write_faq_drafts_fail_closed_checks(isolated_db_path, sample_page):
    """Test 5, 6, 8: 缺少 metadata/review_status 欄位或 clinic_id 不存在時 Fail-Closed。"""
    res = build_faq_drafts(
        sample_page,
        clinic_id="3503190424",
        source_url="https://www.nu-vendome.com/location-detail/Taichung/",
        fetched_at="2026-10-14T08:00:00Z",
    )

    # clinic_id 不存在於 clinic_info
    bad_res = build_faq_drafts(
        sample_page,
        clinic_id="9999999999",
        source_url="https://www.nu-vendome.com/location-detail/Taichung/",
        fetched_at="2026-10-14T08:00:00Z",
    )
    conn = sqlite3.connect(str(isolated_db_path))
    with pytest.raises(ScraperDraftError) as exc:
        write_faq_drafts(conn, bad_res.drafts)
    assert exc.value.reason == "bad_clinic_id"
    conn.close()

    # 缺少 review_status 欄位
    conn_bad = sqlite3.connect(str(isolated_db_path))
    # 建立一個缺少 review_status 的測試表
    conn_bad.execute("CREATE TABLE fake_faq (id INTEGER PRIMARY KEY, question TEXT)")
    import src.pageindex.faq_review as fr_mod
    import src.scraper.drafts as drafts_mod

    # 模擬 has_review_status 為 False
    orig_has_review = drafts_mod.has_review_status
    drafts_mod.has_review_status = lambda c: False
    try:
        with pytest.raises(ScraperDraftError) as exc:
            write_faq_drafts(conn_bad, res.drafts)
        assert exc.value.reason == "review_column_missing"
    finally:
        drafts_mod.has_review_status = orig_has_review

    # 模擬 has_metadata_column 為 False
    orig_has_meta = drafts_mod.has_metadata_column
    drafts_mod.has_metadata_column = lambda c: False
    try:
        with pytest.raises(ScraperDraftError) as exc:
            write_faq_drafts(conn_bad, res.drafts)
        assert exc.value.reason == "metadata_column_missing"
    finally:
        drafts_mod.has_metadata_column = orig_has_meta

    conn_bad.close()
