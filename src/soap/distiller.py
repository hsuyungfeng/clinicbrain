"""
Taiwan Clinic Medical PageIndex RAG System - SOAP 衛教提煉與草稿生成模組 (distiller)
Phase 15: 臨床 SOAP 衛教提煉與審核流 (15-01)

從特定診所之去識別化 soap_records 中分析 Assessment 與 Plan，
依疾病（condition）聚合出現頻率達門檻之居家照護（home_care）重點，
生成符合合規與價格清洗標準之衛教 FAQ 草稿 (source_type='soap_distilled', review_status='pending')，
並呼叫權威寫入函式 faq_writer.upsert_faqs 入庫。
"""

import json
import logging
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

try:
    from .section_parser import extract_general_medical_insights
    from ..pageindex.faq_writer import upsert_faqs
    from ..ingestion.generate_faq import validate_single_faq
    from ..api.routes.query import deep_mask_prices
except (ImportError, ValueError):
    from src.soap.section_parser import extract_general_medical_insights
    from src.pageindex.faq_writer import upsert_faqs
    from src.ingestion.generate_faq import validate_single_faq
    from src.api.routes.query import deep_mask_prices

logger = logging.getLogger(__name__)


def _clean_care_statement(stmt: str) -> str:
    """清理照護敘述句，移除條列編號與前綴標籤。"""
    cleaned = stmt.strip()
    cleaned = re.sub(r"^(?:衛教(?:事項|指導)?[:：]?|\d+[\.、:：\s]*)", "", cleaned).strip()
    return cleaned


def _extract_care_sentences(care_list: List[str]) -> List[str]:
    """將含有衛教關鍵字之文字切割為單一獨立照護句子。"""
    sentences = []
    for raw in care_list:
        parts = re.split(r"[。\n;；]", raw)
        for part in parts:
            cleaned = part.strip()
            if any(kw in cleaned for kw in ("衛教", "多喝水", "多喝溫水", "休息", "飲食", "清淡", "熱敷", "冰敷", "保養", "戒菸", "避免")):
                sub_cleaned = re.sub(r"^(?:衛教(?:事項|指導)?[:：]?|\d+[\.、:：\s]*)", "", cleaned).strip()
                if sub_cleaned and sub_cleaned not in sentences:
                    sentences.append(sub_cleaned)
    return sentences


def distill_soap_records(
    conn: sqlite3.Connection,
    clinic_id: str,
    min_occurrences: int = 2,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """從特定診所之 soap_records 提煉衛教 FAQ 草稿。

    流程：
    1. 查詢該診所所有 soap_records。
    2. 對每筆紀錄萃取一般醫學特徵 (conditions, home_care, symptoms)。
    3. 依 condition 分組，累積對應之照護重點與病歷筆數。
    4. 過濾出現次數 >= min_occurrences 之照護重點。
    5. 組裝標準問答對（含照護重點、就醫警訊、免責聲明、溯源元資料）。
    6. 通過價格清洗、禁詞與用藥劑量檢驗。
    7. 若非 dry_run，呼叫 faq_writer.upsert_faqs(conn, faqs, source_type='soap_distilled') 入庫 (pending)。
    """
    if not clinic_id or not str(clinic_id).strip():
        raise ValueError("clinic_id 必須為非空字串")

    clinic_id = str(clinic_id).strip()

    cur = conn.cursor()
    tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "soap_records" not in tables:
        return {
            "distilled_count": 0,
            "conditions": [],
            "faqs": [],
            "warning": "目標資料庫尚未建立 soap_records 資料表，請先執行 scripts/migrate_soap_schema.py",
        }

    cur.execute(
        """
        SELECT id, subjective, objective, assessment, plan, raw_text
        FROM soap_records
        WHERE clinic_id = ?
        ORDER BY id ASC
        """,
        (clinic_id,),
    )
    rows = cur.fetchall()

    if not rows:
        return {
            "distilled_count": 0,
            "conditions": [],
            "faqs": [],
        }

    condition_records_count: Dict[str, int] = {}
    condition_care_counts: Dict[str, Dict[str, int]] = {}

    for row in rows:
        parsed_soap = {
            "subjective": row[1] or "",
            "objective": row[2] or "",
            "assessment": row[3] or "",
            "plan": row[4] or "",
        }
        insights = extract_general_medical_insights(parsed_soap)
        conds = insights.get("conditions", [])
        raw_care_list = insights.get("home_care", [])
        care_sentences = _extract_care_sentences(raw_care_list)

        for cond in conds:
            condition_records_count[cond] = condition_records_count.get(cond, 0) + 1
            if cond not in condition_care_counts:
                condition_care_counts[cond] = {}

            for cleaned_care in care_sentences:
                condition_care_counts[cond][cleaned_care] = (
                    condition_care_counts[cond].get(cleaned_care, 0) + 1
                )

    distilled_faqs: List[Dict[str, Any]] = []
    processed_conditions: List[str] = []

    for cond, care_dict in condition_care_counts.items():
        rec_count = condition_records_count.get(cond, 0)

        # 篩選出現頻率 >= min_occurrences 之照護重點
        qualifying_care = [
            stmt for stmt, count in care_dict.items() if count >= min_occurrences
        ]

        # 若 min_occurrences 設為 1 且符合之項目為空，則包含所有獨立項目
        if not qualifying_care and min_occurrences <= 1:
            qualifying_care = list(care_dict.keys())

        if not qualifying_care:
            continue

        processed_conditions.append(cond)

        # 1. 條列照護要點
        points_str = "\n".join(f"{i+1}. {stmt}" for i, stmt in enumerate(qualifying_care))

        # 2. 強制就醫警訊 (符合 has_doctor_warning 檢驗)
        doctor_warning = "【就醫警訊】若出現高燒超過3天、呼吸困難、嚴重腹痛或症狀持續加重，請儘速就醫。"

        # 3. 醫療免責宣告
        disclaimer = "【免責聲明】本資訊為臨床病歷居家照護整理，僅供衛教參考，無法取代醫師親自診察。"

        question = f"【照護指引】罹患{cond}應注意哪些居家照護事項？"
        raw_answer = (
            f"以下為罹患{cond}之常見居家照護重點：\n"
            f"{points_str}\n\n"
            f"{doctor_warning}\n"
            f"{disclaimer}"
        )

        # 4. 安全合規清洗與檢核
        clean_answer = deep_mask_prices(raw_answer)

        is_valid, reason = validate_single_faq(
            {"question": question, "answer": clean_answer},
            check_dosage=True,
            require_doctor_warning=True,
        )
        if not is_valid:
            logger.warning(f"疾病 '{cond}' 提煉之衛教內容未通過合規檢驗 ({reason})，安全跳過")
            continue

        metadata_dict = {
            "source": "soap_distilled",
            "record_count": rec_count,
            "condition": cond,
            "clinic_id": clinic_id,
        }

        faq_item = {
            "clinic_id": clinic_id,
            "topic_key": f"care-{cond}",
            "question": question,
            "answer": clean_answer,
            "category": "special",
            "metadata": json.dumps(metadata_dict, ensure_ascii=False),
        }
        distilled_faqs.append(faq_item)

    if distilled_faqs and not dry_run:
        upsert_faqs(conn, distilled_faqs, source_type="soap_distilled")

    return {
        "distilled_count": len(distilled_faqs),
        "conditions": processed_conditions,
        "faqs": distilled_faqs,
    }
