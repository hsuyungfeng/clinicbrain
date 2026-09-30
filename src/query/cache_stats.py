"""
快取統計聚合與寫入模組（Phase 07 CACHE-03）。
提供 cache_stats 統計資料表的單一權威寫入函式與唯讀彙總函式。

隱私設計原則（符合 D-02 規範）：
1. 僅存放日聚合計數，不存放任何使用者問句原文、自由文字或個資。
2. 關鍵字僅記錄已命中於系統固定路由詞表者（ROUTE_KEYWORD_VOCAB 白名單），
   詞表外字串一律於寫入時拋棄，不推測 topic_key。
3. clinic_id 僅在該值確實存在於 clinic_info 時採用，否則正規化為空字串，
   防範外部透過 X-Clinic-ID 標頭注入自由文字。
4. outcome 語意：
   - 'hit': 快取短路命中次數
   - 'miss': 有資格短路但未命中快取的查詢次數（作為命中率分母）
   - 'miss_keyword': 未命中查詢所比對到的固定路由關鍵字計數
5. hit_rate = hit / (hit + miss)，未命中次數不包含無資格短路之查詢（如診所營運問句）。
"""

from collections.abc import Iterable
import sqlite3
from typing import Any, Optional

try:
    from .router import (
        _CLINIC_OPS_KEYWORDS,
        _DRUG_OR_SERVICE_KEYWORDS,
        _PROCEDURE_KEYWORDS,
    )
except ImportError:
    from router import (
        _CLINIC_OPS_KEYWORDS,
        _DRUG_OR_SERVICE_KEYWORDS,
        _PROCEDURE_KEYWORDS,
    )

# 固定路由關鍵字白名單（僅記錄存在於詞表中的字串）
ROUTE_KEYWORD_VOCAB: frozenset[str] = frozenset(
    _CLINIC_OPS_KEYWORDS + _PROCEDURE_KEYWORDS + _DRUG_OR_SERVICE_KEYWORDS
)

OUTCOME_HIT: str = "hit"
OUTCOME_MISS: str = "miss"
OUTCOME_MISS_KEYWORD: str = "miss_keyword"


def record_query_outcome(
    conn: sqlite3.Connection,
    *,
    clinic_id: Optional[str],
    hit: bool,
    matched_keywords: Iterable[str],
) -> int:
    """記錄單次查詢的快取結果至 cache_stats 表（唯一權威寫入函式）。

    回傳：本次寫入或更新之資料列數。
    """
    # 1. clinic_id 嚴格白名單校驗：存在於 clinic_info 才記錄，否則記為空字串
    effective_cid = ""
    if clinic_id and clinic_id.strip():
        clean_cid = clinic_id.strip()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM clinic_info WHERE clinic_id = ?", (clean_cid,))
        if cur.fetchone():
            effective_cid = clean_cid

    # 2. 關鍵字過濾：去重且僅保留存在於 ROUTE_KEYWORD_VOCAB 之字串
    valid_keywords = sorted({
        kw for kw in matched_keywords
        if kw in ROUTE_KEYWORD_VOCAB
    })

    # 3. 準備待寫入列：hit 僅記錄 ('hit', '')；miss 記錄 ('miss', '') 與各個 miss_keyword
    rows_to_write: list[tuple[str, str]] = []
    if hit:
        rows_to_write.append((OUTCOME_HIT, ""))
    else:
        rows_to_write.append((OUTCOME_MISS, ""))
        for kw in valid_keywords:
            rows_to_write.append((OUTCOME_MISS_KEYWORD, kw))

    # 4. 參數化 UPSERT 累加次數
    upsert_sql = """
        INSERT INTO cache_stats (clinic_id, stat_date, outcome, keyword, count)
        VALUES (?, date('now'), ?, ?, 1)
        ON CONFLICT(clinic_id, stat_date, outcome, keyword)
        DO UPDATE SET count = count + 1, updated_at = CURRENT_TIMESTAMP
    """

    cursor = conn.cursor()
    for outcome, keyword in rows_to_write:
        cursor.execute(upsert_sql, (effective_cid, outcome, keyword))

    conn.commit()
    return len(rows_to_write)


def get_cache_stats(
    conn: sqlite3.Connection,
    *,
    clinic_id: Optional[str] = None,
    since_date: Optional[str] = None,
    top_n: int = 20,
) -> dict[str, Any]:
    """唯讀彙總快取統計資料（支援 query_only=ON 連線）。

    回傳：
        {
            "hit": int,
            "miss": int,
            "total": int,
            "hit_rate": float | None,
            "top_miss_keywords": [{"keyword": str, "count": int}, ...]
        }
    """
    conditions: list[str] = []
    params: list[Any] = []

    if clinic_id is not None:
        conditions.append("clinic_id = ?")
        params.append(clinic_id)
    if since_date is not None:
        conditions.append("stat_date >= ?")
        params.append(since_date)

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    cursor = conn.cursor()

    # 1. 查詢 hit 與 miss 總計
    counts_sql = f"""
        SELECT outcome, SUM(count)
        FROM cache_stats
        {where_clause}
        GROUP BY outcome
    """
    cursor.execute(counts_sql, params)

    hit_count = 0
    miss_count = 0
    for outcome, total in cursor.fetchall():
        if outcome == OUTCOME_HIT:
            hit_count = total or 0
        elif outcome == OUTCOME_MISS:
            miss_count = total or 0

    total_eligible = hit_count + miss_count
    hit_rate = round(hit_count / total_eligible, 4) if total_eligible > 0 else None

    # 2. 查詢未命中關鍵字熱門排行
    kw_conditions = list(conditions)
    kw_params = list(params)
    kw_conditions.append("outcome = ?")
    kw_params.append(OUTCOME_MISS_KEYWORD)

    kw_where = f" WHERE {' AND '.join(kw_conditions)}"
    top_kw_sql = f"""
        SELECT keyword, SUM(count) as total_cnt
        FROM cache_stats
        {kw_where}
        GROUP BY keyword
        ORDER BY total_cnt DESC, keyword ASC
        LIMIT ?
    """
    kw_params.append(top_n)
    cursor.execute(top_kw_sql, kw_params)

    top_miss_keywords = [
        {"keyword": row[0], "count": row[1]}
        for row in cursor.fetchall()
    ]

    return {
        "hit": hit_count,
        "miss": miss_count,
        "total": total_eligible,
        "hit_rate": hit_rate,
        "top_miss_keywords": top_miss_keywords,
    }
