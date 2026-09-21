#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 全文檢索分流邏輯
Phase 01 Task 5: search/query interface

核心問題（見 AGENTS.md 2.3 節）：SQLite FTS5 的 trigram tokenizer 要求
查詢字串至少 3 字元才能有效匹配；中文醫療用語有大量 2 字詞（雷射、拆線、
掛號、洗牙等）。這裡實作統一的分流邏輯：3+ 字用 FTS5 trigram MATCH，
少於 3 字用 LIKE '%term%' 全表掃描 fallback。

所有查詢 clinicbrain 三個 FTS5 資料表（drugs_fts/service_items_fts/
page_index_fts）的程式碼都應該透過這裡的 search_text()，不要各自重新
判斷字元長度或組 SQL——保持分流規則只有一個實作。
"""

import sqlite3
from dataclasses import dataclass
from typing import Optional

# trigram tokenizer 對少於此字元數的查詢無法有效匹配，需要 LIKE fallback
FTS_MIN_CHARS = 3


@dataclass
class SearchHit:
    table: str
    row_id: int
    fields: dict


def _use_fts(query: str) -> bool:
    """判斷查詢字串是否該走 FTS5 trigram，還是該用 LIKE fallback。"""
    return len(query.strip()) >= FTS_MIN_CHARS


def search_text(
    conn: sqlite3.Connection,
    table: str,
    fts_table: str,
    query: str,
    select_columns: tuple,
    like_columns: tuple,
    limit: int = 10,
) -> list[SearchHit]:
    """對指定資料表做中文全文檢索，依查詢字串長度自動分流。

    table: 主資料表名稱（如 'drugs'）
    fts_table: 對應 FTS5 虛擬表名稱（如 'drugs_fts'），content_rowid 假設
        對應到 table 的 rowid（drugs/service_items）或 id（page_index_trees，
        呼叫方需自行處理 join 欄位差異，見下方個別查詢函式）
    query: 使用者輸入的查詢字串
    select_columns: 要從 table 取回的欄位（含主鍵）
    like_columns: LIKE fallback 時要比對的欄位（通常是中文名稱欄位）
    limit: 回傳筆數上限
    """
    query = query.strip()
    if not query:
        return []

    cursor = conn.cursor()

    if _use_fts(query):
        cursor.execute(
            f"""
            SELECT {', '.join(select_columns)}
            FROM {table}
            WHERE rowid IN (
                SELECT rowid FROM {fts_table} WHERE {fts_table} MATCH ?
            )
            LIMIT ?
            """,
            (query, limit),
        )
    else:
        where_clause = " OR ".join(f"{col} LIKE ?" for col in like_columns)
        params = [f"%{query}%" for _ in like_columns] + [limit]
        cursor.execute(
            f"""
            SELECT {', '.join(select_columns)}
            FROM {table}
            WHERE {where_clause}
            LIMIT ?
            """,
            params,
        )

    rows = cursor.fetchall()
    return [
        SearchHit(table=table, row_id=row[0], fields=dict(zip(select_columns, row)))
        for row in rows
    ]


def format_drug_display_name(fields: dict) -> str:
    """產生藥品的使用者易讀名稱。
    若有 otc_name_chinese（本地化俗名/用途說明），優先於顯示名稱中凸顯，
    方便病患快速理解藥品臨床用途與通俗稱呼。
    """
    otc = fields.get("otc_name_chinese")
    cname = (fields.get("chinese_name") or "").strip()
    ename = (fields.get("english_name") or "").strip()

    if otc:
        if cname:
            return f"{cname}【{otc}】"
        if ename:
            return f"{ename}【{otc}】"
        return otc
    return cname or ename or "未具名藥品"


def search_drugs(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[SearchHit]:
    hits = search_text(
        conn,
        table="drugs",
        fts_table="drugs_fts",
        query=query,
        select_columns=("code", "chinese_name", "english_name", "ingredient", "otc_name_chinese"),
        like_columns=("chinese_name", "ingredient", "otc_name_chinese"),
        limit=limit,
    )
    for hit in hits:
        hit.fields["display_name"] = format_drug_display_name(hit.fields)
    return hits


def search_service_items(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[SearchHit]:
    return search_text(
        conn,
        table="service_items",
        fts_table="service_items_fts",
        query=query,
        select_columns=("code", "chinese_name", "english_name", "points"),
        like_columns=("chinese_name",),
        limit=limit,
    )


def search_page_index_trees(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[SearchHit]:
    """page_index_trees 的 rowid 對應到 id（AUTOINCREMENT 主鍵），不是預設
    rowid 別名以外的欄位，所以這裡直接用 id 當 select 主鍵，語法上與
    search_text() 的假設一致（SQLite 中 INTEGER PRIMARY KEY 就是 rowid 別名）。
    """
    return search_text(
        conn,
        table="page_index_trees",
        fts_table="page_index_fts",
        query=query,
        select_columns=(
            "id",
            "doc_id",
            "category",
            "pre_op",
            "procedure",
            "post_op_short",
            "maintenance",
            "summary_text",
        ),
        like_columns=("summary_text",),
        limit=limit,
    )
