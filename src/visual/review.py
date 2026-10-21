"""
視覺解說卡審核與對外可見查詢模組 (review)。
Phase 29: P29-SCHEMA, P29-REVIEW, P29-SERVE

設計原則：
- 醫師審核閘門：資產對外可見性受 review_status 嚴格管制，僅 approved 狀態且再次通過 validate_ir 者對外可見。
- 雙重竄改防護：
  1. set_review_status 核准前重新驗證 ir_json，不合格者拒絕核准。
  2. visible_assets 對外輸出前逐筆重新驗證 ir_json，不合格者略過不外洩。
- Fail-Closed：若資料表不存在，查詢安全回傳空清單，審核操作拋出 RuntimeError。
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3
from typing import Any, Optional

from .blueprints import BLUEPRINTS, merge_defaults
from .ir import validate_ir
from .writer import has_visual_assets_table, upsert_assets

VALID_REVIEW_STATUSES = ("pending", "approved", "rejected")

DEFAULT_DURATIONS = {
    "process_diagram": 8,
    "contrast": 9,
    "timeline": 7,
    "skin_energy": 8,
    "laser_action": 8,
    "neuromuscular": 8,
    "dermal_support": 8,
}


def visual_general_topic_key(clinic_id: str, topic_key: str) -> str:
    """計算診所專屬 topic_key 昇華為一般醫學共用 topic_key 時的去前綴結果。

    'tree-<clinic>-<slug>' -> 'tree-<slug>'；'<clinic>-<slug>' -> '<slug>'；其餘原樣保留。
    """
    for prefix, head in ((f"tree-{clinic_id}-", "tree-"), (f"{clinic_id}-", "")):
        if topic_key.startswith(prefix) and len(topic_key) > len(prefix):
            return head + topic_key[len(prefix):]
    return topic_key


def promote_visual_row(
    conn: sqlite3.Connection,
    *,
    clinic_id: str,
    topic_key: str,
    title: str,
    keywords_json: str,
    ir_json: str,
    source_type: str,
    metadata: Optional[str],
) -> dict[str, Any]:
    """將已核准之診所專屬視覺資產昇華為一般醫學共用資產（clinic_id IS NULL，approved）。

    占位規則（只新增或更新同一診所先前昇華的列，絕不覆寫他人內容）：
    - 一般醫學列不存在：新增。
    - 一般醫學列存在，且其 metadata.promoted_from_clinic_id 等於本診所：增量更新。
    - 其餘（一般醫學原生內容，或他診所已佔用）：略過並回報 general_slot_occupied。

    內容變更時 upsert_assets 會先重置為 pending，本函式隨即將其核准。
    驗證失敗時 upsert_assets 拋出 ValueError，由呼叫端決定整體回滾（Fail-Closed）。
    """
    general_key = visual_general_topic_key(clinic_id, topic_key)
    cur = conn.cursor()
    cur.execute(
        "SELECT metadata FROM visual_assets WHERE clinic_id IS NULL AND topic_key = ?",
        (general_key,),
    )
    existing = cur.fetchone()
    if existing is not None:
        try:
            occ_meta = json.loads(existing[0]) if existing[0] else {}
        except Exception:
            occ_meta = {}
        occupant = occ_meta.get("promoted_from_clinic_id") if isinstance(occ_meta, dict) else None
        if occupant != clinic_id:
            return {"status": "skipped", "reason": "general_slot_occupied", "topic_key": general_key}

    ir = json.loads(ir_json)
    ir["topic_key"] = general_key
    keywords = json.loads(keywords_json)

    meta: dict[str, Any] = {}
    try:
        parsed = json.loads(metadata) if metadata else {}
        if isinstance(parsed, dict):
            meta.update(parsed)
    except Exception:
        pass
    meta["promoted_from_clinic_id"] = clinic_id

    upsert_assets(
        conn,
        [{
            "clinic_id": None,
            "topic_key": general_key,
            "title": title,
            "keywords": keywords,
            "ir": ir,
            "metadata": meta,
        }],
        source_type=source_type,
        commit=False,
    )
    # 診所已核准即視為一般醫學已核准（不再重複審核）；呼叫的是一般醫學列，不會遞迴昇華
    set_review_status(conn, general_key, "approved", commit=False, clinic_id=None)
    return {"status": "inserted" if existing is None else "updated", "topic_key": general_key}


def set_review_status(
    conn: sqlite3.Connection,
    topic_key: str,
    status: str,
    commit: bool = True,
    *,
    clinic_id: Optional[str] = None,
    asset_id: Optional[int] = None,
) -> dict[str, Any]:
    """變更指定視覺資產之審核狀態。

    參數：
        conn: SQLite 資料庫連線
        topic_key: 資產主題鍵名
        status: 'pending' | 'approved' | 'rejected'
        commit: 是否自動提交交易
        clinic_id: 診所代碼（選填，預設 None 為一般醫學）
        asset_id: 資料表主鍵 id（選填，若提供則優先以 id 鎖定）

    回傳：
        {"status": "ok", "review_status": status}
        或 {"status": "not_found"}
        或 {"status": "validation_failed", "code": code}
    """
    if status not in VALID_REVIEW_STATUSES:
        raise ValueError(f"無效的 review_status: '{status}'，合法值為 {VALID_REVIEW_STATUSES}")

    if not has_visual_assets_table(conn):
        raise RuntimeError("資料庫尚未建立 visual_assets 資料表，請先執行 scripts/migrate_visual_assets.py 遷移腳本。")

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(visual_assets)")
    has_clinic_col = "clinic_id" in [row[1] for row in cur.fetchall()]

    if asset_id is not None:
        cur.execute("SELECT ir_json FROM visual_assets WHERE id = ?", (asset_id,))
    elif has_clinic_col:
        cur.execute(
            "SELECT ir_json FROM visual_assets WHERE clinic_id IS ? AND topic_key = ?",
            (clinic_id, topic_key),
        )
    else:
        cur.execute("SELECT ir_json FROM visual_assets WHERE topic_key = ?", (topic_key,))

    row = cur.fetchone()
    if row is None:
        return {"status": "not_found"}

    ir_json_str = row[0]

    # 若欲核准，必須先重跑 validate_ir 確保內容合規（防直接修改資料庫後的非法發布）
    if status == "approved":
        try:
            ir = json.loads(ir_json_str)
        except Exception:
            return {"status": "validation_failed", "code": "schema_error"}

        ok, code = validate_ir(ir)
        if not ok:
            return {"status": "validation_failed", "code": code}

    if asset_id is not None:
        where_clause = "WHERE id = ?"
        where_params: tuple[Any, ...] = (asset_id,)
    elif has_clinic_col:
        where_clause = "WHERE clinic_id IS ? AND topic_key = ?"
        where_params = (clinic_id, topic_key)
    else:
        where_clause = "WHERE topic_key = ?"
        where_params = (topic_key,)

    if status == "approved":
        cur.execute(
            f"""
            UPDATE visual_assets
            SET review_status = 'approved',
                reviewed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            {where_clause}
            """,
            where_params,
        )
    elif status == "rejected":
        cur.execute(
            f"""
            UPDATE visual_assets
            SET review_status = 'rejected',
                reviewed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            {where_clause}
            """,
            where_params,
        )
    else:  # pending
        cur.execute(
            f"""
            UPDATE visual_assets
            SET review_status = 'pending',
                reviewed_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            {where_clause}
            """,
            where_params,
        )

    # 診所專屬資產核准時，自動昇華為一般醫學共用資產（同一交易，失敗則整體回滾）
    promotion: Optional[dict[str, Any]] = None
    if status == "approved" and has_clinic_col:
        cur.execute(
            f"SELECT clinic_id, topic_key, title, keywords, ir_json, source_type, metadata FROM visual_assets {where_clause}",
            where_params,
        )
        srow = cur.fetchone()
        if srow is not None and srow[0] is not None:
            promotion = promote_visual_row(
                conn,
                clinic_id=srow[0],
                topic_key=srow[1],
                title=srow[2],
                keywords_json=srow[3],
                ir_json=srow[4],
                source_type=srow[5],
                metadata=srow[6],
            )

    if commit:
        conn.commit()

    result: dict[str, Any] = {"status": "ok", "review_status": status}
    if promotion is not None:
        result["promotion"] = promotion
    return result


def visible_assets(
    conn: sqlite3.Connection,
    clinic_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """查詢所有對外可見（review_status='approved'）之視覺解說卡資產。

    參數：
        conn: SQLite 資料庫連線
        clinic_id: 診所代碼。若為 None（一般醫學模式），回傳所有已核准資產（一般醫學共用
                   與各診所已核准資產，Phase 32 聯邦保底）；若有值，只回傳該診所專屬
                   與一般醫學已核准資產，絕不外洩他院專屬資產。

    安全防護：
    - 缺表時安全回傳空清單（Fail-Closed）。
    - 輸出前逐筆由 Python 執行 validate_ir 檢驗，遭竄改之非法資產自動略過不外露。
    - 指定 clinic_id 時，Python 層再次檢查 row_clinic_id in (clinic_id, None)。
    """
    if not has_visual_assets_table(conn):
        return []

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(visual_assets)")
    cols = [r[1] for r in cur.fetchall()]
    has_clinic_col = "clinic_id" in cols

    if has_clinic_col:
        if clinic_id is None:
            cur.execute(
                """
                SELECT id, topic_key, title, keywords, ir_json, source_type,
                       review_status, reviewed_at, content_version, metadata,
                       created_at, updated_at, clinic_id
                FROM visual_assets
                WHERE review_status = 'approved'
                ORDER BY id ASC
                """
            )
        else:
            cur.execute(
                """
                SELECT id, topic_key, title, keywords, ir_json, source_type,
                       review_status, reviewed_at, content_version, metadata,
                       created_at, updated_at, clinic_id
                FROM visual_assets
                WHERE review_status = 'approved' AND (clinic_id = ? OR clinic_id IS NULL)
                ORDER BY id ASC
                """,
                (clinic_id,),
            )
    else:
        cur.execute(
            """
            SELECT id, topic_key, title, keywords, ir_json, source_type,
                   review_status, reviewed_at, content_version, metadata,
                   created_at, updated_at
            FROM visual_assets
            WHERE review_status = 'approved'
            ORDER BY id ASC
            """
        )

    rows = cur.fetchall()

    result: list[dict[str, Any]] = []
    for r in rows:
        row_clinic_id = r[12] if has_clinic_col else None

        # Python 層檢核診所範圍防護：
        # - 一般醫學 (clinic_id is None)：所有已核准資產（含一般醫學與各診所昇華資產）皆可見
        # - 診所專屬 (clinic_id is not None)：僅該診所專屬及一般醫學資產可見，絕不外洩他院資產
        if clinic_id is not None and row_clinic_id not in (clinic_id, None):
            continue

        raw_ir = r[4]
        try:
            ir = json.loads(raw_ir)
        except Exception:
            continue

        # 輸出防線：重新檢驗 IR
        ok, _ = validate_ir(ir)
        if not ok:
            continue

        try:
            kw = json.loads(r[3])
        except Exception:
            kw = []

        result.append({
            "id": r[0],
            "clinic_id": row_clinic_id,
            "topic_key": r[1],
            "title": r[2],
            "keywords": kw,
            "ir": ir,
            "source_type": r[5],
            "review_status": r[6],
            "reviewed_at": r[7],
            "content_version": r[8],
            "metadata": r[9],
            "created_at": r[10],
            "updated_at": r[11],
        })

    return result


def _format_visual_asset_row(r: tuple[Any, ...], has_clinic_col: bool) -> dict[str, Any]:
    """格式化資料庫單列為包含即時驗證與 merge_defaults 預覽場景之字典。"""
    row_clinic_id = r[12] if has_clinic_col and len(r) > 12 else None
    raw_ir = r[4]
    try:
        ir = json.loads(raw_ir) if isinstance(raw_ir, str) else (raw_ir or {})
    except Exception:
        ir = {}

    ok, code = validate_ir(ir)

    try:
        kw = json.loads(r[3]) if isinstance(r[3], str) else (r[3] or [])
    except Exception:
        kw = []

    # 補齊 scenes 的 params 與 duration_sec
    formatted_scenes: list[dict[str, Any]] = []
    for sc in ir.get("scenes", []):
        if not isinstance(sc, dict):
            continue
        bp = sc.get("blueprint", "")
        raw_params = sc.get("params") if isinstance(sc.get("params"), dict) else None
        if bp in BLUEPRINTS:
            full_params = merge_defaults(bp, raw_params)
        else:
            full_params = raw_params or {}

        dur = sc.get("duration_sec")
        if dur is None or not isinstance(dur, int) or isinstance(dur, bool) or not (4 <= dur <= 12):
            dur = DEFAULT_DURATIONS.get(bp, 8)

        raw_labels = sc.get("labels", [])
        shaped_labels = [
            {
                "text": str(lb.get("text", "")),
                "tone": str(lb.get("tone", "neutral")),
            }
            for lb in raw_labels
            if isinstance(lb, dict)
        ]

        formatted_scenes.append({
            "blueprint": bp,
            "title": str(sc.get("title", "")),
            "caption": str(sc.get("caption", "")),
            "labels": shaped_labels,
            "params": full_params,
            "duration_sec": dur,
        })

    return {
        "id": r[0],
        "clinic_id": row_clinic_id,
        "topic_key": r[1],
        "title": r[2],
        "keywords": kw,
        "ir": ir,
        "scenes": formatted_scenes,
        "validation": {"ok": ok, "code": code},
        "source_type": r[5],
        "review_status": r[6],
        "reviewed_at": r[7],
        "content_version": r[8],
        "metadata": r[9],
        "created_at": r[10],
        "updated_at": r[11],
    }


def get_visual_asset_by_id(
    conn: sqlite3.Connection,
    asset_id: int,
) -> dict[str, Any] | None:
    """依主鍵 id 取得單筆格式化後之視覺資產詳情。"""
    if not has_visual_assets_table(conn):
        return None

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(visual_assets)")
    cols = [r[1] for r in cur.fetchall()]
    has_clinic_col = "clinic_id" in cols

    clinic_select = ", clinic_id" if has_clinic_col else ""
    cur.execute(
        f"""
        SELECT id, topic_key, title, keywords, ir_json, source_type,
               review_status, reviewed_at, content_version, metadata,
               created_at, updated_at{clinic_select}
        FROM visual_assets
        WHERE id = ?
        """,
        (asset_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None

    return _format_visual_asset_row(row, has_clinic_col)


def list_visual_assets(
    conn: sqlite3.Connection,
    *,
    status: Optional[str] = "pending",
    clinic_id: Optional[str] = None,
    scope: str = "all",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """查詢管理端視覺資產列表與總數。"""
    if not has_visual_assets_table(conn):
        return [], 0

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(visual_assets)")
    cols = [r[1] for r in cur.fetchall()]
    has_clinic_col = "clinic_id" in cols

    where_clauses: list[str] = []
    params: list[Any] = []

    if status is not None and status != "all":
        where_clauses.append("review_status = ?")
        params.append(status)

    cid = (clinic_id or "").strip() if clinic_id is not None else None
    if not cid:
        cid = None

    if has_clinic_col:
        if scope == "general":
            where_clauses.append("clinic_id IS NULL")
        elif scope == "clinic":
            if cid:
                where_clauses.append("clinic_id = ?")
                params.append(cid)
            else:
                where_clauses.append("clinic_id IS NOT NULL")
        elif scope == "all":
            if cid:
                where_clauses.append("(clinic_id = ? OR clinic_id IS NULL)")
                params.append(cid)

    where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # 計算總數
    count_sql = f"SELECT COUNT(*) FROM visual_assets {where_str}"
    cur.execute(count_sql, tuple(params))
    total = cur.fetchone()[0]

    # 查詢清單
    clinic_select = ", clinic_id" if has_clinic_col else ""
    select_sql = f"""
        SELECT id, topic_key, title, keywords, ir_json, source_type,
               review_status, reviewed_at, content_version, metadata,
               created_at, updated_at{clinic_select}
        FROM visual_assets
        {where_str}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """
    select_params = list(params) + [limit, offset]
    cur.execute(select_sql, tuple(select_params))
    rows = cur.fetchall()

    items = [_format_visual_asset_row(r, has_clinic_col) for r in rows]
    return items, total


def update_visual_asset_by_id(
    conn: sqlite3.Connection,
    asset_id: int,
    *,
    title: Optional[str] = None,
    keywords: Optional[list[str]] = None,
    scenes: Optional[list[Any]] = None,
    commit: bool = True,
) -> dict[str, Any] | None:
    """管理端修訂視覺資產內容。

    修訂後強制重驗 validate_ir 與零阿拉伯數字檢查。
    若內容有實質變更，自動重置 review_status='pending'、reviewed_at=NULL、content_version+1。
    """
    if not has_visual_assets_table(conn):
        return None

    cur = conn.cursor()
    cur.execute("SELECT title, keywords, ir_json FROM visual_assets WHERE id = ?", (asset_id,))
    row = cur.fetchone()
    if row is None:
        return None

    old_title = row[0]
    try:
        old_keywords = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or [])
    except Exception:
        old_keywords = []

    try:
        current_ir = json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})
    except Exception:
        current_ir = {}

    new_ir = copy.deepcopy(current_ir)

    # 1. 處理 title
    if title is not None:
        new_title = title.strip()
        if re.search(r"\d", new_title):
            raise ValueError("forbidden_phrase")
        new_ir["title"] = new_title
    else:
        new_title = old_title

    # 2. 處理 keywords
    if keywords is not None:
        new_keywords = [str(k).strip() for k in keywords if str(k).strip()]
        for kw in new_keywords:
            if re.search(r"\d", kw):
                raise ValueError("forbidden_phrase")
        new_ir["keywords"] = new_keywords
    else:
        new_keywords = old_keywords

    # 3. 處理 scenes
    if scenes is not None:
        orig_scenes = new_ir.get("scenes", [])
        if len(scenes) > len(orig_scenes):
            raise ValueError("schema_error")
        for idx, sc_update in enumerate(scenes):
            if hasattr(sc_update, "model_dump"):
                data = sc_update.model_dump(exclude_unset=True)
            elif isinstance(sc_update, dict):
                data = sc_update
            else:
                data = {}

            if "title" in data and data["title"] is not None:
                orig_scenes[idx]["title"] = str(data["title"]).strip()
            if "caption" in data and data["caption"] is not None:
                orig_scenes[idx]["caption"] = str(data["caption"]).strip()
            if "labels" in data and data["labels"] is not None:
                orig_scenes[idx]["labels"] = data["labels"]
            if "params" in data and data["params"] is not None:
                orig_scenes[idx]["params"] = data["params"]

        new_ir["scenes"] = orig_scenes

    # 檢查所有場景之文字是否包含阿拉伯數字
    for sc in new_ir.get("scenes", []):
        if not isinstance(sc, dict):
            continue
        if re.search(r"\d", str(sc.get("title", ""))):
            raise ValueError("forbidden_phrase")
        if re.search(r"\d", str(sc.get("caption", ""))):
            raise ValueError("forbidden_phrase")
        for lb in sc.get("labels", []):
            if isinstance(lb, dict) and re.search(r"\d", str(lb.get("text", ""))):
                raise ValueError("forbidden_phrase")

    # 4. 驗證完整 IR
    ok, code = validate_ir(new_ir)
    if not ok:
        raise ValueError(code)

    # 5. 比對實質變更
    changed = (new_title != old_title) or (new_keywords != old_keywords) or (new_ir != current_ir)
    if changed:
        cur.execute(
            """
            UPDATE visual_assets
            SET title = ?,
                keywords = ?,
                ir_json = ?,
                review_status = 'pending',
                reviewed_at = NULL,
                content_version = content_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                new_title,
                json.dumps(new_keywords, ensure_ascii=False),
                json.dumps(new_ir, ensure_ascii=False),
                asset_id,
            ),
        )
        if commit:
            conn.commit()

    return get_visual_asset_by_id(conn, asset_id)
