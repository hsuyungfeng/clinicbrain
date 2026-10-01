"""測試 src/api/access_log_filter.py 存取日誌過濾器。"""

import logging
import pytest

from src.api.access_log_filter import (
    ExcludeGeneralPathFilter,
    install_access_log_filter,
)


@pytest.fixture
def clean_uvicorn_filters():
    """確保測試後還原 uvicorn.access 的 filters 與 level。"""
    logger = logging.getLogger("uvicorn.access")
    original_filters = list(logger.filters)
    original_level = logger.level
    logger.setLevel(logging.INFO)
    yield logger
    logger.filters = original_filters
    logger.setLevel(original_level)


def test_filter_uvicorn_access_post_record():
    """測試過濾標準 uvicorn POST /api/v1/general/query 存取日誌。"""
    f = ExcludeGeneralPathFilter()
    # uvicorn.access 的格式為 '%s - "%s %s HTTP/%s" %d'
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("203.0.113.9:5555", "POST", "/api/v1/general/query", "1.1", 200),
        exc_info=None,
    )
    assert f.filter(record) is False


def test_filter_uvicorn_access_get_with_query_string():
    """測試過濾帶有問句 query string 的 GET 405 存取日誌。"""
    f = ExcludeGeneralPathFilter()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "203.0.113.9:5555",
            "GET",
            "/api/v1/general/query?q=%E8%83%B8%E7%97%9B",
            "1.1",
            405,
        ),
        exc_info=None,
    )
    assert f.filter(record) is False


def test_filter_allows_other_paths():
    """測試不誤傷其他正常業務路徑與健康檢查端點。"""
    f = ExcludeGeneralPathFilter()
    record1 = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1234", "POST", "/api/v1/query", "1.1", 200),
        exc_info=None,
    )
    assert f.filter(record1) is True

    record2 = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1234", "GET", "/health", "1.1", 200),
        exc_info=None,
    )
    assert f.filter(record2) is True


def test_install_access_log_filter_idempotent(clean_uvicorn_filters):
    """測試重複呼叫 install_access_log_filter() 具備冪等性。"""
    logger = clean_uvicorn_filters
    install_access_log_filter()
    install_access_log_filter()

    count = sum(1 for f in logger.filters if isinstance(f, ExcludeGeneralPathFilter))
    assert count == 1


def test_end_to_end_logging_emission(clean_uvicorn_filters):
    """端對端日誌攔截驗證：一般諮詢路徑日誌被攔截，其他路徑正常輸出。"""
    logger = clean_uvicorn_filters
    install_access_log_filter()

    captured_records = []

    class MemoryHandler(logging.Handler):
        def emit(self, record):
            captured_records.append(record.getMessage())

    handler = MemoryHandler()
    logger.addHandler(handler)
    try:
        # 發送兩筆日誌
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "10.0.0.1:1111",
            "POST",
            "/api/v1/general/query",
            "1.1",
            200,
        )
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "10.0.0.1:1111",
            "GET",
            "/health",
            "1.1",
            200,
        )

        assert len(captured_records) == 1
        assert "/health" in captured_records[0]
        assert "/api/v1/general" not in captured_records[0]
    finally:
        logger.removeHandler(handler)
