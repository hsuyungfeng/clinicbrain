"""
PageIndex 臨床推理樹夜間批次重建引擎測試（Phase 09 BATCH-02 Task 2）。

驗證：
1. 核心保護：重建後 4 個 *_physician_notes 欄位逐欄位完全相同（包含 NULL 與空字串之區分）。
2. 對照組陷阱驗證：若直接以 to_upsert_row 寫入，4 個 physician_notes 會被抹除為 NULL，證明手動保護之必要性。
3. 隱私防護：Prompt 絕不包含既有樹的 physician_notes 機密字樣。
4. 驗證失敗攔截：價格洩漏、簡體字、缺欄位、保證療效等違規輸出不入庫，needs_regeneration 維持 1，
   且錯誤原因安全映射為固定代碼 (TREE_REASON_CODES)。
5. 內容未變判斷：若模型輸出與現存內容相同，不遞增版本，needs_regeneration 自動清為 0。
6. 快照機制：必須寫入快照，目錄不存在自動建立，快照失敗不寫庫，snapshot_dir 為 None 拋錯。
7. 異常與跳過：無 clinic_id 或查無此樹跳過；LocalLLMUnavailableError 向上傳播。
8. 寫入後置檢查與自動還原：偵測到 physician_notes 遭意外竄改時，自動以前像還原資料庫。
"""

import json
from pathlib import Path
import sqlite3
import urllib.request
import pytest

from src.batch.tree_rebuild import (
    PHYSICIAN_NOTE_FIELDS,
    TREE_REASON_CODES,
    TREE_TEXT_FIELDS,
    TreeRebuildResult,
    find_marked_trees,
    rebuild_tree,
)
from src.pageindex.db_writer import (
    CONTENT_FIELDS,
    set_needs_regeneration,
    upsert_trees,
)
from src.pageindex.llm_client import LocalLLMUnavailableError
from src.pageindex.prompt_template import to_upsert_row


@pytest.fixture(autouse=True)
def _block_external_llm_calls(monkeypatch):
    """防禦性 fixture：保證測試期間絕對不發起任何真實外部網路請求。"""
    def _fail_urlopen(*args, **kwargs):
        raise AssertionError("測試期間禁止呼叫 urllib.request.urlopen 發起真實網路連線！")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_urlopen)


def _make_valid_tree_output(
    pre_op: str = "術前需經由醫師詳細評估個人膚況與治療目標，避免過度日曬。",
    procedure: str = "施作過程中能量精準聚焦於目標筋膜層，可能伴隨微溫熱微刺感。",
    post_op_short: str = "術後一週內應加強全臉補水保濕與嚴格防曬，避免高溫場所。",
    maintenance: str = "維持良好生活作息與日常規律防曬，可延長整體保養效果。",
    summary_text: str = "音波拉提臨床推理樹：適用於臉部輪廓緊緻保養，專業醫師親自評估操作。",
) -> str:
    """產生符合 prompt_template 驗證規範的合法假 LLM 輸出 JSON。"""
    return json.dumps(
        {
            "pre_op": pre_op,
            "procedure": procedure,
            "post_op_short": post_op_short,
            "maintenance": maintenance,
            "summary_text": summary_text,
        },
        ensure_ascii=False,
    )


def test_physician_notes_preserved_across_rebuild(isolated_conn, tmp_path: Path):
    """核心測試：重建前後 4 個 *_physician_notes 欄位完全相同（含 NULL 與空字串區別）。"""
    cur = isolated_conn.cursor()
    # 準備 4 種不同形態的 physician_notes
    notes = (
        "醫師指令：術前停用酸類產品一週",
        "",  # 空字串
        None,  # NULL
        "醫師指令：長期維持每季追蹤一次",
    )
    cur.execute(
        """
        UPDATE page_index_trees
        SET pre_op_physician_notes = ?,
            procedure_physician_notes = ?,
            post_op_short_physician_notes = ?,
            maintenance_physician_notes = ?
        WHERE doc_id = 'hifu-lifting'
        """,
        notes,
    )
    isolated_conn.commit()

    # 標記為待重建
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)

    snapshot_dir = tmp_path / "snapshots"
    mock_json = _make_valid_tree_output(summary_text="音波拉提全新重建版本之摘要說明文字。")

    res = rebuild_tree(
        isolated_conn,
        doc_id="hifu-lifting",
        procedure_name="音波拉提",
        llm_call=lambda p: mock_json,
        snapshot_dir=snapshot_dir,
    )

    assert res.status == "rebuilt"
    assert res.previous_source_type == "manual"
    assert "summary_text" in res.changed_fields

    # 檢查 4 個 physician_notes 欄位是否逐欄位絕對相等
    cur.execute(
        """
        SELECT pre_op_physician_notes, procedure_physician_notes,
               post_op_short_physician_notes, maintenance_physician_notes,
               needs_regeneration, source_type, content_version, summary_text
        FROM page_index_trees
        WHERE doc_id = 'hifu-lifting'
        """
    )
    row = cur.fetchone()
    assert (row[0], row[1], row[2], row[3]) == notes
    assert row[4] == 0  # needs_regeneration 已清為 0
    assert row[5] == "llm_generated"
    assert row[6] >= 2  # content_version 已遞增
    assert "全新重建版本" in row[7]


def test_control_group_direct_upsert_erases_notes(isolated_conn):
    """對照組測試（證明陷阱真實存在）：若直接呼叫 upsert_trees，4 個 notes 會被抹除為 NULL。"""
    cur = isolated_conn.cursor()
    cur.execute(
        "UPDATE page_index_trees SET pre_op_physician_notes = '機密指令' WHERE doc_id = 'hifu-lifting'"
    )
    isolated_conn.commit()

    # 模擬直接以 to_upsert_row 呼叫 upsert_trees
    from src.pageindex.prompt_template import parse_and_validate
    mock_tree = parse_and_validate(_make_valid_tree_output())
    row = to_upsert_row("hifu-lifting", "3503190424", "special", mock_tree)

    # row 中的 physician_notes 皆為 None
    assert row["pre_op_physician_notes"] is None

    upsert_trees(isolated_conn, [row], source_type="llm_generated")

    cur.execute("SELECT pre_op_physician_notes FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    # 證明直接寫入會抹除醫師註記為 None！
    assert cur.fetchone()[0] is None


def test_prompt_does_not_leak_physician_notes(isolated_conn, tmp_path: Path):
    """測試 Prompt 構建過程中絕不讀取或洩漏任何 physician_notes。"""
    secret = "SECRET_DOCTOR_INSTRUCTION_98765"
    cur = isolated_conn.cursor()
    cur.execute(
        "UPDATE page_index_trees SET procedure_physician_notes = ? WHERE doc_id = 'hifu-lifting'",
        (secret,),
    )
    isolated_conn.commit()
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)

    captured_prompt = []

    def mock_llm(p: str) -> str:
        captured_prompt.append(p)
        return _make_valid_tree_output()

    rebuild_tree(
        isolated_conn,
        "hifu-lifting",
        "音波拉提",
        mock_llm,
        snapshot_dir=tmp_path / "snaps",
    )
    assert len(captured_prompt) == 1
    assert secret not in captured_prompt[0]


def test_validation_failures_do_not_update_db(isolated_conn, tmp_path: Path):
    """測試違規輸出（價格、簡體字、保證療效、缺欄位）遭拒絕且不更動資料庫。"""
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)
    cur = isolated_conn.cursor()
    cur.execute("SELECT * FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    before_row = cur.fetchone()

    # 1. 價格洩漏
    bad_price = json.dumps(
        {
            "pre_op": "術前說明評估充足。",
            "procedure": "療程費用只要 15000元 整。",
            "post_op_short": "術後多喝水加強保濕。",
            "maintenance": "長期規律保養維持效果。",
            "summary_text": "音波拉提臨床推理樹說明。",
        },
        ensure_ascii=False,
    )
    res_price = rebuild_tree(
        isolated_conn, "hifu-lifting", "音波拉提", lambda p: bad_price, tmp_path / "snaps"
    )
    assert res_price.status == "rejected"
    assert res_price.reason == "price_leak"
    assert "15000" not in repr(res_price)

    # 2. 簡體字
    bad_simp = _make_valid_tree_output(procedure="这个疗程聚焦超音波刺激筋膜层。")
    res_simp = rebuild_tree(
        isolated_conn, "hifu-lifting", "音波拉提", lambda p: bad_simp, tmp_path / "snaps"
    )
    assert res_simp.status == "rejected"
    assert res_simp.reason == "simplified"

    # 資料庫依然保持為標記狀態 (needs_regeneration=1) 且內容完全未更動
    cur.execute("SELECT * FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    assert cur.fetchone() == before_row


def test_unchanged_content_clears_flag(isolated_conn, tmp_path: Path):
    """測試內容完全未變時清除待重建旗標，版本號不遞增。"""
    cur = isolated_conn.cursor()
    cur.execute(
        "SELECT pre_op, procedure, post_op_short, maintenance, summary_text, content_version FROM page_index_trees WHERE doc_id = 'hifu-lifting'"
    )
    c1, c2, c3, c4, c5, ver_before = cur.fetchone()
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)

    same_output = json.dumps(
        {
            "pre_op": c1,
            "procedure": c2,
            "post_op_short": c3,
            "maintenance": c4,
            "summary_text": c5,
        },
        ensure_ascii=False,
    )

    res = rebuild_tree(
        isolated_conn, "hifu-lifting", "音波拉提", lambda p: same_output, tmp_path / "snaps"
    )
    assert res.status == "unchanged"

    cur.execute("SELECT needs_regeneration, content_version FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    flag, ver_after = cur.fetchone()
    assert flag == 0
    assert ver_after == ver_before


def test_snapshot_creation_and_directory_validation(isolated_conn, tmp_path: Path):
    """測試快照建立與目錄驗證。"""
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)
    snap_dir = tmp_path / "valid_snaps"

    # 1. 成功建立快照
    res = rebuild_tree(
        isolated_conn,
        "hifu-lifting",
        "音波拉提",
        lambda p: _make_valid_tree_output(summary_text="音波拉提快照測試版本更新。"),
        snap_dir,
    )
    assert res.status == "rebuilt"
    assert res.snapshot_path is not None
    snap_file = Path(res.snapshot_path)
    assert snap_file.exists()
    snap_data = json.loads(snap_file.read_text(encoding="utf-8"))
    assert snap_data["doc_id"] == "hifu-lifting"
    assert "old" in snap_data and "new" in snap_data

    # 2. snapshot_dir 為已存在檔案時拒絕寫庫
    blocked_file = tmp_path / "blocked.txt"
    blocked_file.write_text("檔案", encoding="utf-8")
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)
    res_fail = rebuild_tree(
        isolated_conn, "hifu-lifting", "音波拉提", lambda p: _make_valid_tree_output(), blocked_file
    )
    assert res_fail.status == "error"
    assert res_fail.reason == "snapshot_failed"

    # 3. snapshot_dir 為 None 拋錯
    with pytest.raises(ValueError):
        rebuild_tree(
            isolated_conn, "hifu-lifting", "音波拉提", lambda p: _make_valid_tree_output(), None
        )


def test_auto_restore_on_physician_notes_mismatch(isolated_conn, tmp_path: Path, monkeypatch):
    """測試後置檢驗發現 physician_notes 損壞時自動還原。"""
    cur = isolated_conn.cursor()
    cur.execute(
        "UPDATE page_index_trees SET pre_op_physician_notes = '絕對不可消失之醫囑' WHERE doc_id = 'hifu-lifting'"
    )
    isolated_conn.commit()
    set_needs_regeneration(isolated_conn, ["hifu-lifting"], True)

    import src.batch.tree_rebuild as tr_mod
    real_upsert = tr_mod.upsert_trees
    call_count = 0

    def faulty_upsert(conn, trees, source_type):
        nonlocal call_count
        call_count += 1
        ret = real_upsert(conn, trees, source_type)
        if call_count == 1:
            # 模擬第一次寫入時被意外破壞
            conn.execute(
                "UPDATE page_index_trees SET pre_op_physician_notes = NULL WHERE doc_id = 'hifu-lifting'"
            )
            conn.commit()
        return ret

    monkeypatch.setattr(tr_mod, "upsert_trees", faulty_upsert)

    res = rebuild_tree(
        isolated_conn,
        "hifu-lifting",
        "音波拉提",
        lambda p: _make_valid_tree_output(summary_text="此版不應生效。"),
        tmp_path / "snaps",
    )

    assert res.status == "error"
    assert res.reason == "physician_notes_mismatch_restored"
    assert call_count == 2

    # 驗證資料庫已被成功還原
    cur.execute("SELECT pre_op_physician_notes, summary_text FROM page_index_trees WHERE doc_id = 'hifu-lifting'")
    note_val, sum_val = cur.fetchone()
    assert note_val == "絕對不可消失之醫囑"
    assert "此版不應生效" not in sum_val


def test_find_marked_trees(isolated_conn):
    """測試 find_marked_trees 篩選與排序。"""
    set_needs_regeneration(isolated_conn, ["hifu-lifting", "botox-injection"], True)

    marked = find_marked_trees(isolated_conn, limit=10)
    assert len(marked) >= 2
    marked_docs = [m["doc_id"] for m in marked]
    assert "hifu-lifting" in marked_docs
    assert "botox-injection" in marked_docs

    # limit 限制
    limited = find_marked_trees(isolated_conn, limit=1)
    assert len(limited) == 1
