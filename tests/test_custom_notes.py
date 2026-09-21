"""
Taiwan Clinic Medical PageIndex RAG System - 診所通用備註模組測試
涵蓋 TASK-008 測試範疇：
- 類別 5：clinic_custom_notes UPSERT 行為、重複列防範、參數合法性驗證與查詢整合
所有寫入測試均在 isolated_conn（獨立臨時資料庫複本）上執行，嚴格隔離正式資料庫。
"""

import sqlite3
import pytest
from src.clinic.custom_notes import (
    upsert_clinic_note,
    get_clinic_custom_notes,
    seed_sample_notes,
    VALID_SECTIONS,
    DEFAULT_SAMPLE_NOTES,
)
from src.query.router import handle_query


def test_upsert_clinic_note_duplicate_prevention_and_update(isolated_conn):
    """驗證同 clinic_id + section 寫入兩次時，保留最新一筆且不產生重複列（UPSERT 冪等性）。"""
    clinic_id = "test-clinic"
    section = "pre_op"

    # 第一次寫入
    upsert_clinic_note(isolated_conn, clinic_id, section, "術前提醒第一版：請禁食6小時。")
    
    cursor = isolated_conn.cursor()
    cursor.execute(
        "SELECT note, created_at, updated_at FROM clinic_custom_notes WHERE clinic_id = ? AND section = ?",
        (clinic_id, section),
    )
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "術前提醒第一版：請禁食6小時。"
    first_created_at = rows[0][1]

    # 第二次更新同 clinic_id + section
    upsert_clinic_note(isolated_conn, clinic_id, section, "術前提醒第二版：修正為禁食8小時。")

    cursor.execute(
        "SELECT note, created_at, updated_at FROM clinic_custom_notes WHERE clinic_id = ? AND section = ?",
        (clinic_id, section),
    )
    rows_after = cursor.fetchall()
    assert len(rows_after) == 1, "同 clinic_id + section 不應產生重複列"
    assert rows_after[0][0] == "術前提醒第二版：修正為禁食8小時。"
    assert rows_after[0][1] == first_created_at, "created_at 應保留原始建立時間"


@pytest.mark.parametrize("invalid_section", ["invalid_sec", "pre-op", "PRE_OP", "procedures", ""])
def test_upsert_clinic_note_invalid_section_raises_value_error(isolated_conn, invalid_section: str):
    """驗證非法 section 拋出 ValueError。"""
    with pytest.raises(ValueError, match="無效的 section"):
        upsert_clinic_note(isolated_conn, "zhiyan-clinic", invalid_section, "一些備註內容")


@pytest.mark.parametrize("empty_note", ["", "   ", "\t\n  \r"])
def test_upsert_clinic_note_empty_note_raises_value_error(isolated_conn, empty_note: str):
    """驗證空白或純空格 note 拋出 ValueError。"""
    with pytest.raises(ValueError, match="note 內容不可為空"):
        upsert_clinic_note(isolated_conn, "zhiyan-clinic", "pre_op", empty_note)


def test_upsert_multiple_valid_sections(isolated_conn):
    """驗證合法四個段落均可獨立寫入且互不衝突。"""
    clinic_id = "test-multi-sec"
    notes = {
        "pre_op": "術前備註測試",
        "procedure": "療程備註測試",
        "post_op_short": "術後短期備註測試",
        "maintenance": "維持期備註測試",
    }
    for sec, note in notes.items():
        upsert_clinic_note(isolated_conn, clinic_id, sec, note)

    fetched = get_clinic_custom_notes(isolated_conn, clinic_id)
    assert fetched == notes


def test_get_clinic_custom_notes_nonexistent_clinic(isolated_conn):
    """驗證查詢不存在的診所回傳空字典。"""
    notes = get_clinic_custom_notes(isolated_conn, "nonexistent-clinic-id")
    assert notes == {}


def test_seed_sample_notes_idempotent(isolated_conn):
    """驗證 seed_sample_notes 正確寫入預設 3 筆備註，重複執行不增加筆數。"""
    clinic_id = "test-seed-clinic"
    count1 = seed_sample_notes(isolated_conn, clinic_id)
    assert count1 == len(DEFAULT_SAMPLE_NOTES)

    notes1 = get_clinic_custom_notes(isolated_conn, clinic_id)
    assert len(notes1) == len(DEFAULT_SAMPLE_NOTES)

    # 重複執行確認冪等性
    count2 = seed_sample_notes(isolated_conn, clinic_id)
    assert count2 == len(DEFAULT_SAMPLE_NOTES)
    notes2 = get_clinic_custom_notes(isolated_conn, clinic_id)
    assert len(notes2) == len(DEFAULT_SAMPLE_NOTES)


def test_handle_query_masks_prices_in_custom_notes(isolated_conn):
    """防禦性安全測試：若診所通用備註被誤填寫了具體金額，handle_query 必須強制遮罩。"""
    clinic_id = "zhiyan-clinic"
    # 刻意寫入含有價格的自訂備註
    upsert_clinic_note(isolated_conn, clinic_id, "pre_op", "預收保證金1500元或NT$800，術前空腹。")

    res = handle_query(isolated_conn, "請問診所有什麼術前注意事項？", clinic_id=clinic_id)
    assert res.route == "special"
    assert "pre_op" in res.clinic_custom_notes
    pre_op_note = res.clinic_custom_notes["pre_op"]

    assert "1500元" not in pre_op_note
    assert "NT$800" not in pre_op_note
    assert "[請致電診所確認]" in pre_op_note
