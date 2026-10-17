#!/usr/bin/env python3
"""
scripts/probe_patient_thinking.py - 本地 LLM 思考關閉與解碼速率探測 CLI。

用途：
實機驗證 `reasoning_effort: "none"` 與 `chat_template_kwargs: {"enable_thinking": False}`
對本機 llama-server (Qwen3.8 GGUF) 是否真正生效（關閉思考），並量測實際解碼 tokens/秒。

安全防護鐵則：
1. 預設拒絕執行：必須帶 `--i-approve-live-probe` 且 `--db-copy` 必須為副本庫（禁止等於正式 clinic.db）。
2. 只讀不寫：副本資料庫嚴格以 `mode=ro` URI 開啟，腳本內無任何寫入 SQL。
3. 互斥防護：執行前檢查夜間批次鎖（db_lock），鎖被持有時立即終止退出。
4. 隱私防護：標準輸出僅印出 JSON 統計摘要與經價格屏蔽之前 40 字預覽，絕不輸出 prompt 或回覆全文。
5. 服務保護：無重啟服務、無外部程序管理。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time
import urllib.error
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 確保在 uv 獨立虛擬環境下亦能載入使用者目錄之 opencc
user_site = Path.home() / ".local/lib/python3.12/site-packages"
if user_site.exists() and str(user_site) not in sys.path:
    sys.path.append(str(user_site))

from src.batch.db_lock import release, try_acquire
from src.general.answer_compose import build_compose_prompt
from src.pageindex.llm_client import PATIENT_COMPOSE_SAMPLING
from src.query.router import mask_prices


def _get_reference_prompt(db_copy_path: Path) -> str:
    """以唯讀 URI 開啟資料庫副本，讀取第一筆已核准之 FAQ 作為組稿參考。"""
    resolved = db_copy_path.resolve()
    uri = f"file:{resolved}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT question, answer
            FROM faq_cache
            WHERE review_status = 'approved'
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row and row[0] and row[1]:
            return build_compose_prompt(query=row[0], evidence_blocks=[row[1]], intent="what")
    finally:
        conn.close()

    # 若無已核准資料，使用固定衛教題目組合成約 600 字之標準提示詞
    default_q = "皮秒雷射除斑術後注意事項有哪些？"
    default_ev = (
        "皮秒雷射療程適用於改善斑點、色素沉澱與均勻膚色。"
        "治療後局部可能出現輕微紅腫或灼熱感，此為正常暫時現象，通常於數小時至兩天內緩解。"
        "術後照護應以溫和清潔、加強保濕與嚴格防曬為原則，避免使用含酒精、果酸、美白成分之刺激性保養品。"
        "一週內請勿前往三溫暖、溫泉或高溫曝曬場所，外出請配戴防曬帽、口罩並塗抹防曬乳。"
        "若出現局部異常劇烈紅腫、化膿或體溫異常，請立即回診由專業醫師評估。"
    )
    return build_compose_prompt(query=default_q, evidence_blocks=[default_ev], intent="recovery")


def run_single_probe(
    endpoint: str,
    prompt: str,
    sampling_override: dict,
    timeout: int,
) -> dict:
    """對指定端點發送單次請求並解析性能與思考指標。"""
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        **sampling_override,
    }
    req_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=req_body,
        headers={"Content-Type": "application/json", "User-Agent": "clinicbrain-probe"},
    )

    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp_bytes = resp.read()
    elapsed = max(0.001, time.monotonic() - t0)

    data = json.loads(resp_bytes.decode("utf-8"))
    choices = data.get("choices", [])
    first_choice = choices[0] if choices else {}
    msg = first_choice.get("message", {})
    finish_reason = first_choice.get("finish_reason", "unknown")

    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""

    usage = data.get("usage", {})
    timings = data.get("timings", {})

    completion_tokens = usage.get("completion_tokens")
    if completion_tokens is None:
        completion_tokens = timings.get("predicted_n", 0)

    tokens_per_second = timings.get("predicted_per_second")
    if tokens_per_second is None:
        tokens_per_second = completion_tokens / elapsed if completion_tokens else 0.0

    preview = mask_prices(content[:40])

    return {
        "reasoning_chars": len(reasoning),
        "content_chars": len(content),
        "finish_reason": finish_reason,
        "elapsed_seconds": round(elapsed, 3),
        "completion_tokens": int(completion_tokens),
        "tokens_per_second": round(float(tokens_per_second), 2),
        "content_preview": preview,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="本地 LLM 思考關閉與解碼速率探測小工具（僅支援資料庫副本與單次探測）"
    )
    parser.add_argument(
        "--i-approve-live-probe",
        action="store_true",
        help="確認執行實機探測之必要核准旗標，未帶則拒絕執行",
    )
    parser.add_argument(
        "--db-copy",
        required=False,
        type=str,
        help="資料庫副本路徑（絕對或相對路徑，嚴禁指向正式 clinic.db）",
    )
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:8080/v1/chat/completions",
        help="llama-server completions 端點位址（預設 http://127.0.0.1:8080/v1/chat/completions）",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="單次請求超時秒數（預設 180 秒）",
    )

    args = parser.parse_args(argv)

    # 1. 旗標防護檢查
    if not args.i_approve_live_probe:
        print(
            "❌ 拒絕執行：實機探測需明確指定 `--i-approve-live-probe` 旗標以示核准。",
            file=sys.stderr,
        )
        return 2

    # 2. 資料庫副本檢查
    if not args.db_copy:
        print("❌ 拒絕執行：必須提供 `--db-copy` 資料庫副本路徑。", file=sys.stderr)
        return 2

    copy_path = Path(args.db_copy).resolve()
    if not copy_path.exists():
        print(f"❌ 拒絕執行：指定的副本檔案不存在: {copy_path}", file=sys.stderr)
        return 2

    prod_db = Path("clinic.db").resolve()
    if prod_db.exists() and copy_path == prod_db:
        print(
            "❌ 拒絕執行：`--db-copy` 路徑與專案正式資料庫 clinic.db 相同！探測嚴格禁止使用正式庫。",
            file=sys.stderr,
        )
        return 2

    # 3. 檢查夜間批次鎖
    lock_target = prod_db if prod_db.exists() else copy_path
    lock_fd = try_acquire(lock_target)
    if lock_fd is None:
        print(
            "❌ 拒絕執行：夜間批次或管理作業鎖已被持有，為避免佔用唯一推理 slot 造成排隊或逾時，已中止探測。",
            file=sys.stderr,
        )
        return 2
    release(lock_fd)

    # 4. 讀取參考資料並組裝 prompt
    try:
        prompt = _get_reference_prompt(copy_path)
    except Exception as exc:
        print(f"❌ 讀取資料庫副本參考失敗: {exc}", file=sys.stderr)
        return 2

    # 5. 三變體設定（皆基於 PATIENT_COMPOSE_SAMPLING，max_tokens 3000）
    base_sampling = {
        "temperature": PATIENT_COMPOSE_SAMPLING["temperature"],
        "dry_multiplier": PATIENT_COMPOSE_SAMPLING["dry_multiplier"],
        "repeat_penalty": PATIENT_COMPOSE_SAMPLING["repeat_penalty"],
        "max_tokens": 3000,
    }

    variants = [
        ("reasoning_effort_none", {**base_sampling, "reasoning_effort": "none"}),
        ("enable_thinking_false", {**base_sampling, "chat_template_kwargs": {"enable_thinking": False}}),
        (
            "both",
            {
                **base_sampling,
                "reasoning_effort": "none",
                "chat_template_kwargs": {"enable_thinking": False},
            },
        ),
    ]

    results = []
    for var_name, sampling in variants:
        try:
            res = run_single_probe(args.endpoint, prompt, sampling, args.timeout)
            res["variant"] = var_name
            res["status"] = "success"
            results.append(res)
        except Exception as exc:
            results.append({
                "variant": var_name,
                "status": "error",
                "error": str(exc),
            })

    output_doc = {
        "probe_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "endpoint": args.endpoint,
        "results": results,
    }
    print(json.dumps(output_doc, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
