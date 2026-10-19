"""
Phase 30 Plan 04 Task 2: 病人諮詢頁視覺引擎動畫整合瀏覽器測試 (test_consult_engine_browser.py)。

測試項目：
1. 帶 params 之視覺資產：
   - 卡片以 ClinicVisual 引擎渲染（獨立 SVG viewBox 0 0 800 510）。
   - 進入每個場景自動播放動畫。
   - 上一步／下一步平順切換，最後一步送出 completed 匿名事件。
2. 無 params 之舊版視覺資產（params 為 None）：
   - 安全走既有靜態圖渲染（viewBox 0 0 480 120），不報錯。
3. 缺少 visual_engine.js 檔案（模擬載入失敗）：
   - 安全退回靜態圖，不中斷回答顯示。
4. prefers-reduced-motion: reduce 環境：
   - 直接呈現最終畫面 (u=1)。
"""

from __future__ import annotations

import functools
import http.server
import json
from pathlib import Path
import threading
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "src" / "web" / "static"

SAMPLE_VISUAL_WITH_PARAMS = {
    "topic_key": "autologous-fat-grafting",
    "title": "自體脂肪移植原理與照護",
    "scenes": [
        {
            "blueprint": "process_diagram",
            "title": "脂肪抽取與純化",
            "caption": "自供脂區溫和取出脂肪組織，保留健康脂肪細胞。",
            "labels": [{"text": "溫和抽取", "tone": "neutral"}],
            "params": {"particles": 5},
            "duration_sec": 8,
        },
        {
            "blueprint": "contrast",
            "title": "適量分層填補",
            "caption": "採取多點分層方式均勻植入，降低硬塊風險。",
            "labels": [{"text": "多層微量", "tone": "optimal"}],
            "params": {"left": {"title": "單點過量"}, "right": {"title": "多層微量"}},
            "duration_sec": 9,
        },
        {
            "blueprint": "timeline",
            "title": "術後恢復與穩定",
            "caption": "待組織穩定後呈現自然柔和的輪廓。",
            "labels": [{"text": "穩定自然", "tone": "optimal"}],
            "params": {"units": 3},
            "duration_sec": 7,
        },
    ],
}

SAMPLE_VISUAL_WITHOUT_PARAMS = {
    "topic_key": "autologous-fat-grafting",
    "title": "自體脂肪移植原理與照護",
    "scenes": [
        {
            "blueprint": "process_diagram",
            "title": "脂肪抽取與純化",
            "caption": "自供脂區溫和取出脂肪組織，保留健康脂肪細胞。",
            "labels": [{"text": "溫和抽取", "tone": "neutral"}],
            "params": None,
            "duration_sec": None,
        },
        {
            "blueprint": "contrast",
            "title": "適量分層填補",
            "caption": "採取多點分層方式均勻植入，降低硬塊風險。",
            "labels": [{"text": "多層微量", "tone": "optimal"}],
            "params": None,
            "duration_sec": None,
        },
        {
            "blueprint": "timeline",
            "title": "術後恢復與穩定",
            "caption": "待組織穩定後呈現自然柔和的輪廓。",
            "labels": [{"text": "穩定自然", "tone": "optimal"}],
            "params": None,
            "duration_sec": None,
        },
    ],
}


class MockStaticServer(http.server.BaseHTTPRequestHandler):
    """僅提供 /admin/consult.html, consult.js, visual_engine.js 之最小本機伺服器。"""

    def do_GET(self):
        # 移除 query string
        path_only = self.path.split("?")[0]
        mapping = {
            "/admin/consult.html": (STATIC_DIR / "consult.html", "text/html; charset=utf-8"),
            "/admin/consult.js": (STATIC_DIR / "consult.js", "application/javascript; charset=utf-8"),
            "/admin/visual_engine.js": (STATIC_DIR / "visual_engine.js", "application/javascript; charset=utf-8"),
        }
        if path_only in mapping:
            file_path, ctype = mapping[path_only]
            if file_path.is_file():
                content = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def consult_server():
    """啟動臨時埠 MockStaticServer，測試結束關閉。"""
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockStaticServer)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def test_consult_with_params_uses_engine(playwright_browser, consult_server):
    """驗證帶 params 時 consult.html 使用 ClinicVisual 引擎渲染動畫並正常切換場景與事件。"""
    events_recorded: list[dict] = []
    page = playwright_browser.new_page(viewport={"width": 800, "height": 900})

    try:
        def handle_api(route):
            req = route.request
            url = req.url
            if "/api/v1/general/consult/jobs" in url and req.method == "POST":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"job_id": "mock-job-001"}),
                )
            elif "/api/v1/general/consult/jobs/mock-job-001" in url and req.method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "status": "answered",
                        "message": "自體脂肪補脂說明內容",
                        "disclaimer": "醫療免責聲明",
                        "booking_url": "https://doctor-toolbox.com/",
                        "visual": SAMPLE_VISUAL_WITH_PARAMS,
                    }),
                )
            elif "/api/v1/general/visual/event" in url and req.method == "POST":
                try:
                    payload = json.loads(req.post_data or "{}")
                    events_recorded.append(payload)
                except Exception:
                    pass
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))
            else:
                route.continue_()

        page.route("**/api/v1/general/**", handle_api)
        page.goto(f"{consult_server}/admin/consult.html")

        # 輸入問句並送出
        page.fill("#consultInput", "自體脂肪補脂效果如何？")
        page.click("#btnSubmit")

        # 等待視覺卡片出現
        page.wait_for_selector("#visualCard", state="visible", timeout=10000)

        # 驗證使用引擎畫布（viewBox="0 0 800 510" 且含 .scene-root）
        engine_svg = page.locator("#visualCard svg.visual-engine-canvas")
        engine_svg.wait_for(state="attached", timeout=5000)
        assert engine_svg.count() == 1
        assert engine_svg.get_attribute("viewBox") == "0 0 800 510"
        assert page.locator("#visualCard svg.visual-engine-canvas g.scene-root").count() == 1

        # 驗證首幕 shown 事件已觸發
        assert any(e.get("event") == "shown" for e in events_recorded)

        # 點擊「下一步」兩次推進到最後一幕
        step_indicator = page.locator(".visual-step-indicator")
        assert "1 / 3" in step_indicator.text_content()

        next_btn = page.locator("button.btn-visual-nav", has_text="下一步")
        next_btn.click()
        page.wait_for_function("() => document.querySelector('.visual-step-indicator').textContent.includes('2 / 3')")

        next_btn.click()
        page.wait_for_function("() => document.querySelector('.visual-step-indicator').textContent.includes('3 / 3')")

        # 驗證最後一幕 completed 事件已觸發
        assert any(e.get("event") == "completed" for e in events_recorded)

        # 點擊「上一步」回退
        prev_btn = page.locator("button.btn-visual-nav", has_text="上一步")
        prev_btn.click()
        page.wait_for_function("() => document.querySelector('.visual-step-indicator').textContent.includes('2 / 3')")
    finally:
        page.close()


def test_consult_prefers_reduced_motion(playwright_browser, consult_server):
    """驗證在 prefers-reduced-motion: reduce 環境下，引擎直接渲染場景最終畫面。"""
    context = playwright_browser.new_context(
        viewport={"width": 800, "height": 900},
        reduced_motion="reduce",
    )
    page = context.new_page()
    try:
        def handle_api(route):
            req = route.request
            url = req.url
            if "/api/v1/general/consult/jobs" in url and req.method == "POST":
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"job_id": "mock-job-004"}))
            elif "/api/v1/general/consult/jobs/mock-job-004" in url and req.method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "status": "answered",
                        "message": "說明",
                        "disclaimer": "免責",
                        "booking_url": "https://doctor-toolbox.com/",
                        "visual": SAMPLE_VISUAL_WITH_PARAMS,
                    }),
                )
            elif "/api/v1/general/visual/event" in url:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))
            else:
                route.continue_()

        page.route("**/api/v1/general/**", handle_api)
        page.goto(f"{consult_server}/admin/consult.html")
        page.fill("#consultInput", "自體脂肪補脂效果？")
        page.click("#btnSubmit")
        page.wait_for_selector("#visualCard svg.visual-engine-canvas", state="attached", timeout=10000)

        # 驗證在 reduced motion 下已直接渲染
        assert page.locator("#visualCard svg.visual-engine-canvas g.scene-root").count() == 1
    finally:
        context.close()



def test_consult_without_params_uses_static_svg(playwright_browser, consult_server):
    """驗證舊資產（params 為 None）時安全退回既有靜態圖，不報錯。"""
    page = playwright_browser.new_page(viewport={"width": 800, "height": 900})

    try:
        def handle_api(route):
            req = route.request
            url = req.url
            if "/api/v1/general/consult/jobs" in url and req.method == "POST":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"job_id": "mock-job-002"}),
                )
            elif "/api/v1/general/consult/jobs/mock-job-002" in url and req.method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "status": "answered",
                        "message": "自體脂肪補脂說明內容",
                        "disclaimer": "醫療免責聲明",
                        "booking_url": "https://doctor-toolbox.com/",
                        "visual": SAMPLE_VISUAL_WITHOUT_PARAMS,
                    }),
                )
            elif "/api/v1/general/visual/event" in url and req.method == "POST":
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))
            else:
                route.continue_()

        page.route("**/api/v1/general/**", handle_api)
        page.goto(f"{consult_server}/admin/consult.html")

        page.fill("#consultInput", "自體脂肪補脂諮詢")
        page.click("#btnSubmit")

        page.wait_for_selector("#visualCard", state="visible", timeout=10000)

        # 驗證無引擎 SVG，而是使用既有靜態圖 (480x120)
        assert page.locator("#visualCard svg.visual-engine-canvas").count() == 0
        static_svg = page.locator("#visualCard .visual-svg-wrap svg")
        assert static_svg.count() == 1
        assert static_svg.get_attribute("viewBox") == "0 0 480 120"
    finally:
        page.close()


def test_consult_missing_engine_script_falls_back_to_static(playwright_browser, consult_server):
    """驗證當 visual_engine.js 載入失敗時，頁面自動安全退回靜態圖，不影響諮詢回答。"""
    page = playwright_browser.new_page(viewport={"width": 800, "height": 900})

    try:
        # 阻斷 visual_engine.js
        page.route("**/admin/visual_engine.js", lambda route: route.abort())

        def handle_api(route):
            req = route.request
            url = req.url
            if "/api/v1/general/consult/jobs" in url and req.method == "POST":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"job_id": "mock-job-003"}),
                )
            elif "/api/v1/general/consult/jobs/mock-job-003" in url and req.method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "status": "answered",
                        "message": "自體脂肪補脂說明內容",
                        "disclaimer": "醫療免責聲明",
                        "booking_url": "https://doctor-toolbox.com/",
                        "visual": SAMPLE_VISUAL_WITH_PARAMS,
                    }),
                )
            elif "/api/v1/general/visual/event" in url and req.method == "POST":
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))
            else:
                route.continue_()

        page.route("**/api/v1/general/**", handle_api)
        page.goto(f"{consult_server}/admin/consult.html")

        page.fill("#consultInput", "自體脂肪補脂效果如何？")
        page.click("#btnSubmit")

        page.wait_for_selector("#visualCard", state="visible", timeout=10000)

        # 引擎檔阻斷時退回靜態圖
        assert page.locator("#visualCard svg.visual-engine-canvas").count() == 0
        static_svg = page.locator("#visualCard .visual-svg-wrap svg")
        assert static_svg.count() == 1
        assert static_svg.get_attribute("viewBox") == "0 0 480 120"
    finally:
        page.close()


# ---------------------------------------------------------------------------
# 回歸（2026-10-19）：場景結尾畫面不得變成下一個場景的起點
# 真實瀏覽器驗收發現：播放結束時 renderAt(startT + dur) 恰在邊界，被引擎判為下一場景 u=0，
# 導致場景 1、2 一播完就顯示成下一場景的畫面（只有最後一個場景剛好正確）。
# 既有測試只檢查步驟指示與 viewBox，沒有驗證「畫的是對的 blueprint」，故以獨特標記字串鎖定。
# ---------------------------------------------------------------------------

MARKED_VISUAL = {
    "topic_key": "marker-topic",
    "title": "標記主題",
    "scenes": [
        {"blueprint": "process_diagram", "title": "場景一", "caption": "第一幕說明文字。", "labels": [],
         "params": {"source": {"label": "起點甲", "fill": "skin"}}, "duration_sec": 4},
        {"blueprint": "contrast", "title": "場景二", "caption": "第二幕說明文字。", "labels": [],
         "params": {"left": {"title": "對照乙"}}, "duration_sec": 4},
        {"blueprint": "timeline", "title": "場景三", "caption": "第三幕說明文字。", "labels": [],
         "params": {"milestones": ["里程丙", "里程丁", "里程戊"]}, "duration_sec": 4},
    ],
}
SCENE_MARKERS = ["起點甲", "對照乙", "里程丙"]


def _route_marked_visual(page):
    def handle_api(route):
        req = route.request
        url = req.url
        if "/api/v1/general/consult/jobs" in url and req.method == "POST":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"job_id": "mock-job-marker"}))
        elif "/api/v1/general/consult/jobs/mock-job-marker" in url and req.method == "GET":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "status": "answered", "message": "說明", "disclaimer": "免責", "booking_url": "https://doctor-toolbox.com/",
                "visual": MARKED_VISUAL}))
        elif "/api/v1/general/visual/event" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))
        else:
            route.continue_()

    page.route("**/api/v1/general/**", handle_api)


def _canvas_text(page) -> str:
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('#visualCard svg.visual-engine-canvas text')).map(e => e.textContent).join('|')"
    )


def _assert_only_marker(text: str, idx: int, where: str):
    assert SCENE_MARKERS[idx] in text, f"{where}：場景 {idx + 1} 應畫出自己的標記 {SCENE_MARKERS[idx]}，實際文字：{text}"
    for j, m in enumerate(SCENE_MARKERS):
        if j != idx:
            assert m not in text, f"{where}：場景 {idx + 1} 不得畫出場景 {j + 1} 的標記 {m}，實際文字：{text}"


def test_consult_each_scene_draws_its_own_blueprint_reduced_motion(playwright_browser, consult_server):
    """減少動態路徑：每個場景進入後直接呈現自己的結尾畫面，而不是下一個場景的起點。"""
    ctx = playwright_browser.new_context(viewport={"width": 800, "height": 900}, reduced_motion="reduce")
    page = ctx.new_page()
    try:
        _route_marked_visual(page)
        page.goto(f"{consult_server}/admin/consult.html")
        page.fill("#consultInput", "標記測試")
        page.click("#btnSubmit")
        page.wait_for_selector("#visualCard svg.visual-engine-canvas", state="attached", timeout=10000)

        for idx in range(3):
            page.wait_for_function(
                f"() => document.querySelector('.visual-step-indicator').textContent.includes('{idx + 1} / 3')")
            _assert_only_marker(_canvas_text(page), idx, "reduced-motion")
            if idx < 2:
                page.locator("button.btn-visual-nav", has_text="下一步").click()
    finally:
        ctx.close()


def test_consult_first_scene_animation_end_is_not_next_scene(playwright_browser, consult_server):
    """真實動畫路徑：第一個場景播放完畢（4 秒）後，畫面仍是場景一，不得跳成場景二的起點。"""
    page = playwright_browser.new_page(viewport={"width": 800, "height": 900})
    try:
        _route_marked_visual(page)
        page.goto(f"{consult_server}/admin/consult.html")
        page.fill("#consultInput", "標記測試")
        page.click("#btnSubmit")
        page.wait_for_selector("#visualCard svg.visual-engine-canvas", state="attached", timeout=10000)
        page.wait_for_timeout(5000)  # 場景 duration_sec=4，等待動畫完整結束
        _assert_only_marker(_canvas_text(page), 0, "animation-end")
    finally:
        page.close()
