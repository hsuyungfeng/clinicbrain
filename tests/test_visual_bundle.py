"""
Phase 30 Plan 03 Task 1: 視覺解說卡 bundle 匯出工具測試 (test_visual_bundle.py)。

測試範圍：
1. 核准資產可正常匯出為公開同形 bundle JSON（含完整 params 與 duration_sec）。
2. pending 資產預設不匯出（結束碼 1），帶 --allow-pending 可匯出。
3. 對專案正式庫 clinic.db 帶 --allow-pending 於連線前以結束碼 2 拒絕。
4. 竄改 ir_json（如含 <script> 或非法禁詞）時匯出被拒（結束碼 1）。
5. 匯出結構不含內部欄位（id, review_status, metadata, keywords）。
6. 未遷移庫（缺少 visual_assets 表）以結束碼 2 拒絕。
7. 已存在檔案預設不覆蓋（結束碼 1），--force 可覆蓋。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sqlite3
import pytest

from tests.conftest import apply_visual_migration
from src.visual.writer import upsert_assets
from src.visual.review import set_review_status
from src.visual.ir import validate_ir

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"

try:
    from scripts.export_visual_bundle import main as export_main
except ImportError:
    export_main = None

SAMPLE_IR = {
    "topic_key": "autologous-fat-grafting",
    "title": "自體脂肪移植原理",
    "keywords": ["自體脂肪", "補脂"],
    "scenes": [
        {
            "blueprint": "process_diagram",
            "title": "抽取與純化",
            "caption": "抽取後先經過純化處理，篩選出結構完整的脂肪組織，為後續移植做準備。",
            "labels": [
                {"text": "抽取脂肪", "tone": "neutral"},
                {"text": "離心純化", "tone": "optimal"},
            ],
            "params": {"particles": 6},
            "duration_sec": 8,
        },
        {
            "blueprint": "contrast",
            "title": "少量多層次注射",
            "caption": "採分多層次少量放置的方式，使每份脂肪皆能接觸周圍組織以維持健康狀態。",
            "labels": [
                {"text": "分層少量", "tone": "optimal"},
                {"text": "單處過量", "tone": "warning"},
            ],
        },
        {
            "blueprint": "timeline",
            "title": "術後逐步穩定",
            "caption": "術後一段時間內身體會逐步適應並達到穩定，期間應避免按壓，實際結果因人而異，須由醫師評估。",
            "labels": [
                {"text": "避免按壓", "tone": "warning"},
                {"text": "逐步適應", "tone": "optimal"},
            ],
        },
    ],
}


def _seed_sample_asset(db_path: Path, status: str = "approved"):
    conn = sqlite3.connect(str(db_path))
    asset = {
        "topic_key": SAMPLE_IR["topic_key"],
        "title": SAMPLE_IR["title"],
        "keywords": SAMPLE_IR["keywords"],
        "ir": copy.deepcopy(SAMPLE_IR),
    }
    upsert_assets(conn, [asset], source_type="manual")
    if status != "pending":
        set_review_status(conn, SAMPLE_IR["topic_key"], status)
    conn.close()


def test_export_script_importable():
    """驗證 scripts/export_visual_bundle.py 存在且可匯入 main 函式。"""
    assert export_main is not None, "scripts/export_visual_bundle.py 必須定義 main 函式"


def test_export_approved_topic_succeeds(isolated_db_path: Path, tmp_path: Path):
    """驗證核准主題成功匯出為同形 bundle JSON，params 與 duration_sec 皆補齊。"""
    apply_visual_migration(isolated_db_path)
    _seed_sample_asset(isolated_db_path, status="approved")

    out_file = tmp_path / "bundle.json"
    code = export_main([
        "--db", str(isolated_db_path),
        "--topic", "autologous-fat-grafting",
        "--out", str(out_file),
    ])
    assert code == 0
    assert out_file.exists()

    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["topic_key"] == "autologous-fat-grafting"
    assert data["title"] == "自體脂肪移植原理"
    assert len(data["scenes"]) == 3

    # 驗證排除內部欄位
    assert "id" not in data
    assert "review_status" not in data
    assert "metadata" not in data
    assert "keywords" not in data

    # 驗證補齊預設 params 與 duration_sec
    sc1 = data["scenes"][0]
    assert sc1["params"]["particles"] == 6
    assert sc1["params"]["source"]["label"] == "皮下脂肪"
    assert sc1["duration_sec"] == 8

    sc2 = data["scenes"][1]
    assert "params" in sc2 and sc2["params"]["left"]["title"] == "單處過量"
    assert sc2["duration_sec"] == 9  # contrast 預設 9 秒

    sc3 = data["scenes"][2]
    assert sc3["duration_sec"] == 7  # timeline 預設 7 秒

    # 驗證補上 keywords 後整份 bundle 也符合 validate_ir 的場景規格
    test_ir = dict(data, keywords=["自體脂肪"])
    ok, err_code = validate_ir(test_ir)
    assert ok is True, f"匯出之 bundle 必須通過 validate_ir，錯誤代碼: {err_code}"


def test_export_pending_rejected_by_default(isolated_db_path: Path, tmp_path: Path):
    """驗證未加 --allow-pending 時，pending 狀態資產拒絕匯出並結束碼 1。"""
    apply_visual_migration(isolated_db_path)
    _seed_sample_asset(isolated_db_path, status="pending")

    out_file = tmp_path / "bundle.json"
    code = export_main([
        "--db", str(isolated_db_path),
        "--topic", "autologous-fat-grafting",
        "--out", str(out_file),
    ])
    assert code == 1
    assert not out_file.exists()


def test_export_pending_allowed_with_flag(isolated_db_path: Path, tmp_path: Path):
    """驗證對非正式庫加上 --allow-pending 可匯出 pending 資產。"""
    apply_visual_migration(isolated_db_path)
    _seed_sample_asset(isolated_db_path, status="pending")

    out_file = tmp_path / "bundle.json"
    code = export_main([
        "--db", str(isolated_db_path),
        "--topic", "autologous-fat-grafting",
        "--out", str(out_file),
        "--allow-pending",
    ])
    assert code == 0
    assert out_file.exists()


def test_export_allow_pending_on_prod_db_rejected(tmp_path: Path):
    """驗證對專案根 clinic.db 路徑加上 --allow-pending 於連線前以結束碼 2 拒絕。"""
    out_file = tmp_path / "bundle.json"
    code = export_main([
        "--db", str(PROD_DB_PATH),
        "--topic", "autologous-fat-grafting",
        "--out", str(out_file),
        "--allow-pending",
    ])
    assert code == 2
    assert not out_file.exists()


def test_export_tampered_ir_rejected(isolated_db_path: Path, tmp_path: Path):
    """驗證資料庫內 ir_json 遭竄改後，匯出前 validate_ir 攔截並以結束碼 1 拒絕。"""
    apply_visual_migration(isolated_db_path)
    _seed_sample_asset(isolated_db_path, status="approved")

    # 竄改資料庫內的 ir_json 加入惡意腳本
    bad_ir = copy.deepcopy(SAMPLE_IR)
    bad_ir["scenes"][0]["caption"] = "這段文字帶有 <script>evil()</script> 攻擊碼"
    conn = sqlite3.connect(str(isolated_db_path))
    conn.execute(
        "UPDATE visual_assets SET ir_json = ? WHERE topic_key = ?",
        (json.dumps(bad_ir, ensure_ascii=False), SAMPLE_IR["topic_key"]),
    )
    conn.commit()
    conn.close()

    out_file = tmp_path / "bundle.json"
    code = export_main([
        "--db", str(isolated_db_path),
        "--topic", "autologous-fat-grafting",
        "--out", str(out_file),
    ])
    assert code == 1
    assert not out_file.exists()


def test_export_missing_table_returns_exit_code_2(isolated_db_path: Path, tmp_path: Path):
    """驗證未套用遷移之資料庫以結束碼 2 拒絕。"""
    # isolated_db_path 預設未套用 visual 遷移
    out_file = tmp_path / "bundle.json"
    code = export_main([
        "--db", str(isolated_db_path),
        "--topic", "autologous-fat-grafting",
        "--out", str(out_file),
    ])
    assert code == 2
    assert not out_file.exists()


def test_export_does_not_overwrite_without_force(isolated_db_path: Path, tmp_path: Path):
    """驗證輸出檔案已存在時，未帶 --force 結束碼 1；帶 --force 成功覆蓋。"""
    apply_visual_migration(isolated_db_path)
    _seed_sample_asset(isolated_db_path, status="approved")

    out_file = tmp_path / "bundle.json"
    out_file.write_text("existing content", encoding="utf-8")

    # 未帶 --force -> 結束碼 1，原檔案不變
    code1 = export_main([
        "--db", str(isolated_db_path),
        "--topic", "autologous-fat-grafting",
        "--out", str(out_file),
    ])
    assert code1 == 1
    assert out_file.read_text(encoding="utf-8") == "existing content"

    # 帶 --force -> 結束碼 0，成功覆寫
    code2 = export_main([
        "--db", str(isolated_db_path),
        "--topic", "autologous-fat-grafting",
        "--out", str(out_file),
        "--force",
    ])
    assert code2 == 0
    assert out_file.read_text(encoding="utf-8") != "existing content"
