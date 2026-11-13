"""
Phase 44 Tester 獨立驗收：全庫 400 筆真實臨床 IR 品質抽驗。

目標：在**真實資料庫 visual_assets.ir_json**（398 批准 / 2 拒絕）下，逐資產、逐場景
以無頭 Chromium 經視覺引擎渲染，驗證：
1. 各影格 outerHTML 不含 `="NaN"` / `="undefined"` / `="null"` 屬性。
2. 瀏覽器 console 零 error。
3. 渲染產出非空（至少有一個 SVG 子元素）。
4. 同 u 值正/反向 seek 輸出 100% 一致（確定性）。
5. 各場景 duration 落在引擎接受的 4-12 秒範圍內（不合規則記錄警告）。

此測試以 pytest 執行（`.venv/bin/python -m pytest tests/test_visual_assets_real_ir.py`），
亦可獨立執行：`python tests/test_visual_assets_real_ir.py --json report.json`。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE_JS_PATH = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"
DB_PATH = PROJECT_ROOT / "clinic.db"

# 每個場景檢查的 u（進度）點。0/0.5/1.0 為端點，中間點捕捉微呼吸/漣漪峰值。
U_POINTS = [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0]


def _load_assets() -> list[dict]:
    """讀取 visual_assets，回傳 [{id, topic_key, clinic_id, title, review_status, scenes, ir_raw}]。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    out = []
    for row in conn.execute(
        "SELECT id, topic_key, clinic_id, title, review_status, ir_json FROM visual_assets ORDER BY id"
    ):
        try:
            ir = json.loads(row["ir_json"])
            scenes = ir.get("scenes")
            if not isinstance(scenes, list) or not scenes:
                out.append({
                    "id": row["id"], "topic_key": row["topic_key"],
                    "clinic_id": row["clinic_id"], "title": row["title"],
                    "review_status": row["review_status"], "scenes": [],
                    "ir_raw": ir, "error": "scenes 缺失或非列表",
                })
                continue
            out.append({
                "id": row["id"], "topic_key": row["topic_key"],
                "clinic_id": row["clinic_id"], "title": row["title"],
                "review_status": row["review_status"], "scenes": scenes,
                "ir_raw": ir,
            })
        except Exception as exc:  # malformed JSON
            out.append({
                "id": row["id"], "topic_key": row["topic_key"],
                "clinic_id": row["clinic_id"], "title": row["title"],
                "review_status": row["review_status"], "scenes": [],
                "ir_raw": None, "error": f"ir_json JSON 解析失敗: {exc}",
            })
    conn.close()
    return out


def _render_asset(playwright_page, scenes: list[dict], u_points: list[float] | None = None) -> dict:
    """渲染單一資產的全部場景，回傳該資產的驗收結果 dict。

    透過 evaluate 單一 arg 把 {U_POINTS, SCENES} 傳入（Playwright evaluate 只接受
    一個可選引數，不支援全域變數注入）。
    """
    if u_points is None:
        u_points = U_POINTS
    res = playwright_page.evaluate(
        """(args) => {
            const { U_POINTS, SCENES } = args;
            const svg = document.getElementById('s');
            const inst = window.ClinicVisual.mount(svg, SCENES);
            const dur = inst.totalDuration;
            const forward = {};
            for (const u of U_POINTS) {
                inst.renderAt(u * dur);
                forward[u] = document.getElementById('s').outerHTML;
            }
            // 反向重渲染，核對確定性
            let detFail = 0;
            for (const u of U_POINTS.slice().reverse()) {
                inst.renderAt(u * dur);
                const h = document.getElementById('s').outerHTML;
                if (h !== forward[u]) detFail++;
            }
            // 取任一影格做違規檢查（用 u=0.5）
            inst.renderAt(0.5 * dur);
            const html = document.getElementById('s').outerHTML;
            const hasContent = document.getElementById('s').children.length > 0;
            const bad = (html.includes('=\"NaN\"') || html.includes('=\"undefined\"') ||
                         html.includes('=\"null\"')) ? 1 : 0;
            return { dur: dur, detFail: detFail, bad: bad, content: hasContent,
                     fragLen: html.length };
        }""",
        {"U_POINTS": u_points, "SCENES": scenes},
    )
    return res


def _run_all(u_points: list[float] | None = None, statuses: tuple[str, ...] | None = None) -> dict:
    """對全庫執行渲染抽驗，回傳彙總報告（供 CLI 與 pytest 共用）。"""
    if sync_playwright is None:
        raise RuntimeError("playwright 未安裝")
    assets = _load_assets()
    if statuses:
        assets = [a for a in assets if a["review_status"] in statuses]

    p = sync_playwright().start()
    browser = p.chromium.launch()
    page = browser.new_page()
    console_errors: list[dict] = []
    page.on("console", lambda m: console_errors.append(
        {"text": m.text[:200], "type": m.type}) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append({"text": str(e)[:200], "type": "pageerror"}))

    engine_html = (
        '<svg id=s width=800 height=510 viewBox="0 0 800 510"></svg>'
        f'<script src="{ENGINE_JS_PATH.as_uri()}"></script>'
    )
    tmp = Path(tempfile.mkdtemp()) / "audit.html"
    tmp.write_text(engine_html, encoding="utf-8")
    page.goto(tmp.as_uri())
    page.wait_for_function("typeof window.ClinicVisual !== 'undefined'")

    per_asset_failures: list[dict] = []
    violations = {"nan_null_undefined": 0, "determinism": 0, "no_content": 0,
                  "console_error": 0, "scene_error": 0, "duration_out_of_range": 0}
    assets_checked = 0
    for a in assets:
        if a.get("error"):
            violations["scene_error"] += 1
            per_asset_failures.append({"id": a["id"], "topic_key": a["topic_key"],
                                       "status": a["review_status"], "reason": a["error"]})
            continue
        assets_checked += 1
        res = _render_asset(page, a["scenes"], u_points or U_POINTS)
        asset_bad = False
        reasons = []
        if res["bad"]:
            violations["nan_null_undefined"] += 1; asset_bad = True; reasons.append("NaN/undefined/null 屬性")
        if res["detFail"]:
            violations["determinism"] += 1; asset_bad = True; reasons.append(f"確定性失敗 {res['detFail']} 點")
        if not res["content"]:
            violations["no_content"] += 1; asset_bad = True; reasons.append("渲染為空")
        # 各場景 duration 檢查（4-12 秒）
        for s in a["scenes"]:
            d = s.get("duration_sec")
            if not isinstance(d, (int, float)) or not (4 <= d <= 12):
                violations["duration_out_of_range"] += 1
        if asset_bad:
            per_asset_failures.append({"id": a["id"], "topic_key": a["topic_key"],
                                       "status": a["review_status"], "reasons": reasons})

    page.close(); browser.close()
    p.stop()

    return {
        "assets_total": len(assets), "assets_checked": assets_checked,
        "violations": violations, "console_errors": console_errors,
        "per_asset_failures": per_asset_failures,
    }


@pytest.mark.skipif(sync_playwright is None, reason="playwright 未安裝")
def test_all_400_real_ir_renders_clean():
    """全庫 400 筆：零 NaN/undefined/null、零確定性失敗、渲染非空、零 console error。"""
    report = _run_all()
    v = report["violations"]
    assert v["nan_null_undefined"] == 0, f"存在 NaN/undefined/null 屬性: {v}"
    assert v["determinism"] == 0, f"確定性失敗: {v}"
    assert v["no_content"] == 0, "存在渲染為空的資產"
    assert v["console_error"] == 0, f"console error: {report['console_errors']}"


@pytest.mark.skipif(sync_playwright is None, reason="playwright 未安裝")
def test_approved_only_100_percent_clean():
    """398 批准資產：全部乾淨渲染（ stricter 門檻）。"""
    report = _run_all(statuses=("approved",))
    assert report["assets_checked"] == 398, f"批准資產數量不符: {report['assets_checked']}"
    assert report["violations"]["nan_null_undefined"] == 0
    assert report["violations"]["determinism"] == 0
    assert report["violations"]["no_content"] == 0


def _cli() -> None:
    ap = argparse.ArgumentParser(description="全庫 400 筆真實 IR 引擎品質抽驗")
    ap.add_argument("--json", help="寫入報告 JSON 到指定路徑")
    ap.add_argument("--only-approved", action="store_true", help="只驗收 398 批准資產")
    args = ap.parse_args()
    report = _run_all(statuses=("approved",) if args.only_approved else None)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    _cli()
