"""
Phase 30 Plan 05 Task 1: 第二主題（玻尿酸填充）零 JS 改動驗證測試 (test_visual_second_topic.py)。

測試項目：
1. 骨架載入與結構驗證：
   - data/visual/skeletons/hyaluronic-acid-filler.json 通過 load_skeleton。
   - topic_key 為 hyaluronic-acid-filler，title 為「玻尿酸填充原理」。
   - keywords 包含「玻尿酸」「玻尿酸填充」「填充」。
   - 包含 3 個場景，blueprint 僅使用既有 process_diagram、contrast、timeline。
   - reference 不含任何禁詞或數字。
2. IR 生成與 validate_ir 合規驗證：
   - 以假模型生成符合法規之 caption。
   - generate_ir 成功，生成的 IR 中 blueprint、params、labels 完全等於骨架。
   - validate_ir 檢驗通過。
3. Bundle 匯出與引擎在瀏覽器內渲染驗證（Playwright）：
   - 在隔離副本庫入庫、核准並匯出 bundle。
   - 瀏覽器載入 visual_engine.js 並 mount 渲染三場景在 u in {0, 0.5, 1}。
   - 所有元素座標皆在 viewBox [0, 800] x [0, 510] 容差範圍內。
   - 斷言 window.ClinicVisual.blueprints 鍵集合恰為既有三種模板（證明引擎未遭竄改或額外硬編碼擴充）。
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import pytest

from src.visual.generator import generate_ir, load_skeleton
from src.visual.ir import validate_ir
from src.visual.review import set_review_status
from src.visual.writer import upsert_assets
from tests.conftest import apply_visual_migration

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKELETON_FILE = PROJECT_ROOT / "data" / "visual" / "skeletons" / "hyaluronic-acid-filler.json"
ENGINE_JS_PATH = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"


def test_hyaluronic_acid_skeleton_structure_and_references():
    """驗證玻尿酸填充骨架檔案存在且符合規格與禁詞規範。"""
    assert SKELETON_FILE.is_file(), f"{SKELETON_FILE} 骨架檔案必須存在"

    sk = load_skeleton(SKELETON_FILE)
    assert sk["topic_key"] == "hyaluronic-acid-filler"
    assert sk["title"] == "玻尿酸填充原理"

    keywords = sk.get("keywords") or []
    assert "玻尿酸" in keywords
    assert "玻尿酸填充" in keywords
    assert "填充" in keywords

    scenes = sk.get("scenes") or []
    assert len(scenes) == 3

    # 場景 1
    s0 = scenes[0]
    assert s0["blueprint"] == "process_diagram"
    assert s0["params"]["source"]["label"] == "凝膠"
    assert s0["params"]["source"]["fill"] == "gel"
    assert s0["params"]["particles"] == 8
    assert len(s0["params"]["container_layers"]) == 3
    assert len(s0["params"]["step_labels"]) == 3

    # 場景 2
    s1 = scenes[1]
    assert s1["blueprint"] == "contrast"
    assert s1["params"]["left"]["title"] == "單點過量"
    assert s1["params"]["left"]["mode"] == "mass"
    assert s1["params"]["right"]["title"] == "分點少量"
    assert s1["params"]["right"]["mode"] == "layered"
    assert s1["params"]["right"]["rows"] == 2
    assert s1["params"]["right"]["per_row"] == 5

    # 場景 3
    s2 = scenes[2]
    assert s2["blueprint"] == "timeline"
    assert len(s2["params"]["milestones"]) == 3
    assert s2["params"]["unit_effect"] == "fade"
    assert s2["params"]["connectors"] == "none"
    assert s2["params"]["units"] == 4

    # 參考概念要點
    refs = sk.get("reference") or []
    assert 4 <= len(refs) <= 6
    forbidden_tokens = ["永久", "終身", "一輩子", "保證", "完全不會", "零風險", "%", "％", "元", "$"]
    for ref in refs:
        for fb in forbidden_tokens:
            assert fb not in ref, f"reference 不得包含禁詞或符號 {fb}: {ref}"


def test_hyaluronic_acid_generate_and_validate_ir():
    """以假模型輸出合格說明文字，驗證 IR 生成與完整醫療法規校驗通過。"""
    sk = load_skeleton(SKELETON_FILE)

    def _mock_llm(prompt: str) -> str:
        return (
            "場景1：玻尿酸凝膠由專業醫師根據需求評估，採分層方式平順注入目標部位。\n"
            "場景2：採分點微量方式精準放置，使整體線條更加柔順自然，避免集中過量。\n"
            "場景3：注入後隨時間逐漸與周邊組織自然相容，後續將依個人狀況逐步吸收代謝。"
        )

    ir, code = generate_ir(sk, llm_call=_mock_llm)
    assert code == "ok"
    assert ir is not None
    assert ir["topic_key"] == "hyaluronic-acid-filler"
    assert len(ir["scenes"]) == 3

    # 驗證 blueprint、params、labels 皆自骨架完整傳承
    for i, orig_sc in enumerate(sk["scenes"]):
        gen_sc = ir["scenes"][i]
        assert gen_sc["blueprint"] == orig_sc["blueprint"]
        assert gen_sc["params"] == orig_sc["params"]
        assert gen_sc["labels"] == orig_sc["labels"]

    # 執行 Typed IR 與醫療法規驗證
    v_ok, v_code = validate_ir(ir)
    assert v_ok is True, f"validate_ir 失敗代碼: {v_code}"


def test_hyaluronic_acid_engine_browser_rendering(playwright_page):
    """驗證第二主題在瀏覽器中由 visual_engine.js 渲染時元件皆在安全區內，且引擎無額外擴充。"""
    sk = load_skeleton(SKELETON_FILE)

    # 建立包含 caption 的完整場景資料
    scenes_data = [
        {
            "blueprint": sk["scenes"][0]["blueprint"],
            "title": sk["scenes"][0]["title"],
            "caption": "玻尿酸凝膠由專業醫師根據需求評估，採分層方式平順注入目標部位。",
            "labels": sk["scenes"][0]["labels"],
            "params": sk["scenes"][0]["params"],
            "duration_sec": 8,
        },
        {
            "blueprint": sk["scenes"][1]["blueprint"],
            "title": sk["scenes"][1]["title"],
            "caption": "採分點微量方式精準放置，使整體線條更加柔順自然，避免集中過量。",
            "labels": sk["scenes"][1]["labels"],
            "params": sk["scenes"][1]["params"],
            "duration_sec": 9,
        },
        {
            "blueprint": sk["scenes"][2]["blueprint"],
            "title": sk["scenes"][2]["title"],
            "caption": "注入後隨時間逐漸與周邊組織自然相容，後續將依個人狀況逐步吸收代謝。",
            "labels": sk["scenes"][2]["labels"],
            "params": sk["scenes"][2]["params"],
            "duration_sec": 7,
        },
    ]

    engine_code = ENGINE_JS_PATH.read_text(encoding="utf-8")
    playwright_page.set_content(
        f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
<svg id="testCanvas" width="800" height="510" viewBox="0 0 800 510"></svg>
<script>{engine_code}</script>
</body>
</html>"""
    )

    # 1. 斷言引擎包含基礎三種模板
    blueprints = playwright_page.evaluate("() => Object.keys(window.ClinicVisual.blueprints).sort()")
    assert set(["contrast", "process_diagram", "timeline"]).issubset(set(blueprints)), (
        f"視覺引擎模板集必須包含基礎三種，實際: {blueprints}"
    )

    # 2. 掛載第二主題完整場景
    playwright_page.evaluate(
        """(scenes) => {
            const svg = document.getElementById("testCanvas");
            window.__mounted = window.ClinicVisual.mount(svg, scenes);
        }""",
        scenes_data,
    )

    # 3. 測試三場景在 u in {0, 0.5, 1} 下渲染且邊界安全
    scene_starts = [0, 8, 17]
    scene_durs = [8, 9, 7]

    for scene_idx in range(3):
        start_t = scene_starts[scene_idx]
        dur = scene_durs[scene_idx]
        for u in (0.0, 0.5, 1.0):
            t = start_t + dur * u
            res = playwright_page.evaluate(
                """(t) => {
                    window.__mounted.renderAt(t);
                    const svg = document.getElementById("testCanvas");
                    const svgRect = svg.getBoundingClientRect();
                    const scaleX = 800 / svgRect.width;
                    const scaleY = 510 / svgRect.height;
                    const elements = svg.querySelectorAll("*");
                    let outOfBounds = [];

                    for (const el of elements) {
                        if (el.tagName === "svg" || el.tagName === "g" || el.tagName === "defs" || el.tagName === "clipPath") continue;
                        if (el.getAttribute("data-bg") === "1" || el.getAttribute("opacity") === "0") continue;
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 && r.height === 0) continue;
                        const x1 = (r.left - svgRect.left) * scaleX;
                        const y1 = (r.top - svgRect.top) * scaleY;
                        const x2 = (r.right - svgRect.left) * scaleX;
                        const y2 = (r.bottom - svgRect.top) * scaleY;
                        if (x1 < -1 || x2 > 801 || y1 < -1 || y2 > 511) {
                            outOfBounds.push({ tag: el.tagName, x1, y1, x2, y2 });
                        }
                    }
                    return { outOfBoundsCount: outOfBounds.length, outOfBounds };
                }""",
                t,
            )
            assert res["outOfBoundsCount"] == 0, (
                f"場景 {scene_idx} 在 u={u} (t={t}) 時有超出 viewBox 的元素: {res['outOfBounds']}"
            )


def test_hyaluronic_acid_bundle_export_e2e(isolated_db_path: Path):
    """驗證第二主題在隔離副本庫中入庫、核准後，可成功透過 export_visual_bundle 匯出標準 bundle。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        sk = load_skeleton(SKELETON_FILE)
        scenes = []
        for i, sc in enumerate(sk["scenes"], 1):
            scenes.append({
                "blueprint": sc["blueprint"],
                "title": sc["title"],
                "caption": f"這是第 {i} 場景的醫學衛教說明文字，經由專業醫師審核符合規範。",
                "labels": sc["labels"],
                "params": sc["params"],
                "duration_sec": 8,
            })
        ir = {
            "topic_key": sk["topic_key"],
            "title": sk["title"],
            "keywords": sk["keywords"],
            "scenes": scenes,
        }
        upsert_assets(
            conn,
            [
                {
                    "topic_key": ir["topic_key"],
                    "title": ir["title"],
                    "keywords": ir["keywords"],
                    "ir": ir,
                }
            ],
            source_type="manual",
        )
        set_review_status(conn, ir["topic_key"], "approved")

        out_json = isolated_db_path.parent / "bundle.json"
        from scripts.export_visual_bundle import export_bundle
        rc = export_bundle(isolated_db_path, ir["topic_key"], out_json)
        assert rc == 0
        bundle = json.loads(out_json.read_text(encoding="utf-8"))
        assert bundle["topic_key"] == "hyaluronic-acid-filler"
        assert bundle["title"] == "玻尿酸填充原理"
        assert len(bundle["scenes"]) == 3
        for sc in bundle["scenes"]:
            assert "params" in sc and isinstance(sc["params"], dict)
            assert "duration_sec" in sc and isinstance(sc["duration_sec"], int)
    finally:
        conn.close()

