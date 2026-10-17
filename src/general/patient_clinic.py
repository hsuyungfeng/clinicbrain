"""
病人端固定診所範圍解析模組 (patient_clinic)。

設計原則：
1. 伺服器決定原則：診所由伺服器設定 (CLINICBRAIN_PATIENT_CLINIC_ID) 決定，而非請求決定。
2. 安全預設 (Fail-Closed)：未設定、格式不合、查無此診所或資料表異常時一律回 None，絕不改查他院。
3. 零寫入與純查詢：僅使用純 SELECT 查詢 clinic_info，無資料持久化，符合守門測試規範（不使用 logging）。
"""

from __future__ import annotations

import sqlite3
from typing import Optional


def resolve_patient_clinic(conn: sqlite3.Connection, configured: Optional[str]) -> Optional[str]:
    """解析並驗證伺服器設定之病人諮詢固定診所代碼。

    驗證規則：
    1. configured 為 None 或空字串 -> 回傳 None。
    2. configured 必須為恰好 10 碼純數字（台灣醫事機構代碼標準格式），否則回傳 None。
    3. 必須於 clinic_info 資料表中存在該診所代碼，否則回傳 None。
    4. 任何查詢例外（如資料表不存在）皆 Fail-Closed 回傳 None。
    """
    if not configured:
        return None

    c = str(configured).strip()
    if len(c) != 10 or not c.isdigit():
        return None

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM clinic_info WHERE clinic_id = ?", (c,))
        row = cursor.fetchone()
        return c if row else None
    except Exception:
        return None
