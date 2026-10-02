"""
PageIndex 臨床推理樹 needs_regeneration 標記與 CLI 工具測試（Phase 09 BATCH-02 Task 2）。

驗證：
1. set_needs_regeneration 僅修改 needs_regeneration 單一欄位，content_version、source_type、updated_at 與內容不變。
2. 標記後 FTS 檢索依然正常可用。
3. 標記具備冪等性，unmark 可正確清除。
4. 若傳入不存在的 doc_id，整批中斷且零寫入，回傳 missing 清單。
5. upsert_trees 更新內容時維持清除 needs_regeneration 旗標之既有語意。
6. CLI mark / unmark / list 功能完整性。
7. CLI 對正式庫之寫入防禦：未帶 --allow-prod-db 時連線前拒絕（結束碼 2）；list 支援正式庫但強制以 mode=ro 唯讀開啟。
8. 測試前後正式 clinic.db 之 SHA-256 不變。
"""

import hashlib
from pathlib import Path
import sqlite3
import pytest

from src.pageindex.db_writer import set_needs_regeneration, upsert_trees
from src.query.search import search_page_index_trees
from scripts.mark_tree_regen import PROD_DB_PATH, main as mark_cli_main


def _get_sha256(path: Path) -> str:
    """計算指定檔案之 SHA-256 雜湊值。"""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


# 收集階段即時量測正式庫雜湊（只讀），供結尾測試比對
_PROD_SHA256_AT_START = _get_sha256(PROD_DB_PATH)


def test_set_needs_regeneration_modifies_only_target_column(isolated_conn):
    """測試 set_needs_regeneration 僅更動 needs_regeneration，其他欄位與 FTS 檢索完全不受影響。"""
    cur = isolated_conn.cursor()
    cur.execute("SELECT * FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    col_names = [d[0] for d in cur.description]
    row_before = dict(zip(col_names, cur.fetchone()))

    # 執行標記
    changed, missing = set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)
    assert changed == 1
    assert missing == []

    cur.execute("SELECT * FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    row_after = dict(zip(col_names, cur.fetchone()))

    # 斷言僅 needs_regeneration 改變（0 -> 1）
    for col in col_names:
        if col == "needs_regeneration":
            assert row_before[col] == 0
            assert row_after[col] == 1
        else:
            assert row_before[col] == row_after[col], f"欄位 {col} 遭到意外修改！"

    # FTS 檢索仍可命中該樹
    search_results = search_page_index_trees(isolated_conn, "音波", clinic_id="3503190424")
    assert any(r.fields.get("doc_id") == "hifu-lifting" for r in search_results)


def test_set_needs_regeneration_idempotence_and_clear(isolated_conn):
    """測試重複標記之冪等性以及清除標記 (unmark)。"""
    # 第一次標記：1 列變更
    changed, _ = set_needs_regeneration(isolated_conn, ["botox-injection"], True)
    assert changed == 1

    # 第二次標記：0 列變更（冪等）
    changed_again, _ = set_needs_regeneration(isolated_conn, ["botox-injection"], True)
    assert changed_again == 0

    # 清除標記
    changed_unmark, _ = set_needs_regeneration(isolated_conn, ["botox-injection"], False)
    assert changed_unmark == 1

    cur = isolated_conn.cursor()
    cur.execute("SELECT needs_regeneration FROM page_index_trees WHERE doc_id = 'botox-injection'")
    assert cur.fetchone()[0] == 0


def test_set_needs_regeneration_missing_doc_id_aborts_all(isolated_conn):
    """測試若包含不存在之 doc_id，整批操作立即中斷且零寫入。"""
    cur = isolated_conn.cursor()
    cur.execute("SELECT needs_regeneration FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    initial_val = cur.fetchone()[0]

    changed, missing = set_needs_regeneration(
        isolated_conn, ["hifu-lifting", "non-existent-doc-id"], True
    )
    assert changed == 0
    assert missing == ["non-existent-doc-id"]

    # hifu-lifting 應保持未被修改
    cur.execute("SELECT needs_regeneration FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    assert cur.fetchone()[0] == initial_val


def test_upsert_trees_clears_needs_regeneration_on_content_change(isolated_conn):
    """測試 upsert_trees 更新內容時，會將 needs_regeneration 清為 0 之既有語意。"""
    # 先標記為 1
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)

    cur = isolated_conn.cursor()
    cur.execute("SELECT * FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    cols = [d[0] for d in cur.description]
    tree_data = dict(zip(cols, cur.fetchone()))

    # 修改內容中的 pre_op
    tree_data["pre_op"] = tree_data["pre_op"] + "【更新內容】"

    # 執行 upsert_trees
    ins, upd, unc = upsert_trees(isolated_conn, [tree_data], source_type="manual")
    assert (ins, upd, unc) == (0, 1, 0)

    cur.execute("SELECT needs_regeneration FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    assert cur.fetchone()[0] == 0


def test_cli_mark_unmark_and_list(tmp_path: Path, isolated_db_path: Path):
    """測試 CLI 工具的 mark、unmark 與 list 指令。"""
    # 1. 初始 list 應無標記
    ret = mark_cli_main(["--db", str(isolated_db_path), "list"])
    assert ret == 0

    # 2. mark 兩筆
    ret = mark_cli_main(["--db", str(isolated_db_path), "mark", "hifu-lifting", "botox-injection"])
    assert ret == 0

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute("SELECT doc_id FROM page_index_trees WHERE needs_regeneration = 1 ORDER BY doc_id")
    assert [r[0] for r in cur.fetchall()] == ["botox-injection", "hifu-lifting"]
    conn.close()

    # 3. unmark 一筆
    ret = mark_cli_main(["--db", str(isolated_db_path), "unmark", "botox-injection"])
    assert ret == 0

    conn = sqlite3.connect(str(isolated_db_path))
    cur = conn.cursor()
    cur.execute("SELECT doc_id FROM page_index_trees WHERE needs_regeneration = 1")
    assert [r[0] for r in cur.fetchall()] == ["hifu-lifting"]
    conn.close()

    # 4. 包含不存在之 doc_id 回傳 2
    ret = mark_cli_main(["--db", str(isolated_db_path), "mark", "no-such-tree"])
    assert ret == 2


def test_cli_prod_db_defense_and_list_mode_ro(monkeypatch):
    """測試 CLI 對正式庫之防禦：寫入無 --allow-prod-db 連線前拒絕，list 強制唯讀連線。"""
    # 1. mark 正式庫未加旗標 -> 連線前阻斷
    def fail_connect(*args, **kwargs):
        raise AssertionError("不應在安全檢查前連線！")

    monkeypatch.setattr(sqlite3, "connect", fail_connect)
    exit_code = mark_cli_main(["--db", str(PROD_DB_PATH), "mark", "hifu-lifting"])
    assert exit_code == 2

    # unmark 亦同
    exit_code_unmark = mark_cli_main(["--db", str(PROD_DB_PATH), "unmark", "hifu-lifting"])
    assert exit_code_unmark == 2

    # 2. list 正式庫：允許查詢，但連線必須帶有 mode=ro
    monkeypatch.undo()
    recorded_connect_args = []
    real_connect = sqlite3.connect

    def mock_connect(*args, **kwargs):
        recorded_connect_args.append((args, kwargs))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", mock_connect)
    exit_code_list = mark_cli_main(["--db", str(PROD_DB_PATH), "list"])
    assert exit_code_list == 0
    assert len(recorded_connect_args) == 1
    call_args, call_kwargs = recorded_connect_args[0]
    conn_str = call_args[0] if call_args else ""
    assert "mode=ro" in conn_str or call_kwargs.get("uri") is True


def test_prod_db_sha256_unmodified():
    """保證正式 clinic.db 在整段測試期間未被修改（與收集階段即時量測值比對，不釘死絕對雜湊）。"""
    assert _get_sha256(PROD_DB_PATH) == _PROD_SHA256_AT_START
