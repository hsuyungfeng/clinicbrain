"""GENERAL-03 隱私驗收測試：資料庫與日誌掃描、AST 靜態分析。

驗證核心隱私承諾：
1. 資料庫複本在請求前後 sha256 與列數不變，查無任何問句原文或 Header 哨兵。
2. 系統日誌（含 root, uvicorn.*, fastapi 等）查無問句或敏感資訊。
3. 回應模型永不回顯使用者問句。
4. 驗證錯誤 422 永不回顯輸入內容或將其寫入日誌。
5. AST 靜態語法樹檢查確保程式碼層級無 logging、print、寫入語句。
"""

import ast
import hashlib
import logging
from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient

from src.api.access_log_filter import ExcludeGeneralPathFilter
from src.api.app import create_app
from src.api.config import config
from src.pageindex.faq_writer import upsert_faqs

SENT_A = "哨兵甲乙丙丁"
QUERY_ANSWERED = SENT_A + "是什麼呢我想知道癸壬"

SENT_N = "壬癸子丑寅卯"
QUERY_NOMATCH = SENT_N + "是什麼呢我想知道辰巳"

SENT_R = "甲乙丙丁戊己"
QUERY_REDFLAG = SENT_R + "胸痛我想知道午未"

HEADERS_SENTINEL = {
    "X-Test-Personal": "PERSONAL-SENTINEL-8842",
    "X-Forwarded-For": "198.51.100.77",
    "User-Agent": "SentinelAgent/9.9",
}


@pytest.fixture
def api_client(isolated_db_path, monkeypatch):
    """建立指向隔離複本的 TestClient。"""
    monkeypatch.setattr(config, "db_path", isolated_db_path)
    app = create_app()
    with TestClient(app) as client:
        yield client


def _plant_sentinel_faq(db_path: Path):
    """植入 SENT_A 之一般 FAQ。"""
    conn = sqlite3.connect(db_path)
    faq = {
        "question": f"關於{SENT_A}的衛教說明",
        "answer": "這是測試用的一般衛教內容。",
        "category": "general",
        "clinic_id": None,
        "topic_key": "sentinel-topic",
    }
    upsert_faqs(conn, [faq], source_type="manual")
    conn.close()


def _get_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """取得資料庫中所有使用者資料表的列數。"""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall() if not r[0].startswith("sqlite_")]
    counts = {}
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        counts[t] = cur.fetchone()[0]
    return counts


def test_db_has_no_question_text_after_requests(isolated_db_path, api_client):
    """測試發送問句後，資料庫完全未被寫入且位元組與 dump 中查無問句哨兵。"""
    _plant_sentinel_faq(isolated_db_path)

    # 記錄植入後的狀態
    conn = sqlite3.connect(isolated_db_path)
    initial_counts = _get_table_counts(conn)
    conn.close()

    initial_bytes = isolated_db_path.read_bytes()
    initial_sha = hashlib.sha256(initial_bytes).hexdigest()

    # 發送三種路徑請求並驗證狀態
    r_ans = api_client.post(
        "/api/v1/general/query",
        json={"query": QUERY_ANSWERED},
        headers=HEADERS_SENTINEL,
    )
    assert r_ans.status_code == 200
    assert r_ans.json()["status"] == "answered"
    assert any(h["topic_key"] == "sentinel-topic" for h in r_ans.json()["faq_hits"])

    r_no = api_client.post(
        "/api/v1/general/query",
        json={"query": QUERY_NOMATCH},
        headers=HEADERS_SENTINEL,
    )
    assert r_no.status_code == 200
    assert r_no.json()["status"] == "no_match"

    r_red = api_client.post(
        "/api/v1/general/query",
        json={"query": QUERY_REDFLAG},
        headers=HEADERS_SENTINEL,
    )
    assert r_red.status_code == 200
    assert r_red.json()["status"] == "red_flag"

    # 驗證資料庫檔案 hash 完全一致
    after_bytes = isolated_db_path.read_bytes()
    after_sha = hashlib.sha256(after_bytes).hexdigest()
    assert after_sha == initial_sha, "資料庫檔案 sha256 於請求後被改變！"

    # 驗證資料表列數完全一致
    conn = sqlite3.connect(isolated_db_path)
    after_counts = _get_table_counts(conn)
    assert after_counts == initial_counts

    if "sync_logs" in after_counts:
        assert after_counts["sync_logs"] == initial_counts["sync_logs"]
    if "cache_stats" in after_counts:
        assert after_counts["cache_stats"] == initial_counts["cache_stats"]

    # 掃描 iterdump 文字與位元組
    dump_text = "\n".join(conn.iterdump())
    conn.close()

    forbidden_strings = [
        QUERY_ANSWERED,
        QUERY_NOMATCH,
        QUERY_REDFLAG,
        SENT_N,
        SENT_R,
        HEADERS_SENTINEL["X-Test-Personal"],
        HEADERS_SENTINEL["X-Forwarded-For"],
        HEADERS_SENTINEL["User-Agent"],
    ]

    for s in forbidden_strings:
        assert s not in dump_text, f"資料庫 dump 洩漏敏感字串: {s}"
        assert s.encode("utf-8") not in after_bytes, f"資料庫位元組洩漏敏感字串: {s}"

    # SENT_A 為 FAQ 既有內容，出現在 dump 中是預期的，但 QUERY_ANSWERED 全字串絕不能出現
    assert QUERY_ANSWERED not in dump_text
    assert QUERY_ANSWERED.encode("utf-8") not in after_bytes


def test_no_log_contains_question_or_headers(isolated_db_path, api_client, caplog):
    """測試日誌掃描：任何層級之 logger 皆不得包含問句或標頭哨兵。"""
    _plant_sentinel_faq(isolated_db_path)

    loggers_to_patch = [
        logging.getLogger(),
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.error"),
        logging.getLogger("uvicorn.access"),
        logging.getLogger("fastapi"),
        logging.getLogger("httpx"),
        logging.getLogger("httpcore"),
    ]
    orig_states = [(l, l.level, l.propagate) for l in loggers_to_patch]

    try:
        caplog.set_level(logging.DEBUG)
        for l in loggers_to_patch:
            l.setLevel(logging.DEBUG)
            l.propagate = True

        r1 = api_client.post(
            "/api/v1/general/query",
            json={"query": QUERY_ANSWERED},
            headers=HEADERS_SENTINEL,
        )
        assert r1.json()["status"] == "answered"

        r2 = api_client.post(
            "/api/v1/general/query",
            json={"query": QUERY_NOMATCH},
            headers=HEADERS_SENTINEL,
        )
        assert r2.json()["status"] == "no_match"

        r3 = api_client.post(
            "/api/v1/general/query",
            json={"query": QUERY_REDFLAG},
            headers=HEADERS_SENTINEL,
        )
        assert r3.json()["status"] == "red_flag"

        # 檢驗 caplog 文字與 records
        all_logs = caplog.text + "\n" + "\n".join(r.getMessage() for r in caplog.records)
        forbidden_in_logs = [
            QUERY_ANSWERED,
            QUERY_NOMATCH,
            QUERY_REDFLAG,
            SENT_A,
            SENT_N,
            SENT_R,
            HEADERS_SENTINEL["X-Test-Personal"],
            HEADERS_SENTINEL["X-Forwarded-For"],
            HEADERS_SENTINEL["User-Agent"],
        ]
        for s in forbidden_in_logs:
            assert s not in all_logs, f"日誌中洩漏敏感字串: {s}"

    finally:
        for l, lvl, prop in orig_states:
            l.setLevel(lvl)
            l.propagate = prop


def test_response_never_echoes_question(isolated_db_path, api_client):
    """測試回應永遠不回顯完整問句，亦不包含 query 欄位。"""
    _plant_sentinel_faq(isolated_db_path)

    cases = [
        (QUERY_ANSWERED, "answered"),
        (QUERY_NOMATCH, "no_match"),
        (QUERY_REDFLAG, "red_flag"),
    ]
    for q, expected_status in cases:
        resp = api_client.post("/api/v1/general/query", json={"query": q})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == expected_status
        assert "query" not in data
        assert q not in resp.text


def test_422_responses_do_not_echo_or_log_input(api_client, caplog):
    """測試 422 驗證錯誤不回顯哨兵且不記入日誌。"""
    caplog.set_level(logging.DEBUG)

    cases = [
        {"json": {"query": SENT_A * 100}},
        {"json": {"query": "   "}},
        {"json": {"query": ["x", SENT_A]}},
        {"json": {"query": {"a": SENT_A}}},
        {
            "content": f'{{"query": "{SENT_A}'.encode("utf-8"),
            "headers": {"Content-Type": "application/json"},
        },
        {
            "content": SENT_A.encode("utf-8"),
            "headers": {"Content-Type": "text/plain"},
        },
    ]

    for kwargs in cases:
        resp = api_client.post("/api/v1/general/query", **kwargs)
        assert resp.status_code == 422
        assert resp.json() == {"detail": "請求格式不正確"}
        assert SENT_A not in resp.text
        assert "input" not in resp.text
        assert "ctx" not in resp.text
        assert "loc" not in resp.text

    all_logs = caplog.text + "\n" + "\n".join(r.getMessage() for r in caplog.records)
    assert SENT_A not in all_logs


def test_get_is_rejected_and_access_filter_covers_it(api_client):
    """測試 GET 請求被 405 拒絕且日誌過濾器能攔截對應的記錄。"""
    resp = api_client.get(f"/api/v1/general/query?q={SENT_A}")
    assert resp.status_code == 405

    f = ExcludeGeneralPathFilter()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "198.51.100.77:1234",
            "GET",
            f"/api/v1/general/query?q={SENT_A}",
            "1.1",
            405,
        ),
        exc_info=None,
    )
    assert f.filter(record) is False


def test_src_general_has_no_logging_or_persistence():
    """AST 靜態分析：檢查原始碼確保無 logging、print 或非 SELECT 的 SQL 語句。"""
    repo_root = Path(__file__).parent.parent
    files_to_check = list((repo_root / "src" / "general").glob("*.py"))
    files_to_check.append(repo_root / "src" / "api" / "routes" / "general.py")

    for py_file in files_to_check:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            # 1. 不得 import logging
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "logging", f"{py_file.name} 不得 import logging"
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "logging", f"{py_file.name} 不得 from logging import"

            # 2. 檢查函式呼叫不得含 print, commit, executescript, executemany, getLogger
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                forbidden_calls = {"print", "commit", "executescript", "executemany", "getLogger"}
                assert func_name not in forbidden_calls, f"{py_file.name} 包含禁用呼叫: {func_name}"

                # 3. 若為 execute 呼叫且第一引數為字串常數，必須為 SELECT
                if func_name == "execute" and node.args:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                        sql_text = first_arg.value.strip().upper()
                        assert sql_text.startswith("SELECT"), (
                            f"{py_file.name} 中包含非 SELECT 的 execute 呼叫: {sql_text[:30]}"
                        )

    # 查證 src/query/router.py 與 src/query/search.py 不 import logging
    for q_file in [repo_root / "src" / "query" / "router.py", repo_root / "src" / "query" / "search.py"]:
        q_tree = ast.parse(q_file.read_text(encoding="utf-8"), filename=str(q_file))
        for node in ast.walk(q_tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "logging", f"{q_file.name} 不得 import logging"
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "logging", f"{q_file.name} 不得 from logging import"
