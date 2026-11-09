"""台灣健保 1-400 大疾病目錄資料庫檢索與 LLM 選取模組。

本模組提供對 nhi_catalog_1_400 與 nhi_catalog_fts 的查詢介面：
1. 支援 trigram FTS5 與短字串 LIKE 混合查詢。
2. 回傳疾病名稱、ICD-10、症狀關鍵字、臨床特徵與動畫可用性 (visual_available)。
3. 提供結構化上下文組裝函式，供 LLM 在門診諮詢時選取最精確的疾病代碼與衛教動畫。
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from typing import Any, Dict, List, Optional


def _normalize_query(text: str) -> str:
    """NFKC 正規化並去除多餘空白。"""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).strip().lower()


def search_nhi_catalog(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 5,
    system: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """檢索 1-400 健保疾病目錄。
    
    若查詢詞大於等於 3 字元，優先走 FTS5 trigram 檢索；
    若小於 3 字元，走 LIKE 子字串比對。
    """
    clean_q = _normalize_query(query)
    if not clean_q:
        return []

    cur = conn.cursor()
    system_filter = " AND c.system = ?" if system else ""
    params: list[Any] = []

    # 1. 3 字以上使用 FTS5 trigram
    if len(clean_q) >= 3:
        sql = f"""
            SELECT c.index_no, c.id, c.system, c.category, c.name, c.icd10,
                   c.alias, c.keywords, c.clinical_feature, c.topic_key, c.visual_available
            FROM nhi_catalog_fts f
            JOIN nhi_catalog_1_400 c ON f.index_no = c.index_no
            WHERE nhi_catalog_fts MATCH ? {system_filter}
            ORDER BY c.visual_available DESC, c.index_no ASC
            LIMIT ?
        """
        params.append(clean_q)
        if system:
            params.append(system)
        params.append(limit)
        try:
            rows = cur.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            rows = []
    else:
        rows = []

    # 2. 若 FTS 未命中或查詢小於 3 字，使用 LIKE 備援
    if not rows:
        like_term = f"%{clean_q}%"
        sql = f"""
            SELECT c.index_no, c.id, c.system, c.category, c.name, c.icd10,
                   c.alias, c.keywords, c.clinical_feature, c.topic_key, c.visual_available
            FROM nhi_catalog_1_400 c
            WHERE (c.name LIKE ? OR c.keywords LIKE ? OR c.alias LIKE ? OR c.clinical_feature LIKE ?) {system_filter}
            ORDER BY c.visual_available DESC, c.index_no ASC
            LIMIT ?
        """
        params = [like_term, like_term, like_term, like_term]
        if system:
            params.append(system)
        params.append(limit)
        rows = cur.execute(sql, params).fetchall()

    results: List[Dict[str, Any]] = []
    for r in rows:
        try:
            alias_list = json.loads(r[6]) if r[6] else []
        except Exception:
            alias_list = [r[6]] if r[6] else []
        try:
            kw_list = json.loads(r[7]) if r[7] else []
        except Exception:
            kw_list = [r[7]] if r[7] else []

        results.append({
            "index_no": r[0],
            "id": r[1],
            "system": r[2],
            "category": r[3],
            "name": r[4],
            "icd10": r[5],
            "alias": alias_list,
            "keywords": kw_list,
            "clinical_feature": r[8],
            "topic_key": r[9],
            "visual_available": bool(r[10]),
        })

    return results


def get_nhi_entry(
    conn: sqlite3.Connection,
    identifier: str | int,
) -> Optional[Dict[str, Any]]:
    """依 index_no (1-400)、ID (例如 W201) 或 topic_key 取得單筆資料。"""
    cur = conn.cursor()
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        row = cur.execute(
            """
            SELECT index_no, id, system, category, name, icd10, alias, keywords, clinical_feature, topic_key, visual_available
            FROM nhi_catalog_1_400 WHERE index_no = ?
            """,
            (int(identifier),),
        ).fetchone()
    else:
        row = cur.execute(
            """
            SELECT index_no, id, system, category, name, icd10, alias, keywords, clinical_feature, topic_key, visual_available
            FROM nhi_catalog_1_400 WHERE id = ? OR topic_key = ?
            """,
            (str(identifier), str(identifier)),
        ).fetchone()

    if not row:
        return None

    try:
        alias_list = json.loads(row[6]) if row[6] else []
    except Exception:
        alias_list = [row[6]] if row[6] else []
    try:
        kw_list = json.loads(row[7]) if row[7] else []
    except Exception:
        kw_list = [row[7]] if row[7] else []

    return {
        "index_no": row[0],
        "id": row[1],
        "system": row[2],
        "category": row[3],
        "name": row[4],
        "icd10": row[5],
        "alias": alias_list,
        "keywords": kw_list,
        "clinical_feature": row[8],
        "topic_key": row[9],
        "visual_available": bool(row[10]),
    }


def format_nhi_context_for_llm(entries: List[Dict[str, Any]]) -> str:
    """將檢索到的健保疾病條目組裝為提供給 LLM 選取的精簡上下文。"""
    if not entries:
        return ""
    lines = ["【健保基層門診 1-400 疾病參考索引】:"]
    for e in entries:
        anim_tag = " [含3幕衛教動畫]" if e.get("visual_available") else ""
        lines.append(
            f"- [編號 {e['index_no']} | {e['id']}] {e['name']} (ICD-10: {e['icd10']}){anim_tag}\n"
            f"  類別: {e['category']} | 核心特徵: {e['clinical_feature']}\n"
            f"  關鍵字: {', '.join(e['keywords'][:5])}"
        )
    return "\n".join(lines)
