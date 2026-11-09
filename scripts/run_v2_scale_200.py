#!/usr/bin/env python3
"""
scripts/run_v2_scale_200.py

48 小時 200 筆動畫規模化升級與生成腳本：
1. 依據 data/visual/nhi200_v2_manifest.json 依序處理 200 筆衛教動畫。
2. 前 88 筆既有資產升級 V2：保留既有 ID 與 topic_key，更新 24 秒 IR，遞增 content_version，review_status='pending'。
3. 後 112 筆專科疾病新建 V2：寫入資料庫，review_status='pending'。
4. Teacher-Student 雙引擎：
   - DeepSeek 提煉專科解剖結構與病理事實卡（< 2s，極低消耗）
   - 本地 8080 Ornith-35B 本地編譯 24 秒 IR（< 2s，零 API 成本）
   - 內建自癒校驗與長度截斷雙模自動降級
5. 支援 --night-wait（自動等待至 00:30 離峰半價時段開始運行）、--resume（斷點續跑）、--limit、--allow-daytime。
"""

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import sys
import time as time_mod

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.pageindex.deepseek_client import call_deepseek
from src.visual.blueprints import BLUEPRINTS
from src.visual.ir import validate_ir
from scripts.generate_nhi200_visual_batch import (
    extract_anatomy_fact_sheet_deepseek,
    compile_visual_ir_local,
    post_process_self_heal,
    map_disease_to_blueprint_archetype
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("v2_scale_200")

MANIFEST_PATH = ROOT / "data" / "visual" / "nhi200_v2_manifest.json"
DB_PATH = ROOT / "clinic.db"


def backup_database(db_path: Path = DB_PATH) -> Path:
    """自動備份資料庫快照。"""
    if not db_path.exists():
        return db_path
    ts = int(time_mod.time())
    bak_path = db_path.with_name(f"{db_path.name}.bak-{ts}")
    shutil.copy2(db_path, bak_path)
    logger.info("📦 資料庫已備份至：%s", bak_path)
    return bak_path


def is_nighttime() -> bool:
    """判斷當前是否處於 DeepSeek 優惠時段 (00:30 ~ 08:30)。"""
    now = datetime.now().time()
    return time(0, 30) <= now <= time(8, 30)


def wait_until_nighttime():
    """等待直到今晚或明晨 00:30。"""
    now = datetime.now()
    target = now.replace(hour=0, minute=30, second=0, microsecond=0)
    if now.time() > time(0, 30):
        # 如果已經過了今天的 00:30（例如現在 19:10），目標是明天的 00:30
        target += timedelta(days=1)

    wait_seconds = (target - now).total_seconds()
    logger.info("⏳ 目前時間：%s，目標夜間優惠時段：%s", now.strftime("%Y-%m-%d %H:%M:%S"), target.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("⏳ 預計等待 %.1f 分鐘（%.0f 秒）後自動開始執行...", wait_seconds / 60, wait_seconds)

    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            break
        sleep_chunk = min(remaining, 60)
        time_mod.sleep(sleep_chunk)
        if int(remaining) % 600 == 0 or remaining < 120:
            logger.info("⏳ 等待夜間時段中，尚餘 %.1f 分鐘...", remaining / 60)

    logger.info("🌙 夜間離峰半價時段已到達！立即啟動 200 筆批次生成！")


def upsert_v2_asset(conn: sqlite3.Connection, item: dict, ir_data: dict) -> int:
    """寫入或升級資產至資料庫。"""
    cur = conn.cursor()
    topic_key = item["topic_key"]
    title = item["title"]
    clinic_id = item.get("clinic_id", "3503190424")
    keywords_json = json.dumps(item.get("keywords", []), ensure_ascii=False)
    ir_json = json.dumps(ir_data, ensure_ascii=False)

    existing = cur.execute(
        "SELECT id, content_version FROM visual_assets WHERE topic_key = ?", (topic_key,)
    ).fetchone()

    if existing:
        asset_id, old_ver = existing
        new_ver = (old_ver or 1) + 1
        cur.execute(
            """
            UPDATE visual_assets
            SET title = ?, clinic_id = ?, keywords = ?, ir_json = ?,
                content_version = ?, review_status = 'pending',
                source_type = 'llm_generated', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title, clinic_id, keywords_json, ir_json, new_ver, asset_id)
        )
        conn.commit()
        return asset_id
    else:
        cur.execute(
            """
            INSERT INTO visual_assets (clinic_id, topic_key, title, keywords, ir_json, source_type, review_status, content_version)
            VALUES (?, ?, ?, ?, ?, 'llm_generated', 'pending', 1)
            """,
            (clinic_id, topic_key, title, keywords_json, ir_json)
        )
        conn.commit()
        return cur.lastrowid


def run_v2_batch(
    manifest_path: Path = MANIFEST_PATH,
    limit: int | None = None,
    offset: int = 0,
    allow_daytime: bool = False,
    night_wait: bool = False,
    resume: bool = False,
    dry_run: bool = False
):
    if not manifest_path.exists():
        logger.error("找不到清單檔案：%s，請先執行 build_nhi200_v2_manifest.py", manifest_path)
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 檢查夜間優惠時段
    if not allow_daytime and not is_nighttime():
        if night_wait:
            wait_until_nighttime()
        else:
            logger.error("❌ 目前非 DeepSeek 夜間優惠時段 (00:30 ~ 08:30)！")
            logger.info("💡 請使用 --night-wait 讓腳本自動等待至 00:30，或在測試時帶入 --allow-daytime。")
            sys.exit(2)

    total_items = len(manifest)
    selected_items = manifest[offset : (offset + limit) if limit else total_items]
    logger.info("📋 載入任務清單：%d 筆（處理區間 %d ~ %d）", total_items, offset + 1, offset + len(selected_items))

    if dry_run:
        logger.info("🔍 [Dry Run] 預覽即將處理的任務：")
        for item in selected_items[:10]:
            print(f"  #{item['index']}: {item['title']} ({item['topic_key']}) | V2升級: {item['is_v2_upgrade']}")
        if len(selected_items) > 10:
            print(f"  ... 尚有 {len(selected_items) - 10} 筆")
        return

    backup_database(DB_PATH)
    conn = sqlite3.connect(DB_PATH)

    success_count = 0
    fail_count = 0
    t0 = time_mod.time()

    for idx, item in enumerate(selected_items, start=1):
        num = item["index"]
        t_key = item["topic_key"]
        t_title = item["title"]
        is_upgrade = item.get("is_v2_upgrade", False)

        # 斷點續跑：檢查是否已有審核通過或已升級為 V2
        if resume:
            cur = conn.cursor()
            existing = cur.execute(
                "SELECT content_version, ir_json FROM visual_assets WHERE topic_key = ?", (t_key,)
            ).fetchone()
            if existing:
                c_ver, raw_ir = existing
                if is_upgrade and c_ver and c_ver >= 2:
                    logger.info("⏩ [#%d/%d] 跳過已升級 V2: %s (v%d)", num, total_items, t_title, c_ver)
                    continue
                elif not is_upgrade and raw_ir:
                    logger.info("⏩ [#%d/%d] 跳過已生成資產: %s", num, total_items, t_title)
                    continue

        logger.info("▶️ [#%d/%d] 開始生成【%s】(%s)...", num, total_items, t_title, "V2升級" if is_upgrade else "新建")
        st_start = time_mod.time()

        try:
            # 確保 name 欄位存在
            if "name" not in item:
                item["name"] = item.get("disease_name", "")

            # 取得原型骨架
            archetype = map_disease_to_blueprint_archetype(item)

            # Step 1: DeepSeek 提煉專科解剖結構與三幕事實卡
            fact_sheet = extract_anatomy_fact_sheet_deepseek(item, archetype)
            logger.info("   [1/3] 解剖部位: %s | 病理機轉: %s", fact_sheet.get("anatomy_target") or fact_sheet.get("organ_label"), fact_sheet.get("lesion_type") or fact_sheet.get("lesion_label"))

            # Step 2: 本地 8080 Ornith-35B 編譯 24 秒 IR (失敗時自動降級回退 DeepSeek)
            raw_ir = compile_visual_ir_local(item, archetype, fact_sheet)
            if not raw_ir:
                raise ValueError("LLM 編譯回傳空 IR")

            # Step 3: 自癒校驗 (24s、純繁中、零阿拉伯數字、無價格、免責聲明)
            clean_ir = post_process_self_heal(raw_ir, archetype, item)
            ok, code = validate_ir(clean_ir)
            if not ok:
                raise ValueError(f"IR 自癒後校驗仍未通過: [{code}]")

            # Step 4: 寫入資料庫
            asset_id = upsert_v2_asset(conn, item, clean_ir)
            cost_s = time_mod.time() - st_start
            logger.info("   ✅ [#%d/%d] 成功入庫 Asset #%d (%s) 耗時: %.2fs", num, total_items, asset_id, t_title, cost_s)
            success_count += 1

        except Exception as e:
            logger.error("   ❌ [#%d/%d] 生成失敗: %s: %s", num, total_items, t_title, e, exc_info=True)
            fail_count += 1

        # 友善微延遲 0.2s 釋放 GPU 與事件循環
        time_mod.sleep(0.2)

    conn.close()
    elapsed = time_mod.time() - t0
    logger.info("🎉 批次完成！成功: %d 筆, 失敗: %d 筆, 總耗時: %.1fs (平均 %.2fs/筆)",
                success_count, fail_count, elapsed, elapsed / max(1, success_count))


def main():
    parser = argparse.ArgumentParser(description="48小時 200 筆衛教動畫 V2 規模化升級與批次生成")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH, help="任務清單路徑")
    parser.add_argument("--limit", type=int, default=None, help="處理上限筆數")
    parser.add_argument("--offset", type=int, default=0, help="起始筆數偏移")
    parser.add_argument("--allow-daytime", action="store_true", help="強制在日間執行（測試用）")
    parser.add_argument("--night-wait", action="store_true", help="自動倒數等待至 00:30 夜間優惠時段開始運行")
    parser.add_argument("--resume", action="store_true", help="斷點續跑（跳過已升級/已存在的資產）")
    parser.add_argument("--dry-run", action="store_true", help="僅預覽任務清單不執行生成")
    args = parser.parse_args()

    run_v2_batch(
        manifest_path=args.manifest,
        limit=args.limit,
        offset=args.offset,
        allow_daytime=args.allow_daytime,
        night_wait=args.night_wait,
        resume=args.resume,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
