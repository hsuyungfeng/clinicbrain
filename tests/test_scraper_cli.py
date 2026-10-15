"""Phase 23 Task 3 單元測試：CLI 入口與生產資料庫守門防線。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import pytest

from scripts.scrape_site import main as cli_main
from src.api.config import config
from src.scraper.runner import OWNERSHIP_FILE

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scraper"
SOURCES_JSON = Path(__file__).parents[1] / "data" / "scraper" / "sources.json"


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_interval_below_minimum_rejected(capsys, monkeypatch):
    """Task 3 Test 1: --interval 2 小於下限 3.0，退出碼 2，無 socket 建立。"""
    socket_called = False

    def fake_create_connection(*args, **kwargs):
        nonlocal socket_called
        socket_called = True
        raise RuntimeError("socket should not be opened")

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)

    code = cli_main([
        "--clinic-id", "3503190424",
        "--interval", "2.0",
        "--fixture-dir", str(FIXTURES_DIR),
    ])
    assert code == 2
    assert socket_called is False
    captured = capsys.readouterr()
    assert "不得小於 3.0 秒" in captured.err


def test_cli_unallowlisted_url_rejected(capsys):
    """Task 3 Test 2: --url 不在白名單內，退出碼 2。"""
    code = cli_main([
        "--clinic-id", "3503190424",
        "--url", "https://example.com/other/",
        "--live",
    ])
    assert code == 2
    captured = capsys.readouterr()
    assert "安全政策拒絕" in captured.err


def test_cli_prod_db_guard_realpath(tmp_path, isolated_db_path, monkeypatch, capsys):
    """Task 3 Test 3: --write 指向正式庫且缺少 --allow-prod-db，退出碼 2。"""
    # 將 config.db_path 模擬為 target db
    monkeypatch.setattr(config, "db_path", isolated_db_path)

    code = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(isolated_db_path),
        "--write",
        "--fixture-dir", str(FIXTURES_DIR),
    ])
    assert code == 2
    captured = capsys.readouterr()
    assert "--allow-prod-db" in captured.err


def test_cli_prod_db_guard_symlink_and_relative(tmp_path, isolated_db_path, monkeypatch, capsys):
    """Task 3 Test 4: 以符號連結指向正式庫，仍被 realpath 判定為正式庫並拒絕。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    symlink_db = tmp_path / "symlink_clinic.db"
    symlink_db.symlink_to(isolated_db_path)

    code = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(symlink_db),
        "--write",
        "--fixture-dir", str(FIXTURES_DIR),
    ])
    assert code == 2
    captured = capsys.readouterr()
    assert "--allow-prod-db" in captured.err


def test_cli_prod_db_guard_hardlink(tmp_path, isolated_db_path, monkeypatch, capsys):
    """Task 3 Test 4b: 以硬連結指向正式庫檔案，仍被 os.path.samefile 判定並拒絕。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    hardlink_db = tmp_path / "hardlink_clinic.db"
    os.link(isolated_db_path, hardlink_db)
    try:
        code = cli_main([
            "--clinic-id", "3503190424",
            "--db-path", str(hardlink_db),
            "--write",
            "--fixture-dir", str(FIXTURES_DIR),
        ])
        assert code == 2
        captured = capsys.readouterr()
        assert "--allow-prod-db" in captured.err
    finally:
        # 硬連結會讓 isolated_db_path 的資料區塊在 fixture 刪檔後仍被佔用，必須一併移除
        hardlink_db.unlink(missing_ok=True)


def test_cli_prod_db_guard_missing_confirm_backup(isolated_db_path, monkeypatch, capsys):
    """Task 3 Test 5: 帶有 --allow-prod-db 但缺少 --confirm-prod-backup，退出碼 2。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)

    code = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(isolated_db_path),
        "--write",
        "--allow-prod-db",
        "--fixture-dir", str(FIXTURES_DIR),
    ])
    assert code == 2
    captured = capsys.readouterr()
    assert "--confirm-prod-backup" in captured.err


def test_cli_dry_run_preflight_and_no_mutation(isolated_db_path, capsys):
    """Task 3 Test 6: --dry-run 退出碼 0，資料庫 hash 不變，輸出含 schema_preflight。"""
    h_before = _hash_file(isolated_db_path)

    code = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(isolated_db_path),
        "--dry-run",
        "--fixture-dir", str(FIXTURES_DIR),
    ])
    assert code == 0
    h_after = _hash_file(isolated_db_path)
    assert h_before == h_after

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["summary"]["drafts_written"] == 0
    assert "schema_preflight" in data
    assert data["schema_preflight"]["has_metadata_column"] is True
    assert data["schema_preflight"]["has_review_status"] is True


def test_cli_dry_run_special_characters_in_db_path(tmp_path, isolated_db_path, capsys):
    """Task 3 Test 7: 資料庫路徑含空白與特殊字元（?、#、%），經 URL 編碼後仍可正常 mode=ro 連線。"""
    special_dir = tmp_path / "clinic test #1 %20 ?query"
    special_dir.mkdir(parents=True, exist_ok=True)
    target_db = special_dir / "target.db"
    shutil.copy2(isolated_db_path, target_db)

    try:
        code = cli_main([
            "--clinic-id", "3503190424",
            "--db-path", str(target_db),
            "--dry-run",
            "--fixture-dir", str(FIXTURES_DIR),
        ])
        assert code == 0
        captured = capsys.readouterr()
        assert '"status": "ok"' in captured.out
    finally:
        # 複製的資料庫約 45 MB，測試結束即整個目錄移除
        shutil.rmtree(special_dir, ignore_errors=True)


def test_cli_fixture_dir_offline_mode(isolated_db_path, capsys):
    """Task 3 Test 8: --fixture-dir 離線模式，不發網路，產生草稿數量正確。"""
    code = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(isolated_db_path),
        "--dry-run",
        "--fixture-dir", str(FIXTURES_DIR),
    ])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["summary"]["total"] >= 2
    for out in data["outcomes"]:
        assert out["host"] == "fixture"


def test_cli_unexpected_exception_exit_1(monkeypatch, capsys, isolated_db_path):
    """Task 3 Test 9: 內部非預期例外，退出碼 1，stderr 僅含例外類別名。"""
    import scripts.scrape_site as cli_mod

    def fake_run(*args, **kwargs):
        raise RuntimeError("Internal crash detail should be masked")

    monkeypatch.setattr(cli_mod, "run_scrape_urls", fake_run)

    code = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(isolated_db_path),
        "--dry-run",
        "--fixture-dir", str(FIXTURES_DIR),
    ])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "RuntimeError"
    assert "Internal crash" not in captured.err


def test_cli_urls_file_parsing(tmp_path, isolated_db_path, monkeypatch, capsys):
    """Task 3 Test 10: --urls-file 解析，忽略註解與空行。"""
    urls_file = tmp_path / "targets.txt"
    urls_file.write_text(
        "# 診所據點\n"
        "\n"
        "https://www.nu-vendome.com/location-detail/Taichung/\n"
        "   \n"
        "# 另一分院\n"
        "https://www.nu-vendome.com/location-detail/Taipei/\n",
        encoding="utf-8",
    )

    captured_urls = []
    import scripts.scrape_site as cli_mod

    def fake_run(urls, **kwargs):
        nonlocal captured_urls
        captured_urls = urls
        from src.scraper.report import BatchReport
        return BatchReport(status="ok")

    monkeypatch.setattr(cli_mod, "run_scrape_urls", fake_run)

    code = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(isolated_db_path),
        "--urls-file", str(urls_file),
        "--live",
    ])
    assert code == 0
    assert len(captured_urls) == 2
    assert captured_urls[0] == "https://www.nu-vendome.com/location-detail/Taichung/"
    assert captured_urls[1] == "https://www.nu-vendome.com/location-detail/Taipei/"


def test_cli_git_notice_on_prod_write(isolated_db_path, monkeypatch, capsys):
    """Task 3 Test 11: 寫入正式庫成功後，stderr 輸出請勿直接 git add 警示。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)

    import scripts.scrape_site as cli_mod
    from src.scraper.report import BatchReport

    def fake_run(*args, **kwargs):
        return BatchReport(status="ok")

    monkeypatch.setattr(cli_mod, "run_scrape_urls", fake_run)

    code = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(isolated_db_path),
        "--write",
        "--allow-prod-db",
        "--confirm-prod-backup",
        "--fixture-dir", str(FIXTURES_DIR),
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "clinic.db 受 git 追蹤" in captured.err


def test_cli_rejects_contact_argument():
    """Task 3 Test 12: 不接受 --contact 參數，argparse 報錯，退出碼 2。"""
    with pytest.raises(SystemExit) as exc:
        cli_main([
            "--clinic-id", "3503190424",
            "--contact", "https://example.com/bot",
            "--fixture-dir", str(FIXTURES_DIR),
        ])
    assert exc.value.code == 2


def test_cli_live_and_ownership_gate(tmp_path, isolated_db_path, monkeypatch, capsys):
    """Task 3 Test 13: --live 與擁有權授權防線 (a) 缺 --live (b) 缺 ownership (c) 互斥 (d) confirmed=false。"""
    url = "https://www.nu-vendome.com/location-detail/Taichung/"

    # (a) 缺 --live
    code_a = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(isolated_db_path),
        "--url", url,
    ])
    assert code_a == 2
    captured_a = capsys.readouterr()
    assert "--live" in captured_a.err

    # (b) 帶 --live 但 ownership 檔不存在
    import scripts.scrape_site as cli_mod
    monkeypatch.setattr(cli_mod, "OWNERSHIP_FILE", tmp_path / "missing.json")

    code_b = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(isolated_db_path),
        "--url", url,
        "--live",
    ])
    assert code_b == 2
    captured_b = capsys.readouterr()
    assert "ownership_unconfirmed" in captured_b.err

    # (c) --fixture-dir 與 --live 互斥
    code_c = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(isolated_db_path),
        "--fixture-dir", str(FIXTURES_DIR),
        "--live",
    ])
    assert code_c == 2
    captured_c = capsys.readouterr()
    assert "互斥" in captured_c.err

    # (d) confirmed_by_user 為 false
    bad_json = tmp_path / "bad.json"
    bad_json.write_text(json.dumps({"domain": "nu-vendome.com", "confirmed_by_user": False}), encoding="utf-8")
    monkeypatch.setattr(cli_mod, "OWNERSHIP_FILE", bad_json)

    code_d = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(isolated_db_path),
        "--url", url,
        "--live",
    ])
    assert code_d == 2


def test_cli_fixture_exempt_from_live_and_ownership(isolated_db_path, capsys):
    """Task 3 Test 14: --fixture-dir 模式不需 --live 與 ownership 檔，退出碼 0。"""
    code = cli_main([
        "--clinic-id", "3503190424",
        "--db-path", str(isolated_db_path),
        "--dry-run",
        "--fixture-dir", str(FIXTURES_DIR),
    ])
    assert code == 0
