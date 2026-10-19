"""
Phase 29 Plan 02 Task 2: 視覺解說卡生成 CLI 與醫師審核 CLI 單元測試。
"""

from pathlib import Path
import sqlite3
import pytest

from tests.conftest import apply_visual_migration
from src.visual.review import visible_assets

PROD_DB_PATH = Path(__file__).resolve().parent.parent / "clinic.db"

try:
    from scripts.generate_visual_assets import main as gen_main
    from scripts.review_visual import main as rev_main
except ImportError:
    gen_main = None
    rev_main = None


VALID_MODEL_OUTPUT = (
    "場景1：自體脂肪移植會先由適當部位抽取脂肪組織，並透過純化程序篩選出結構完整的脂肪細胞備用。\n"
    "場景2：醫師採用少量多層次的方式將脂肪均勻放置於目標區域，有助於組織接觸周圍環境並減少局部硬塊。\n"
    "場景3：術後初期應避免按壓填補部位並維持正常作息，經過一段時間後組織會逐步適應並達到一定程度的穩定。"
)


def test_cli_imports():
    """驗證兩個 CLI 腳本可匯入且定義 main。"""
    assert gen_main is not None, "scripts/generate_visual_assets.py 必須定義 main"
    assert rev_main is not None, "scripts/review_visual.py 必須定義 main"


def test_generate_cli_dry_run_does_not_connect_db(tmp_path, monkeypatch, capsys):
    """驗證 --dry-run 只載入驗證骨架並印出規劃，不連線資料庫、不呼叫 LLM。"""
    called_connect = False
    orig_connect = sqlite3.connect

    def guard_connect(*args, **kwargs):
        nonlocal called_connect
        called_connect = True
        return orig_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", guard_connect)

    llm_called = False

    def guard_llm(p: str) -> str:
        nonlocal llm_called
        llm_called = True
        return VALID_MODEL_OUTPUT

    code = gen_main(["--db", str(tmp_path / "nonexistent.db"), "--dry-run"], llm_call=guard_llm)
    assert code == 0
    assert called_connect is False
    assert llm_called is False
    out = capsys.readouterr().out
    assert "autologous-fat-grafting" in out


def test_generate_and_review_cli_prod_db_guard(capsys):
    """驗證未帶 --allow-prod-db 時對正式庫路徑以結束碼 2 拒絕。"""
    assert gen_main(["--db", str(PROD_DB_PATH)], llm_call=lambda p: VALID_MODEL_OUTPUT) == 2
    assert rev_main(["--db", str(PROD_DB_PATH), "approve", "autologous-fat-grafting"]) == 2
    assert rev_main(["--db", str(PROD_DB_PATH), "reject", "autologous-fat-grafting"]) == 2


def test_generate_cli_unmigrated_db_exits_2(isolated_db_path, capsys):
    """驗證未遷移的資料庫（缺 visual_assets）以結束碼 2 退出並印出處置指引。"""
    code = gen_main(["--db", str(isolated_db_path)], llm_call=lambda p: VALID_MODEL_OUTPUT)
    assert code == 2
    err = capsys.readouterr().err
    assert "migrate_visual_assets.py" in err


def test_full_cli_lifecycle_generate_list_show_approve_reject(isolated_db_path, capsys):
    """驗證生成 pending -> list -> show（含警語）-> approve 可見 -> reject 不可見完整流程。"""
    apply_visual_migration(isolated_db_path)

    # 1. 生成寫入 pending
    code_gen = gen_main(["--db", str(isolated_db_path)], llm_call=lambda p: VALID_MODEL_OUTPUT)
    assert code_gen == 0

    conn = sqlite3.connect(str(isolated_db_path))
    assert visible_assets(conn) == []
    conn.close()

    # 2. list
    capsys.readouterr()
    code_list = rev_main(["--db", str(isolated_db_path), "list"])
    assert code_list == 0
    out_list = capsys.readouterr().out
    assert "autologous-fat-grafting" in out_list
    assert "pending" in out_list

    # 3. show 含固定警語
    code_show = rev_main(["--db", str(isolated_db_path), "show", "autologous-fat-grafting"])
    assert code_show == 0
    out_show = capsys.readouterr().out
    assert "請逐句確認醫學敘述與用詞後再核准" in out_show
    assert "抽取與純化" in out_show

    # show 未知主題回 1
    assert rev_main(["--db", str(isolated_db_path), "show", "no-such-topic"]) == 1

    # 4. approve 後可見
    code_app = rev_main(["--db", str(isolated_db_path), "approve", "autologous-fat-grafting"])
    assert code_app == 0
    conn = sqlite3.connect(str(isolated_db_path))
    vis = visible_assets(conn)
    assert len(vis) == 1
    assert vis[0]["topic_key"] == "autologous-fat-grafting"
    conn.close()

    # 5. reject 後不可見
    code_rej = rev_main(["--db", str(isolated_db_path), "reject", "autologous-fat-grafting"])
    assert code_rej == 0
    conn = sqlite3.connect(str(isolated_db_path))
    assert visible_assets(conn) == []
    conn.close()


def test_generate_cli_failure_does_not_leak_raw_output(isolated_db_path, capsys):
    """驗證生成失敗時結束碼為 1，且輸出只含代碼、不洩漏模型原文。"""
    apply_visual_migration(isolated_db_path)
    secret_raw = (
        "場景1：自體脂肪移植保證永久有效，機密原文 SECRET_LEAK_TOKEN_ABC 不得外洩。\n"
        "場景2：醫師採用少量多層次的方式將脂肪均勻放置於目標區域，有助於組織接觸周圍環境並減少局部硬塊。\n"
        "場景3：術後初期應避免按壓填補部位並維持正常作息，經過一段時間後組織會逐步適應並達到一定程度的穩定。"
    )
    capsys.readouterr()
    code = gen_main(["--db", str(isolated_db_path)], llm_call=lambda p: secret_raw)
    assert code == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "forbidden_phrase" in combined
    assert "SECRET_LEAK_TOKEN_ABC" not in combined
