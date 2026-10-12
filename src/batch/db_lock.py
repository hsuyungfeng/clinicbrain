"""
資料庫層級的跨行程互斥鎖（與夜間批次共用同一把檔案鎖）。

夜間批次（scripts/run_nightly_batch.py）在獨立行程執行，持有 `<db>.nightly.lock`。
背景補齊作業位於 API 行程，若不取得同一把鎖，兩者會同時對本機 llama-server 送出請求，
server 僅 `-np 1` 一個 slot，排隊造成逾時與誤判離線。

語意：背景補齊作業開始時取得鎖、結束時釋放；夜間批次若遇到鎖被持有，依既有規則
「持鎖略過」（結束碼 0）。反向：夜間批次持鎖時，背景作業拒絕啟動（409）。
""" 

import fcntl
import os
from pathlib import Path
from typing import Optional


def nightly_lock_path(db_path) -> Path:
    """與 scripts/run_nightly_batch.py:lock_path_for 相同命名規則（測試以此確保一致）。"""
    resolved = Path(db_path).resolve()
    return resolved.with_name(f"{resolved.name}.nightly.lock")


def try_acquire(db_path) -> Optional[int]:
    """非阻塞取得鎖；成功回傳 fd（呼叫端負責 release），已被持有則回傳 None。"""
    path = nightly_lock_path(db_path)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def release(fd: Optional[int]) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
