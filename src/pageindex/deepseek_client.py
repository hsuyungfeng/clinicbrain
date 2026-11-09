#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - DeepSeek API 客戶端
Phase 39 Wave 1: 整合雲端 DeepSeek API（deepseek-chat），實作夜間優惠時段判定與本機 8080 llama-server 雙模 Fallback。

官方計費優惠：
DeepSeek 於夜間離峰時段（UTC 16:30 至 00:30，即台灣時間 00:30 至 08:30）提供半價優惠。
本模組實施夜間時段守門：批次任務預設限定於夜間優惠時段執行（除非傳入 allow_daytime=True 或 is_test=True）。
"""

import json
import os
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .llm_client import LocalLLMUnavailableError, local_llm_call

DEEPSEEK_DEFAULT_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEEPSEEK_DEFAULT_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEFAULT_MODEL = "deepseek-chat"


class DeepSeekAPIError(Exception):
    """DeepSeek API 連線、認證或服務端異常。"""


class DeepSeekDaytimeBlockedError(RuntimeError):
    """非夜間優惠時段，禁止啟動大規模生成批次（除非指定 allow_daytime=True）。"""


def is_off_peak_hours(dt: Optional[datetime] = None) -> bool:
    """
    判定指定時間（預設當前 UTC 時間）是否處於 DeepSeek 官方半價優惠時段。
    優惠區間：UTC 16:30 ~ 00:30（對應台灣時間 00:30 ~ 08:30）。
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    else:
        if dt.tzinfo is None:
            # 若無時區資訊，預設視為 UTC
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

    # 換算為當日分鐘數 (0 ~ 1439)
    current_minute = dt.hour * 60 + dt.minute
    start_minute = 16 * 60 + 30  # 16:30 UTC (990分)
    end_minute = 0 * 60 + 30     # 00:30 UTC (30分)

    # 跨午夜區間：當前分鐘 >= 16:30 或 <= 00:30 即為離峰優惠時段
    return current_minute >= start_minute or current_minute <= end_minute


def get_deepseek_api_key() -> str:
    """取得有效之 DeepSeek API 金鑰。"""
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    return key if key else DEEPSEEK_DEFAULT_KEY


def call_deepseek(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    timeout: int = 60,
    api_key: Optional[str] = None,
    allow_daytime: bool = False,
    is_test: bool = False,
    fallback_to_local: bool = True,
) -> str:
    """
    呼叫 DeepSeek API 進行結構化醫學推論與生成。

    參數：
        prompt: 輸入繁體中文提示詞。
        model: 模型名稱，預設 deepseek-chat（亦可指定 deepseek-flash）。
        temperature: 取樣溫度（醫療場景預設 0.2）。
        max_tokens: 輸出長度上限。
        timeout: 超時秒數。
        api_key: 可選明確指定 API Key，預設自環境變數或專案安全組態取得。
        allow_daytime: 若為 True，允許於非優惠日間時段執行。
        is_test: 單題測試標旗，測試時不受夜間優惠時段限制。
        fallback_to_local: 若 API 連線失敗或報錯，是否自動降級改呼叫本地 8080 llama-server。

    回傳：
        模型回覆文字內容（已濾除 reasoning 思考過程）。
    """
    # 1. 優惠時段檢查（非測試且未明確放行日間時，阻斷高成本生成）
    if not is_test and not allow_daytime and not is_off_peak_hours():
        raise DeepSeekDaytimeBlockedError(
            "目前為日間一般計費時段。為落實專案成本控制，請於夜間優惠時段（台灣時間 00:30~08:30）執行，或傳入 allow_daytime=True 強制執行。"
        )

    resolved_key = (api_key or "").strip() or get_deepseek_api_key()
    if not resolved_key:
        if fallback_to_local:
            return local_llm_call(prompt, timeout=timeout)
        raise DeepSeekAPIError("未設定 DEEPSEEK_API_KEY 且無可用之預設金鑰")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    encoded_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        DEEPSEEK_DEFAULT_ENDPOINT,
        data=encoded_data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {resolved_key}",
            "User-Agent": "clinicbrain-deepseek-client",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw_bytes = response.read()
            resp_json = json.loads(raw_bytes.decode("utf-8"))

        choices = resp_json.get("choices", [])
        if not choices:
            raise DeepSeekAPIError(f"DeepSeek 回傳格式異常，缺少 choices: {resp_json}")

        message = choices[0].get("message", {})
        content = (message.get("content") or "").strip()
        if not content:
            raise DeepSeekAPIError("DeepSeek 回傳內容為空")

        return content

    except Exception as e:
        if fallback_to_local:
            # 平滑降級至本地 8080 llama-server
            try:
                return local_llm_call(prompt, timeout=timeout)
            except Exception as local_err:
                raise DeepSeekAPIError(
                    f"DeepSeek API 失敗 ({e}) 且本機 LLM 降級亦失敗 ({local_err})"
                ) from e
        raise DeepSeekAPIError(f"呼叫 DeepSeek API 發生異常: {e}") from e
