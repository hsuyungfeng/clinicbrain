"""
常見問題主題來源與手動清單驗證測試（Phase 09 BATCH-04 Task 1）。

驗證：
1. 載入真實清單 data/batch/faq_seeds.json 成功、結構完整、通過醫療四層驗證。
2. validate_seed_data 驗證拒絕：價格、簡體字、保證療效禁詞、格式非法、關鍵字超界等。
3. select_topics 熱門關鍵字選題：門檻過濾、降冪排序、手動主題排後、去重、unmapped 提示。
4. select_topics 日期範圍過濾與 max_topics 截斷。
5. 嚴格隱私性：trace callback 證明 select_topics 僅查詢 cache_stats，永不存取問句全文。
6. cache_stats 資料表不存在時平穩降級：stats_available=False 且仍回傳手動主題。
"""

from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import pytest

from src.batch.topic_sources import (
    SeedFile,
    SeedFileError,
    SeedTopic,
    load_seed_file,
    select_topics,
    validate_seed_data,
)
from src.query.cache_stats import ROUTE_KEYWORD_VOCAB, record_query_outcome

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_SEEDS_PATH = PROJECT_ROOT / "data" / "batch" / "faq_seeds.json"


def test_load_real_seed_file():
    """測試真實種子清單檔合法性與基本元素。"""
    seed = load_seed_file(REAL_SEEDS_PATH)
    assert len(seed.topics) >= 4
    assert len(seed.tree_procedure_names) == 6

    # 必須包含正式庫 6 個 doc_id
    expected_doc_ids = {
        "laser-skin-resurfacing",
        "botox-injection",
        "electrowave-facelift",
        "hyaluronic-acid-filler",
        "fractional-laser",
        "hifu-lifting",
    }
    assert set(seed.tree_procedure_names.keys()) == expected_doc_ids

    # 必須含至少一筆 category='general' 且 clinic_id 為 None 且 always=True 的主題
    general_topics = [
        t for t in seed.topics
        if t.category == "general" and t.clinic_id is None and t.always is True
    ]
    assert len(general_topics) >= 1

    # 所有 keywords 必須屬於 ROUTE_KEYWORD_VOCAB
    for t in seed.topics:
        for kw in t.keywords:
            assert kw in ROUTE_KEYWORD_VOCAB, f"關鍵字 '{kw}' 不在路由詞表中"


def test_validate_seed_data_rejections():
    """測試清單資料校驗失敗之各類防禦分支。"""
    base_valid = {
        "schema_version": 1,
        "description": "測試清單",
        "tree_procedure_names": {"hifu-lifting": "音波拉提"},
        "topics": [
            {
                "topic_key": "valid-topic",
                "title": "合法主題",
                "category": "special",
                "clinic_id": "3503190424",
                "keywords": ["音波"],
                "always": False,
                "tree_doc_id": "hifu-lifting",
                "questions": ["音波拉提效果如何？"],
            }
        ],
    }

    # 1. 簡體字拒絕（「这个」）
    data_simp = json.loads(json.dumps(base_valid))
    data_simp["topics"][0]["questions"][0] = "这个音波拉提效果如何？"
    errs = validate_seed_data(data_simp)
    assert any("簡體" in e for e in errs)

    # 2. 價格數字拒絕（「收費1500元」）
    data_price = json.loads(json.dumps(base_valid))
    data_price["topics"][0]["questions"][0] = "音波拉提收費1500元合理嗎？"
    errs = validate_seed_data(data_price)
    assert any("價格" in e or "合規" in e for e in errs)

    # 3. 保證療效禁詞拒絕（「保證有效」）
    data_guar = json.loads(json.dumps(base_valid))
    data_guar["topics"][0]["questions"][0] = "音波拉提保證有效嗎？"
    errs = validate_seed_data(data_guar)
    assert any("保證療效" in e or "合規" in e for e in errs)

    # 4. 非法 topic_key (大寫/底線)
    data_key = json.loads(json.dumps(base_valid))
    data_key["topics"][0]["topic_key"] = "Invalid_Key"
    errs = validate_seed_data(data_key)
    assert any("topic_key" in e for e in errs)

    # 5. special 缺少 clinic_id
    data_spec_no_id = json.loads(json.dumps(base_valid))
    data_spec_no_id["topics"][0]["clinic_id"] = None
    errs = validate_seed_data(data_spec_no_id)
    assert any("clinic_id" in e for e in errs)

    # 6. general 帶非空 clinic_id
    data_gen_with_id = json.loads(json.dumps(base_valid))
    data_gen_with_id["topics"][0]["category"] = "general"
    errs = validate_seed_data(data_gen_with_id)
    assert any("general" in e for e in errs)

    # 7. keywords 不在 ROUTE_KEYWORD_VOCAB
    data_kw = json.loads(json.dumps(base_valid))
    data_kw["topics"][0]["keywords"] = ["未知火舞"]
    errs = validate_seed_data(data_kw)
    assert any("未知火舞" in e for e in errs)

    # 8. 重複 (clinic_id, topic_key)
    data_dup = json.loads(json.dumps(base_valid))
    data_dup["topics"].append(data_dup["topics"][0])
    errs = validate_seed_data(data_dup)
    assert any("重複" in e for e in errs)

    # 9. schema_version 非 1
    data_ver = json.loads(json.dumps(base_valid))
    data_ver["schema_version"] = 2
    errs = validate_seed_data(data_ver)
    assert any("schema_version" in e for e in errs)


def test_load_seed_file_raises_on_invalid_json(tmp_path: Path):
    """測試載入非合法 JSON 或檔案錯誤時拋出 SeedFileError。"""
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{invalid json", encoding="utf-8")
    with pytest.raises(SeedFileError) as exc_info:
        load_seed_file(bad_json)
    assert len(exc_info.value.errors) > 0


def test_select_topics_hot_keywords_and_manual(isolated_conn):
    """測試 select_topics 依據未命中統計與手動設定之選題行為。"""
    # 建立測試用的 SeedFile
    topic_nail = SeedTopic(
        topic_key="nail-care",
        title="甲溝炎照護",
        category="special",
        clinic_id="3503190424",
        keywords=("甲溝炎",),
        always=False,
        tree_doc_id=None,
        questions=("甲溝炎如何護理？",),
    )
    topic_hifu = SeedTopic(
        topic_key="hifu-care",
        title="音波拉提照護",
        category="special",
        clinic_id="3503190424",
        keywords=("音波", "拉提"),
        always=False,
        tree_doc_id="hifu-lifting",
        questions=("音波拉提後注意？",),
    )
    topic_filler = SeedTopic(
        topic_key="filler-care",
        title="玻尿酸照護",
        category="special",
        clinic_id="3503190424",
        keywords=("玻尿酸",),
        always=False,
        tree_doc_id="hyaluronic-acid-filler",
        questions=("玻尿酸維持多久？",),
    )
    topic_cold = SeedTopic(
        topic_key="cold-care",
        title="感冒照護",
        category="general",
        clinic_id=None,
        keywords=(),
        always=True,
        tree_doc_id=None,
        questions=("感冒多喝水嗎？",),
    )
    seed = SeedFile(
        topics=[topic_nail, topic_hifu, topic_filler, topic_cold],
        tree_procedure_names={"hifu-lifting": "音波拉提"},
    )

    # 模擬 cache_stats 統計資料：
    # 甲溝炎: 5次（達門檻）
    # 玻尿酸: 2次（未達門檻 min_miss_count=3）
    # 雷射: 4次（達門檻但無對應 topic）
    for _ in range(5):
        record_query_outcome(isolated_conn, clinic_id="3503190424", hit=False, matched_keywords=["甲溝炎"])
    for _ in range(2):
        record_query_outcome(isolated_conn, clinic_id="3503190424", hit=False, matched_keywords=["玻尿酸"])
    for _ in range(4):
        record_query_outcome(isolated_conn, clinic_id="3503190424", hit=False, matched_keywords=["雷射"])

    selection = select_topics(
        seed,
        isolated_conn,
        min_miss_count=3,
        since_days=14,
    )

    assert selection.stats_available is True
    # 選中的主題清單：甲溝炎（熱門，排第一）、感冒（always=True 手動，排後）
    selected_keys = [st.topic.topic_key for st in selection.topics]
    assert selected_keys == ["nail-care", "cold-care"]

    st_nail = selection.topics[0]
    assert st_nail.reason == "hot_keyword:甲溝炎"
    assert st_nail.hot_count == 5

    st_cold = selection.topics[1]
    assert st_cold.reason == "manual"
    assert st_cold.hot_count == 0

    # 玻尿酸（2次）因未達 min_miss_count=3 被略過
    assert "filler-care" not in selected_keys

    # 雷射（4次）因無對應 topic 列入 unmapped_keywords
    assert ("雷射", 4) in selection.unmapped_keywords


def test_select_topics_date_window_and_max_topics(isolated_conn):
    """測試 select_topics 之時間窗過濾與 max_topics 截斷。"""
    topic_hifu = SeedTopic(
        topic_key="hifu-care",
        title="音波拉提照護",
        category="special",
        clinic_id="3503190424",
        keywords=("音波",),
        always=False,
        tree_doc_id=None,
        questions=("問題？",),
    )
    topic_manual1 = SeedTopic(
        topic_key="m1", title="手動1", category="general", clinic_id=None,
        keywords=(), always=True, tree_doc_id=None, questions=("問1？",),
    )
    topic_manual2 = SeedTopic(
        topic_key="m2", title="手動2", category="general", clinic_id=None,
        keywords=(), always=True, tree_doc_id=None, questions=("問2？",),
    )
    seed = SeedFile(
        topics=[topic_hifu, topic_manual1, topic_manual2],
        tree_procedure_names={},
    )

    # 寫入 5 次音波，並將其日期手動改為 30 天前
    record_query_outcome(isolated_conn, clinic_id="3503190424", hit=False, matched_keywords=["音波"])
    cur = isolated_conn.cursor()
    past_date = (date.today() - timedelta(days=30)).isoformat()
    cur.execute("UPDATE cache_stats SET stat_date = ?", (past_date,))
    isolated_conn.commit()

    # 1. since_days=14 應過濾掉 30 天前資料，hifu-care 不被選入
    sel_14 = select_topics(seed, isolated_conn, since_days=14, min_miss_count=1)
    sel_keys_14 = [st.topic.topic_key for st in sel_14.topics]
    assert "hifu-care" not in sel_keys_14
    assert sel_keys_14 == ["m1", "m2"]

    # 2. max_topics=1 截斷
    sel_max1 = select_topics(seed, isolated_conn, max_topics=1)
    assert len(sel_max1.topics) == 1


def test_select_topics_privacy_trace(isolated_conn):
    """測試 select_topics 執行期間僅讀取 cache_stats 表，絕不存取任何問句全文。"""
    executed_sqls = []

    def trace_callback(sql: str):
        executed_sqls.append(sql)

    isolated_conn.set_trace_callback(trace_callback)
    try:
        seed = load_seed_file(REAL_SEEDS_PATH)
        select_topics(seed, isolated_conn)
    finally:
        isolated_conn.set_trace_callback(None)

    assert len(executed_sqls) > 0
    for query in executed_sqls:
        query_upper = query.upper()
        # 僅限 SELECT cache_stats
        assert "FAQ_CACHE" not in query_upper
        assert "PAGE_INDEX_TREES" not in query_upper
        assert "QUESTION" not in query_upper or "CACHE_STATS" in query_upper


def test_select_topics_fallback_when_cache_stats_missing(tmp_path: Path):
    """測試 cache_stats 表不存在時，select_topics 平穩降級回傳手動主題。"""
    empty_db = tmp_path / "no_stats.db"
    conn = sqlite3.connect(str(empty_db))
    # 建立完全不含 cache_stats 的資料庫

    seed = load_seed_file(REAL_SEEDS_PATH)
    selection = select_topics(seed, conn)

    assert selection.stats_available is False
    assert selection.unmapped_keywords == []
    # 仍應回傳 always=True 的手動主題
    assert len(selection.topics) >= 1
    assert all(st.reason == "manual" for st in selection.topics)
    conn.close()
