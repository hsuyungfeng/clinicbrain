"""一般醫療諮詢業務層模組。

提供 consult_general() 作為一般諮詢的唯一業務入口：
- 紅旗短路：優先偵測急重症徵候，命中立即回傳固定就醫提示，完全不執行資料庫檢索。
- 資料隔離：僅檢索一般類別（category='general' 且 clinic_id IS NULL）之快取與指引樹。
- 誠實無捏造：未命中檢索結果時回傳固定提示，附上法定免責聲明。
- 零日誌與無狀態：不記錄問句、不呼叫外部模型、不進行任何寫入操作。
"""

from dataclasses import dataclass
import sqlite3
from typing import Literal

from src.general.disclaimer import (
    ANSWERED_MESSAGE,
    DISCLAIMER_TEXT,
    NO_MATCH_MESSAGE,
    RED_FLAG_DISCLAIMER_TEXT,
    message_for_red_flag,
)
from src.general.red_flags import detect_red_flag
from src.query.router import extract_search_terms, mask_prices
from src.query.search import SearchHit, search_faq_cache, search_text


@dataclass
class GeneralConsultResult:
    """一般醫療諮詢回傳結果。"""

    status: Literal["red_flag", "answered", "no_match"]
    red_flag_level: str | None
    message: str
    disclaimer: str
    faq_hits: list[dict]
    guide_hits: list[dict]


def _retrieve_general(
    conn: sqlite3.Connection,
    terms: list[str],
    limit: int,
) -> tuple[list[dict], list[dict]]:
    """檢索一般類別之問答快取與衛教指引樹。"""
    seen_faq_ids: set[int] = set()
    faq_results: list[dict] = []

    seen_guide_ids: set[int] = set()
    guide_results: list[dict] = []

    for term in terms:
        # 1. 檢索一般問答快取
        try:
            faq_hits = search_faq_cache(
                conn,
                query=term,
                limit=limit,
                clinic_id=None,
                category="general",
            )
            for hit in faq_hits:
                if hit.row_id not in seen_faq_ids:
                    seen_faq_ids.add(hit.row_id)
                    faq_results.append(
                        {
                            "topic_key": hit.fields.get("topic_key"),
                            "question": mask_prices(hit.fields.get("question") or ""),
                            "answer": mask_prices(hit.fields.get("answer") or ""),
                        }
                    )
        except sqlite3.OperationalError:
            pass

        # 2. 檢索一般衛教指引樹（排除任何特定機構欄位與備註）
        try:
            tree_hits = search_text(
                conn,
                table="page_index_trees",
                fts_table="page_index_fts",
                query=term,
                select_columns=(
                    "id",
                    "doc_id",
                    "pre_op",
                    "procedure",
                    "post_op_short",
                    "maintenance",
                    "summary_text",
                ),
                like_columns=("summary_text",),
                limit=limit,
                extra_where="category = 'general' AND clinic_id IS NULL",
            )
            for hit in tree_hits:
                if hit.row_id not in seen_guide_ids:
                    seen_guide_ids.add(hit.row_id)
                    guide_results.append(
                        {
                            "doc_id": hit.fields.get("doc_id"),
                            "summary_text": mask_prices(
                                hit.fields.get("summary_text") or ""
                            ),
                            "pre_op": mask_prices(hit.fields.get("pre_op") or ""),
                            "procedure": mask_prices(hit.fields.get("procedure") or ""),
                            "post_op_short": mask_prices(
                                hit.fields.get("post_op_short") or ""
                            ),
                            "maintenance": mask_prices(
                                hit.fields.get("maintenance") or ""
                            ),
                        }
                    )
        except sqlite3.OperationalError:
            pass

    return faq_results[:limit], guide_results[:limit]


def consult_general(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 5,
) -> GeneralConsultResult:
    """執行一般醫療諮詢業務流程。

    先進行急重症紅旗偵測，若命中則立即短路回傳固定就醫指示，完全不進行任何檢索。
    未命中時僅檢索一般性公開衛教資料庫，並一律附帶免責聲明。
    """
    # 步驟 1：急重症紅旗偵測（優先短路，不存取資料庫）
    red_flag = detect_red_flag(query)
    if red_flag is not None:
        return GeneralConsultResult(
            status="red_flag",
            red_flag_level=red_flag.level,
            message=message_for_red_flag(red_flag.level, red_flag.rule_id),
            disclaimer=RED_FLAG_DISCLAIMER_TEXT,
            faq_hits=[],
            guide_hits=[],
        )

    # 步驟 2：擷取搜尋詞
    terms = extract_search_terms(query)
    if not terms:
        return GeneralConsultResult(
            status="no_match",
            red_flag_level=None,
            message=NO_MATCH_MESSAGE,
            disclaimer=DISCLAIMER_TEXT,
            faq_hits=[],
            guide_hits=[],
        )

    # 步驟 3：檢索一般衛教資料
    faq_hits, guide_hits = _retrieve_general(conn, terms, limit=limit)

    # 步驟 4：判定結果狀態
    if not faq_hits and not guide_hits:
        return GeneralConsultResult(
            status="no_match",
            red_flag_level=None,
            message=NO_MATCH_MESSAGE,
            disclaimer=DISCLAIMER_TEXT,
            faq_hits=[],
            guide_hits=[],
        )

    return GeneralConsultResult(
        status="answered",
        red_flag_level=None,
        message=ANSWERED_MESSAGE,
        disclaimer=DISCLAIMER_TEXT,
        faq_hits=faq_hits,
        guide_hits=guide_hits,
    )
