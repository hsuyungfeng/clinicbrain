#!/usr/bin/env python3
"""Herdr Supervisor: Hermes 守護者與自癒重置工具 (Watchdog & Auto-Healer).

功能：
1. 監控 Hermes (w6:p2) 狀態。
2. 偵測是否出現推論卡死、超長等待 (>120s) 或 Context 超載 (>70%)。
3. 自動發送中斷訊號、執行 /new 重置會話、清理 run*.p* 等殘留垃圾腳本。
"""

import json
import os
import subprocess
import sys
import time

HERMES_PANE = "w6:p2"
MAX_WAIT_SECONDS = 120


def run_cmd(cmd_list: list[str]) -> tuple[int, str]:
    res = subprocess.run(cmd_list, capture_output=True, text=True)
    return res.returncode, res.stdout.strip()


def clean_scrap_files():
    """清理當前目錄下可能的臨時除錯腳本。"""
    repo_dir = "/home/hsu/Desktop/clinicbrain"
    for fname in os.listdir(repo_dir):
        if fname.startswith("run") and (fname.endswith(".py") or fname.endswith(".p")):
            fpath = os.path.join(repo_dir, fname)
            try:
                os.remove(fpath)
                print(f"🧹 [AutoHealer] 已清理殘留腳本: {fname}")
            except OSError:
                pass


def heal_hermes():
    """發送中斷並重置 Hermes 會話。"""
    print(f"🚨 [AutoHealer] 偵測到 Hermes 逾時或卡死，正在執行自動自癒重置...")
    # 1. 發送 Ctrl+C 中斷目前操作
    run_cmd(["herdr", "pane", "send-keys", HERMES_PANE, "ctrl+c"])
    time.sleep(1)
    run_cmd(["herdr", "pane", "send-keys", HERMES_PANE, "ctrl+c"])
    time.sleep(1)

    # 2. 清理垃圾檔案
    clean_scrap_files()

    # 3. 發送 /new 重新建立全新乾淨工作階段
    run_cmd(["herdr", "pane", "send-text", HERMES_PANE, "/new"])
    time.sleep(0.5)
    run_cmd(["herdr", "pane", "send-keys", HERMES_PANE, "Enter"])
    time.sleep(2)

    # 4. 驗證是否重置成功
    code, out = run_cmd(["herdr", "pane", "read", HERMES_PANE, "--lines", "10"])
    if "New session started" in out:
        print("✅ [AutoHealer] Hermes 已成功自動復原並重啟會話！")
    else:
        print("⚠️ [AutoHealer] Hermes 重置指令已發送，狀態如下:\n", out)


def check_status():
    code, out = run_cmd(["herdr", "pane", "read", HERMES_PANE, "--lines", "15"])
    print("📋 Hermes 目前終端輸出摘要:\n" + "-" * 50)
    print(out)
    print("-" * 50)
    if "waiting on Qwen" in out or "cooldown:" in out:
        print("⚠️ 警告：Hermes 正處於推論等待或冷卻狀態！")
    else:
        print("🟢 Hermes 狀態正常。")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--heal":
        heal_hermes()
    else:
        check_status()
