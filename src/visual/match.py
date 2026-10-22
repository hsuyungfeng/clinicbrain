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

import re
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


def find_visual(
    conn: sqlite3.Connection,
    query: str,
    clinic_id: str | None = None,
) -> dict[str, Any] | None:
    """根據病人問句比對已核准之視覺解說卡並回傳對外安全結構。

    比對與優先級規則：
    - 呼叫 visible_assets(conn, clinic_id=clinic_id)。
    - Python 層再次防護：若 clinic_id is None，只保留 asset.get("clinic_id") is None；
      若 clinic_id 有值，只保留 asset.get("clinic_id") in (clinic_id, None)。
    - 問句與各資產 keywords 皆做 NFKC 正規化（轉小寫）。
    - 計算問句中包含的關鍵字子字串數量（hit_count）。
    - hit_count <= 0 時略過。
    - 排序優先序：
      tier 0: clinic_id 存在且 asset.get("clinic_id") == clinic_id（診所專屬）
      tier 1: 一般醫學（clinic_id is None）
      排序鍵：(tier, -hits, topic_key)
      即：診所專屬永遠優先於一般醫學；同層級比命中關鍵字數（多者優先），再比 topic_key 字典序。
    - 輸出維持 _shape_public_visual，僅含 {"topic_key", "title", "scenes"}，不含 clinic_id。
    - 缺表或任何資料庫錯誤一律回傳 None（Fail-Closed）。
    - 純 SELECT、零 logging、零 print。
    """
    if not isinstance(query, str) or not query.strip():
        return None

    try:
        norm_query = _normalize_text(query)
        if not norm_query.strip():
            return None

        assets = visible_assets(conn, clinic_id=clinic_id)
        if not assets:
            return None

        best_asset: dict[str, Any] | None = None
        best_key: tuple[int, int, str] | None = None

        for asset in assets:
            # Python 層雙重檢查診所範圍：
            # - 一般醫學 (clinic_id is None)：所有已核准資產皆可比對調用
            # - 診所專屬 (clinic_id is not None)：僅限該診所專屬或一般醫學共用資產
            asset_clinic = asset.get("clinic_id")
            if clinic_id is not None and asset_clinic not in (clinic_id, None):
                continue

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
            # 優先級：
            # 若為診所查詢：該診所專屬 (tier 0) > 原生一般醫學 (tier 1)
            # 若為一般醫學查詢：原生一般醫學 (tier 0) > 診所昇華資產 (tier 1)
            # 同 tier 比命中數 (-hits)；同分比 topic_key 字典序
            if clinic_id:
                tier = 0 if asset_clinic == clinic_id else 1
            else:
                tier = 0 if asset_clinic is None else 1
            candidate_sort_key = (tier, -hits, topic_key)

            if best_key is None or candidate_sort_key < best_key:
                best_key = candidate_sort_key
                best_asset = asset

        if best_asset is None:
            return None

        return _shape_public_visual(best_asset)
    except Exception:
        return None


_GENERAL_TOPIC_RE = re.compile(r"^tree-\d{10}-")


def visuals_for_tree_sources(
    conn: sqlite3.Connection,
    doc_ids: list[str],
    clinic_id: str | None = None,
) -> list[dict[str, Any]]:
    """依引用之推理樹 doc_id 取得已核准的視覺解說卡（每個療程最多一筆）。

    排序規則（Phase 34 / 2.32）：
    - 診所上下文：該診所專屬版優先，其次一般醫學共用版（不回傳他院版本）。
    - 一般醫學上下文：一般醫學共用版優先，其次任一已核准診所版。
    同一療程的診所版與共用版只回一筆，避免重複。純讀取；任何錯誤回傳空清單（Fail-Closed）。
    """
    from .autodraft import normalize_tree_topic_key

    try:
        assets = visible_assets(conn, clinic_id=clinic_id)
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in dict.fromkeys(d for d in doc_ids if isinstance(d, str) and d):
        try:
            tk = normalize_tree_topic_key(doc)
        except ValueError:
            continue
        general = _GENERAL_TOPIC_RE.sub("tree-", tk)
        # 無 tree- 前綴的既有動畫（如 Phase 29 骨架 autologous-fat-grafting）以療程 slug 對應；
        # FAQ 的 topic_key 即為裸 slug，必須能對到此類動畫（2.32 病患端 FAQ 對應）
        bare = tk[len("tree-"):]
        candidates = [a for a in assets if a.get("topic_key") in (tk, general, bare)]
        if not candidates:
            continue

        def _rank(a: dict[str, Any]) -> tuple[int, int]:
            is_clinic = a.get("clinic_id") is not None
            exact = 0 if a.get("topic_key") == (tk if clinic_id is not None else general) else 1
            if clinic_id is not None:
                return (0 if a.get("clinic_id") == clinic_id else 1, exact)
            return (1 if is_clinic else 0, exact)

        best = min(candidates, key=_rank)
        if general in seen:
            continue
        seen.add(general)
        out.append(_shape_public_visual(best))
    return out
