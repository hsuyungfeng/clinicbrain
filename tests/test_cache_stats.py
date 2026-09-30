"""
快取統計資料表、寫入與彙總函式及遷移腳本測試（Phase 07 CACHE-03）。
保證：
1. 嚴格隱私性：問句全文與詞表外敏感文字絕不落入資料庫。
2. clinic_id 與關鍵字白名單校驗。
3. 聚合查詢與 query_only=ON 唯讀相容性。
4. 遷移腳本之冪等性、資料不變性、與對正式庫的強制防禦（先於連線阻斷）。
"""

from pathlib import Path
import sqlite3
import pytest

from src.query.cache_stats import (
    OUTCOME_HIT,
    OUTCOME_MISS,
    OUTCOME_MISS_KEYWORD,
    ROUTE_KEYWORD_VOCAB,
    get_cache_stats,
    record_query_outcome,
)
from scripts.migrate_cache_stats import (
    PROD_DB_PATH,
    apply_cache_stats_schema,
    main as migrate_main,
)


def _dump_table(conn: sqlite3.Connection) -> str:
    """傾印 cache_stats 整張表所有列轉成單一字串，供全表隱私檢驗。"""
    cur = conn.cursor()
    cur.execute("SELECT id, clinic_id, stat_date, outcome, keyword, count FROM cache_stats")
    rows = cur.fetchall()
    return " | ".join(str(r) for r in rows)


# ==============================================================================
# Task 1: 結構、寫入與彙總單元測試
# ==============================================================================

def test_cache_stats_schema_columns(isolated_conn):
    """測試測試複本已具備 cache_stats 表且欄位完全符合設計。"""
    cur = isolated_conn.cursor()
    cur.execute("PRAGMA table_info(cache_stats)")
    columns = [row[1] for row in cur.fetchall()]
    assert columns == ["id", "clinic_id", "stat_date", "outcome", "keyword", "count", "updated_at"]


def test_record_query_outcome_hit_accumulation(isolated_conn):
    """測試 hit 寫入累積，多次命中只累加 ('hit', '') 列之 count，不寫 miss_keyword。"""
    res1 = record_query_outcome(
        isolated_conn,
        clinic_id="3503190424",
        hit=True,
        matched_keywords=["音波"],
    )
    assert res1 == 1

    res2 = record_query_outcome(
        isolated_conn,
        clinic_id="3503190424",
        hit=True,
        matched_keywords=["音波"],
    )
    assert res2 == 1

    cur = isolated_conn.cursor()
    cur.execute("SELECT clinic_id, outcome, keyword, count FROM cache_stats")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0] == ("3503190424", "hit", "", 2)


def test_record_query_outcome_miss_and_keywords(isolated_conn):
    """測試未命中時記錄 1 列 miss 與各關鍵字 1 列 miss_keyword。"""
    rows_written = record_query_outcome(
        isolated_conn,
        clinic_id="3503190424",
        hit=False,
        matched_keywords=["音波", "拉提", "術後"],
    )
    # 1 列 miss + 3 列 miss_keyword
    assert rows_written == 4

    cur = isolated_conn.cursor()
    cur.execute("SELECT outcome, keyword, count FROM cache_stats ORDER BY outcome, keyword")
    rows = cur.fetchall()
    assert len(rows) == 4
    assert rows[0] == ("miss", "", 1)
    assert rows[1] == ("miss_keyword", "拉提", 1)
    assert rows[2] == ("miss_keyword", "術後", 1)
    assert rows[3] == ("miss_keyword", "音波", 1)


def test_record_query_outcome_privacy_vocab_filtering(isolated_conn):
    """測試詞表外之字串（模擬病患問句/個資）被丟棄，絕不出現在資料庫中。"""
    secret_text = "我的隱私問句QZX_病患身分證A123456789"
    record_query_outcome(
        isolated_conn,
        clinic_id="3503190424",
        hit=False,
        matched_keywords=["音波", secret_text],
    )

    dumped = _dump_table(isolated_conn)
    assert secret_text not in dumped
    assert "音波" in dumped


def test_record_query_outcome_keyword_deduplication(isolated_conn):
    """測試單次呼叫重複關鍵字僅累加 1 次。"""
    written = record_query_outcome(
        isolated_conn,
        clinic_id="3503190424",
        hit=False,
        matched_keywords=["音波", "音波", "音波"],
    )
    assert written == 2  # 1 miss + 1 miss_keyword

    cur = isolated_conn.cursor()
    cur.execute("SELECT count FROM cache_stats WHERE outcome = 'miss_keyword' AND keyword = '音波'")
    assert cur.fetchone()[0] == 1


def test_record_query_outcome_clinic_id_validation(isolated_conn):
    """測試 clinic_id 檢核：存在於 clinic_info 才寫入，否則填空字串。"""
    # 1. 不存在之 clinic_id
    record_query_outcome(
        isolated_conn,
        clinic_id="PRIVATE-TEXT-XYZ",
        hit=True,
        matched_keywords=[],
    )
    # 2. None
    record_query_outcome(
        isolated_conn,
        clinic_id=None,
        hit=True,
        matched_keywords=[],
    )
    # 3. 正確之 3503190424
    record_query_outcome(
        isolated_conn,
        clinic_id="3503190424",
        hit=True,
        matched_keywords=[],
    )

    cur = isolated_conn.cursor()
    cur.execute("SELECT clinic_id, count FROM cache_stats ORDER BY clinic_id")
    rows = cur.fetchall()
    # 前兩次因有效 clinic_id 皆為空字串，累加為 count=2
    assert rows[0] == ("", 2)
    assert rows[1] == ("3503190424", 1)


def test_record_query_outcome_empty_keywords_miss(isolated_conn):
    """測試無關鍵字且未命中時僅記錄 1 列 miss。"""
    written = record_query_outcome(
        isolated_conn,
        clinic_id="3503190424",
        hit=False,
        matched_keywords=[],
    )
    assert written == 1
    cur = isolated_conn.cursor()
    cur.execute("SELECT outcome, keyword FROM cache_stats")
    assert cur.fetchall() == [("miss", "")]


def test_record_query_outcome_commits_transaction(isolated_db_path, isolated_conn):
    """測試 record_query_outcome 執行後已完成 commit，另一連線可即時讀取。"""
    record_query_outcome(
        isolated_conn,
        clinic_id="3503190424",
        hit=True,
        matched_keywords=[],
    )

    other_conn = sqlite3.connect(str(isolated_db_path))
    cur = other_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM cache_stats WHERE outcome = 'hit'")
    assert cur.fetchone()[0] == 1
    other_conn.close()


def test_get_cache_stats_aggregation_and_hit_rate(isolated_conn):
    """測試 get_cache_stats 彙總計算 hit_rate 與排行。"""
    # 3 次 hit
    for _ in range(3):
        record_query_outcome(isolated_conn, clinic_id="3503190424", hit=True, matched_keywords=[])
    # 1 次 miss（帶 音波 與 拉提）
    record_query_outcome(isolated_conn, clinic_id="3503190424", hit=False, matched_keywords=["音波", "拉提"])
    # 1 次 miss（僅帶 音波）
    record_query_outcome(isolated_conn, clinic_id="3503190424", hit=False, matched_keywords=["音波"])

    stats = get_cache_stats(isolated_conn)
    assert stats["hit"] == 3
    assert stats["miss"] == 2
    assert stats["total"] == 5
    assert stats["hit_rate"] == 0.6  # 3 / 5

    top_kw = stats["top_miss_keywords"]
    assert len(top_kw) == 2
    assert top_kw[0] == {"keyword": "音波", "count": 2}
    assert top_kw[1] == {"keyword": "拉提", "count": 1}


def test_get_cache_stats_empty_database(isolated_conn):
    """測試無資料時 get_cache_stats 回傳合理預設值（hit_rate 為 None）。"""
    stats = get_cache_stats(isolated_conn)
    assert stats["hit"] == 0
    assert stats["miss"] == 0
    assert stats["total"] == 0
    assert stats["hit_rate"] is None
    assert stats["top_miss_keywords"] == []


def test_get_cache_stats_filtering_by_clinic_and_date(isolated_conn):
    """測試 get_cache_stats 支援 clinic_id 與 since_date 篩選。"""
    record_query_outcome(isolated_conn, clinic_id="3503190424", hit=True, matched_keywords=[])
    record_query_outcome(isolated_conn, clinic_id="", hit=True, matched_keywords=[])

    stats_clinic = get_cache_stats(isolated_conn, clinic_id="3503190424")
    assert stats_clinic["hit"] == 1

    stats_all = get_cache_stats(isolated_conn, clinic_id=None)
    assert stats_all["hit"] == 2

    # since_date 未來日期
    stats_future = get_cache_stats(isolated_conn, since_date="2099-01-01")
    assert stats_future["hit"] == 0


def test_get_cache_stats_query_only_connection(isolated_db_path, isolated_conn):
    """測試在 PRAGMA query_only=ON 的唯讀連線上執行 get_cache_stats 不拋錯。"""
    record_query_outcome(isolated_conn, clinic_id="3503190424", hit=True, matched_keywords=[])

    read_conn = sqlite3.connect(str(isolated_db_path))
    read_conn.execute("PRAGMA query_only = ON;")
    try:
        stats = get_cache_stats(read_conn)
        assert stats["hit"] == 1
    finally:
        read_conn.close()


def test_missing_table_raises_operational_error(tmp_path):
    """測試當資料表不存在時拋出 sqlite3.OperationalError（模組不自動建表）。"""
    empty_db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(empty_db))
    try:
        with pytest.raises(sqlite3.OperationalError):
            get_cache_stats(conn)
        with pytest.raises(sqlite3.OperationalError):
            record_query_outcome(conn, clinic_id=None, hit=True, matched_keywords=[])
    finally:
        conn.close()


# ==============================================================================
# Task 2: 遷移腳本 migrate_cache_stats.py 測試
# ==============================================================================

def test_apply_cache_stats_schema_idempotency_and_preserves_data(isolated_db_path):
    """測試遷移腳本冪等性且不動既有資料。"""
    conn = sqlite3.connect(str(isolated_db_path))
    # 紀錄既有資料列數
    faq_cnt = conn.execute("SELECT COUNT(*) FROM faq_cache").fetchone()[0]
    trees_cnt = conn.execute("SELECT COUNT(*) FROM page_index_trees").fetchone()[0]
    drugs_cnt = conn.execute("SELECT COUNT(*) FROM drugs").fetchone()[0]

    # 模擬表不存在
    conn.execute("DROP TABLE IF EXISTS cache_stats")
    conn.commit()
    conn.close()

    # 第一次套用
    apply_cache_stats_schema(isolated_db_path)
    # 寫入一筆測試資料
    conn2 = sqlite3.connect(str(isolated_db_path))
    record_query_outcome(conn2, clinic_id="3503190424", hit=True, matched_keywords=[])
    conn2.close()

    # 第二次套用（冪等測試）
    apply_cache_stats_schema(isolated_db_path)

    # 驗證既有資料與新寫入資料完全未受破壞
    conn3 = sqlite3.connect(str(isolated_db_path))
    assert conn3.execute("SELECT COUNT(*) FROM faq_cache").fetchone()[0] == faq_cnt
    assert conn3.execute("SELECT COUNT(*) FROM page_index_trees").fetchone()[0] == trees_cnt
    assert conn3.execute("SELECT COUNT(*) FROM drugs").fetchone()[0] == drugs_cnt
    assert conn3.execute("SELECT COUNT(*) FROM cache_stats").fetchone()[0] == 1
    conn3.close()


def test_migrate_main_success_on_copy(isolated_db_path, capsys):
    """測試 CLI 針對複本路徑執行 main() 成功並回傳 0。"""
    exit_code = migrate_main(["--db", str(isolated_db_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "成功將 cache_stats 結構套用至" in captured.out


def test_migrate_main_nonexistent_file_returns_2(tmp_path, capsys):
    """測試 CLI 針對不存在之檔案回傳 2 且不建檔。"""
    non_path = tmp_path / "not_found.db"
    exit_code = migrate_main(["--db", str(non_path)])
    assert exit_code == 2
    assert not non_path.exists()
    captured = capsys.readouterr()
    assert "目標資料庫檔案不存在" in captured.err


def test_migrate_main_refuses_prod_without_backup_flag(monkeypatch, capsys):
    """測試 CLI 針對正式庫無備份旗標時立即拒絕（結束碼 2），且先於任何 sqlite3.connect。"""
    def _forbidden_connect(*args, **kwargs):
        raise AssertionError("在拒絕分支前絕不可呼叫 sqlite3.connect！")

    monkeypatch.setattr(sqlite3, "connect", _forbidden_connect)

    exit_code = migrate_main(["--db", str(PROD_DB_PATH)])
    assert exit_code == 2

    captured = capsys.readouterr()
    assert "操作拒絕" in captured.err
    assert "cp clinic.db clinic.db.bak-" in captured.err


def test_migrate_main_dry_run(tmp_path, capsys):
    """測試 --dry-run 僅輸出預覽，不修改資料庫。"""
    copy_db = tmp_path / "dry_copy.db"
    conn = sqlite3.connect(str(copy_db))
    conn.execute("CREATE TABLE dummy (id INT);")
    conn.commit()
    conn.close()

    exit_code = migrate_main(["--db", str(copy_db), "--dry-run"])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "預覽模式" in captured.out
    assert "未修改資料庫" in captured.out

    # 驗證表仍不存在
    conn2 = sqlite3.connect(str(copy_db))
    cur = conn2.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cache_stats'")
    assert cur.fetchone() is None
    conn2.close()
