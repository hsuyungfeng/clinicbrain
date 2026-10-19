"""
視覺解說卡關鍵字比對與對外輸出整形模組 (match)。
Phase 29: P29-SERVE

設計原則：
1. 純讀取且確定性比對：僅檢索 visible_assets (已核准且通過再驗證之資產)，
   對問句與關鍵字進行 NFKC 正規化後計算子字串命中數。
2. 零儲存零日誌：問句僅於記憶體內比對，絕不儲存、絕不記錄、不進統計。
3. 最小對外暴露：僅輸出前端渲染所需之 {"topic_key", "title", "scenes"}，
   嚴格排除資料庫 id、ir_json 原文、審核欄位、metadata、keywords 等內部欄位。
4. Fail-Closed：缺表或任何資料庫/解析錯誤一律安全回傳 None。
"""

from __future__ import annotations

import sqlite3
import unicodedata
from typing import Any

from .review import visible_assets


def _normalize_text(text: str) -> str:
    """對文字執行 NFKC 正規化並轉小寫，確保相容字元與全半形一致比對。"""
    return unicodedata.normalize("NFKC", text).lower()


def _shape_public_visual(asset: dict[str, Any]) -> dict[str, Any]:
    """將內部資產結構整形為對外安全結構，移除所有內部與審核欄位。"""
    ir = asset.get("ir") or {}
    raw_scenes = ir.get("scenes") or []
    shaped_scenes: list[dict[str, Any]] = []

    for sc in raw_scenes:
        raw_labels = sc.get("labels") or []
        shaped_labels = [
            {
                "text": str(lb.get("text", "")),
                "tone": str(lb.get("tone", "neutral")),
            }
            for lb in raw_labels
            if isinstance(lb, dict)
        ]
        shaped_scenes.append(
            {
                "blueprint": str(sc.get("blueprint", "")),
                "title": str(sc.get("title", "")),
                "caption": str(sc.get("caption", "")),
                "labels": shaped_labels,
                "params": sc.get("params") if isinstance(sc.get("params"), dict) else None,
                "duration_sec": (
                    int(sc["duration_sec"])
                    if isinstance(sc.get("duration_sec"), int) and not isinstance(sc.get("duration_sec"), bool)
                    else None
                ),
            }
        )

    return {
        "topic_key": str(asset.get("topic_key", "")),
        "title": str(asset.get("title", "")),
        "scenes": shaped_scenes,
    }


def find_visual(conn: sqlite3.Connection, query: str) -> dict[str, Any] | None:
    """根據病人問句比對已核准之視覺解說卡並回傳對外安全結構。

    比對規則：
    - 問句與各資產 keywords 皆做 NFKC 正規化（轉小寫）。
    - 計算問句中包含的關鍵字子字串數量（hit_count）。
    - hit_count == 0 時回傳 None。
    - 多筆命中時取 hit_count 最高者；同分時取字典序較小的 topic_key（確定性）。
    - 缺表或任何資料庫錯誤一律回傳 None（Fail-Closed）。
    """
    if not isinstance(query, str) or not query.strip():
        return None

    try:
        norm_query = _normalize_text(query)
        if not norm_query.strip():
            return None

        assets = visible_assets(conn)
        if not assets:
            return None

        best_asset: dict[str, Any] | None = None
        best_key: tuple[int, str] | None = None

        for asset in assets:
            keywords = asset.get("keywords")
            if not isinstance(keywords, list):
                continue

            hits = 0
            for kw in keywords:
                if not isinstance(kw, str):
                    continue
                norm_kw = _normalize_text(kw).strip()
                if norm_kw and norm_kw in norm_query:
                    hits += 1

            if hits <= 0:
                continue

            topic_key = str(asset.get("topic_key", ""))
            # 排序鍵：(-hits, topic_key) 越小越優先（即 hits 越大越優先，同分取較小 topic_key）
            candidate_sort_key = (-hits, topic_key)
            if best_key is None or candidate_sort_key < best_key:
                best_key = candidate_sort_key
                best_asset = asset

        if best_asset is None:
            return None

        return _shape_public_visual(best_asset)
    except Exception:
        return None
