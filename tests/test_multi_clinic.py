"""
Phase 04 多診所支援測試套件
涵蓋 TASK-00 與 TASK-01 的各項驗收標準：
1. page_index_trees 缺少 clinic_id 拋出 ValueError
2. page_index_trees UPDATE 時維持既有 clinic_id 不受覆寫
3. search_page_index_trees() 的 clinic_id 過濾與向後相容（None）
4. seed_clinic_info 從零建庫重建與冪等性測試
"""

import sqlite3
from pathlib import Path
import pytest

from src.pageindex.db_writer import upsert_trees
from src.pageindex.seed_clinic_info import seed_clinic_info, CLINIC_ID as SEED_CLINIC_ID
from src.query.search import search_page_index_trees
from src.query.router import get_clinic_hours, get_clinic_info, get_clinic_custom_notes, handle_query
from src.clinic.custom_notes import seed_sample_notes


def _build_dummy_tree(doc_id: str, clinic_id: str | None = None, procedure: str = "測試療程步驟", summary: str = "測試摘要") -> dict:
    tree = {
        "doc_id": doc_id,
        "category": "special",
        "pre_op": "術前需禁食",
        "pre_op_physician_notes": None,
        "procedure": procedure,
        "procedure_physician_notes": None,
        "post_op_short": "術後冰敷",
        "post_op_short_physician_notes": None,
        "maintenance": "長期防曬",
        "maintenance_physician_notes": None,
        "summary_text": summary,
    }
    if clinic_id is not None:
        tree["clinic_id"] = clinic_id
    return tree


def test_upsert_trees_missing_clinic_id_raises_value_error(isolated_conn):
    """驗證 upsert_trees() 在 tree dict 缺少 clinic_id 鍵或值為空時，拋出明確的 ValueError。"""
    # 缺少 clinic_id 鍵
    tree_missing_key = _build_dummy_tree("test-proc-no-key")
    with pytest.raises(ValueError, match="缺少必要之 'clinic_id' 鍵"):
        upsert_trees(isolated_conn, [tree_missing_key], source_type="manual")

    # clinic_id 為 None
    tree_none = _build_dummy_tree("test-proc-none", clinic_id=None)
    tree_none["clinic_id"] = None
    with pytest.raises(ValueError, match="缺少必要之 'clinic_id' 鍵"):
        upsert_trees(isolated_conn, [tree_none], source_type="manual")

    # clinic_id 為空字串
    tree_empty = _build_dummy_tree("test-proc-empty", clinic_id="")
    with pytest.raises(ValueError, match="缺少必要之 'clinic_id' 鍵"):
        upsert_trees(isolated_conn, [tree_empty], source_type="manual")


def test_upsert_trees_update_preserves_existing_clinic_id(isolated_conn):
    """驗證 upsert_trees() 對既有 doc_id 執行 UPDATE 時，clinic_id 保持不變，不被覆寫。"""
    orig_clinic_id = "3503190424"
    doc_id = "test-preserve-clinic-id"

    # 1. 首次寫入
    initial_tree = _build_dummy_tree(doc_id, clinic_id=orig_clinic_id, procedure="初版療程步驟")
    ins, upd, unch = upsert_trees(isolated_conn, [initial_tree], source_type="manual")
    assert ins == 1

    # 2. 模擬更新：嘗試傳入不同的 clinic_id 與修改後的內容
    modified_tree = _build_dummy_tree(doc_id, clinic_id="9999999999", procedure="已更新的療程步驟")
    ins2, upd2, unch2 = upsert_trees(isolated_conn, [modified_tree], source_type="manual")
    assert ins2 == 0
    assert upd2 == 1

    # 3. 檢查資料庫記錄：clinic_id 必須維持原始值，procedure 已更新，content_version 已遞增
    cursor = isolated_conn.cursor()
    cursor.execute("SELECT clinic_id, procedure, content_version FROM page_index_trees WHERE doc_id = ?", (doc_id,))
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == orig_clinic_id  # clinic_id 維持原值 "3503190424"！
    assert row[1] == "已更新的療程步驟"
    assert row[2] == 2  # content_version 遞增至 2


def test_search_page_index_trees_clinic_id_filtering(isolated_conn):
    """驗證 search_page_index_trees() 依 clinic_id 過濾與向後相容行為。"""
    # 建立第二家診所的療程資料
    other_clinic_id = "8888888888"
    other_tree = _build_dummy_tree(
        doc_id="other-clinic-hifu",
        clinic_id=other_clinic_id,
        procedure="第二診所的音波拉提特色療程說明",
        summary="第二診所 音波拉提 緊緻拉提療程",
    )
    upsert_trees(isolated_conn, [other_tree], source_type="manual")

    # --- 測試 FTS 路徑（3字以上，如 '音波拉提'）---
    # 1. 指定既有診所 "3503190424"：只回傳該診所資料
    hits_zhiyan = search_page_index_trees(isolated_conn, "音波拉提", clinic_id="3503190424")
    assert len(hits_zhiyan) > 0
    for hit in hits_zhiyan:
        assert hit.fields["clinic_id"] == "3503190424"
    assert "hifu-lifting" in [h.fields["doc_id"] for h in hits_zhiyan]
    assert "other-clinic-hifu" not in [h.fields["doc_id"] for h in hits_zhiyan]

    # 2. 指定第二家診所 "8888888888"：只回傳第二家診所資料
    hits_other = search_page_index_trees(isolated_conn, "音波拉提", clinic_id=other_clinic_id)
    assert len(hits_other) == 1
    assert hits_other[0].fields["clinic_id"] == other_clinic_id
    assert hits_other[0].fields["doc_id"] == "other-clinic-hifu"

    # 3. 指定不存在的診所代碼：回傳空串列
    hits_none = search_page_index_trees(isolated_conn, "音波拉提", clinic_id="nonexistent-code")
    assert hits_none == []

    # 4. 不指定 clinic_id（None）：向後相容，回傳所有診所資料
    hits_all = search_page_index_trees(isolated_conn, "音波拉提", clinic_id=None)
    doc_ids_all = [h.fields["doc_id"] for h in hits_all]
    assert "hifu-lifting" in doc_ids_all
    assert "other-clinic-hifu" in doc_ids_all

    # --- 測試 LIKE fallback 路徑（2字，如 '音波'）---
    # 1. 指定診所
    like_hits_zhiyan = search_page_index_trees(isolated_conn, "音波", clinic_id="3503190424")
    assert len(like_hits_zhiyan) > 0
    for hit in like_hits_zhiyan:
        assert hit.fields["clinic_id"] == "3503190424"

    # 2. 不存在診所
    like_hits_none = search_page_index_trees(isolated_conn, "音波", clinic_id="nonexistent-code")
    assert like_hits_none == []

    # 3. None 向後相容
    like_hits_all = search_page_index_trees(isolated_conn, "音波", clinic_id=None)
    like_doc_ids_all = [h.fields["doc_id"] for h in like_hits_all]
    assert "hifu-lifting" in like_doc_ids_all
    assert "other-clinic-hifu" in like_doc_ids_all


def test_seed_clinic_info_zero_state_rebuild(tmp_path: Path, conn: sqlite3.Connection):
    """驗證 seed_clinic_info() 在空資料庫上建置之資料與正式 clinic.db 完全一致，且具冪等性。"""
    schema_path = Path(__file__).resolve().parent.parent / "src" / "db" / "clinic_schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    new_db_path = tmp_path / "fresh_clinic.db"
    new_conn = sqlite3.connect(str(new_db_path))
    new_conn.executescript(schema_sql)

    # clinic_schema.sql 本身不再內嵌 clinic_info 的種子資料（2026-09-22 修正，
    # 見 schema.sql 的「Sample Data」章節註解）——seed_clinic_info.py 是唯一
    # 權威來源，這裡從零開始執行純結構建庫後應該直接是零筆，不需要再手動
    # DELETE。保留這個斷言本身作為「起始狀態確實是零筆」的顯式驗證。
    cur = new_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM clinic_info")
    assert cur.fetchone()[0] == 0

    # 執行種子寫入
    inserted = seed_clinic_info(new_conn)
    assert inserted == 1

    # 取得新建立的資料
    cur.execute("SELECT clinic_id, name, phone, address, website, opening_date, clinic_type FROM clinic_info WHERE clinic_id = ?", (SEED_CLINIC_ID,))
    new_row = cur.fetchone()
    assert new_row is not None

    # 從正式/fixture 連線讀取既有資料做對比
    prod_cur = conn.cursor()
    prod_cur.execute("SELECT clinic_id, name, phone, address, website, opening_date, clinic_type FROM clinic_info WHERE clinic_id = ?", (SEED_CLINIC_ID,))
    prod_row = prod_cur.fetchone()
    assert prod_row is not None

    # 內容必須完全吻合
    assert new_row == prod_row

    # 冪等性測試：重複執行不拋錯且不新增重複行
    inserted_again = seed_clinic_info(new_conn)
    assert inserted_again == 0
    cur.execute("SELECT COUNT(*) FROM clinic_info")
    assert cur.fetchone()[0] == 1

    new_conn.close()


def test_task02_functions_require_clinic_id(conn: sqlite3.Connection):
    """TASK-02: 驗證 4 個底層相關函式均強制要求 clinic_id 為必填參數（未提供時拋出 TypeError），
    而 handle_query() 保留 clinic_id: str | None = None（general 路由可省略，special 路由未給時拋出 ValueError）。
    """
    # 1. get_clinic_hours(conn) 缺少必填參數
    with pytest.raises(TypeError):
        get_clinic_hours(conn)  # type: ignore[call-arg]

    # 2. get_clinic_info(conn) 缺少必填參數
    with pytest.raises(TypeError):
        get_clinic_info(conn)  # type: ignore[call-arg]

    # 3. get_clinic_custom_notes(conn) 缺少必填參數
    with pytest.raises(TypeError):
        get_clinic_custom_notes(conn)  # type: ignore[call-arg]

    # 4. seed_sample_notes(conn) 缺少必填參數
    with pytest.raises(TypeError):
        seed_sample_notes(conn)  # type: ignore[call-arg]

    # 5. handle_query(conn, query) 在 special 路由下缺少 clinic_id 時拋出 ValueError
    with pytest.raises(ValueError, match="special 路由查詢診所營運資訊需要提供 clinic_id"):
        handle_query(conn, "診所幾點開門？")

    # 6. handle_query(conn, query) 在 general 路由下可正常執行（不依賴 clinic_id）
    res_general = handle_query(conn, "高血壓可以吃什麼水果？")
    assert res_general.route == "general"
    assert res_general.clinic_info is None


def test_handle_query_scopes_page_index_hits_by_clinic_id(isolated_conn: sqlite3.Connection):
    """TASK-02: 驗證 handle_query() 將 clinic_id 傳入 search_page_index_trees 達成療程樹診所隔離。"""
    # 建立第二家診所的音波拉提療程資料
    other_clinic_id = "8888888888"
    other_tree = _build_dummy_tree(
        doc_id="other-clinic-hifu",
        clinic_id=other_clinic_id,
        procedure="第二診所的音波拉提專屬程序",
        summary="第二診所 音波拉提 專屬療程",
    )
    upsert_trees(isolated_conn, [other_tree], source_type="manual")

    # 1. 查詢緻妍外科診所 "3503190424"：只會拿到該診所的樹
    res_zhiyan = handle_query(isolated_conn, "音波拉提會痛嗎？", clinic_id="3503190424")
    assert res_zhiyan.route == "special"
    doc_ids_zhiyan = [h.fields["doc_id"] for h in res_zhiyan.page_index_hits]
    assert "hifu-lifting" in doc_ids_zhiyan
    assert "other-clinic-hifu" not in doc_ids_zhiyan

    # 2. 查詢第二家診所 "8888888888"：只會拿到第二家診所的樹
    res_other = handle_query(isolated_conn, "音波拉提會痛嗎？", clinic_id=other_clinic_id)
    assert res_other.route == "special"
    doc_ids_other = [h.fields["doc_id"] for h in res_other.page_index_hits]
    assert "other-clinic-hifu" in doc_ids_other
    assert "hifu-lifting" not in doc_ids_other

    # 3. 查詢不存在的診所代碼：療程樹命中為空
    res_none = handle_query(isolated_conn, "音波拉提會痛嗎？", clinic_id="nonexistent-id")
    assert res_none.route == "special"
    assert res_none.page_index_hits == []

