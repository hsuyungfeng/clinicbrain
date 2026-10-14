"""Phase 23 Task 1：HTML 結構化欄位擷取與 schema_drift 偵測。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
import re

SCHEMA_VERSION = "1"

PRICE_PATTERN = re.compile(r"(?:NT\$|\$)\s*[\d,]+|[\d,]{3,}\s*(?:元|塊)|(?:\b\d+\s*(?:元|塊))", re.IGNORECASE)
CELL_PHONE_PATTERN = re.compile(r"09\d{2}[-\s]?\d{3}[-\s]?\d{3}|09\d{8}")
EMAIL_PATTERN = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
LINE_PATTERN = re.compile(r"LINE(?:\s*ID)?[:\s]*[\w\-_.]+", re.IGNORECASE)


@dataclass
class ExtractedClinicPage:
    """診所網頁結構化擷取資料。注意：doctors 僅供記憶體暫存與比對使用，嚴禁持久化至資料庫或 metadata。"""

    institution_name: str = ""
    address: str = ""
    phone: str = ""
    business_hours: str = ""
    services: list[dict] = field(default_factory=list)
    doctors: list[dict] = field(default_factory=list)
    schema_drift: bool = False
    drift_fields: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def is_usable(self) -> bool:
        """判定擷取資料是否可用（未發生 schema_drift 且具備有效服務項目）。"""
        return (not self.schema_drift) and bool(self.institution_name) and (len(self.services) > 0)

    def to_dict(self) -> dict:
        return asdict(self)


class _ClinicHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.institution_name = ""
        self.address = ""
        self.phone = ""
        self.business_hours = ""
        self.raw_services: list[dict] = []
        self.raw_doctors: list[dict] = []

        self._tag_stack: list[str] = []
        self._class_stack: list[list[str]] = []
        self._current_text: list[str] = []
        self._in_ignored_tag = False

        self._current_service: dict | None = None
        self._current_doctor: dict | None = None
        self._current_field: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        self._tag_stack.append(tag_lower)
        if tag_lower in ("script", "style", "noscript"):
            self._in_ignored_tag = True

        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        classes = [c.lower() for c in attrs_dict.get("class", "").split()]
        self._class_stack.append(classes)

        if "service" in classes or tag_lower == "article" and any("service" in c for c in classes):
            self._current_service = {"name": "", "description": ""}

        if "doctor" in classes or tag_lower == "article" and any("doctor" in c for c in classes):
            self._current_doctor = {"name": "", "specialty": ""}

        if tag_lower in ("h3", "h4", "h2") and self._current_service is not None and not self._current_service["name"]:
            self._current_field = "service_name"
        elif tag_lower == "p" and self._current_service is not None:
            self._current_field = "service_desc"
        elif tag_lower in ("h4", "h3") and self._current_doctor is not None and not self._current_doctor["name"]:
            self._current_field = "doctor_name"
        elif ("specialty" in classes or tag_lower == "p" and "specialty" in classes) and self._current_doctor is not None:
            self._current_field = "doctor_specialty"
        elif "address" in classes or tag_lower in ("address",):
            self._current_field = "address"
        elif "phone" in classes or tag_lower == "span" and "phone" in classes:
            self._current_field = "phone"
        elif "hours" in classes or any("hour" in c for c in classes):
            self._current_field = "hours"
        elif tag_lower == "h1" and not self.institution_name:
            self._current_field = "institution_name"

        self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        text = "".join(self._current_text).strip()

        if self._current_field == "institution_name" and not self.institution_name:
            self.institution_name = text
            self._current_field = None
        elif self._current_field == "address" and not self.address:
            self.address = text
            self._current_field = None
        elif self._current_field == "phone" and not self.phone:
            # 排除 09 開頭行動號
            clean_phone = text
            if not CELL_PHONE_PATTERN.search(clean_phone) and not clean_phone.startswith("09"):
                self.phone = clean_phone
            self._current_field = None
        elif self._current_field == "hours" and not self.business_hours:
            self.business_hours = text
            self._current_field = None
        elif self._current_field == "service_name" and self._current_service is not None:
            self._current_service["name"] = text
            self._current_field = None
        elif self._current_field == "service_desc" and self._current_service is not None:
            self._current_service["description"] = text
            self._current_field = None
        elif self._current_field == "doctor_name" and self._current_doctor is not None:
            self._current_doctor["name"] = text
            self._current_field = None
        elif self._current_field == "doctor_specialty" and self._current_doctor is not None:
            self._current_doctor["specialty"] = text
            self._current_field = None

        classes = self._class_stack[-1] if self._class_stack else []
        if ("service" in classes or tag_lower == "article") and self._current_service is not None:
            if self._current_service["name"] and self._current_service["description"]:
                self.raw_services.append(self._current_service)
            self._current_service = None

        if ("doctor" in classes or tag_lower == "article") and self._current_doctor is not None:
            if self._current_doctor["name"]:
                self.raw_doctors.append(self._current_doctor)
            self._current_doctor = None

        if self._tag_stack and self._tag_stack[-1] == tag_lower:
            self._tag_stack.pop()
        if self._class_stack:
            self._class_stack.pop()

        if tag_lower in ("script", "style", "noscript"):
            self._in_ignored_tag = False

        self._current_text = []

    def handle_data(self, data: str) -> None:
        if not self._in_ignored_tag:
            self._current_text.append(data)


def _clean_text_contacts(text: str) -> str:
    """清除字串中的行動電話、email 與 LINE ID。"""
    cleaned = CELL_PHONE_PATTERN.sub("", text)
    cleaned = EMAIL_PATTERN.sub("", cleaned)
    cleaned = LINE_PATTERN.sub("", cleaned)
    return cleaned.strip()


def extract_clinic_page(html: str) -> ExtractedClinicPage:
    """解析診所 HTML 頁面結構，擷取核心欄位並過濾敏感聯絡資訊與價格。"""
    if not isinstance(html, str) or not html.strip():
        return ExtractedClinicPage(schema_drift=True, drift_fields=["html_empty"])

    parser = _ClinicHTMLParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return ExtractedClinicPage(schema_drift=True, drift_fields=["html_parse_error"])

    # 處理服務項目
    clean_services: list[dict] = []
    for svc in parser.raw_services:
        name = _clean_text_contacts(svc.get("name", ""))
        desc = _clean_text_contacts(svc.get("description", ""))

        # 價格檢查：若含價格字樣，整個描述欄位清空並視為無效服務（不保留遮蔽字串充數）
        if PRICE_PATTERN.search(desc) or PRICE_PATTERN.search(name):
            desc = ""

        if name and len(desc) >= 30:
            clean_services.append({"name": name, "description": desc})

    # 處理醫師資料（僅記憶體保留姓名與專長，完全濾除私人聯絡）
    clean_doctors: list[dict] = []
    for doc in parser.raw_doctors:
        name = _clean_text_contacts(doc.get("name", ""))
        spec = _clean_text_contacts(doc.get("specialty", ""))
        if name:
            clean_doctors.append({"name": name, "specialty": spec})

    drift_fields: list[str] = []
    if not parser.institution_name:
        drift_fields.append("institution_name")
    if not clean_services:
        drift_fields.append("services")

    schema_drift = bool(drift_fields)

    return ExtractedClinicPage(
        institution_name=_clean_text_contacts(parser.institution_name),
        address=_clean_text_contacts(parser.address),
        phone=_clean_text_contacts(parser.phone),
        business_hours=_clean_text_contacts(parser.business_hours),
        services=clean_services,
        doctors=clean_doctors,
        schema_drift=schema_drift,
        drift_fields=drift_fields,
        schema_version=SCHEMA_VERSION,
    )
