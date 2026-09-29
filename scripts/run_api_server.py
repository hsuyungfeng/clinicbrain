#!/usr/bin/env python3
"""
clinicbrain API 服務啟動入口腳本（Phase 05 TASK-04）。
提供命令列介面（CLI）與環境變數支援，啟動 FastAPI / Uvicorn 服務。

使用範例：
    python3 scripts/run_api_server.py
    python3 scripts/run_api_server.py --port 8000 --reload
    python3 scripts/run_api_server.py --host 0.0.0.0 --port 8080 --workers 2
"""

import argparse
import os
import sys
from pathlib import Path

# 將專案根目錄加入 Python 模組搜尋路徑
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.config import config


def parse_args():
    parser = argparse.ArgumentParser(
        description="clinicbrain API 服務啟動器（緻妍診所 Taiwan PageIndex RAG 系統）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        type=str,
        default=config.host,
        help="服務監聽位址 (預設綁定本機 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=config.port,
        help="服務監聽連接埠",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="啟用程式碼變更自動熱重載 (開發模式)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Uvicorn Worker 數量 (生產環境可依 CPU 核心調整，但啟用 reload 時強制為 1)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="日誌輸出等級",
    )
    return parser.parse_args()


def print_banner(host: str, port: int, reload: bool, workers: int):
    docs_status = f"http://{host}:{port}/docs" if config.enable_docs else "已停用 (未開放外部文件)"
    print("=" * 66)
    print(" 🏥 clinicbrain — Taiwan Clinic Medical PageIndex RAG System")
    print(f" 📍 服務監聽位址:   http://{host}:{port}")
    print(f" 🏢 預設診所代碼:   {config.default_clinic_id} (緻妍外科診所)")
    print(f" 🗄️  資料庫檔案:     {config.db_path} ({'存在' if config.db_path.exists() else '⚠️ 未找到，請先執行 seed 腳本'})")
    print(f" 📖 API 互動文件:   {docs_status}")
    print(f" 💓 系統健康端點:   http://{host}:{port}/health")
    print(f" ⚙️  執行模式:       {'自動重載 (Reload)' if reload else f'多核心生產模式 ({workers} workers)'}")
    print("=" * 66)


def main():
    args = parse_args()

    # 更新全域組態物件
    config.host = args.host
    config.port = args.port

    import uvicorn

    print_banner(args.host, args.port, args.reload, args.workers)

    # 執行 uvicorn 服務
    if args.reload:
        uvicorn.run(
            "src.api.app:app",
            host=args.host,
            port=args.port,
            reload=True,
            log_level=args.log_level,
        )
    else:
        uvicorn.run(
            "src.api.app:app",
            host=args.host,
            port=args.port,
            workers=args.workers,
            log_level=args.log_level,
        )


if __name__ == "__main__":
    main()
