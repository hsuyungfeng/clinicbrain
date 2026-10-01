"""
夜間批次 systemd 服務與排程範本測試（Phase 09 BATCH-03 Task 1）。

驗證：
1. clinicbrain-nightly.service：Type=oneshot、ExecStart 正確、無金鑰洩漏、資源限制設定。
2. clinicbrain-nightly.timer：OnCalendar 凌晨設定、Persistent=true、RandomizedDelaySec、關聯至 service。
3. 安全規範：範本非註解行絕對不含任何 systemctl、enable 或 start 指令。
4. 繁體中文與 UTF-8 編碼驗證。
"""

import configparser
from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICE_PATH = REPO_ROOT / "clinicbrain-nightly.service"
TIMER_PATH = REPO_ROOT / "clinicbrain-nightly.timer"


def _read_unit_file(path: Path) -> configparser.ConfigParser:
    assert path.exists(), f"找不到範本檔案: {path}"
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    # 預設 optionxform 會將 key 轉為小寫
    parser.read(path, encoding="utf-8")
    return parser


def test_nightly_service_template():
    """測試 clinicbrain-nightly.service 範本設定值與安全防護。"""
    config = _read_unit_file(SERVICE_PATH)

    # 1. [Unit] 區段
    assert "Unit" in config
    unit = config["Unit"]
    after = unit.get("after", "")
    assert "network.target" in after
    assert "llama-server.service" in after
    wants = unit.get("wants", "")
    assert "llama-server.service" in wants

    # 2. [Service] 區段
    assert "Service" in config
    svc = config["Service"]
    assert svc.get("type") == "oneshot"

    exec_start = svc.get("execstart", "")
    assert "scripts/run_nightly_batch.py" in exec_start
    assert "--db" in exec_start
    assert "--allow-prod-db" in exec_start
    assert "--dry-run" not in exec_start

    assert svc.get("workingdirectory") == "/home/hsu/Desktop/clinicbrain"
    assert "PYTHONUNBUFFERED=1" in svc.get("environment", "")
    assert svc.get("nice") is not None
    assert svc.get("ioschedulingclass") is not None
    assert svc.get("timeoutstartsec") is not None

    # 不應有單獨開機自啟的 [Install] 區段
    assert "Install" not in config

    # 內容不應包含任何 API Key / 金鑰字串
    raw_text = SERVICE_PATH.read_text(encoding="utf-8")
    assert "api_key" not in raw_text.lower()
    assert "authkey" not in raw_text.lower()


def test_nightly_timer_template():
    """測試 clinicbrain-nightly.timer 範本設定值。"""
    config = _read_unit_file(TIMER_PATH)

    # 1. [Timer] 區段
    assert "Timer" in config
    timer = config["Timer"]
    assert timer.get("persistent") == "true"
    assert timer.get("randomizeddelaysec") is not None
    assert timer.get("unit") == "clinicbrain-nightly.service"

    on_calendar = timer.get("oncalendar", "")
    assert on_calendar != ""
    # 驗證時間落在凌晨 00:00 ~ 05:59
    time_match = re.search(r"(\d{2}):(\d{2})", on_calendar)
    assert time_match is not None
    hour = int(time_match.group(1))
    assert 0 <= hour <= 5

    # 2. [Install] 區段
    assert "Install" in config
    install = config["Install"]
    assert install.get("wantedby") == "timers.target"


def test_no_systemctl_commands_in_templates():
    """保證兩範本去除註解行後，絕無 systemctl、enable、start 等執行指令。"""
    for path in [SERVICE_PATH, TIMER_PATH]:
        lines = path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            assert "systemctl" not in stripped, f"{path.name} 行 {idx} 包含 systemctl: {stripped}"
            assert not re.search(r"\benable\b", stripped, re.IGNORECASE), f"{path.name} 行 {idx} 包含 enable: {stripped}"
            assert not re.search(r"\bstart\s+", stripped, re.IGNORECASE), f"{path.name} 行 {idx} 包含 start: {stripped}"


def test_template_encoding_and_chinese():
    """測試範本檔案為 UTF-8 且註解包含繁體中文關鍵字。"""
    for path in [SERVICE_PATH, TIMER_PATH]:
        content = path.read_text(encoding="utf-8")
        assert "夜間" in content or "批次" in content or "排程" in content
