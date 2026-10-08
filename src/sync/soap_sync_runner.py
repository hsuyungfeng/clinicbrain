"""
Taiwan Clinic Medical PageIndex RAG System - 定時 SOAP 病歷增量同步與預拉取模組 (soap_sync_runner)
Phase 16 Plan 16-02: 定時增量同步契約模組與夜間預拉取整合

提供：
1. process_soap_records: 個資去識別化與價格清洗二次防護處理
2. sync_and_ingest_soap_records: 增量寫入/更新 soap_records 專用進入點
3. pull_remote_soap_records: 向遠端 EHR / 診所系統進行 REST API 安全拉取
4. sync_soap_records_before_batch: 夜間批次前置同步掛鉤（異常時優雅降級不中斷批次）
"""

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
import urllib.parse
import urllib.request

try:
    from ..soap.soap_writer import upsert_soap_records
    from ..soap.deid import DeidKeyError, deidentify_text, generate_patient_token, is_safe_identifier
    from ..api.routes.query import deep_mask_prices
except (ImportError, ValueError):
    from src.soap.soap_writer import upsert_soap_records
    from src.soap.deid import DeidKeyError, deidentify_text, generate_patient_token, is_safe_identifier
    from src.api.routes.query import deep_mask_prices

logger = logging.getLogger(__name__)


@dataclass
class SoapSyncResult:
    """SOAP 同步與寫入結果統計。"""
    status: str = "completed"  # "completed", "failed", "degraded"
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: int = 0
    error_message: Optional[str] = None
    processed_count: int = 0


def process_soap_records(
    records: List[Dict[str, Any]],
    clinic_id: str,
) -> List[Dict[str, Any]]:
    """
    對傳入之 SOAP 紀錄進行文字清洗、個資去識別化、價格屏蔽與欄位補全。
    """
    cleaned_records: List[Dict[str, Any]] = []

    for item in records:
        ext_id = str(item.get("external_id") or "").strip()
        if not ext_id:
            continue

        raw_text = str(item.get("raw_text") or "").strip()
        subjective = str(item.get("subjective") or "").strip()
        objective = str(item.get("objective") or "").strip()
        assessment = str(item.get("assessment") or "").strip()
        plan = str(item.get("plan") or "").strip()

        # 個資去識別化與價格二次清洗
        clean_raw = deidentify_text(raw_text) if raw_text else ""
        clean_s = deidentify_text(subjective) if subjective else ""
        clean_o = deidentify_text(objective) if objective else ""
        clean_a = deidentify_text(assessment) if assessment else ""
        clean_p = deidentify_text(plan) if plan else ""

        # 病患代號生成與檢驗
        ptoken = str(item.get("patient_token") or item.get("patient_id") or "").strip()
        if not ptoken or not is_safe_identifier(ptoken):
            try:
                ptoken = generate_patient_token(ptoken or ext_id, clinic_id)
            except DeidKeyError:
                # 無金鑰時以 safe identifier 為預設
                ptoken = f"PTK-{ext_id}"

        cleaned_records.append({
            "clinic_id": clinic_id,
            "external_id": ext_id,
            "patient_token": ptoken,
            "encounter_date": item.get("encounter_date"),
            "raw_text": clean_raw or f"S: {clean_s} O: {clean_o} A: {clean_a} P: {clean_p}",
            "subjective": clean_s,
            "objective": clean_o,
            "assessment": clean_a,
            "plan": clean_p,
            "tags": item.get("tags"),
        })

    return cleaned_records


def sync_and_ingest_soap_records(
    conn: sqlite3.Connection,
    records: List[Dict[str, Any]],
    clinic_id: str,
    *,
    dry_run: bool = False,
) -> SoapSyncResult:
    """
    處理並寫入傳入之 SOAP 紀錄集合。
    """
    result = SoapSyncResult()
    if not records:
        return result

    try:
        processed = process_soap_records(records, clinic_id)
        result.processed_count = len(processed)

        if processed and not dry_run:
            ins, upd, unc = upsert_soap_records(conn, processed, clinic_id)
            result.inserted = ins
            result.updated = upd
            result.unchanged = unc

        return result
    except Exception as e:
        logger.error(f"SOAP 紀錄處理入庫失敗: {e}")
        result.status = "failed"
        result.errors = len(records)
        result.error_message = str(e)
        return result


def pull_remote_soap_records(
    remote_url: str,
    api_key: Optional[str] = None,
    clinic_id: str = "3503190424",
    since_days: int = 1,
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    向遠端服務發起 REST GET / POST 請求拉取 SOAP 病歷資料。
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    payload = json.dumps({"clinic_id": clinic_id, "since_days": since_days}).encode("utf-8")
    req = urllib.request.Request(remote_url, data=payload, headers=headers, method="POST")

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP 請求失敗，狀態碼: {resp.status}")
        data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict):
            return data.get("records", [])
        elif isinstance(data, list):
            return data
        return []


def sync_soap_records_before_batch(
    conn: sqlite3.Connection,
    clinic_id: str = "3503190424",
    *,
    remote_url: Optional[str] = None,
    api_key: Optional[str] = None,
    local_records: Optional[List[Dict[str, Any]]] = None,
    dry_run: bool = False,
) -> SoapSyncResult:
    """
    夜間批次前置同步掛鉤。
    若拉取或網路異常，記錄警報並優雅降級（status='degraded'），保證不中斷夜間批次後續執行。
    """
    result = SoapSyncResult()

    records_to_sync: List[Dict[str, Any]] = []
    if local_records:
        records_to_sync.extend(local_records)

    if remote_url:
        try:
            pulled = pull_remote_soap_records(remote_url, api_key=api_key, clinic_id=clinic_id)
            records_to_sync.extend(pulled)
        except Exception as e:
            logger.warning(f"夜間前置同步拉取網路異常 (URL: {remote_url}): {e}，優雅降級繼續執行")
            result.status = "degraded"
            result.error_message = f"遠端拉取失敗: {e}"

    if records_to_sync:
        ingest_res = sync_and_ingest_soap_records(conn, records_to_sync, clinic_id, dry_run=dry_run)
        result.inserted = ingest_res.inserted
        result.updated = ingest_res.updated
        result.unchanged = ingest_res.unchanged
        result.processed_count = ingest_res.processed_count
        if ingest_res.status == "failed":
            result.status = "degraded"
            result.error_message = ingest_res.error_message

    return result
