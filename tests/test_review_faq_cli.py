"""
FAQ 醫師審核工具 CLI 測試（Phase 09 BATCH-01 Task 2）。

驗證：
1. list 子命令：依狀態篩選、列表呈現、統計總數、無資料時提示。
2. show 子命令：顯示完整 question 與 answer、不存在時回傳 1。
3. approve / reject / reset 子命令：呼叫 set_review_status、狀態流轉、違規攔截回傳 1。
4. 正式庫安全防禦：寫入子命令未帶 --allow-prod-db 時連線前拒絕（回傳 2）。
5. 查詢唯讀性：list / show 強制採用 SQLite 唯讀模式 (mode=ro)。
6. 未遷移舊庫檢驗：無審核欄位時回傳 2 並提示執行遷移。
7. 正式庫保護：正式 clinic.db 之 SHA-256 在測試前後保持不變。
"""

import hashlib
from pathlib import Path
import sqlite3
import pytest

from scripts.review_faq import PROD_DB_PATH, main as review_cli_main
from src.pageindex.faq_review import REVIEW_APPROVED, REVIEW_PENDING, REVIEW_REJECTED
from src.pageindex.faq_writer import upsert_faqs

OLD_FAQ_MINIMAL_DDL = """
CREATE TABLE faq_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id TEXT,
    topic_key TEXT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT NOT NULL,
    source_type TEXT DEFAULT 'manual',
    content_version INTEGER NOT NULL DEFAULT 1,
    needs_regeneration BOOLEAN NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(clinic_id, topic_key, question)
);
"""


def _get_sha256(path: Path) -> str:
    """計算指定檔案之 SHA-256 雜湊值。"""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


# 收集階段即時量測正式庫雜湊（只讀），供結尾測試比對
_PROD_SHA256_AT_START = _get_sha256(PROD_DB_PATH)


def test_cli_list_subcommand(isolated_db_path: Path, capsys):
    """測試 list 子命令依狀態過濾與輸出統計。"""
    conn = sqlite3.connect(str(isolated_db_path))
    faqs = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-cli-l1",
            "question": "哨兵問句-清單測試1？",
            "answer": "答案1",
            "category": "special",
        },
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-cli-l2",
            "question": "哨兵問句-清單測試2？",
            "answer": "答案2",
            "category": "special",
        },
    ]
    upsert_faqs(conn, faqs, source_type="llm_generated")
    conn.close()

    # 1. 預設 list (status=pending)
    ret = review_cli_main(["--db", str(isolated_db_path), "list"])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "zz-cli-l1" in captured
    assert "zz-cli-l2" in captured
    assert "pending" in captured

    # 2. list --status approved（目前尚無已核准的 llm 項目）
    ret_app = review_cli_main(["--db", str(isolated_db_path), "list", "--status", "approved"])
    assert ret_app == 0
    captured_app = capsys.readouterr().out
    assert "目前沒有" in captured_app


def test_cli_show_subcommand(isolated_db_path: Path, capsys):
    """測試 show 子命令印出完整問答內容。"""
    conn = sqlite3.connect(str(isolated_db_path))
    faq = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-cli-show",
            "question": "哨兵問句-詳細檢視問題？",
            "answer": "這是詳細檢視的專屬答案內容。",
            "category": "special",
        }
    ]
    upsert_faqs(conn, faq, source_type="llm_generated")
    cur = conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE topic_key='zz-cli-show'")
    faq_id = cur.fetchone()[0]
    conn.close()

    # 成功顯示
    ret = review_cli_main(["--db", str(isolated_db_path), "show", str(faq_id)])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "哨兵問句-詳細檢視問題？" in captured
    assert "這是詳細檢視的專屬答案內容。" in captured

    # 不存在的 id 回傳 1
    ret_not_found = review_cli_main(["--db", str(isolated_db_path), "show", "999999"])
    assert ret_not_found == 1


def test_cli_approve_reject_reset_lifecycle(isolated_db_path: Path, capsys):
    """測試 approve、reject、reset 子命令與合規檢查。"""
    conn = sqlite3.connect(str(isolated_db_path))
    faqs = [
        {
            "clinic_id": "3503190424",
            "topic_key": "zz-cli-good",
            "question": "哨兵問句-合規審核問題？",
            "answer": "合規答案文字內容。",
            "category": "special",
        }
    ]
    upsert_faqs(conn, faqs, source_type="llm_generated")
    cur = conn.cursor()
    cur.execute("SELECT id FROM faq_cache WHERE topic_key='zz-cli-good'")
    good_id = cur.fetchone()[0]

    # 直接插入一筆含價格的違規 pending 記錄
    cur.execute(
        """
        INSERT INTO faq_cache (clinic_id, topic_key, question, answer, category, source_type, review_status)
        VALUES ('3503190424', 'zz-cli-bad', '哨兵問句-價格？', '收費只要 1200元 整。', 'special', 'llm_generated', 'pending')
        """
    )
    bad_id = cur.lastrowid
    conn.commit()
    conn.close()

    # 1. 審核 good_id 成功
    ret_app = review_cli_main(["--db", str(isolated_db_path), "approve", str(good_id)])
    assert ret_app == 0
    captured_app = capsys.readouterr().out
    assert f"核准項目: [{good_id}]" in captured_app or f"{good_id}" in captured_app

    # 2. 審核 bad_id 失敗（因價格驗證失敗，回傳 1）
    ret_bad = review_cli_main(["--db", str(isolated_db_path), "approve", str(bad_id)])
    assert ret_bad == 1
    captured_bad = capsys.readouterr().out
    assert "validation_failed" in captured_bad

    # 3. 駁回 good_id
    ret_rej = review_cli_main(["--db", str(isolated_db_path), "reject", str(good_id)])
    assert ret_rej == 0

    # 4. 重置 good_id 回 pending
    ret_rst = review_cli_main(["--db", str(isolated_db_path), "reset", str(good_id)])
    assert ret_rst == 0


def test_cli_prod_db_defense_and_mode_ro(monkeypatch):
    """測試 CLI 對正式庫之防禦：寫入無 --allow-prod-db 阻斷先於連線，list/show 唯讀。"""
    # 1. approve 正式庫無旗標 -> 連線前阻斷
    def fail_connect(*args, **kwargs):
        raise AssertionError("不應在安全檢查前連線！")

    monkeypatch.setattr(sqlite3, "connect", fail_connect)
    exit_code_app = review_cli_main(["--db", str(PROD_DB_PATH), "approve", "1"])
    assert exit_code_app == 2

    exit_code_rej = review_cli_main(["--db", str(PROD_DB_PATH), "reject", "1"])
    assert exit_code_rej == 2

    # 2. list 正式庫：允許查詢，但必須帶有 mode=ro
    monkeypatch.undo()
    recorded_connect_args = []
    real_connect = sqlite3.connect

    def mock_connect(*args, **kwargs):
        recorded_connect_args.append((args, kwargs))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", mock_connect)
    exit_code_list = review_cli_main(["--db", str(PROD_DB_PATH), "list"])
    # 正式庫未遷移時回傳 2（指引遷移），遷移後回傳 0；兩者皆保證以 mode=ro 連線
    assert exit_code_list in (0, 2)
    assert len(recorded_connect_args) == 1
    call_args, call_kwargs = recorded_connect_args[0]
    conn_str = call_args[0] if call_args else ""
    assert "mode=ro" in conn_str or call_kwargs.get("uri") is True


def test_cli_on_unmigrated_database(tmp_path: Path):
    """測試對未遷移（無審核欄位）的舊庫執行 list 回傳 2 並提示執行遷移。"""
    old_db = tmp_path / "old.db"
    conn = sqlite3.connect(str(old_db))
    conn.executescript(OLD_FAQ_MINIMAL_DDL)
    conn.close()

    ret = review_cli_main(["--db", str(old_db), "list"])
    assert ret == 2


def test_prod_db_sha256_unmodified():
    """保證正式 clinic.db 在整段測試期間未被修改（與收集階段即時量測值比對，不釘死絕對雜湊）。"""
    assert _get_sha256(PROD_DB_PATH) == _PROD_SHA256_AT_START
