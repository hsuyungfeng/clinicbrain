"""
夜間批次 CLI 命令列介面測試（Phase 09 BATCH-03 Task 2）。

驗證：
1. 正式庫安全防禦：非 dry-run 未帶 --allow-prod-db 連線前拒絕（回傳 2）。
2. dry-run 模式：對正式庫唯讀允許，不呼叫 LLM，回傳 0。
3. 複本端到端：一般執行、日誌檔建立、回傳 0。
4. LLM 不可用：優雅結束，回傳 0。
5. 錯誤碼規格：不存在資料庫 (2)、清單檔錯誤 (2)、未遷移庫 (2)、未預期例外 (1)、無效參數 (2)。
6. 檔案鎖互斥：同資料庫同目錄鎖檔跨 log-dir 互斥，被持有時回傳 0。
7. 預設 log-dir 解析為絕對路徑，不隨工作目錄改變。
8. 零外部請求防禦保證。
"""

import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import urllib.request
import pytest

from scripts.run_nightly_batch import (
    PROD_DB_PATH,
    lock_path_for,
    main as cli_main,
    resolve_log_dir,
)
from src.batch.runner import BatchPreflightError
from src.pageindex.llm_client import LocalLLMUnavailableError


@pytest.fixture(autouse=True)
def _block_external_llm_calls(monkeypatch):
    """防禦性 fixture：保證測試期間絕對不發起任何真實外部網路請求。"""
    def _fail_urlopen(*args, **kwargs):
        raise AssertionError("測試期間禁止呼叫 urllib.request.urlopen 發起真實網路連線！")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_urlopen)


def _get_file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _create_minimal_seed_file(path: Path) -> Path:
    data = {
        "schema_version": 1,
        "description": "CLI 測試用種子清單",
        "tree_procedure_names": {
            "hifu-lifting": "音波拉提",
        },
        "topics": [
            {
                "topic_key": "zz-cli-topic",
                "title": "CLI 測試主題",
                "category": "special",
                "clinic_id": "3503190424",
                "keywords": ["音波"],
                "always": True,
                "tree_doc_id": "hifu-lifting",
                "questions": ["CLI測試問題一？"],
            }
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_prod_db_guard_before_connect(monkeypatch):
    """測試正式庫防禦：非 dry-run 且無 --allow-prod-db 時，在連線前即以代碼 2 拒絕。"""
    def fail_connect(*args, **kwargs):
        raise AssertionError("正式庫防禦失敗：不應呼叫 sqlite3.connect！")

    monkeypatch.setattr(sqlite3, "connect", fail_connect)

    exit_code = cli_main(["--db", str(PROD_DB_PATH)])
    assert exit_code == 2


def test_prod_db_dry_run_allowed(isolated_db_path: Path, monkeypatch):
    """測試正式庫搭配 --dry-run 時允許執行，且連線採用唯讀 mode=ro 模式。"""
    connected_modes = []
    orig_connect = sqlite3.connect

    def fake_connect(uri_str, **kwargs):
        connected_modes.append((uri_str, kwargs))
        return orig_connect(uri_str, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", fake_connect)

    seed_file = _create_minimal_seed_file(isolated_db_path.parent / "seed.json")

    exit_code = cli_main([
        "--db", str(isolated_db_path),
        "--seed-file", str(seed_file),
        "--dry-run",
    ])

    assert exit_code == 0
    assert len(connected_modes) == 1
    uri, kw = connected_modes[0]
    assert "mode=ro" in str(uri)
    assert kw.get("uri") is True


def test_replica_end_to_end_execution(isolated_db_path: Path, tmp_path: Path):
    """測試在複本資料庫上正常端到端執行，產生日誌檔且回傳 0。"""
    seed_file = _create_minimal_seed_file(tmp_path / "seed.json")
    log_dir = tmp_path / "logs"

    def mock_llm(p: str) -> str:
        return json.dumps([
            {"question": "CLI測試問題一？", "answer": "這是符合長度的合格回答文字內容說明。"}
        ], ensure_ascii=False)

    exit_code = cli_main(
        [
            "--db", str(isolated_db_path),
            "--seed-file", str(seed_file),
            "--log-dir", str(log_dir),
            "--max-faq-topics", "1",
            "--max-trees", "1",
        ],
        llm_call=mock_llm,
        health_check=lambda: None,
    )

    assert exit_code == 0
    log_files = list(log_dir.glob("nightly-*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "batch_summary" in content


def test_llm_unavailable_graceful_exit(isolated_db_path: Path, tmp_path: Path):
    """測試 LLM 不可用時優雅結束並回傳 0。"""
    seed_file = _create_minimal_seed_file(tmp_path / "seed.json")
    log_dir = tmp_path / "logs"

    def mock_health_fail():
        raise LocalLLMUnavailableError("健康檢查失敗")

    exit_code = cli_main(
        [
            "--db", str(isolated_db_path),
            "--seed-file", str(seed_file),
            "--log-dir", str(log_dir),
        ],
        llm_call=lambda p: "",
        health_check=mock_health_fail,
    )

    assert exit_code == 0
    log_files = list(log_dir.glob("nightly-*.log"))
    assert len(log_files) == 1
    assert "llm_unavailable" in log_files[0].read_text(encoding="utf-8")


def test_cli_error_codes(isolated_db_path: Path, tmp_path: Path, monkeypatch):
    """測試各類錯誤情境之結束碼。"""
    # 1. 資料庫不存在 -> 2
    assert cli_main(["--db", str(tmp_path / "not_exist.db")]) == 2

    # 2. 清單檔不存在 -> 2
    assert cli_main([
        "--db", str(isolated_db_path),
        "--seed-file", str(tmp_path / "not_exist.json"),
    ]) == 2

    # 3. 未遷移資料庫（非 dry-run） -> 2
    seed_file = _create_minimal_seed_file(tmp_path / "seed.json")
    monkeypatch.setattr("src.batch.runner.has_review_status", lambda conn: False)
    assert cli_main([
        "--db", str(isolated_db_path),
        "--seed-file", str(seed_file),
        "--log-dir", str(tmp_path / "logs"),
    ], llm_call=lambda p: "", health_check=lambda: None) == 2

    # 4. 未預期例外 -> 1
    def mock_unexpected(*args, **kwargs):
        raise RuntimeError("未預期嚴重系統崩潰")

    monkeypatch.setattr("scripts.run_nightly_batch.run_batch", mock_unexpected)
    assert cli_main([
        "--db", str(isolated_db_path),
        "--seed-file", str(seed_file),
        "--log-dir", str(tmp_path / "logs"),
    ], llm_call=lambda p: "", health_check=lambda: None) == 1

    # 5. 無效參數（負數或非法型別） -> SystemExit (code=2)
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["--max-faq-topics", "abc"])
    assert excinfo.value.code == 2


def test_file_lock_across_log_dirs(isolated_db_path: Path, tmp_path: Path):
    """測試同資料庫之非阻塞檔案鎖跨 log-dir 互斥，被持有時略過並回傳 0。"""
    seed_file = _create_minimal_seed_file(tmp_path / "seed.json")
    lock_file = lock_path_for(isolated_db_path)

    # 外部行程持有檔案鎖
    lock_fd = open(lock_file, "w")
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    called_llm = False

    def mock_llm(p: str) -> str:
        nonlocal called_llm
        called_llm = True
        return "[]"

    # 使用兩個不同的 log-dir 執行，皆應略過且回傳 0
    code1 = cli_main(
        [
            "--db", str(isolated_db_path),
            "--seed-file", str(seed_file),
            "--log-dir", str(tmp_path / "logs1"),
        ],
        llm_call=mock_llm,
        health_check=lambda: None,
    )
    assert code1 == 0
    assert called_llm is False

    code2 = cli_main(
        [
            "--db", str(isolated_db_path),
            "--seed-file", str(seed_file),
            "--log-dir", str(tmp_path / "logs2"),
        ],
        llm_call=mock_llm,
        health_check=lambda: None,
    )
    assert code2 == 0
    assert called_llm is False

    # 釋放鎖後可正常執行
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    lock_fd.close()

    code3 = cli_main(
        [
            "--db", str(isolated_db_path),
            "--seed-file", str(seed_file),
            "--log-dir", str(tmp_path / "logs3"),
            "--max-faq-topics", "1",
        ],
        llm_call=lambda p: json.dumps([{"question": "CLI測試問題一？", "answer": "回答內容文字說明足夠長度。"}], ensure_ascii=False),
        health_check=lambda: None,
    )
    assert code3 == 0


def test_resolve_log_dir_absolute(tmp_path: Path, monkeypatch):
    """測試預設 log-dir 解析為專案絕對路徑，不隨當前工作目錄變更。"""
    monkeypatch.chdir(tmp_path)
    default_dir = resolve_log_dir(None)
    assert default_dir.is_absolute()
    assert "logs/nightly_batch" in str(default_dir)

    custom_dir = resolve_log_dir("custom_logs")
    assert custom_dir.is_absolute()
    assert str(custom_dir) == str((tmp_path / "custom_logs").resolve())
