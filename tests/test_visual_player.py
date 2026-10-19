"""
Phase 30 Plan 03 Task 2: 通用視覺解說播放器測試 (test_visual_player.py)。

測試項目：
1. 靜態安全掃描：
   - player.html 與 player.js 絕不含禁用子字串（innerHTML, eval, localStorage, setInterval, setTimeout, performance.now 等，含註解）。
   - player.html 不得含內嵌 <script>，僅允許引入 visual_engine.js 與 player.js 兩隻外部檔。
2. 參數安全性測試（負例路徑拒絕）：
   - //evil.com/a.json, /data/x.json, a//b.json, ../x.json, http://x/a.json, C:\\x.json, 含空白, 非 .json。
   - 非法路徑一律顯示固定錯誤訊息「無法載入」，不洩漏路徑。
3. 功能與互動測試（Playwright 瀏覽器測試）：
   - 章節清單依 bundle 動態生成。
   - seek(0), seek(10), seek(24) 狀態、字幕與章節指示器正確切換。
   - 結尾預約卡（CTA）僅在播放結束時顯示，點擊「重新播放」回到開頭。
"""

from __future__ import annotations

import functools
import http.server
import json
from pathlib import Path
import re
import shutil
import threading
import uuid
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLAYER_HTML_PATH = PROJECT_ROOT / "demo" / "visual" / "player.html"
PLAYER_JS_PATH = PROJECT_ROOT / "demo" / "visual" / "player.js"
TEST_BUNDLE_BASE = PROJECT_ROOT / "demo" / "visual" / "out" / "_test"

SAMPLE_BUNDLE = {
    "topic_key": "autologous-fat-grafting",
    "title": "自體脂肪移植原理",
    "scenes": [
        {
            "blueprint": "process_diagram",
            "title": "抽取與純化",
            "caption": "抽取後先經過純化處理，篩選出結構完整的脂肪組織。",
            "labels": [{"text": "抽取脂肪", "tone": "neutral"}],
            "params": {"particles": 5},
            "duration_sec": 8,
        },
        {
            "blueprint": "contrast",
            "title": "少量多層次注射",
            "caption": "採分多層次少量放置，使每份脂肪皆能接觸周圍組織。",
            "labels": [{"text": "分層少量", "tone": "optimal"}],
            "params": {"left": {"title": "單處過量"}, "right": {"title": "分層少量"}},
            "duration_sec": 9,
        },
        {
            "blueprint": "timeline",
            "title": "術後逐步穩定",
            "caption": "術後一段時間內身體會逐步適應並達到穩定狀態。",
            "labels": [{"text": "逐步適應", "tone": "optimal"}],
            "params": {"units": 3},
            "duration_sec": 7,
        },
    ],
}


@pytest.fixture(scope="module")
def local_http_server():
    """以 repo 根目錄為根的臨時埠本機 HTTP 伺服器。"""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(PROJECT_ROOT))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}"

    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def test_bundle_path():
    """於 demo/visual/out/_test/ 建立隨機目錄存放測試 bundle，teardown 必刪。"""
    uid = uuid.uuid4().hex
    target_dir = TEST_BUNDLE_BASE / uid
    target_dir.mkdir(parents=True, exist_ok=True)
    bundle_file = target_dir / "bundle.json"
    bundle_file.write_text(json.dumps(SAMPLE_BUNDLE, ensure_ascii=False), encoding="utf-8")

    rel_path = bundle_file.relative_to(PROJECT_ROOT).as_posix()
    yield rel_path

    shutil.rmtree(target_dir, ignore_errors=True)


def test_player_static_safety():
    """靜態安全掃描：不含危險 API、不含 eval、無內嵌 script。"""
    assert PLAYER_HTML_PATH.exists(), f"{PLAYER_HTML_PATH} 必須存在"
    assert PLAYER_JS_PATH.exists(), f"{PLAYER_JS_PATH} 必須存在"

    html_content = PLAYER_HTML_PATH.read_text(encoding="utf-8")
    js_content = PLAYER_JS_PATH.read_text(encoding="utf-8")
    combined = html_content + "\n" + js_content

    forbidden_list = [
        "innerHTML",
        "insertAdjacentHTML",
        "document.write",
        "outerHTML",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "setInterval",
        "setTimeout",
        "Date.now",
        "Math.random",
        "new Date",
        "performance.now",
        "XMLHttpRequest",
        "import(",
    ]

    for sub in forbidden_list:
        assert sub not in combined, f"播放器檔案不得包含禁用子字串: {sub}"

    assert "eval" not in combined.lower(), "播放器檔案不得包含任何含有 eval 的字詞（含註解）"

    # 檢查無內嵌 <script>
    inline_scripts = [m for m in re.findall(r"<script\b([^>]*)>", html_content, re.IGNORECASE) if "src=" not in m]
    assert inline_scripts == [], "player.html 不得含有內嵌 <script>"

    # 檢查只引用允許的外部腳本
    scripts = re.findall(r"<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]*)['\"]", html_content, re.IGNORECASE)
    expected_scripts = ["../../src/web/static/visual_engine.js", "player.js"]
    assert scripts == expected_scripts, f"外部腳本引用不符，預期 {expected_scripts}，實際 {scripts}"


def test_player_bundle_path_negative_cases(playwright_page, local_http_server):
    """驗證非法或跨來源路徑參數皆被拒絕並顯示固定錯誤訊息「無法載入」。"""
    invalid_paths = [
        "//evil.com/a.json",
        "/data/x.json",
        "a//b.json",
        "../x.json",
        "http://x/a.json",
        "C:\\x.json",
        "bundle with spaces.json",
        "bundle.txt",
    ]

    for bad_path in invalid_paths:
        url = f"{local_http_server}/demo/visual/player.html?bundle={bad_path}"
        playwright_page.goto(url)
        playwright_page.wait_for_selector("#errorBox")
        error_text = playwright_page.inner_text("#errorBox")
        assert "無法載入" in error_text, f"路徑 '{bad_path}' 應顯示固定訊息『無法載入』，實際：{error_text}"
        # 確保不回顯非法路徑字串
        assert bad_path not in error_text


def test_player_load_and_seek_behavior(playwright_page, local_http_server, test_bundle_path):
    """驗證正常 bundle 載入、章節生成、seek 推進與結尾卡顯示。"""
    url = f"{local_http_server}/demo/visual/player.html?bundle={test_bundle_path}"
    playwright_page.goto(url)

    # 等待播放器初始化完畢
    playwright_page.wait_for_function("window.__player && window.__player.ready === true")

    total = playwright_page.evaluate("window.__player.total")
    assert total == 24  # 8 + 9 + 7

    # 驗證章節標籤數
    chapters = playwright_page.query_selector_all(".chap")
    assert len(chapters) == 3

    # seek(0) -> 第一章節
    playwright_page.evaluate("window.__player.seek(0)")
    assert "抽取與純化" in playwright_page.inner_text("#chapTitle")
    assert "抽取後先經過純化處理" in playwright_page.inner_text("#cap")
    assert not playwright_page.is_visible("#cta")

    # seek(10) -> 第二章節
    playwright_page.evaluate("window.__player.seek(10)")
    assert "少量多層次注射" in playwright_page.inner_text("#chapTitle")
    assert "採分多層次少量放置" in playwright_page.inner_text("#cap")
    assert not playwright_page.is_visible("#cta")

    # seek(24) -> 結尾，CTA 顯示
    playwright_page.evaluate("window.__player.seek(24)")
    assert "術後逐步穩定" in playwright_page.inner_text("#chapTitle")
    assert playwright_page.is_visible("#cta")
    assert "https://doctor-toolbox.com/" in playwright_page.get_attribute("#cta a", "href")
    assert "本系統不收集任何個人資料" in playwright_page.inner_text("#cta")

    # 點擊「重新播放」按鈕 -> 回到 0，CTA 隱藏
    playwright_page.click("#again")
    assert "抽取與純化" in playwright_page.inner_text("#chapTitle")
    assert not playwright_page.is_visible("#cta")
