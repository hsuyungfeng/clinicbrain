#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 本地 LLM 客戶端 Adapter
Phase 02 Task 1: local LLM inference layer adapter (llama-server)

架構核心定位（見 .planning/phases/02-local-llm-layer/TASK-PLAN.md）：
- 串接本機 llama-server (llama.cpp)，監聽 http://127.0.0.1:8080
- 提供標準 local_llm_call(prompt: str, timeout: int = 90) -> str 函式，
  簽章完全符合 generate_tree() 所需之 Callable[[str], str]
- 嚴格僅使用 Python 標準庫 urllib.request，不額外依賴 requests
- 僅讀取 choices[0].message.content，嚴格忽略 reasoning_content 思考過程
- 連線失敗或逾時拋出明確之自訂例外 LocalLLMUnavailableError
"""

import json
import socket
import urllib.error
import urllib.request
from typing import Optional

LLM_ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"
MODELS_ENDPOINT = "http://127.0.0.1:8080/v1/models"
DEFAULT_MODEL_NAME = "Qwen3.8-27B-UD-Q4_K_XL"


class LocalLLMUnavailableError(Exception):
    """本地 LLM 服務未啟動、連線失敗或回應逾時。"""


class LLMEmptyOutputError(RuntimeError):
    """本地 LLM 回傳內容為空（例如思考長度耗盡 token、未完成生成等單題異常，非伺服器崩潰）。"""


class LLMTruncatedError(LLMEmptyOutputError):
    """本地 LLM 輸出達 max_tokens 被截斷，視為失敗。"""


# 忠實引用資料的任務（RAG 提問）：單次請求關閉重複懲罰並降低溫度，避免模型為了「不重複」而改字、掉字
FAITHFUL_SAMPLING = {
    "temperature": 0.1,
    "dry_multiplier": 0.0,
    "repeat_penalty": 1.0,
}

# 病人端即時組稿取樣常數：
# 依據 Phase 28 Plan 07 實機探測與複審評估（28-PROBE.md）：
# 1. chat_template_kwargs.enable_thinking=False 經實測證實能完全關閉思考（reasoning_chars=0），
#    而 reasoning_effort: "none" 無效故予以移除。
# 2. 考量真實衛教組稿（價值段 2～4 句＋追問＋警訊句）長度與防範合規長句被長度誤截斷（LLMTruncatedError），
#    max_tokens 設定為 800（於 22.5 tok/s 最壞延遲約 35.5 秒，遠低於 240 秒逾時）。使用端應以 dict(...) 複製後使用。
PATIENT_COMPOSE_SAMPLING = {
    **FAITHFUL_SAMPLING,
    "max_tokens": 800,
    "chat_template_kwargs": {"enable_thinking": False},
}

# 病人端一般醫學說明（AGENTS 2.24 未審草稿 JSON 路徑）取樣常數：
# 考量 JSON 格式與一般衛教說明可能包含 100～600 字之完整醫學內容，
# max_tokens 設定為 1500（於 22.5 tok/s 最壞延遲約 66.7 秒，遠低於 240 秒逾時），並以 chat_template_kwargs 關閉思考
PATIENT_GENERAL_SAMPLING = {
    **FAITHFUL_SAMPLING,
    "max_tokens": 1500,
    "chat_template_kwargs": {"enable_thinking": False},
}

# 視覺解說卡場景說明預生成取樣常數（Phase 29 P29-GEN）：
# 忠實取樣、關閉思考（enable_thinking=False）、上限 600 tokens，不使用無效之 reasoning_effort
VISUAL_SAMPLING = {
    **FAITHFUL_SAMPLING,
    "max_tokens": 600,
    "chat_template_kwargs": {"enable_thinking": False},
}



def check_llm_health(timeout: int = 5) -> str:
    """檢查本地 llama-server 是否正常存活。
    成功時回傳當前載入之模型 ID 或名稱；若服務未啟動則拋出 LocalLLMUnavailableError。
    """
    req = urllib.request.Request(MODELS_ENDPOINT, headers={"User-Agent": "clinicbrain-client"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise LocalLLMUnavailableError(
                    f"本地 LLM 健康檢查回傳非 200 狀態碼：{response.status}"
                )
            data = json.loads(response.read().decode("utf-8"))
            models = data.get("data", []) or data.get("models", [])
            if models:
                model_id = models[0].get("id") or models[0].get("name") or DEFAULT_MODEL_NAME
                return model_id
            return DEFAULT_MODEL_NAME
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        raise LocalLLMUnavailableError(
            "本地 LLM 服務未啟動於 http://127.0.0.1:8080，請確認 llama-server 是否運行"
        ) from e


def local_llm_call(prompt: str, timeout: int = 420, sampling: Optional[dict] = None) -> str:
    """呼叫本機 llama-server，回傳 message.content（忽略 reasoning_content）。

    函式簽章完全符合 generate_tree(procedure_name, llm_call) 的介面需求。
    連線失敗或逾時拋出清楚的 LocalLLMUnavailableError 例外。

    sampling：單次請求的取樣參數覆寫（例如 {"dry_multiplier": 0.0, "repeat_penalty": 1.0}）。
    伺服器啟動時常設重複懲罰以改善自由寫作，但「依據資料忠實引用」的任務（RAG）會因此被迫
    改用近似字，造成錯字或掉字，這類任務應於單次請求關閉重複懲罰，而不必改動伺服器設定。
    """
    # 呼叫前先進行健康檢查確認服務運行
    check_llm_health(timeout=5)

    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 6144,
        "reasoning_effort": "low",
    }
    if sampling:
        payload.update(sampling)
        # 依據 28-07 實機探測：關閉思考時 reasoning_effort 無效且矛盾，自 payload 移除
        if payload.get("chat_template_kwargs", {}).get("enable_thinking") is False:
            payload.pop("reasoning_effort", None)
    encoded_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        LLM_ENDPOINT,
        data=encoded_data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "clinicbrain-client",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw_bytes = response.read()
            resp_json = json.loads(raw_bytes.decode("utf-8"))
    except (socket.timeout, TimeoutError) as e:
        raise LocalLLMUnavailableError(f"呼叫本地 LLM 逾時（超過 {timeout} 秒）：{e}") from e
    except urllib.error.URLError as e:
        # 區分是否為內部 socket timeout
        if isinstance(e.reason, (socket.timeout, TimeoutError)) or "timed out" in str(e).lower():
            raise LocalLLMUnavailableError(f"呼叫本地 LLM 逾時（超過 {timeout} 秒）：{e}") from e
        raise LocalLLMUnavailableError(
            "本地 LLM 服務未啟動於 http://127.0.0.1:8080，請確認 llama-server 是否運行"
        ) from e
    except Exception as e:
        raise LocalLLMUnavailableError(f"本地 LLM 呼叫發生未預期異常：{e}") from e

    choices = resp_json.get("choices")
    if not choices or not isinstance(choices, list):
        raise LocalLLMUnavailableError(f"本地 LLM 回應格式異常，缺少 choices：{resp_json}")

    first_choice = choices[0]
    fr = first_choice.get("finish_reason")
    if fr == "length":
        usage = resp_json.get("usage", {})
        raise LLMTruncatedError(
            f"本地 LLM 輸出達長度限制被截斷（finish_reason=length, usage={usage}）"
        )

    message = first_choice.get("message", {})
    content = message.get("content")

    # 嚴格驗證 content，絕不使用 reasoning_content
    if content is None or not str(content).strip():
        fr = choices[0].get("finish_reason")
        rc_len = len(message.get("reasoning_content") or "")
        usage = resp_json.get("usage", {})
        raise LLMEmptyOutputError(
            f"本地 LLM 回應之 content 為空（可能未完成生成或僅輸出思考過程，finish_reason={fr}, rc_len={rc_len}, usage={usage}）"
        )

    from src.ingestion.convert_chinese import to_traditional

    return to_traditional(str(content).strip())


if __name__ == "__main__":
    print("檢查本地 LLM 連線...")
    try:
        model = check_llm_health()
        print(f"健康檢查成功！載入模型：{model}")
        print("發送測試訊息...")
        test_reply = local_llm_call("你好，請僅回覆繁體中文『系統連線正常』六個字")
        print(f"本地 LLM 回覆：{test_reply}")
    except LocalLLMUnavailableError as err:
        print(f"連線失敗：{err}")
