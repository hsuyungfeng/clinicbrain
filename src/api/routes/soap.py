"""
Taiwan Clinic Medical PageIndex RAG System - SOAP 紀錄接收與醫師檢索 API 路由模組
Phase 14: 臨床語音與 SOAP 紀錄擷取 (D-04, D-05, D-06, D-07, D-08)

提供：
1. POST /api/v1/soap/records: 接收外部推播，自動切分、去識別化、價格清洗並入庫。
2. POST /api/v1/soap/search: 醫師專用歷史案例 FTS5 trigram 全文檢索（限同診所）。
3. GET /api/v1/soap/records/{external_id}: 調閱單筆 SOAP 紀錄。
"""

import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import get_read_db, get_write_db, verify_admin_key
from ..models.soap import (
    SoapIngestRequest,
    SoapIngestResponse,
    SoapRecordInput,
    SoapRecordItem,
    SoapSearchRequest,
    SoapSearchResponse,
)

try:
    from ...soap.soap_writer import upsert_soap_records
    from ...soap.section_parser import parse_soap_text, extract_general_medical_insights
    from ...soap.deid import deidentify_text, generate_patient_token
    from ...query.router import get_clinic_info
except (ImportError, ValueError):
    from src.soap.soap_writer import upsert_soap_records
    from src.soap.section_parser import parse_soap_text, extract_general_medical_insights
    from src.soap.deid import deidentify_text, generate_patient_token
    from src.query.router import get_clinic_info

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/soap", tags=["臨床語音與 SOAP 紀錄"])


def _verify_clinic_exists(conn: sqlite3.Connection, clinic_id: str) -> None:
    """驗證診所代碼是否存在於 clinic_info，若不存在拋出 HTTP 400。"""
    try:
        info = get_clinic_info(conn, clinic_id)
        if not info:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"無效的診所代碼：'{clinic_id}'，診所不存在於系統中",
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"無效的診所代碼：'{clinic_id}'",
        )


@router.post(
    "/records",
    response_model=SoapIngestResponse,
    summary="接收外部推播 SOAP 紀錄",
    dependencies=[Depends(verify_admin_key)],
)
def ingest_soap_records(
    req: SoapIngestRequest,
    conn: sqlite3.Connection = Depends(get_write_db),
) -> SoapIngestResponse:
    """接收 doctor-toolbox.com 等外部系統推播之 SOAP 紀錄。

    流程：
    1. 驗證 clinic_id 存在性與合法性。
    2. 對每筆紀錄檢查段落：若無 S/O/A/P 則自動切分 raw_text/transcript。
    3. 執行一般醫學特徵擷取，將匹配之疾病與症狀標籤整合入 tags。
    4. 執行病患個資去識別化與 deep_mask_prices 價格清洗。
    5. 產生不可逆且具診所隔離之 patient_token。
    6. 呼叫單一權威寫入函式 upsert_soap_records 入庫。
    """
    _verify_clinic_exists(conn, req.clinic_id)

    processed_records: List[Dict[str, Any]] = []
    total_conditions: List[str] = []
    total_symptoms: List[str] = []

    for idx, item in enumerate(req.records):
        raw_source = item.raw_text or item.transcript or ""

        # 1. 段落剖析（若有傳入已拆分之欄位則優先採用，否則切分 raw_source）
        s_val = item.subjective
        o_val = item.objective
        a_val = item.assessment
        p_val = item.plan

        if not any((s_val, o_val, a_val, p_val)):
            parsed = parse_soap_text(raw_source)
            s_val = parsed["subjective"]
            o_val = parsed["objective"]
            a_val = parsed["assessment"]
            p_val = parsed["plan"]
            if not raw_source:
                raw_source = parsed["raw_text"]
        else:
            if not raw_source:
                raw_source = f"S: {s_val or ''}\nO: {o_val or ''}\nA: {a_val or ''}\nP: {p_val or ''}".strip()

        # 2. 一般醫學資料分析擷取（依使用者指示，將 SOAP 資料分析應用於一般醫學）
        insights = extract_general_medical_insights({
            "subjective": s_val or "",
            "objective": o_val or "",
            "assessment": a_val or "",
            "plan": p_val or "",
        })
        for c in insights["conditions"]:
            if c not in total_conditions:
                total_conditions.append(c)
        for sym in insights["symptoms"]:
            if sym not in total_symptoms:
                total_symptoms.append(sym)

        # 3. 標籤整併
        merged_tags = list(item.tags or [])
        for stag in insights["suggested_tags"]:
            if stag not in merged_tags:
                merged_tags.append(stag)

        # 4. 病患 Token 衍生
        if item.patient_token and item.patient_token.strip():
            final_token = item.patient_token.strip()
        else:
            final_token = generate_patient_token(item.patient_id, req.clinic_id)

        # 5. 去識別化與價格清洗
        clean_s = deidentify_text(s_val or "")
        clean_o = deidentify_text(o_val or "")
        clean_a = deidentify_text(a_val or "")
        clean_p = deidentify_text(p_val or "")
        clean_raw = deidentify_text(raw_source)

        processed_records.append({
            "external_id": item.external_id,
            "patient_token": final_token,
            "subjective": clean_s,
            "objective": clean_o,
            "assessment": clean_a,
            "plan": clean_p,
            "raw_text": clean_raw,
            "tags": ",".join(merged_tags),
        })

    try:
        inserted, updated, unchanged = upsert_soap_records(conn, processed_records, req.clinic_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SOAP 寫入格式檢驗失敗：{e}",
        )
    except Exception as e:
        logger.exception("SOAP 紀錄推播寫入發生未預期異常")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SOAP 紀錄入庫失敗：{e}",
        )

    return SoapIngestResponse(
        success=True,
        summary={"inserted": inserted, "updated": updated, "unchanged": unchanged},
        message=f"成功處理 {len(processed_records)} 筆 SOAP 紀錄（新增 {inserted} 筆，更新 {updated} 筆，未變更 {unchanged} 筆）",
        general_insights_summary={
            "extracted_conditions": total_conditions,
            "extracted_symptoms": total_symptoms,
        },
    )


@router.post(
    "/search",
    response_model=SoapSearchResponse,
    summary="醫師專用 SOAP 臨床歷史全文檢索",
    dependencies=[Depends(verify_admin_key)],
)
def search_soap_records(
    req: SoapSearchRequest,
    conn: sqlite3.Connection = Depends(get_read_db),
) -> SoapSearchResponse:
    """醫師專用臨床歷史案例全文檢索（嚴格同診所隔離）。

    使用 FTS5 trigram MATCH 進行繁體中文臨床症狀、處置與標籤匹配；
    當關鍵字少於 3 字元時自動分流至 LIKE 模糊搜尋（遵守 trigram 鐵則）。
    """
    _verify_clinic_exists(conn, req.clinic_id)

    query_str = (req.query or "").strip()
    if not query_str:
        return SoapSearchResponse(total=0, records=[])

    cursor = conn.cursor()
    params: List[Any] = [req.clinic_id]

    # trigram 全文檢索分流邏輯（3字以上走 FTS trigram，少於 3 字走 LIKE 混合）
    if len(query_str) >= 3:
        sql = """
            SELECT r.id, r.clinic_id, r.external_id, r.patient_token,
                   r.subjective, r.objective, r.assessment, r.plan,
                   r.raw_text, r.tags, r.created_at, r.updated_at
            FROM soap_records_fts fts
            JOIN soap_records r ON fts.rowid = r.id
            WHERE r.clinic_id = ? AND soap_records_fts MATCH ?
        """
        # 清理並轉義 FTS MATCH 關鍵字
        safe_match = query_str.replace('"', '""')
        params.append(f'"{safe_match}"')
    else:
        sql = """
            SELECT r.id, r.clinic_id, r.external_id, r.patient_token,
                   r.subjective, r.objective, r.assessment, r.plan,
                   r.raw_text, r.tags, r.created_at, r.updated_at
            FROM soap_records r
            WHERE r.clinic_id = ? AND (
                r.subjective LIKE ? OR
                r.objective LIKE ? OR
                r.assessment LIKE ? OR
                r.plan LIKE ? OR
                r.tags LIKE ?
            )
        """
        like_pattern = f"%{query_str}%"
        params.extend([like_pattern, like_pattern, like_pattern, like_pattern, like_pattern])

    if req.tag and req.tag.strip():
        sql += " AND r.tags LIKE ?"
        params.append(f"%{req.tag.strip()}%")

    sql += " ORDER BY r.created_at DESC LIMIT ?"
    params.append(req.limit)

    cursor.execute(sql, params)
    rows = cursor.fetchall()

    items: List[SoapRecordItem] = []
    for row in rows:
        tag_list = [t.strip() for t in (row[9] or "").split(",") if t.strip()]
        items.append(
            SoapRecordItem(
                id=row[0],
                clinic_id=row[1],
                external_id=row[2],
                patient_token=row[3],
                subjective=row[4],
                objective=row[5],
                assessment=row[6],
                plan=row[7],
                raw_text=row[8],
                tags=tag_list,
                created_at=str(row[10]),
                updated_at=str(row[11]),
            )
        )

    return SoapSearchResponse(total=len(items), records=items)


@router.get(
    "/records/{external_id}",
    response_model=SoapRecordItem,
    summary="調閱單筆 SOAP 紀錄",
    dependencies=[Depends(verify_admin_key)],
)
def get_soap_record(
    external_id: str,
    clinic_id: str = Query(..., description="診所代碼"),
    conn: sqlite3.Connection = Depends(get_read_db),
) -> SoapRecordItem:
    """調閱指定 external_id 之單筆 SOAP 紀錄。"""
    _verify_clinic_exists(conn, clinic_id)

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, clinic_id, external_id, patient_token,
               subjective, objective, assessment, plan,
               raw_text, tags, created_at, updated_at
        FROM soap_records
        WHERE clinic_id = ? AND external_id = ?
        """,
        (clinic_id, external_id),
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"查無外部識別碼 '{external_id}' 之 SOAP 紀錄",
        )

    tag_list = [t.strip() for t in (row[9] or "").split(",") if t.strip()]
    return SoapRecordItem(
        id=row[0],
        clinic_id=row[1],
        external_id=row[2],
        patient_token=row[3],
        subjective=row[4],
        objective=row[5],
        assessment=row[6],
        plan=row[7],
        raw_text=row[8],
        tags=tag_list,
        created_at=str(row[10]),
        updated_at=str(row[11]),
    )
