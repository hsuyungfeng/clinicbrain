"""診所高頻診斷碼 (ICD-10-CM) 擷取、統計排行與健保 1–400 目錄對齊模組。

支援雙來源輸入：
1. 診所去識別化 `soap_records`（擷取 `assessment` 與 `raw_text` 中之標準 ICD-10-CM 碼）
2. 外部同步匯入之聚合頻率清單（list[dict]，僅含代碼、次數與可選描述）

設計原則：
- 嚴格唯讀與隱私保護：僅統計並輸出聚合代碼與次數，絕不保留病患個資。
- 容錯對齊：`nhi_catalog_1_400` 優先精確比對 `icd10`，次之比對 3 碼大類前綴，最後退回名稱關鍵字檢索。
- FTS5 中文查詢遵守 3+ 字 `MATCH`、短詞 `LIKE ... ESCAPE '\'` 規範。
"""

from __future__ import annotations

from collections import Counter
import json
import re
import sqlite3
from typing import Any, Optional, Sequence

from src.query.nhi_index import search_nhi_catalog
from src.query.search import escape_like

# 標準 ICD-10-CM 代碼格式（首碼 A-T 或 V-Z，第 2-3 碼為數字或數字+字母，可選小數點後 1-4 碼）
# 注意：排除純英文字或常見非診斷縮寫（如 COVID19 / SOAP 等不含標準結構）
_ICD10_RE = re.compile(
    r"(?<![A-Z0-9])([A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?)(?![A-Z0-9])",
    re.IGNORECASE,
)

# 常見非 ICD-10 干擾代碼黑名單（例如維生素、分期等）
_NON_ICD_EXCLUSIONS = frozenset({"B12", "B1", "B2", "B6", "C19", "T1", "T2", "T3", "T4"})

_SPLIT_CODES_RE = re.compile(r"[,;/\s]+")


def extract_icd10_codes(text: str) -> list[str]:
    """從病歷或診斷文字擷取去重並大寫正規化之 ICD-10-CM 代碼清單。"""
    if not text or not isinstance(text, str):
        return []

    seen: set[str] = set()
    codes: list[str] = []
    for match in _ICD10_RE.finditer(text):
        code = match.group(1).upper()
        if code in _NON_ICD_EXCLUSIONS:
            continue
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def rank_icd10_from_soap(
    conn: sqlite3.Connection,
    clinic_id: Optional[str] = None,
    *,
    since_days: Optional[int] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """從 `soap_records` 統計診所高頻 ICD-10-CM 診斷碼排行。

    若 `soap_records` 資料表不存在或無符合紀錄，安全回傳空清單 `[]`。
    """
    if limit <= 0 or not _table_exists(conn, "soap_records"):
        return []

    where_clauses: list[str] = []
    params: list[Any] = []
    if clinic_id and str(clinic_id).strip():
        where_clauses.append("clinic_id = ?")
        params.append(str(clinic_id).strip())
    if since_days is not None and since_days > 0:
        where_clauses.append("created_at >= datetime('now', ?)")
        params.append(f"-{int(since_days)} days")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = f"SELECT assessment, raw_text FROM soap_records {where_sql}"

    cur = conn.cursor()
    rows = cur.execute(sql, tuple(params)).fetchall()

    counts: Counter[str] = Counter()
    for assessment, raw_text in rows:
        combined = f"{assessment or ''}\n{raw_text or ''}"
        for code in extract_icd10_codes(combined):
            counts[code] += 1

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [
        {"icd10": code, "count": cnt, "label": None, "source": "soap_records"}
        for code, cnt in ranked
    ]


def rank_icd10_from_aggregated(
    items: Sequence[dict[str, Any]],
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """對外部同步匯入之去識別化聚合診斷碼清單執行驗證、合併與排行。

    items 元素格式：`{"icd10": "J06.9", "count": 18, "label": "急性上呼吸道感染"}`
    """
    if limit <= 0 or not items:
        return []

    counts: Counter[str] = Counter()
    labels: dict[str, str] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        raw_code = str(item.get("icd10") or "").strip().upper()
        extracted = extract_icd10_codes(raw_code)
        if not extracted or extracted[0] != raw_code:
            continue
        try:
            cnt = int(item.get("count", 0))
        except (TypeError, ValueError):
            continue
        if cnt <= 0:
            continue
        counts[raw_code] += cnt
        raw_label = str(item.get("label") or "").strip()
        if raw_label and raw_code not in labels:
            labels[raw_code] = raw_label

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [
        {
            "icd10": code,
            "count": cnt,
            "label": labels.get(code),
            "source": "aggregated",
        }
        for code, cnt in ranked
    ]


def _row_to_catalog_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    try:
        kw_list = json.loads(row[6]) if row[6] else []
    except Exception:
        kw_list = [row[6]] if row[6] else []
    return {
        "index_no": row[0],
        "system": row[1],
        "category": row[2],
        "disease_name": row[3],
        "catalog_icd10": row[4],
        "topic_key": row[5],
        "keywords": kw_list,
        "clinical_feature": row[7] or "",
        "visual_available": bool(row[8]),
    }


def _lookup_nhi_by_icd10(
    conn: sqlite3.Connection,
    code: str,
    label: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    cur = conn.cursor()
    select_cols = (
        "index_no, system, category, name, icd10, topic_key, "
        "keywords, clinical_feature, visual_available"
    )
    norm_code = code.strip().upper()

    # 1. 精確匹配（支援目錄中單碼或多碼分隔字串）
    rows = cur.execute(
        f"""
        SELECT {select_cols}
        FROM nhi_catalog_1_400
        WHERE icd10 IS NOT NULL AND UPPER(icd10) LIKE ? ESCAPE '\\'
        ORDER BY visual_available DESC, index_no ASC
        """,
        (f"%{escape_like(norm_code)}%",),
    ).fetchall()
    for row in rows:
        tokens = [t.strip().upper() for t in _SPLIT_CODES_RE.split(row[4] or "") if t.strip()]
        if norm_code in tokens:
            return _row_to_catalog_dict(row)

    # 2. 退回前 3 碼大類前綴比對（如 J06.9 -> J06）
    prefix = norm_code.split(".")[0][:3]
    if len(prefix) == 3:
        prefix_rows = cur.execute(
            f"""
            SELECT {select_cols}
            FROM nhi_catalog_1_400
            WHERE icd10 IS NOT NULL AND UPPER(icd10) LIKE ? ESCAPE '\\'
            ORDER BY visual_available DESC, index_no ASC
            LIMIT 1
            """,
            (f"{escape_like(prefix)}%",),
        ).fetchall()
        if prefix_rows:
            return _row_to_catalog_dict(prefix_rows[0])

    # 3. 若提供中文診斷描述，退回 nhi_index 檢索
    if label and label.strip():
        matches = search_nhi_catalog(conn, label.strip(), limit=1)
        if matches:
            m = matches[0]
            return {
                "index_no": m.get("index_no"),
                "system": m.get("system"),
                "category": m.get("category"),
                "disease_name": m.get("name"),
                "catalog_icd10": m.get("icd10"),
                "topic_key": m.get("topic_key"),
                "keywords": m.get("keywords") or [],
                "clinical_feature": m.get("clinical_feature") or "",
                "visual_available": bool(m.get("visual_available")),
            }
    return None


def align_icd10_with_nhi_catalog(
    conn: sqlite3.Connection,
    ranked_codes: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """將高頻診斷碼對齊至 `nhi_catalog_1_400` 目錄。"""
    has_catalog = _table_exists(conn, "nhi_catalog_1_400")
    results: list[dict[str, Any]] = []

    for rank_idx, entry in enumerate(ranked_codes, start=1):
        code = str(entry.get("icd10") or "").strip().upper()
        count = int(entry.get("count", 0))
        label = entry.get("label")
        matched = _lookup_nhi_by_icd10(conn, code, label=label) if (has_catalog and code) else None

        if matched is not None:
            results.append({
                "clinic_rank": rank_idx,
                "icd10": code,
                "count": count,
                "source": entry.get("source", "unknown"),
                "catalog_matched": True,
                "topic_key": matched["topic_key"],
                "disease_name": matched["disease_name"],
                "system": matched["system"],
                "clinical_feature": matched["clinical_feature"],
                "keywords": matched["keywords"],
                "visual_available": matched["visual_available"],
            })
        else:
            results.append({
                "clinic_rank": rank_idx,
                "icd10": code,
                "count": count,
                "source": entry.get("source", "unknown"),
                "catalog_matched": False,
                "topic_key": f"icd10-{code.lower().replace('.', '-')}" if code else None,
                "disease_name": label or code,
                "system": None,
                "clinical_feature": "",
                "keywords": [],
                "visual_available": False,
            })

    return results


def get_top_clinic_diseases(
    conn: sqlite3.Connection,
    clinic_id: Optional[str] = None,
    *,
    aggregated_counts: Optional[Sequence[dict[str, Any]]] = None,
    since_days: Optional[int] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """統一入口：合併 `soap_records` 與外部聚合診斷碼，排行後對齊 `nhi_catalog_1_400`。"""
    if limit <= 0:
        return []

    soap_ranked = rank_icd10_from_soap(
        conn, clinic_id=clinic_id, since_days=since_days, limit=limit * 2
    )
    agg_ranked = (
        rank_icd10_from_aggregated(aggregated_counts, limit=limit * 2)
        if aggregated_counts
        else []
    )

    merged_counts: Counter[str] = Counter()
    labels: dict[str, str] = {}
    sources: dict[str, str] = {}

    for item in soap_ranked + agg_ranked:
        code = item["icd10"]
        merged_counts[code] += item["count"]
        if item.get("label") and code not in labels:
            labels[code] = item["label"]
        sources[code] = (
            "mixed" if (code in sources and sources[code] != item["source"]) else item["source"]
        )

    combined = [
        {
            "icd10": code,
            "count": cnt,
            "label": labels.get(code),
            "source": sources[code],
        }
        for code, cnt in sorted(merged_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    ]
    return align_icd10_with_nhi_catalog(conn, combined)
