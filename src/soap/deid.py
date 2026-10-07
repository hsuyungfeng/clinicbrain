"""
Taiwan Clinic Medical PageIndex RAG System - 病患個資去識別化與代號生成模組
Phase 14: 臨床語音與 SOAP 紀錄擷取 (D-06, D-07)

提供台灣醫療個資（身分證字號、居留證號、手機、市話、真實姓名）自動偵測遮蔽，
整合價格二次清洗，並透過確定性 HMAC-SHA256 生成不可逆之病患代號 (patient_token)。
"""

import hashlib
import hmac
import os
import re
from typing import Optional

try:
    from ..api.routes.query import deep_mask_prices
except (ImportError, ValueError):
    from src.api.routes.query import deep_mask_prices

# 台灣身分證首字英文字母權重表
_ID_LETTER_MAP = {
    "A": 10, "B": 11, "C": 12, "D": 13, "E": 14, "F": 15, "G": 16, "H": 17,
    "J": 18, "K": 19, "L": 20, "M": 21, "N": 22, "P": 23, "Q": 24, "R": 25,
    "S": 26, "T": 27, "U": 28, "V": 29, "X": 30, "Y": 31, "W": 32, "Z": 33,
    "I": 34, "O": 35,
}

# 注意：不可使用 \b。Python 3 的 \b 在 Unicode 下把中文字視為 \w，
# 「身分證A123456789」「電話0912345678」中英數交界沒有 \b，會整段漏遮蔽。
_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9])([A-Z][1289A-D]\d{8})(?!\d)", re.IGNORECASE)
_MOBILE_PATTERN = re.compile(r"(?<!\d)(09\d{2}[-\s]?\d{3}[-\s]?\d{3}|09\d{8})(?!\d)")
_LANDLINE_PATTERN = re.compile(r"(?<!\d)(0\d{1,2}[-\s]?\d{7,8})(?!\d)")
# 「姓名」標籤後可直接接姓名；「病患／患者」因常接症狀描述（患者持續發燒），必須帶分隔符才遮蔽
_NAME_LABEL_PATTERN = re.compile(
    r"((?:病患姓名|患者姓名|姓名)[：:\s]*|(?:病患|患者)[：:\s]+)([\u4e00-\u9fa5]{2,4})"
)

# patient_token／external_id 等外部傳入識別欄位允許的字元（拒絕姓名、空白與標點夾帶個資）
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")


class DeidKeyError(RuntimeError):
    """未設定去識別化 HMAC 金鑰（Fail-Closed，不使用內建預設值）。"""


def contains_pii_identifier(text: str) -> bool:
    """文字內是否含身分證／居留證號或電話（用於拒絕外部識別欄位夾帶個資）。"""
    t = text or ""
    return bool(_ID_PATTERN.search(t) or _MOBILE_PATTERN.search(t) or _LANDLINE_PATTERN.search(t))


def is_safe_identifier(value: str) -> bool:
    """外部識別碼是否為安全格式：限定字元集、長度，且不得形似身分證或電話。"""
    v = (value or "").strip()
    return bool(_SAFE_IDENTIFIER.match(v)) and not contains_pii_identifier(v)


def validate_taiwan_id(id_str: str) -> bool:
    """驗證台灣身分證字號檢查碼演算法是否合法。"""
    s = (id_str or "").strip().upper()
    if len(s) != 10:
        return False
    first = s[0]
    if first not in _ID_LETTER_MAP:
        return False
    if not s[1:].isdigit():
        return False

    num = _ID_LETTER_MAP[first]
    n1 = num // 10
    n2 = num % 10
    digits = [int(c) for c in s[1:]]

    weights = [8, 7, 6, 5, 4, 3, 2, 1]
    total = n1 * 1 + n2 * 9
    for d, w in zip(digits[:8], weights):
        total += d * w
    check = (10 - (total % 10)) % 10
    return check == digits[8]


def deidentify_text(text: str) -> str:
    """對輸入文字進行個資去識別化與價格二次清洗。

    遮蔽項目：
    1. 身分證字號／居留證號 -> [身分證已遮蔽]
    2. 手機與市話號碼 -> [電話已遮蔽]
    3. 明顯標記之姓名 -> [姓名已遮蔽]
    4. 具體金額數字 -> [請致電診所確認] (經由 deep_mask_prices)
    """
    if not text or not isinstance(text, str):
        return ""

    cleaned = text

    # 1. 身分證/居留證遮蔽
    def _mask_id(match: re.Match) -> str:
        matched_code = match.group(1).upper()
        # 若通過身分證檢查碼或前綴為常見居留證字軌，進行遮蔽
        if validate_taiwan_id(matched_code) or matched_code[1] in "89ABCD":
            return "[身分證已遮蔽]"
        return match.group(0)

    cleaned = _ID_PATTERN.sub(_mask_id, cleaned)

    # 2. 電話遮蔽
    cleaned = _MOBILE_PATTERN.sub("[電話已遮蔽]", cleaned)
    cleaned = _LANDLINE_PATTERN.sub("[電話已遮蔽]", cleaned)

    # 3. 姓名標籤遮蔽
    cleaned = _NAME_LABEL_PATTERN.sub(r"\1[姓名已遮蔽]", cleaned)

    # 4. 價格清洗
    cleaned = deep_mask_prices(cleaned)

    return cleaned


def generate_patient_token(patient_id: Optional[str], clinic_id: str) -> str:
    """以 clinic_id 與 patient_id 透過 HMAC-SHA256 生成去識別化代號。

    特點：
    - 同一診所內相同外部 patient_id 產生相同 token（支援縱向歷程比對）。
    - 跨診所資料隔離（即使不同診所代號相同，其 token 亦不相同）。
    - 金鑰取自環境變數 CLINICBRAIN_DEID_KEY（未設定時退回 CLINICBRAIN_ADMIN_API_KEY），
      程式碼內不得有預設金鑰：身分證字號搜尋空間小，公開 salt 等於可被字典攻擊還原。
    - 兩者皆未設定時拋出 DeidKeyError（Fail-Closed）。
    """
    secret = (os.environ.get("CLINICBRAIN_DEID_KEY") or os.environ.get("CLINICBRAIN_ADMIN_API_KEY") or "").strip()
    if not secret:
        raise DeidKeyError("未設定 CLINICBRAIN_DEID_KEY（或 CLINICBRAIN_ADMIN_API_KEY），無法產生病患代號")

    clean_clinic = (clinic_id or "default").strip()
    clean_pid = (patient_id or "anonymous").strip()

    key = f"{clean_clinic}:{clean_pid}".encode("utf-8")
    token_hex = hmac.new(secret.encode("utf-8"), key, hashlib.sha256).hexdigest()[:12].upper()
    return f"PTK-{token_hex}"
