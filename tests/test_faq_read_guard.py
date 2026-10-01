"""
FAQ 資料表讀取靜態守衛測試（Phase 09 BATCH-01 Task 1）。

靜態分析掃描 src/ 與 scripts/ 下所有 Python 檔案，防範未來新增未經審核閘門
(visible_faq_sql) 的直接讀取路徑 (FROM faq_cache / JOIN faq_cache / faq_cache_fts)。
"""

from pathlib import Path
import re
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 靜態守衛正規表達式
FAQ_READ_PATTERN = re.compile(
    r"(FROM\s+faq_cache|JOIN\s+faq_cache|faq_cache_fts)",
    re.IGNORECASE,
)

# 授權白名單（相對路徑 -> 授權理由繁體中文）
FAQ_READ_WHITELIST: dict[str, str] = {
    "src/query/search.py": "檢索閘門本體，已實作 visible_faq_sql 審核過濾",
    "src/pageindex/faq_writer.py": "權威寫入端，僅以 (clinic_id, topic_key, question) 比對既有資料以進行 UPSERT 去重",
    "src/pageindex/faq_review.py": "審核管理模組，提供醫師檢視與狀態流轉",
    "src/api/routes/sync.py": "已套用 visible_faq_sql 審核過濾之官方雲端同步匯出端點",
    "scripts/migrate_faq_review_status.py": "資料庫結構遷移腳本，執行 table_info 與歷史回填",
    "src/batch/faq_generator.py": "批次生成模組，僅 SELECT question 進行存在性檢查以防重複生成，不對外回傳答案",
}


def scan_faq_reads(root: Path) -> dict[str, list[tuple[int, str]]]:
    """掃描指定根目錄下之 Python 原始檔，找出所有命中 FAQ 讀取語句之檔案與行號。"""
    hits: dict[str, list[tuple[int, str]]] = {}
    for py_file in root.rglob("*.py"):
        try:
            rel_path = py_file.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel_path = py_file.as_posix()

        lines = py_file.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, start=1):
            # 排除註解行
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if FAQ_READ_PATTERN.search(line):
                hits.setdefault(rel_path, []).append((idx, line.strip()))
    return hits


def test_no_unauthorized_faq_cache_reads():
    """保證專案內除白名單授權檔案外，絕無任何直接存取 faq_cache 的繞行路徑。"""
    src_hits = scan_faq_reads(PROJECT_ROOT / "src")
    scripts_hits = scan_faq_reads(PROJECT_ROOT / "scripts")

    all_hits: dict[str, list[tuple[int, str]]] = {}
    for path, matches in src_hits.items():
        all_hits[f"src/{path}"] = matches
    for path, matches in scripts_hits.items():
        all_hits[f"scripts/{path}"] = matches

    unauthorized: dict[str, list[tuple[int, str]]] = {}
    for file_path, matches in all_hits.items():
        if file_path not in FAQ_READ_WHITELIST:
            unauthorized[file_path] = matches

    if unauthorized:
        report = []
        for f, ms in unauthorized.items():
            for line_no, content in ms:
                report.append(f"  - {f}:{line_no} -> {content}")
        pytest.fail(
            "檢測到未經授權之 faq_cache 直接讀取路徑，可能繞過審核閘門！\n"
            + "\n".join(report)
        )


def test_whitelist_entries_are_active():
    """驗證白名單中現存的檔案確實有命中，防止白名單過期產生死條目。"""
    for rel_path, reason in FAQ_READ_WHITELIST.items():
        full_path = PROJECT_ROOT / rel_path
        if not full_path.exists():
            # 尚未建立之模組（如 09-04 的 faq_generator.py）允許暫時略過
            continue
        hits = scan_faq_reads(full_path.parent)
        file_subpath = full_path.name
        # 該檔必須包含至少一筆命中
        assert any(
            h_path.endswith(file_subpath) for h_path in hits
        ), f"白名單項目 '{rel_path}' 未包含任何 faq_cache 存取語句，請檢查是否為多餘白名單！"


def test_guard_detects_violations_in_temp_dir(tmp_path: Path):
    """測試掃描工具本身之有效性：在暫存目錄中建立違規檔案應被正確抓出。"""
    bad_file = tmp_path / "leak.py"
    bad_file.write_text(
        "query = 'SELECT answer FROM faq_cache WHERE question = ?'\n",
        encoding="utf-8",
    )
    detected = scan_faq_reads(tmp_path)
    assert "leak.py" in detected
    assert len(detected["leak.py"]) == 1
    assert detected["leak.py"][0][0] == 1
