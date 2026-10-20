"""
Phase 29 Task 1: 視覺解說卡關鍵字比對與對外輸出整形測試 (test_visual_match.py)。

驗證目標：
1. 核准資產被關鍵字命中並整形為對外安全結構。
2. pending / rejected 狀態資產絕不命中。
3. 關鍵字不在問句中回傳 None。
4. 竄改資料庫 ir_json（如注入 <script>）後不回傳。
5. 缺表或任何資料庫錯誤安全回傳 None（Fail-Closed）。
6. 多資產命中時選擇命中關鍵字數最高者；同分時取較小 topic_key（確定性）。
7. 回傳 dict 僅含 {"topic_key", "title", "scenes"} 及對應場景/標籤欄位，不含資料庫 id、ir_json 原文、審核欄位、metadata、keywords。
8. NFKC 正規化：全形英數與相容字元可正確命中。
9. AST 掃描確認 src/visual/match.py 為純 SELECT 讀取模組（無 INSERT/UPDATE/DELETE、無 logging、無 print）。
"""

from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import apply_visual_migration
from src.visual.writer import upsert_assets
from src.visual.review import set_review_status
from src.visual.match import find_visual


def _make_sample_ir(
    topic_key: str = "autologous-fat-grafting",
    title: str = "自體脂肪移植原理與照護",
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    if keywords is None:
        keywords = ["自體脂肪", "補脂", "脂肪移植"]
    return {
        "topic_key": topic_key,
        "title": title,
        "keywords": keywords,
        "scenes": [
            {
                "blueprint": "process_diagram",
                "title": "脂肪抽取與純化",
                "caption": "自供脂區溫和取出脂肪組織，經純化處理去除雜質與油脂，保留健康脂肪細胞。",
                "labels": [
                    {"text": "溫和抽取", "tone": "neutral"},
                    {"text": "純化處理", "tone": "optimal"},
                ],
            },
            {
                "blueprint": "contrast",
                "title": "適量分層填補",
                "caption": "採取多點分層方式均勻植入，有助於移植組織獲得足夠養分供應並降低硬塊風險。",
                "labels": [
                    {"text": "單點過量", "tone": "warning"},
                    {"text": "多層微量", "tone": "optimal"},
                ],
            },
            {
                "blueprint": "timeline",
                "title": "術後恢復與穩定",
                "caption": "初期會有自然腫脹反應，部分脂肪會被吸收，待組織穩定後呈現自然柔和的輪廓。",
                "labels": [
                    {"text": "初期腫脹", "tone": "neutral"},
                    {"text": "穩定自然", "tone": "optimal"},
                ],
            },
        ],
    }


def _seed_asset(
    conn: sqlite3.Connection,
    ir: dict[str, Any],
    source_type: str = "manual",
    metadata: Any = None,
) -> None:
    upsert_assets(
        conn,
        [
            {
                "topic_key": ir["topic_key"],
                "title": ir["title"],
                "keywords": ir["keywords"],
                "ir": ir,
                "metadata": metadata,
            }
        ],
        source_type=source_type,
    )


def test_find_visual_matches_approved_and_shapes_output(isolated_db_path: Path):
    """核准資產被問句關鍵字命中，且回傳結構經嚴格整形，不含敏感或內部欄位。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir = _make_sample_ir()
        _seed_asset(conn, ir, source_type="manual", metadata={"note": "internal"})
        set_review_status(conn, "autologous-fat-grafting", "approved")

        res = find_visual(conn, "請問臉部自體脂肪移植術後要注意什麼？")
        assert res is not None
        assert set(res.keys()) == {"topic_key", "title", "scenes"}
        assert res["topic_key"] == "autologous-fat-grafting"
        assert res["title"] == "自體脂肪移植原理與照護"
        assert len(res["scenes"]) == 3

        for s in res["scenes"]:
            assert set(s.keys()) == {"blueprint", "title", "caption", "labels", "params", "duration_sec"}
            for lb in s["labels"]:
                assert set(lb.keys()) == {"text", "tone"}

        # 嚴格確認禁出欄位皆不存在
        forbidden_keys = {
            "id",
            "ir_json",
            "ir",
            "source_type",
            "review_status",
            "reviewed_at",
            "content_version",
            "metadata",
            "keywords",
            "created_at",
            "updated_at",
        }
        assert forbidden_keys.isdisjoint(res.keys())
    finally:
        conn.close()


def test_find_visual_ignores_pending_and_rejected(isolated_db_path: Path):
    """pending 與 rejected 資產絕不命中。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir = _make_sample_ir()
        _seed_asset(conn, ir, source_type="llm_generated")
        # 預設為 pending
        assert find_visual(conn, "我想了解自體脂肪補脂") is None

        # 設為 rejected
        set_review_status(conn, "autologous-fat-grafting", "rejected")
        assert find_visual(conn, "我想了解自體脂肪補脂") is None
    finally:
        conn.close()


def test_find_visual_returns_none_when_no_keyword_matched(isolated_db_path: Path):
    """關鍵字不在問句中時回傳 None；空字串問句亦回傳 None。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir = _make_sample_ir()
        _seed_asset(conn, ir, source_type="manual")
        set_review_status(conn, "autologous-fat-grafting", "approved")

        assert find_visual(conn, "請問玻尿酸注射後會腫幾天？") is None
        assert find_visual(conn, "") is None
    finally:
        conn.close()


def test_find_visual_rejects_tampered_ir_in_db(isolated_db_path: Path):
    """核准後若資料庫 ir_json 遭竄改（如注入 <script>），visible_assets 再驗證攔截，回傳 None。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir = _make_sample_ir()
        _seed_asset(conn, ir, source_type="manual")
        set_review_status(conn, "autologous-fat-grafting", "approved")

        # 直接在資料庫竄改 ir_json 注入 <script>
        conn.execute(
            "UPDATE visual_assets SET ir_json = replace(ir_json, '自體脂肪移植原理與照護', '<script>alert(1)</script>') WHERE topic_key = 'autologous-fat-grafting'"
        )
        conn.commit()

        assert find_visual(conn, "請問自體脂肪移植恢復期？") is None
    finally:
        conn.close()


def test_find_visual_fail_closed_when_table_missing_or_db_error(isolated_db_path: Path):
    """未執行遷移（缺表）或連線異常時，安全回傳 None（Fail-Closed）。"""
    # 未呼叫 apply_visual_migration
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        assert find_visual(conn, "自體脂肪補脂") is None
    finally:
        conn.close()

    # 已關閉的連線亦不拋出例外，安全回傳 None
    assert find_visual(conn, "自體脂肪補脂") is None


def test_find_visual_deterministic_tie_breaking_and_max_hits(isolated_db_path: Path):
    """多資產命中時取命中關鍵字數最高者；同分時取字典序較小的 topic_key（確定性）。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir_b = _make_sample_ir(
            topic_key="topic-beta",
            title="主題B解說",
            keywords=["超音波", "拉提"],
        )
        ir_a = _make_sample_ir(
            topic_key="topic-alpha",
            title="主題A解說",
            keywords=["超音波", "緊膚"],
        )
        ir_c = _make_sample_ir(
            topic_key="topic-gamma",
            title="主題C解說",
            keywords=["超音波", "拉提", "筋膜層"],
        )
        for item in (ir_b, ir_a, ir_c):
            _seed_asset(conn, item, source_type="manual")
            set_review_status(conn, item["topic_key"], "approved")

        # 1. 同時命中 alpha 與 beta 各 1 個關鍵字（「超音波」），也命中 gamma 1 個關鍵字
        # 同分（1 hit）應確定性選擇字典序最小的 topic-alpha
        res_tie = find_visual(conn, "請問超音波療程是什麼？")
        assert res_tie is not None
        assert res_tie["topic_key"] == "topic-alpha"

        # 2. 命中 gamma 3 個關鍵字、beta 2 個、alpha 1 個 -> 選擇命中數最高的 topic-gamma
        res_max = find_visual(conn, "請問超音波拉提作用在筋膜層嗎？")
        assert res_max is not None
        assert res_max["topic_key"] == "topic-gamma"
    finally:
        conn.close()


def test_find_visual_nfkc_normalization(isolated_db_path: Path):
    """問句經 NFKC 正規化後比對（如相容漢字或全形符號不影響子字串比對）。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir = _make_sample_ir(keywords=["自體脂肪", "補脂"])
        _seed_asset(conn, ir, source_type="manual")
        set_review_status(conn, "autologous-fat-grafting", "approved")

        # 含全形空白與標點
        res = find_visual(conn, "請問　自體脂肪　效果如何？")
        assert res is not None
        assert res["topic_key"] == "autologous-fat-grafting"
    finally:
        conn.close()


def test_match_module_ast_pure_select_and_no_logging():
    """以 AST 掃描確認 src/visual/match.py 無寫入 SQL、無 logging、無 print。"""
    match_path = Path(__file__).resolve().parent.parent / "src" / "visual" / "match.py"
    source = match_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(match_path))

    forbidden_sql = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE")
    for node in ast.walk(tree):
        # 禁止 import logging
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "logging", "match.py 不得 import logging"
        if isinstance(node, ast.ImportFrom):
            assert node.module != "logging", "match.py 不得 from logging import ..."

        # 禁止呼叫 print
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "print", "match.py 不得呼叫 print"

        # 禁止字串常數含寫入 SQL 關鍵字
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            upper_val = node.value.upper()
            for kw in forbidden_sql:
                assert f"{kw} " not in upper_val, f"match.py 不得含寫入 SQL: {kw}"


def test_find_visual_with_params_and_duration_sec(isolated_db_path: Path):
    """帶 params 與 duration_sec 的核准資產可正確輸出，且舊資產無 params 時為 None。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir_with_params = _make_sample_ir()
        ir_with_params["scenes"][0]["params"] = {"particles": 5}
        ir_with_params["scenes"][0]["duration_sec"] = 8
        _seed_asset(conn, ir_with_params, source_type="manual")
        set_review_status(conn, "autologous-fat-grafting", "approved")

        res = find_visual(conn, "自體脂肪補脂諮詢")
        assert res is not None
        s0 = res["scenes"][0]
        assert s0["params"] == {"particles": 5}
        assert s0["duration_sec"] == 8

        s1 = res["scenes"][1]
        assert s1["params"] is None
        assert s1["duration_sec"] is None
    finally:
        conn.close()


def test_find_visual_tampered_params_rejected_by_visible_assets(isolated_db_path: Path):
    """資料庫內 params 遭竄改（如含 fill="#fff"）時，visible_assets 自動略過，find_visual 回傳 None。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        ir_valid = _make_sample_ir()
        _seed_asset(conn, ir_valid, source_type="manual")
        set_review_status(conn, "autologous-fat-grafting", "approved")

        # 繞過審核直接以 SQL 竄改 ir_json，加入違法屬性
        cur = conn.cursor()
        cur.execute("SELECT ir_json FROM visual_assets WHERE topic_key = 'autologous-fat-grafting'")
        data = json.loads(cur.fetchone()[0])
        data["scenes"][0]["params"] = {"particles": 5, "fill": "#ffffff"}
        cur.execute(
            "UPDATE visual_assets SET ir_json = ? WHERE topic_key = 'autologous-fat-grafting'",
            (json.dumps(data, ensure_ascii=False),),
        )
        conn.commit()

        # visible_assets 應因 validate_ir 失敗而排除該筆，find_visual 應安全回傳 None
        res = find_visual(conn, "自體脂肪補脂諮詢")
        assert res is None
    finally:
        conn.close()


def test_find_visual_clinic_priority_and_isolation(isolated_db_path: Path):
    """驗證診所專屬資產優先於一般醫學資產，且他院資產絕不外洩。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        # 1. 一般醫學資產（命中 2 個關鍵字："自體脂肪"、"補脂"）
        gen_ir = _make_sample_ir(
            topic_key="general-fat-grafting",
            title="一般醫學自體脂肪移植",
            keywords=["自體脂肪", "補脂"],
        )
        upsert_assets(
            conn,
            [{"clinic_id": None, "topic_key": gen_ir["topic_key"], "title": gen_ir["title"], "keywords": gen_ir["keywords"], "ir": gen_ir}],
            source_type="manual",
        )
        set_review_status(conn, gen_ir["topic_key"], "approved", clinic_id=None)

        # 2. 診所 A (3503190424) 資產（僅命中 1 個關鍵字："自體脂肪"）
        clinic_a_ir = _make_sample_ir(
            topic_key="clinic-a-fat-grafting",
            title="緻妍診所專屬自體脂肪",
            keywords=["自體脂肪"],
        )
        upsert_assets(
            conn,
            [{"clinic_id": "3503190424", "topic_key": clinic_a_ir["topic_key"], "title": clinic_a_ir["title"], "keywords": clinic_a_ir["keywords"], "ir": clinic_a_ir}],
            source_type="manual",
        )
        set_review_status(conn, clinic_a_ir["topic_key"], "approved", clinic_id="3503190424")

        q = "請問自體脂肪補脂手術細節？"  # 同時命中 gen_ir(2 hits) 與 clinic_a_ir(1 hit)

        # (a) 帶 clinic_id="3503190424"：即使診所 A 僅命中 1 個關鍵字，診所專屬優先於一般醫學 (2 hits)
        res_a = find_visual(conn, q, clinic_id="3503190424")
        assert res_a is not None
        assert res_a["topic_key"] == "clinic-a-fat-grafting"
        assert res_a["title"] == "緻妍診所專屬自體脂肪"
        assert "clinic_id" not in res_a

        # (b) 不帶 clinic_id (None)：必選一般醫學資產
        res_gen = find_visual(conn, q, clinic_id=None)
        assert res_gen is not None
        assert res_gen["topic_key"] == "general-fat-grafting"
        assert res_gen["title"] == "一般醫學自體脂肪移植"
        assert "clinic_id" not in res_gen

        # (c) 帶診所 B ("3503264627")：絕不外洩診所 A 資產，安全退回一般醫學資產
        res_b = find_visual(conn, q, clinic_id="3503264627")
        assert res_b is not None
        assert res_b["topic_key"] == "general-fat-grafting"
        assert res_b["title"] == "一般醫學自體脂肪移植"
        assert "clinic_id" not in res_b
    finally:
        conn.close()

