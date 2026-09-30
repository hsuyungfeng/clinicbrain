"""
FastAPI 服務管理員認證強制化（AUTH-01）自動化驗收測試。
驗證三條成功標準：
  1. 未設定金鑰且無開發旗標時拒絕啟動（CLI 腳本、lifespan、直接 uvicorn 皆阻斷）。
  2. 提供明確開發旗標（--allow-no-auth 或 CLINICBRAIN_ALLOW_NO_AUTH=1）時可啟動並輸出警告。
  3. 設定金鑰時同步端點強制驗證（401 / 200），查詢端點與 /health 維持開放。

所有涉及資料庫的測試一律使用 isolated_db_path，保證正式 clinic.db 零寫入。
"""

import os
import subprocess
import sys
from pathlib import Path
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from src.api.app import create_app
from src.api.config import config
from src.api.dependencies import verify_admin_key
from src.api.security import (
    ADMIN_KEY_ENV,
    ALLOW_NO_AUTH_ENV,
    AuthConfigError,
    check_auth_config,
)
import scripts.run_api_server as run_api_server

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _clean_env(**extra) -> dict:
    """產生乾淨環境變數複本，移除認證相關環境變數後套用額外設定。"""
    env = os.environ.copy()
    env.pop(ADMIN_KEY_ENV, None)
    env.pop(ALLOW_NO_AUTH_ENV, None)
    env.update(extra)
    return env


# ==============================================================================
# 成功標準 1：未設定金鑰且無旗標時拒絕啟動
# ==============================================================================

def test_script_refuses_without_key():
    """驗收標準 1：啟動腳本在無金鑰無旗標時非 0 退出（exit code 2），印出繁體中文處置指引。"""
    res = subprocess.run(
        [sys.executable, "scripts/run_api_server.py", "--port", "8792"],
        cwd=str(PROJECT_ROOT),
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 2
    assert "CLINICBRAIN_ADMIN_API_KEY" in res.stderr
    assert "--allow-no-auth" in res.stderr
    assert "Uvicorn running" not in res.stdout
    assert "Uvicorn running" not in res.stderr


def test_script_blank_key_also_refuses():
    """驗收標準 1 邊界：金鑰為純空白字串時視為未設定，以 exit code 2 拒絕啟動。"""
    res = subprocess.run(
        [sys.executable, "scripts/run_api_server.py", "--port", "8792"],
        cwd=str(PROJECT_ROOT),
        env=_clean_env(**{ADMIN_KEY_ENV: "   "}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 2
    assert "CLINICBRAIN_ADMIN_API_KEY" in res.stderr


def test_main_refuses_in_process(monkeypatch):
    """驗收標準 1：run_api_server.main() 在程序內檢查失敗直接 SystemExit(2)。"""
    monkeypatch.setattr(config, "admin_api_key", None)
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "host", "127.0.0.1")
    monkeypatch.setattr(config, "port", 8000)
    monkeypatch.setattr(sys, "argv", ["run_api_server.py"])

    called = []

    def fake_run(*args, **kwargs):
        called.append(True)

    monkeypatch.setattr("uvicorn.run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        run_api_server.main()
    assert exc_info.value.code == 2
    assert not called


def test_lifespan_refuses_without_key(isolated_db_path, monkeypatch):
    """驗收標準 1：create_app() 本身可建立，但 TestClient 進入 lifespan 時因無金鑰拋出 AuthConfigError。"""
    monkeypatch.setattr(config, "admin_api_key", None)
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "db_path", isolated_db_path)

    app = create_app()
    with pytest.raises(AuthConfigError) as exc_info:
        with TestClient(app):
            pass
    assert "CLINICBRAIN_ADMIN_API_KEY" in str(exc_info.value)


def test_direct_uvicorn_refuses(tmp_path):
    """驗收標準 1：直接執行 uvicorn src.api.app:app 繞過腳本，亦因 lifespan 阻斷而失敗退出。"""
    pytest.importorskip("uvicorn")
    dummy_db = tmp_path / "nonexistent.db"

    res = subprocess.run(
        [sys.executable, "-m", "uvicorn", "src.api.app:app", "--port", "8793"],
        cwd=str(PROJECT_ROOT),
        env=_clean_env(CLINICBRAIN_DB_PATH=str(dummy_db)),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode != 0
    # 斷言錯誤訊息來自 lifespan 中的認證檢核失敗
    combined_err = res.stdout + res.stderr
    assert "CLINICBRAIN_ADMIN_API_KEY" in combined_err or "startup failed" in combined_err.lower() or "application startup failed" in combined_err.lower()


# ==============================================================================
# 成功標準 2：開發旗標放行與警告
# ==============================================================================

def test_main_allow_no_auth_flag_warns_and_runs(monkeypatch, capsys):
    """驗收標準 2：CLI 指定 --allow-no-auth 旗標時印出警告、設定環境變數並啟動服務。"""
    monkeypatch.setattr(config, "admin_api_key", None)
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "host", "127.0.0.1")
    monkeypatch.setattr(config, "port", 8000)
    monkeypatch.setenv(ALLOW_NO_AUTH_ENV, "0")
    monkeypatch.setattr(sys, "argv", ["run_api_server.py", "--allow-no-auth"])

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("uvicorn.run", fake_run)

    run_api_server.main()

    assert len(calls) == 1
    assert os.environ[ALLOW_NO_AUTH_ENV] == "1"
    assert config.allow_no_auth is True

    captured = capsys.readouterr()
    assert "警告" in captured.err
    assert "認證已停用" in captured.err


def test_main_env_flag_runs_without_cli_flag(monkeypatch, capsys):
    """驗收標準 2：設定 CLINICBRAIN_ALLOW_NO_AUTH=1 時無需 CLI 旗標即可正常啟動並輸出警告。"""
    monkeypatch.setattr(config, "admin_api_key", None)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "host", "127.0.0.1")
    monkeypatch.setattr(config, "port", 8000)
    monkeypatch.setattr(sys, "argv", ["run_api_server.py"])

    calls = []

    def fake_run(*args, **kwargs):
        calls.append(True)

    monkeypatch.setattr("uvicorn.run", fake_run)

    run_api_server.main()

    assert len(calls) == 1
    captured = capsys.readouterr()
    assert "警告" in captured.err
    assert "認證已停用" in captured.err


def test_main_with_key_no_warning(monkeypatch, capsys):
    """驗收標準 2：設定金鑰時正常啟動，不輸出任何認證已停用警告。"""
    monkeypatch.setattr(config, "admin_api_key", "secret-test-key")
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "host", "127.0.0.1")
    monkeypatch.setattr(config, "port", 8000)
    monkeypatch.setattr(sys, "argv", ["run_api_server.py"])

    calls = []

    def fake_run(*args, **kwargs):
        calls.append(True)

    monkeypatch.setattr("uvicorn.run", fake_run)

    run_api_server.main()

    assert len(calls) == 1
    captured = capsys.readouterr()
    assert "認證已停用" not in captured.err


def test_lifespan_allows_dev_mode(isolated_db_path, monkeypatch):
    """驗收標準 2：開發放行模式下 lifespan 順利通過，健康端點可正常存取。"""
    monkeypatch.setattr(config, "admin_api_key", None)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "db_path", isolated_db_path)

    app = create_app()
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200


def test_subprocess_env_flag_allows_subprocesses():
    """執行備註 1：驗證子行程繼承 CLINICBRAIN_ALLOW_NO_AUTH=1 環境變數時能正確評估為 dev_no_auth。"""
    res = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.api.security import check_auth_config; print(check_auth_config())",
        ],
        cwd=str(PROJECT_ROOT),
        env=_clean_env(**{ALLOW_NO_AUTH_ENV: "1"}),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert res.returncode == 0
    assert res.stdout.strip() == "dev_no_auth"


# ==============================================================================
# 成功標準 3：設定金鑰後的認證行為（同步 401/200，查詢開放）
# ==============================================================================

def test_sync_requires_key_when_configured(isolated_db_path, monkeypatch):
    """驗收標準 3：設定金鑰時，同步端點缺少或錯誤 X-API-Key 回 401，正確金鑰回 200。"""
    monkeypatch.setattr(config, "admin_api_key", "test-secret-key")
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "db_path", isolated_db_path)

    app = create_app()
    sync_payload = {
        "clinic_id": "3503190424",
        "data": {
            "notes": {
                "pre_op": "安全驗證測試"
            }
        },
    }

    with TestClient(app) as client:
        # 1. 缺少 X-API-Key: 401
        res_missing = client.post("/api/v1/sync/import", json=sync_payload)
        assert res_missing.status_code == 401

        # 2. 錯誤 X-API-Key: 401
        res_wrong = client.post(
            "/api/v1/sync/import",
            headers={"X-API-Key": "wrong-key"},
            json=sync_payload,
        )
        assert res_wrong.status_code == 401

        # 3. 正確 X-API-Key: 200
        res_ok = client.post(
            "/api/v1/sync/import",
            headers={"X-API-Key": "test-secret-key"},
            json=sync_payload,
        )
        assert res_ok.status_code == 200
        assert res_ok.json()["success"] is True


def test_query_and_health_open_without_key(isolated_db_path, monkeypatch):
    """驗收標準 3：即使強制設定金鑰，查詢端點與 /health 仍維持公開存取，不需認證。"""
    monkeypatch.setattr(config, "admin_api_key", "test-secret-key")
    monkeypatch.setattr(config, "allow_no_auth", False)
    monkeypatch.setattr(config, "db_path", isolated_db_path)

    app = create_app()

    with TestClient(app) as client:
        # /health 不需金鑰
        res_health = client.get("/health")
        assert res_health.status_code == 200

        # /api/v1/clinics/{clinic_id}/query 不需金鑰
        query_payload = {"query": "音波拉提術前與術後需要注意什麼？"}
        res_query = client.post(
            "/api/v1/clinics/3503190424/query",
            json=query_payload,
        )
        assert res_query.status_code == 200
        data = res_query.json()
        assert data["route"] == "special"
        assert "page_index_hits" in data


def test_verify_admin_key_503_when_misconfigured(monkeypatch):
    """驗收標準 3 防禦：未設金鑰且未開啟開發模式時，verify_admin_key 拋出 503 fail-closed。"""
    monkeypatch.setattr(config, "admin_api_key", None)
    monkeypatch.setattr(config, "allow_no_auth", False)

    with pytest.raises(HTTPException) as exc_info:
        verify_admin_key(None)
    assert exc_info.value.status_code == 503
    assert "CLINICBRAIN_ADMIN_API_KEY" in exc_info.value.detail


# ==============================================================================
# 執行備註 3：check_auth_config 純函式單元測試
# ==============================================================================

def test_check_auth_config_unit():
    """執行備註 3：測試 check_auth_config 多態判斷邏輯。"""
    class MockConfig:
        def __init__(self, key, no_auth):
            self.admin_api_key = key
            self.allow_no_auth = no_auth

    # 1. 金鑰與旗標並存 -> enforced（金鑰優先）
    cfg_both = MockConfig("my-key", True)
    assert check_auth_config(cfg_both) == "enforced"

    # 2. 空白金鑰 + 旗標 -> dev_no_auth
    cfg_blank_dev = MockConfig("   ", True)
    assert check_auth_config(cfg_blank_dev) == "dev_no_auth"

    # 3. 無金鑰無旗標 -> 拋出 AuthConfigError
    cfg_none = MockConfig(None, False)
    with pytest.raises(AuthConfigError):
        check_auth_config(cfg_none)

    # 4. 純空白金鑰且無旗標 -> 拋出 AuthConfigError
    cfg_blank_no_flag = MockConfig("   ", False)
    with pytest.raises(AuthConfigError):
        check_auth_config(cfg_blank_no_flag)
