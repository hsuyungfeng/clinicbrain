#!/usr/bin/env python3
"""Phase 34 Plan 02：49 筆推理樹動畫草稿的逐場景渲染驗收、接觸表與報告。

對 `visual_assets` 中 `topic_key LIKE 'tree-%' AND clinic_id IS NOT NULL` 的草稿：
- 每個場景在 u=0 / 0.5 / 1 以 visual_engine.js 渲染，檢查圖元邊界、字幕安全區與
  正向／倒退 seek 的確定性。
- 每筆產生一張接觸表 PNG（3 場景 × 3 進度）。
- 每次執行覆寫 report.json 與 REPORT.md（不沿用過時報告）。

守門：資料庫以 mode=ro 開啟並設 PRAGMA query_only；不呼叫 LLM；不寫入資料庫。
需要 Playwright 與 Pillow，建議以系統 python3 執行：
    python3 scripts/check_draft_renders.py --db clinic.db --out demo/visual/out/batch_49
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENGINE_JS = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"
U_POINTS = (0.0, 0.5, 1.0)
THUMB_W, THUMB_H = 400, 255

# 與 tests/test_visual_engine_browser.py 的邊界量測一致（容差 1 單位）
BOUNDS_JS = """(function() {
    const svgEl = document.getElementById('s');
    const svgRect = svgEl.getBoundingClientRect();
    const scaleX = 800 / svgRect.width;
    const scaleY = 510 / svgRect.height;
    const violations = [];
    for (const el of svgEl.querySelectorAll('*')) {
        const tag = el.tagName.toLowerCase();
        if (tag === 'defs' || tag === 'clippath' || tag === 'g' || tag === 'svg') continue;
        if (el.closest('defs') || el.closest('clipPath')) continue;
        if (el.getAttribute('data-bg') === '1') continue;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') continue;
        const op = parseFloat(style.opacity);
        if (Number.isFinite(op) && op <= 0.01) continue;
        const attrOp = parseFloat(el.getAttribute('opacity'));
        if (Number.isFinite(attrOp) && attrOp <= 0.01) continue;
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0.1 || rect.height <= 0.1) continue;
        const vx1 = (rect.left - svgRect.left) * scaleX;
        const vy1 = (rect.top - svgRect.top) * scaleY;
        const vx2 = (rect.right - svgRect.left) * scaleX;
        const vy2 = (rect.bottom - svgRect.top) * scaleY;
        if (vx1 < 5 || vx2 > 795 || vy1 < 5 || vy2 > 505) {
            violations.push({ tag: tag, type: 'out_of_bounds' });
        }
        if (tag === 'text' && vy2 > 411) {
            violations.push({ tag: tag, type: 'subtitle_overlap' });
        }
    }
    return violations;
})()"""

MOUNT_JS = """([bp, title, params]) => {
    const svg = document.getElementById('s');
    svg.innerHTML = '';
    window.__m = window.ClinicVisual.mount(svg, [{ blueprint: bp, title: title, params: params }]);
    return window.__m.totalDuration;
}"""


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """唯讀開啟資料庫，並以 PRAGMA query_only 雙重防禦。"""
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON;")
    return conn


def load_drafts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, clinic_id, topic_key, title, review_status, ir_json
        FROM visual_assets
        WHERE topic_key LIKE 'tree-%' AND clinic_id IS NOT NULL
        ORDER BY clinic_id, topic_key
        """
    ).fetchall()
    drafts = []
    for r in rows:
        try:
            scenes = json.loads(r["ir_json"]).get("scenes", [])
        except Exception:  # noqa: BLE001 - 單筆損毀不中斷整批
            scenes = []
        drafts.append({
            "id": r["id"],
            "clinic_id": r["clinic_id"],
            "topic_key": r["topic_key"],
            "title": r["title"],
            "review_status": r["review_status"],
            "scenes": scenes,
        })
    return drafts


def summarize_scene(index: int, blueprint: str, violations: list, deterministic: bool, error: str | None) -> dict:
    ok = (not violations) and deterministic and error is None
    return {
        "index": index,
        "blueprint": blueprint,
        "ok": ok,
        "violations": violations,
        "deterministic": deterministic,
        "error": error,
    }


def build_report(results: list[dict], generated_at: str) -> dict:
    total = len(results)
    failed = [r["topic_key"] for r in results if not r["ok"]]
    return {
        "generated_at": generated_at,
        "draft_count": total,
        "ok_count": total - len(failed),
        "failed_topic_keys": failed,
        "drafts": results,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# 草稿渲染驗收報告（自動產生，每次執行覆寫）",
        "",
        f"- 產生時間：{report['generated_at']}",
        f"- 草稿數：{report['draft_count']}；通過：{report['ok_count']}；未通過：{len(report['failed_topic_keys'])}",
        "",
        "| 診所 | topic_key | 審核狀態 | 場景 1 | 場景 2 | 場景 3 | 結果 |",
        "|---|---|---|---|---|---|---|",
    ]
    for d in report["drafts"]:
        cells = []
        for s in d["scenes"]:
            mark = "通過" if s["ok"] else "未通過"
            cells.append(f"{s['blueprint']}（{mark}）")
        while len(cells) < 3:
            cells.append("—")
        overall = "通過" if d["ok"] else "未通過"
        lines.append(
            f"| {d['clinic_id']} | {d['topic_key']} | {d['review_status']} | "
            f"{cells[0]} | {cells[1]} | {cells[2]} | {overall} |"
        )
    return "\n".join(lines) + "\n"


def write_outputs(out_dir: Path, report: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "REPORT.md").write_text(render_markdown(report), encoding="utf-8")


def _contact_sheet(frames: list[list[bytes]], out_path: Path) -> None:
    from PIL import Image

    rows, cols = len(frames), len(U_POINTS)
    sheet = Image.new("RGB", (THUMB_W * cols + 10 * (cols - 1), THUMB_H * rows + 10 * (rows - 1)), "white")
    for r, row in enumerate(frames):
        for c, png in enumerate(row):
            im = Image.open(io_bytes(png)).convert("RGB").resize((THUMB_W, THUMB_H))
            sheet.paste(im, (c * (THUMB_W + 10), r * (THUMB_H + 10)))
    sheet.save(out_path)


def io_bytes(data: bytes):
    import io

    return io.BytesIO(data)


def render_drafts(drafts: list[dict], out_dir: Path) -> list[dict]:
    from playwright.sync_api import sync_playwright

    html_path = out_dir / "_render_page.html"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path.write_text(
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;background:#000"><svg id="s" width="800" height="510" viewBox="0 0 800 510"></svg>'
        f'<script src="{ENGINE_JS.as_uri()}"></script></body></html>',
        encoding="utf-8",
    )
    sheets_dir = out_dir / "contact_sheets"
    sheets_dir.mkdir(exist_ok=True)

    results: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 510})
        page.goto(html_path.as_uri())
        for d in drafts:
            scene_results, frame_rows = [], []
            for idx, sc in enumerate(d["scenes"][:3]):
                bp = sc.get("blueprint", "")
                title = sc.get("title", "")
                params = sc.get("params")
                try:
                    total = page.evaluate(MOUNT_JS, [bp, title, params])
                    violations: list = []
                    frames = []
                    for u in U_POINTS:
                        page.evaluate(f"window.__m.renderAt({u} * {total})")
                        violations.extend(page.evaluate(BOUNDS_JS))
                        frames.append(page.locator("#s").screenshot())
                    # 確定性：正向 seek 與倒退 seek 的 SVG 必須完全一致
                    forward = {}
                    for u in U_POINTS:
                        page.evaluate(f"window.__m.renderAt({u} * {total})")
                        forward[u] = page.evaluate("document.getElementById('s').outerHTML")
                    deterministic = True
                    for u in (1.0, 0.5, 0.0):
                        page.evaluate(f"window.__m.renderAt({u} * {total})")
                        if page.evaluate("document.getElementById('s').outerHTML") != forward[u]:
                            deterministic = False
                    scene_results.append(summarize_scene(idx, bp, violations, deterministic, None))
                    frame_rows.append(frames)
                except Exception as exc:  # noqa: BLE001 - 單一場景錯誤只記錄，不中斷整批
                    scene_results.append(summarize_scene(idx, bp, [], False, f"{type(exc).__name__}"))
                    frame_rows.append([page.locator("#s").screenshot()] * len(U_POINTS))
            while len(frame_rows) < 3:
                frame_rows.append([frame_rows[-1][0]] * len(U_POINTS) if frame_rows else [b""] * len(U_POINTS))
            _contact_sheet(frame_rows[:3], sheets_dir / f"{d['topic_key']}.png")
            results.append({
                "id": d["id"],
                "clinic_id": d["clinic_id"],
                "topic_key": d["topic_key"],
                "review_status": d["review_status"],
                "scenes": scene_results,
                "ok": all(s["ok"] for s in scene_results) and len(scene_results) == 3,
            })
        browser.close()
    html_path.unlink(missing_ok=True)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="49 筆草稿逐場景渲染驗收（唯讀）")
    parser.add_argument("--db", default=str(PROJECT_ROOT / "clinic.db"))
    parser.add_argument("--out", default=str(PROJECT_ROOT / "demo" / "visual" / "out" / "batch_49"))
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"找不到資料庫：{db_path}", file=sys.stderr)
        return 1
    conn = open_readonly(db_path)
    try:
        drafts = load_drafts(conn)
    finally:
        conn.close()

    out_dir = Path(args.out).resolve()
    results = render_drafts(drafts, out_dir)
    report = build_report(results, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    write_outputs(out_dir, report)
    print(f"草稿 {report['draft_count']} 筆，通過 {report['ok_count']} 筆；報告：{out_dir / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
