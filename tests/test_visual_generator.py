"""
Phase 29 Plan 02 Task 1: 視覺解說卡骨架載入與生成器單元測試。
"""

import copy
from pathlib import Path
import pytest

from src.pageindex.llm_client import LLMTruncatedError, LocalLLMUnavailableError
from src.pageindex.llm_lock import GENERATION_LOCK
from src.visual.ir import VISUAL_EXTRA_FORBIDDEN

try:
    from src.pageindex.llm_client import VISUAL_SAMPLING
except ImportError:
    VISUAL_SAMPLING = None

try:
    from src.visual.generator import (
        load_skeleton,
        build_prompt,
        parse_output,
        generate_ir,
        DEFAULT_SKELETON_DIR,
    )
except ImportError:
    load_skeleton = None
    build_prompt = None
    parse_output = None
    generate_ir = None
    DEFAULT_SKELETON_DIR = Path("data/visual/skeletons")


VALID_MODEL_OUTPUT = (
    "場景1：自體脂肪移植會先由適當部位抽取脂肪組織，並透過純化程序篩選出結構完整的脂肪細胞備用。\n"
    "場景2：醫師採用少量多層次的方式將脂肪均勻放置於目標區域，有助於組織接觸周圍環境並減少局部硬塊。\n"
    "場景3：術後初期應避免按壓填補部位並維持正常作息，經過一段時間後組織會逐步適應並達到一定程度的穩定。"
)


def test_visual_sampling_constant():
    """驗證 llm_client.VISUAL_SAMPLING 規格。"""
    assert VISUAL_SAMPLING is not None, "llm_client 必須定義 VISUAL_SAMPLING"
    assert VISUAL_SAMPLING["max_tokens"] == 600
    assert VISUAL_SAMPLING["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_effort" not in VISUAL_SAMPLING
    assert VISUAL_SAMPLING["temperature"] == 0.1
    assert VISUAL_SAMPLING["dry_multiplier"] == 0.0
    assert VISUAL_SAMPLING["repeat_penalty"] == 1.0


def test_load_autologous_fat_grafting_skeleton(tmp_path):
    """驗證預設骨架檔 autologous-fat-grafting.json 載入與結構檢驗。"""
    assert load_skeleton is not None, "src/visual/generator.py 必須定義 load_skeleton"
    skel_path = Path("data/visual/skeletons/autologous-fat-grafting.json")
    assert skel_path.exists(), f"骨架檔不存在: {skel_path}"

    skel = load_skeleton(skel_path)
    assert skel["topic_key"] == "autologous-fat-grafting"
    assert skel["title"] == "自體脂肪移植原理"
    for kw in ["自體脂肪", "脂肪移植", "脂肪填充", "補脂", "自體脂肪移植"]:
        assert kw in skel["keywords"]
    assert len(skel["scenes"]) == 3
    assert [s["blueprint"] for s in skel["scenes"]] == ["process_diagram", "contrast", "timeline"]
    assert 4 <= len(skel["reference"]) <= 6

    # 若骨架含禁詞或數字則載入失敗
    bad_skel = copy.deepcopy(skel)
    bad_skel["reference"][0] = "保證存活率達到 90% 永久維持。"
    bad_file = tmp_path / "bad.json"
    import json
    bad_file.write_text(json.dumps(bad_skel, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        load_skeleton(bad_file)


def test_build_prompt_syncs_forbidden_terms():
    """驗證 build_prompt 包含 VISUAL_EXTRA_FORBIDDEN 所有禁用詞與替代語指引。"""
    skel = load_skeleton(Path("data/visual/skeletons/autologous-fat-grafting.json"))
    prompt = build_prompt(skel)

    for word in VISUAL_EXTRA_FORBIDDEN:
        assert word in prompt, f"prompt 缺少禁用詞: {word}"

    assert "因人而異" in prompt
    assert "一段時間" in prompt
    assert "場景1：" in prompt


def test_parse_output_think_tags_and_line_matching():
    """驗證 parse_output 清理 think 標籤並精準擷取場景說明。"""
    raw_with_think = f"<think>先思考一下怎麼寫...</think>\n{VALID_MODEL_OUTPUT}"
    caps = parse_output(raw_with_think, 3)
    assert caps is not None
    assert len(caps) == 3
    assert caps[0].startswith("自體脂肪移植會先由")

    # 缺行回傳 None
    incomplete = "場景1：只有第一行說明文字，長度超過二十個字元以上。\n場景2：只有第二行說明文字，長度超過二十個字元以上。"
    assert parse_output(incomplete, 3) is None

    # 夾帶額外場景4被拒絕或忽略（回傳 None 或只取前 3 個）
    extra = VALID_MODEL_OUTPUT + "\n場景4：這是模型自己多寫的第四個場景說明文字。"
    res_extra = parse_output(extra, 3)
    assert res_extra is None or len(res_extra) == 3


def test_generate_ir_success_and_structure_immutability():
    """驗證合格輸出組成 IR，且結構欄位完全由骨架決定，模型無法篡改。"""
    skel = load_skeleton(Path("data/visual/skeletons/autologous-fat-grafting.json"))

    def fake_llm(prompt: str) -> str:
        return VALID_MODEL_OUTPUT

    ir, code = generate_ir(skel, fake_llm)
    assert code == "ok"
    assert ir is not None
    assert ir["topic_key"] == skel["topic_key"]
    assert ir["title"] == skel["title"]
    assert ir["keywords"] == skel["keywords"]
    for i, sc in enumerate(ir["scenes"]):
        assert sc["blueprint"] == skel["scenes"][i]["blueprint"]
        assert sc["title"] == skel["scenes"][i]["title"]
        assert sc["labels"] == skel["scenes"][i]["labels"]


def test_generate_ir_retry_on_forbidden_and_exhaustion():
    """驗證第一次含禁詞失敗、第二次合格則成功；兩次皆不合格則放棄並回傳代碼（不含原文）。"""
    skel = load_skeleton(Path("data/visual/skeletons/autologous-fat-grafting.json"))

    bad_output = (
        "場景1：自體脂肪移植抽取後純化，存活率高達 90% 且效果永久維持不變。\n"
        "場景2：醫師採用少量多層次的方式將脂肪均勻放置於目標區域，有助於組織接觸周圍環境並減少局部硬塊。\n"
        "場景3：術後初期應避免按壓填補部位並維持正常作息，經過一段時間後組織會逐步適應並達到一定程度的穩定。"
    )

    calls = []

    def retry_then_ok_llm(prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return bad_output
        return VALID_MODEL_OUTPUT

    ir, code = generate_ir(skel, retry_then_ok_llm, max_attempts=2)
    assert code == "ok"
    assert ir is not None
    assert len(calls) == 2

    # 兩次皆失敗（夾帶 HTML <script>）
    html_output = (
        "場景1：自體脂肪移植<script>alert(1)</script>透過純化程序篩選出結構完整的脂肪細胞備用。\n"
        "場景2：醫師採用少量多層次的方式將脂肪均勻放置於目標區域，有助於組織接觸周圍環境並減少局部硬塊。\n"
        "場景3：術後初期應避免按壓填補部位並維持正常作息，經過一段時間後組織會逐步適應並達到一定程度的穩定。"
    )
    ir2, code2 = generate_ir(skel, lambda p: html_output, max_attempts=2)
    assert ir2 is None
    assert code2 == "text_unsafe"
    assert "<script>" not in code2


def test_generate_ir_truncated_unavailable_and_busy(tmp_path):
    """驗證 LLMTruncatedError 重試、LocalLLMUnavailableError 立即中止、以及忙碌鎖防護。"""
    skel = load_skeleton(Path("data/visual/skeletons/autologous-fat-grafting.json"))

    # 1. Truncated 兩次後回 truncated
    trunc_calls = 0

    def trunc_llm(prompt: str) -> str:
        nonlocal trunc_calls
        trunc_calls += 1
        raise LLMTruncatedError("truncated")

    ir_t, code_t = generate_ir(skel, trunc_llm, max_attempts=2)
    assert ir_t is None
    assert code_t == "truncated"
    assert trunc_calls == 2

    # 2. Unavailable 立即中止不重試（只呼叫 1 次）
    unavail_calls = 0

    def unavail_llm(prompt: str) -> str:
        nonlocal unavail_calls
        unavail_calls += 1
        raise LocalLLMUnavailableError("offline")

    ir_u, code_u = generate_ir(skel, unavail_llm, max_attempts=2)
    assert ir_u is None
    assert code_u == "llm_unavailable"
    assert unavail_calls == 1

    # 3. GENERATION_LOCK 被佔用時回 busy，不呼叫 LLM
    busy_calls = 0

    def should_not_call(prompt: str) -> str:
        nonlocal busy_calls
        busy_calls += 1
        return VALID_MODEL_OUTPUT

    assert GENERATION_LOCK.acquire(blocking=False)
    try:
        ir_b, code_b = generate_ir(skel, should_not_call)
        assert ir_b is None
        assert code_b == "busy"
        assert busy_calls == 0
    finally:
        GENERATION_LOCK.release()

    # 4. nightly_batch_running 為 True 時回 busy
    from src.batch import db_lock
    fake_db = tmp_path / "clinic.db"
    fake_db.write_text("dummy")
    fd = db_lock.try_acquire(fake_db)
    assert fd is not None
    try:
        ir_nb, code_nb = generate_ir(skel, should_not_call, db_path=fake_db)
        assert ir_nb is None
        assert code_nb == "busy"
        assert busy_calls == 0
    finally:
        db_lock.release(fd)


def test_skeleton_with_valid_params_and_duration_sec(tmp_path):
    """Phase 30 Task 3: 驗證骨架帶合法 params 與 duration_sec 可載入，且原樣帶入 IR。"""
    import json
    from src.visual.blueprints import default_params

    skel = load_skeleton(Path("data/visual/skeletons/autologous-fat-grafting.json"))
    custom_skel = copy.deepcopy(skel)
    for sc in custom_skel["scenes"]:
        sc["params"] = default_params(sc["blueprint"])
        sc["duration_sec"] = 7

    custom_file = tmp_path / "custom_skel.json"
    custom_file.write_text(json.dumps(custom_skel, ensure_ascii=False), encoding="utf-8")

    loaded = load_skeleton(custom_file)
    for sc in loaded["scenes"]:
        assert "params" in sc
        assert sc["duration_sec"] == 7

    ir, code = generate_ir(loaded, lambda p: VALID_MODEL_OUTPUT)
    assert code == "ok"
    assert ir is not None
    for sc_ir, sc_skel in zip(ir["scenes"], loaded["scenes"]):
        assert sc_ir["params"] == sc_skel["params"]
        assert sc_ir["duration_sec"] == 7


def test_skeleton_with_invalid_params_rejected(tmp_path):
    """Phase 30 Task 3: 驗證骨架 scene 若含非法 params 或 duration_sec，load_skeleton 拒絕。"""
    import json

    skel = load_skeleton(Path("data/visual/skeletons/autologous-fat-grafting.json"))

    # 1. params 含未知鍵
    bad_skel1 = copy.deepcopy(skel)
    bad_skel1["scenes"][0]["params"] = {"unknown_key": "val"}
    f1 = tmp_path / "bad1.json"
    f1.write_text(json.dumps(bad_skel1, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError) as exc1:
        load_skeleton(f1)
    assert "param_error" in str(exc1.value)

    # 2. params 填入禁止顏色
    bad_skel2 = copy.deepcopy(skel)
    bad_skel2["scenes"][0]["params"] = {"source": {"fill": "#fff"}}
    f2 = tmp_path / "bad2.json"
    f2.write_text(json.dumps(bad_skel2, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError) as exc2:
        load_skeleton(f2)
    assert "param_error" in str(exc2.value)

    # 3. duration_sec 超出範圍 (3 或 15)
    bad_skel3 = copy.deepcopy(skel)
    bad_skel3["scenes"][0]["duration_sec"] = 15
    f3 = tmp_path / "bad3.json"
    f3.write_text(json.dumps(bad_skel3, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError) as exc3:
        load_skeleton(f3)
    assert "param_error" in str(exc3.value)

    # 4. scene 含多餘未知欄位
    bad_skel4 = copy.deepcopy(skel)
    bad_skel4["scenes"][0]["extra_field"] = "bad"
    f4 = tmp_path / "bad4.json"
    f4.write_text(json.dumps(bad_skel4, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError) as exc4:
        load_skeleton(f4)
    assert "schema_error" in str(exc4.value)


def test_model_output_cannot_alter_params():
    """Phase 30 Task 3: 驗證模型輸出夾帶 JSON 或企圖更改 params 時無效，IR 的 params 仍鎖定骨架內容。"""
    from src.visual.blueprints import default_params

    skel = load_skeleton(Path("data/visual/skeletons/autologous-fat-grafting.json"))
    custom_skel = copy.deepcopy(skel)
    for sc in custom_skel["scenes"]:
        sc["params"] = default_params(sc["blueprint"])
        sc["duration_sec"] = 5

    malicious_model_output = (
        '場景1：自體脂肪移植會先由適當部位抽取脂肪組織，並透過純化程序篩選出結構完整的脂肪細胞備用。 {"particles": 999}\n'
        '場景2：醫師採用少量多層次的方式將脂肪均勻放置於目標區域，有助於組織接觸周圍環境並減少局部硬塊。\n'
        '場景3：術後初期應避免按壓填補部位並維持正常作息，經過一段時間後組織會逐步適應並達到一定程度的穩定。'
    )
    # 模型輸出含阿拉伯數字 999，即使通過解析也會被数字檢核攔截；
    # 這裡用不含數字但夾帶 params 字眼的輸出：
    malicious_no_digits = (
        '場景1：自體脂肪移植會先由適當部位抽取脂肪組織，並透過純化程序篩選出結構完整的脂肪細胞備用。\n'
        '場景2：醫師採用少量多層次的方式將脂肪均勻放置於目標區域，有助於組織接觸周圍環境並減少局部硬塊。\n'
        '場景3：術後初期應避免按壓填補部位並維持正常作息，經過一段時間後組織會逐步適應並達到一定程度的穩定。'
    )
    ir, code = generate_ir(custom_skel, lambda p: malicious_no_digits)
    assert code == "ok"
    assert ir is not None
    # 驗證 params 仍與 custom_skel 相同，particles 仍為 5，duration_sec 仍為 5
    assert ir["scenes"][0]["params"]["particles"] == 5
    assert ir["scenes"][0]["duration_sec"] == 5

