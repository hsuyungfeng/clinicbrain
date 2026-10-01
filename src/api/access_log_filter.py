"""存取日誌隱私過濾器。

攔截並過濾 uvicorn.access logger 中針對 /api/v1/general 端點的所有請求紀錄，
確保一般諮詢問句、查詢字串與呼叫端 IP 不會落入系統存取日誌中。
"""

import logging

GENERAL_PATH_PREFIX = "/api/v1/general"


class ExcludeGeneralPathFilter(logging.Filter):
    """過濾一般諮詢路徑的 access log 紀錄。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """檢查日誌訊息是否包含一般諮詢路徑。若包含則丟棄（回傳 False）。"""
        try:
            msg = record.getMessage()
            return GENERAL_PATH_PREFIX not in msg
        except Exception:
            # 保守丟棄，避免非預期格式導致洩漏
            return False


def install_access_log_filter() -> None:
    """將過濾器安裝至 uvicorn.access logger（具冪等性）。"""
    logger = logging.getLogger("uvicorn.access")
    for f in logger.filters:
        if isinstance(f, ExcludeGeneralPathFilter):
            return
    logger.addFilter(ExcludeGeneralPathFilter())
