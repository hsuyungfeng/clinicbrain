"""模型生成共用鎖與夜間批次狀態探測模組。

設計原則：
- 本機 llama-server 為單 slot 序列推論服務，同一時間只能處理一個生成任務。
- 病人端即時組稿、AGENTS 2.24 未審一般說明、管理端單題生成、向 LLM 提問與背景補齊
  共用同一把行程內模型生成鎖 GENERATION_LOCK。
- 遇忙碌時病人端非阻塞回傳 busy，不排隊等待，避免拖垮系統。
- nightly_batch_running() 提供跨行程探測：檢驗夜間批次是否持有檔案鎖，探測後立即釋放，不長期佔用。
"""

import threading
from pathlib import Path
from typing import Any

from src.batch import db_lock

# 全系統唯一的本機 LLM 生成鎖（病人端、管理端單題生成、向 LLM 提問、背景補齊共用）
GENERATION_LOCK = threading.Lock()


def nightly_batch_running(db_path: Any) -> bool:
    """探測夜間批次是否正在執行（持有檔案鎖）。

    參數:
        db_path: SQLite 資料庫路徑（字串或 Path）。

    回傳:
        True: 夜間批次正持有鎖執行中。
        False: 檔案鎖未被持有、或路徑無效/為空/:memory:/檔案不存在。
    """
    if not db_path:
        return False

    str_path = str(db_path).strip()
    if not str_path or str_path == ":memory:":
        return False

    path_obj = Path(str_path)
    if not path_obj.exists():
        return False

    # 嘗試非阻塞取得檔案鎖
    fd = db_lock.try_acquire(path_obj)
    if fd is None:
        # 取不到鎖，代表夜間批次或其他行程正在持有
        return True

    # 成功取得代表未在執行，立即釋放不佔用
    db_lock.release(fd)
    return False
