"""
Taiwan Clinic Medical PageIndex RAG System - 診所常見問答衝突比對模組 (faq_conflicts)
Phase 12 General Content Generation: GC-04 (相近診所 FAQ 檢索比對)

設計原則與局限說明：
- 詞彙守衛非主題守衛：覆蓋率高不代表主題衝突、未列出不代表沒有衝突。
  當病患或審核題目使用相近字眼提問時，提供可能存在個別化臨床指示之診所 FAQ 供醫師人工審閱。
- 嚴格唯讀：本模組絕不寫入資料庫、不記錄業務日誌、不調用外部 LLM。
- 全表掃描取捨：由於診所端上線之 FAQ 規模精簡（通常數十至數百筆），採全表可見項目掃描計算覆蓋率，
  換取 100% 精確的雙向 Bigram 與停用詞比對，避免 FTS5 trigram 漏檢短詞。
"""

import sqlite3
from typing import Any, Optional

from src.pageindex.faq_review import visible_faq_sql
from src.query.faq_shortcut import CLINIC_RELATED_FLOOR, faq_coverage
from src.query.router import STOPWORD_SPLIT_PATTERN


def find_similar_clinic_faqs(
    conn: sqlite3.Connection,
    general_question: str,
    *,
    clinic_id: Optional[str] = None,
    floor: float = CLINIC_RELATED_FLOOR,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    自資料庫檢索與指定 general 問句相近之診所 special FAQ 列表。

    比對規則：
    - 僅比對 category='special' 且 clinic_id IS NOT NULL 且對外可見 (visible_faq_sql) 之列
    - 以 general FAQ 問句為 query、診所 FAQ 問句為候選，計算標準化覆蓋率 (query_coverage)
    - 僅保留 query_coverage >= floor 之候選
    - 排序規則：(-query_coverage, -question_coverage, id 升冪)
    - 回傳最多 limit 筆結果字典（包含 id, clinic_id, topic_key, question, answer, query_coverage, question_coverage）
    """
    cur = conn.cursor()
    where_parts = [
        "category = 'special'",
        "clinic_id IS NOT NULL",
        visible_faq_sql(conn),
    ]
    params: list[Any] = []

    if clinic_id:
        where_parts.append("clinic_id = ?")
        params.append(clinic_id)

    cur.execute(
        f"""
        SELECT id, clinic_id, topic_key, question, answer
        FROM faq_cache
        WHERE {' AND '.join(where_parts)}
        """,
        params,
    )
    rows = cur.fetchall()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        faq_id, c_id, t_key, q_text, a_text = row
        q_cov, cand_cov = faq_coverage(general_question, q_text, STOPWORD_SPLIT_PATTERN)
        if q_cov >= floor:
            candidates.append(
                {
                    "id": faq_id,
                    "clinic_id": c_id,
                    "topic_key": t_key,
                    "question": q_text,
                    "answer": a_text,
                    "query_coverage": q_cov,
                    "question_coverage": cand_cov,
                }
            )

    candidates.sort(key=lambda x: (-x["query_coverage"], -x["question_coverage"], x["id"]))
    return candidates[:limit]
