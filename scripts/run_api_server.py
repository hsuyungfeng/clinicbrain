#!/usr/bin/env python3
"""
clinicbrain API 服務啟動入口腳本（Phase 05 TASK-04, Phase 06 AUTH-01）。
提供命令列介面（CLI）與環境變數支援，啟動 FastAPI / Uvicorn 服務。

注意：正式環境啟動前必須先設定環境變數 CLINICBRAIN_ADMIN_API_KEY。
若未設定金鑰且未指定本機開發旗標，腳本將拒絕啟動（結束碼 2）。

使用範例：
    export CLINICBRAIN_ADMIN_API_KEY="your-secret-key"
    python3 scripts/run_api_server.py
    python3 scripts/run_api_server.py --port 8000 --reload
    python3 scripts/run_api_server.py --host 0.0.0.0 --port 8080 --workers 2
    python3 scripts/run_api_server.py --allow-no-auth   # 僅限本機開發
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
from src.api.security import (
    ALLOW_NO_AUTH_ENV,
    AuthConfigError,
    build_dev_warning,
    check_auth_config,
)


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
    parser.add_argument(
        "--allow-no-auth",
        action="store_true",
        default=False,
        help="僅限本機開發：在未設定 CLINICBRAIN_ADMIN_API_KEY 時仍允許啟動（認證停用，切勿用於對外服務）",
    )
    return parser.parse_args()


def print_banner(host: str, port: int, reload: bool, workers: int):
    docs_status = f"http://{host}:{port}/docs" if config.enable_docs else "已停用 (未開放外部文件)"
    print("=" * 66)
    print(" 🏥 clinicbrain — Taiwan Clinic Medical PageIndex RAG System")
    print(f" 📍 服務監聽位址:   http://{host}:{port}")
    print(" 🏢 診所識別:       無預設診所，請求須帶 clinic_id 或 Header X-Clinic-ID")
    print(f" 🗄️  資料庫檔案:     {config.db_path} ({'存在' if config.db_path.exists() else '⚠️ 未找到，請先執行 seed 腳本'})")
    print(f" 📖 API 互動文件:   {docs_status}")
    print(f" 💓 系統健康端點:   http://{host}:{port}/health")
    print(f" ⚙️  執行模式:       {'自動重載 (Reload)' if reload else f'多核心生產模式 ({workers} workers)'}")
    print("=" * 66)


def main():
    args = parse_args()

    # 處理本機開發免認證旗標
    if args.allow_no_auth:
        config.allow_no_auth = True
        # --reload 與 workers>1 的 uvicorn 子行程只繼承環境變數，見 config 於 import 時求值
        os.environ[ALLOW_NO_AUTH_ENV] = "1"

    # 啟動前認證組態檢核（Fail-Fast）
    try:
        mode = check_auth_config()
    except AuthConfigError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(2)

    if mode == "dev_no_auth":
        print(build_dev_warning(), file=sys.stderr)

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
