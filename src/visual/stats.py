"""
視覺解說卡匿名事件計數模組 (stats)。
Phase 29: P29-STATS

設計原則：
1. 嚴格白名單：僅接受 event ∈ {"shown", "completed"}，且 topic_key 必須存在於 visible_assets（已核准且通過再驗證之資產），
   否則回傳 False 且絕不寫入資料庫（防止透過未核准或任意字串灌入統計表）。
2. 獨立可寫連線與日聚合 UPSERT：開啟獨立 SQLite 連線，對 (topic_key, stat_date, event) 執行 count + 1 累加。
3. 零個資與全吞例外（Fail-Safe）：不接收、不記錄任何 IP、標頭或問句；任何資料庫或缺表錯誤一律全吞並回傳 False。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .review import visible_assets

VALID_VISUAL_EVENTS: tuple[str, ...] = ("shown", "completed")


def _has_visual_stats_table(conn: sqlite3.Connection) -> bool:
    """檢查資料庫是否已建立 visual_stats 資料表。"""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='visual_stats'")
    return cur.fetchone() is not None


def record_event(db_path: str | Path, topic_key: str, event: str) -> bool:
    """記錄單次視覺解說卡匿名事件至 visual_stats 表（唯一權威寫入函式）。

    參數：
        db_path: SQLite 資料庫檔案路徑
        topic_key: 視覺解說卡主題識別碼
        event: 'shown' | 'completed'

    回傳：
        True 代表成功累加寫入；False 代表事件不合法、主題未核准、缺表或發生例外。
    """
    if not isinstance(event, str) or event not in VALID_VISUAL_EVENTS:
        return False
    if not isinstance(topic_key, str) or not topic_key.strip():
        return False

    clean_topic = topic_key.strip()

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            if not _has_visual_stats_table(conn):
                return False

            # 嚴格白名單：必須對應 visible_assets 中已核准且合規的資產
            approved_topics = {
                str(item.get("topic_key", ""))
                for item in visible_assets(conn)
            }
            if clean_topic not in approved_topics:
                return False

            conn.execute(
                """
                INSERT INTO visual_stats (topic_key, stat_date, event, count)
                VALUES (?, date('now'), ?, 1)
                ON CONFLICT(topic_key, stat_date, event)
                DO UPDATE SET count = count + 1
                """,
                (clean_topic, event),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        return False
