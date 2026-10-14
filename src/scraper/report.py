"""Phase 23 Task 1：網站擷取器批次報告資料結構與安全日誌格式。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
from typing import Any, Optional
import urllib.parse

logger = logging.getLogger("scraper")


def path_hint(url: str) -> str:
    """擷取 URL 路徑前兩段作為提示，徹底剔除 query string、fragment 與憑證。"""
    if not isinstance(url, str) or not url.strip():
        return "/"

    trimmed = url.strip()
    if trimmed.startswith("fixture://"):
        filename = trimmed[len("fixture://"):].split("?")[0].split("#")[0]
        return f"/{filename}" if filename else "/"

    try:
        parsed = urllib.parse.urlsplit(trimmed)
    except Exception:
        return "/"

    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return "/"
    return "/" + "/".join(parts[:2])


@dataclass
class UrlOutcome:
    """單一網址擷取結果，to_dict() 嚴格白名單化，絕不外洩內文與醫師資訊。"""

    host: str = ""
    path_hint: str = ""
    status: str = "ok"  # "ok", "failed", "skipped"
    reason: str = ""
    drafts_count: int = 0
    rejected_count: int = 0
    schema_drift: bool = False
    doctors_count: int = 0
    html_bytes: int = 0
    # 內部使用欄位，to_dict() 絕不包含
    url: str = field(default="", repr=False)

    def to_dict(self) -> dict[str, Any]:
        """僅輸出安全統計欄位，排除原始 URL、HTML、問答與醫師名稱等敏感資訊。"""
        return {
            "host": self.host,
            "path_hint": self.path_hint,
            "status": self.status,
            "reason": self.reason,
            "drafts_count": self.drafts_count,
            "rejected_count": self.rejected_count,
            "schema_drift": self.schema_drift,
            "doctors_count": self.doctors_count,
            "html_bytes": self.html_bytes,
        }


@dataclass
class BatchReport:
    """批次擷取執行報告。"""

    outcomes: list[UrlOutcome] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    status: str = "ok"  # "ok", "skipped_locked"
    drafts_written: int = 0
    unchanged: int = 0
    fetched_count: int = 0
    schema_preflight: Optional[dict[str, bool]] = None

    @property
    def summary(self) -> dict[str, Any]:
        total = len(self.outcomes)
        ok_count = sum(1 for o in self.outcomes if o.status == "ok")
        failed_count = sum(1 for o in self.outcomes if o.status == "failed")
        schema_drift_count = sum(1 for o in self.outcomes if o.schema_drift)
        skipped_by_policy = sum(
            1
            for o in self.outcomes
            if o.reason
            in (
                "not_allowlisted",
                "skipped_by_policy",
                "scheme",
                "credentials",
                "port",
                "dns_resolution",
                "private_ip",
                "cgnat_ip",
                "ipv4_mapped",
                "robots_denied",
            )
        )
        total_html_bytes = sum(o.html_bytes for o in self.outcomes)
        # 若 fetched_count 未明確指定，以實際有讀取到 html_bytes 或 status=='ok' 的 outcome 數量估計
        actual_fetched = self.fetched_count or sum(1 for o in self.outcomes if o.html_bytes > 0)

        return {
            "total": total,
            "ok": ok_count,
            "failed": failed_count,
            "schema_drift": schema_drift_count,
            "drafts_written": self.drafts_written,
            "unchanged": self.unchanged,
            "skipped_by_policy": skipped_by_policy,
            "skipped_locked": self.status == "skipped_locked",
            "fetched_count": actual_fetched,
            "total_html_bytes": total_html_bytes,
        }

    def to_dict(self) -> dict[str, Any]:
        res: dict[str, Any] = {
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "summary": self.summary,
            "outcomes": [o.to_dict() for o in self.outcomes],
        }
        if self.schema_preflight is not None:
            res["schema_preflight"] = self.schema_preflight
        return res

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def safe_log_line(outcome: UrlOutcome) -> str:
    """產生結構化安全日誌單行，不包含敏感文字。"""
    return (
        f"scrape host={outcome.host} "
        f"path={outcome.path_hint} "
        f"status={outcome.status} "
        f"reason={outcome.reason} "
        f"drafts={outcome.drafts_count}"
    )
