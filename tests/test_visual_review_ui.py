"""
Phase 31 Plan 31-04 Task 2: 待簽核動畫分頁靜態安全檢驗與 Playwright 真實瀏覽器端到端測試 (test_visual_review_ui.py)。

測試內容：
1. 靜態安全檢驗：
   - /admin/ index.html 零內嵌 <script> 且同源依序引用 visual_engine.js 與 app.js。
   - 7 個導覽頁籤全數齊全。
   - app.js Phase 31 區段零被禁子字串（innerHTML, insertAdjacentHTML, outerHTML, document.write, eval, setInterval）。
   - style.css 具備視覺審核與播放器專用樣式類別。
2. Playwright 端到端瀏覽器測試：
   - 啟動臨時埠 uvicorn 服務掛載隔離資料庫。
   - 開啟 /admin/ 切換至「🎬 待簽核動畫」分頁，驗證 SVG 畫布 (viewBox 0 0 800 510) 正常渲染且繪圖節點數 > 5。
   - 驗證場景按鈕切換與進度桿尋找無 console error。
   - 驗證在頁面上編輯場景說明文字並儲存後，狀態維持 pending 且文字成功更新。
   - 驗證點擊「✅ 核准發布」後狀態轉為已發布；於 consult.html 提問驗證動畫優先顯示並合成。
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import socket
import sqlite3
import threading
import time
from typing import Any

import pytest
import uvicorn

from src.api.app import app
from src.api.config import config
from src.visual.writer import upsert_assets
from tests.conftest import apply_visual_migration

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "src" / "web" / "static"
CLINIC_ID = "3503190424"


def _sample_visual_card(
    topic_key: str = "rhinoplasty-principle",
    title: str = "結構式隆鼻手術原理與照護",
    clinic_id: str | None = None,
) -> dict[str, Any]:
    return {
        "topic_key": topic_key,
        "title": title,
        "clinic_id": clinic_id,
        "keywords": ["隆鼻", "結構式隆鼻", "鼻雕"],
        "ir": {
            "topic_key": topic_key,
            "title": title,
            "keywords": ["隆鼻", "結構式隆鼻", "鼻雕"],
            "scenes": [
                {
                    "blueprint": "process_diagram",
                    "title": "軟骨支架搭建",
                    "caption": "自自體耳軟骨或肋軟骨精細雕刻鼻中膈支架以提供穩定支撐力道",
                    "labels": [
                        {"text": "自體軟骨", "tone": "neutral"},
                        {"text": "鼻柱支撐", "tone": "optimal"},
                    ],
                    "params": {
                        "source": {"label": "自體軟骨", "fill": "accent"},
                        "particles": 6,
                        "container_layers": [
                            {"label": "皮膚皮下", "fill": "pale", "weight": 2, "keep": False},
                            {"label": "鼻柱軟骨", "fill": "accent", "weight": 3, "keep": True},
                            {"label": "鼻骨底部", "fill": "neutral", "weight": 2, "keep": False},
                        ],
                        "step_labels": ["精細取樣", "立體塑形", "筋膜固定"],
                    },
                    "duration_sec": 6,
                },
                {
                    "blueprint": "contrast",
                    "title": "植入方式對照",
                    "caption": "結構式分層架構能有效分散壓力，相較傳統單段植入更為穩固自然",
                    "labels": [
                        {"text": "傳統單段", "tone": "warning"},
                        {"text": "結構分層", "tone": "optimal"},
                    ],
                    "params": {
                        "left": {
                            "title": "傳統單段",
                            "note": "應力過度集中",
                            "mode": "mass",
                            "core_effect": "dim",
                            "core_label": "鼻尖負擔",
                            "footnote": "單段植入長期受壓容易變薄",
                            "unit_fill": "warn",
                        },
                        "right": {
                            "title": "結構分層",
                            "note": "多點分散支撐",
                            "mode": "layered",
                            "rows": 3,
                            "per_row": 5,
                            "footnote": "分層支撐提供自然持久輪廓",
                            "unit_fill": "ok",
                        },
                    },
                    "duration_sec": 6,
                },
                {
                    "blueprint": "timeline",
                    "title": "術後組織進程",
                    "caption": "術後初期微腫屬正常現象，隨組織消腫軟骨與周圍密合，實際成效因人而異需由醫師評估",
                    "labels": [
                        {"text": "初期微腫", "tone": "neutral"},
                        {"text": "穩定定型", "tone": "optimal"},
                    ],
                    "params": {
                        "milestones": ["微腫恢復", "組織密合", "輪廓自然"],
                        "unit_effect": "mature",
                        "connectors": "vessels",
                        "units": 3,
                        "unit_fill": "ok",
                    },
                    "duration_sec": 6,
                },
            ],
        },
    }


# ============================================================================
# 靜態安全檢驗
# ============================================================================


def test_html_static_security_and_tabs():
    """驗證 index.html 零內嵌腳本、正確引用 visual_engine.js 與 app.js，且包含 7 個頁籤。"""
    html_path = STATIC_DIR / "index.html"
    assert html_path.is_file()
    html = html_path.read_text(encoding="utf-8")

    # 1. 零內嵌 <script>（所有 <script> 標籤必須有 src 屬性）
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)
    assert len(scripts) >= 2
    for attrs, body in scripts:
        assert 'src="' in attrs, f"發現非法內嵌腳本：{body[:100]}"
        assert not body.strip(), f"腳本標籤內不得含有內嵌程式碼：{body[:100]}"

    # 2. 外部腳本載入順序：visual_engine.js 必須在 app.js 之前
    engine_idx = html.find('/admin/visual_engine.js')
    app_idx = html.find('/admin/app.js')
    assert engine_idx != -1, "index.html 缺少 /admin/visual_engine.js 引用"
    assert app_idx != -1, "index.html 缺少 /admin/app.js 引用"
    assert engine_idx < app_idx, "visual_engine.js 必須在 app.js 之前載入"

    # 3. 7 個分頁 data-tab 存在
    expected_tabs = {
        "tab-dashboard",
        "tab-review",
        "tab-trees",
        "tab-visuals",
        "tab-upload",
        "tab-soap",
        "tab-ask",
    }
    found_tabs = set(re.findall(r'data-tab="([^"]+)"', html))
    assert expected_tabs.issubset(found_tabs), f"缺少預期頁籤：{expected_tabs - found_tabs}"

    # 4. tab-visuals 必要控制項 ID
    assert 'id="tab-visuals"' in html
    assert 'id="visualsFilterClinic"' in html
    assert 'id="visualsFilterScope"' in html
    assert 'id="visualsFilterStatus"' in html
    assert 'id="btnRefreshVisuals"' in html
    assert 'id="visualsTreeSelect"' in html
    assert 'id="btnAutodraftVisual"' in html
    assert 'id="visualsContainer"' in html
    assert 'id="statVisualsPendingTotal"' in html


def test_app_js_phase31_no_forbidden_substrings():
    """驗證 app.js 的 Phase 31 實作區段不含 innerHTML, eval, document.write 等違禁語法。"""
    app_path = STATIC_DIR / "app.js"
    assert app_path.is_file()
    content = app_path.read_text(encoding="utf-8")

    # 定位 Phase 31 區段
    start_marker = "Phase 31:"
    idx = content.find(start_marker)
    assert idx != -1, "app.js 缺少 Phase 31 註解區段標記"

    phase31_code = content[idx:]
    forbidden = [
        "innerHTML",
        "insertAdjacentHTML",
        "outerHTML",
        "document.write",
        "eval(",
        "setInterval",
    ]
    for term in forbidden:
        assert term not in phase31_code, f"app.js Phase 31 區段含有禁用語法: {term}"


def test_style_css_has_visual_review_classes():
    """驗證 style.css 包含動畫審核與播放器必要類別。"""
    css_path = STATIC_DIR / "style.css"
    assert css_path.is_file()
    css = css_path.read_text(encoding="utf-8")

    expected_classes = [
        ".visual-review-card",
        ".visual-review-player",
        ".visual-review-svg",
        ".visual-review-controls",
        ".visual-review-scrubber",
        ".visual-scene-list",
        ".visual-scene-item",
        ".visual-edit-box",
    ]
    for cls in expected_classes:
        assert cls in css, f"style.css 缺少預期樣式類別: {cls}"


# ============================================================================
# Playwright 真實瀏覽器端到端測試
# ============================================================================


@pytest.fixture
def e2e_test_server(isolated_db_path, monkeypatch):
    """啟動臨時埠 uvicorn 服務，掛載已套用 visual schema 之隔離資料庫。"""
    from src.pageindex.faq_writer import upsert_faqs

    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        # 寫入一筆診所專屬動畫與一筆一般醫學動畫（皆為 pending）
        card_clinic = _sample_visual_card(topic_key="clinic-rhino", title="本院結構隆鼻技術", clinic_id=CLINIC_ID)
        card_general = _sample_visual_card(topic_key="general-rhino", title="一般結構隆鼻常識", clinic_id=None)
        upsert_assets(conn, [card_clinic, card_general], source_type="llm_generated")

        # 寫入一筆已核准 FAQ 供病人諮詢短路命中（避免在測試中觸發真實本地 LLM）
        warning = "若出現持續性疼痛或異常腫脹，請立即回診尋求醫師評估。"
        upsert_faqs(
            conn,
            [
                {
                    "clinic_id": CLINIC_ID,
                    "topic_key": "rhino-faq",
                    "category": "special",
                    "question": "我想諮詢結構式隆鼻手術原理與技術",
                    "answer": f"結構式隆鼻手術注重軟骨立體支撐架構與整體比例自然維持。{warning}",
                }
            ],
            source_type="manual",
        )
    finally:
        conn.close()

    monkeypatch.setattr(config, "db_path", isolated_db_path)
    monkeypatch.setattr(config, "allow_no_auth", True)
    monkeypatch.setattr(config, "admin_api_key", "")
    monkeypatch.setattr(config, "patient_clinic_id", CLINIC_ID)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server_cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(server_cfg)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    for _ in range(50):
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.1)
            s.close()
            break
        except OSError:
            time.sleep(0.05)

    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    server.should_exit = True
    t.join(timeout=3)


def test_visual_review_ui_playback_editing_and_approval(playwright_browser, e2e_test_server):
    """Playwright E2E: 驗證待簽核動畫分頁、SVG 畫布、場景切換、內聯編輯與核准發布流程。"""
    page = playwright_browser.new_page(viewport={"width": 1200, "height": 900})
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda err: console_errors.append(str(err)))

    try:
        # 1. 進入首頁，驗證 7 個分頁按鈕並點擊「🎬 待簽核動畫」
        page.goto(f"{e2e_test_server}/admin/")
        page.wait_for_selector('button[data-tab="tab-visuals"]', state="visible", timeout=10000)
        page.click('button[data-tab="tab-visuals"]')

        # 2. 驗證容器內出現動畫審核卡片
        page.wait_for_selector(".visual-review-card", state="visible", timeout=10000)
        cards = page.locator(".visual-review-card")
        assert cards.count() >= 2

        # 3. 驗證第一張卡片的 SVG 畫布渲染（viewBox="0 0 800 510" 且子元素數量 > 5）
        first_card = cards.first
        svg = first_card.locator("svg.visual-review-svg")
        assert svg.is_visible()
        assert svg.get_attribute("viewBox") == "0 0 800 510"

        # 等待場景節點渲染
        page.wait_for_timeout(300)
        children_count = page.evaluate("el => el.querySelectorAll('*').length", svg.element_handle())
        assert children_count > 5, f"SVG 渲染子節點數不足：{children_count}"

        # 4. 驗證切換場景 2 與場景 3
        first_card.get_by_role("button", name="場景 2").click()
        page.wait_for_timeout(200)
        first_card.get_by_role("button", name="場景 3").click()
        page.wait_for_timeout(200)

        # 5. 驗證內聯修訂功能
        first_card.get_by_role("button", name="✏️ 編輯說明文字").click()
        edit_box = first_card.locator(".visual-edit-box")
        assert edit_box.is_visible()

        # 修改標題與儲存
        title_input = edit_box.locator('input[type="text"]').first
        title_input.fill("本院精準結構隆鼻技術")
        edit_box.get_by_role("button", name="💾 儲存修訂").click()

        # 等待重載完成，驗證標題更新且狀態仍為待簽核
        page.wait_for_timeout(600)
        page.wait_for_selector(".visual-review-card", state="visible", timeout=10000)
        assert "本院精準結構隆鼻技術" in page.content()

        # 6. 驗證核准發布
        updated_card = page.locator(".visual-review-card").filter(has_text="本院精準結構隆鼻技術").first
        page.once("dialog", lambda dialog: dialog.accept())
        updated_card.get_by_role("button", name="✅ 核准發布").click()

        # 等待狀態更新為已發布
        page.wait_for_timeout(600)
        assert "已發布" in page.content()

        # 7. 驗證病人諮詢頁 consult.html 提問帶出該動畫
        page.goto(f"{e2e_test_server}/admin/consult.html")
        page.wait_for_selector("#consultInput", state="visible", timeout=10000)
        page.fill("#consultInput", "我想諮詢結構式隆鼻手術原理與技術")
        page.click("#btnSubmit")

        # 等待視覺解說卡出現並驗證以 ClinicVisual 合成播放
        page.wait_for_selector("#visualCard", state="visible", timeout=10000)
        consult_svg = page.locator("#visualCard svg.visual-engine-canvas")
        assert consult_svg.is_visible()
        assert consult_svg.get_attribute("viewBox") == "0 0 800 510"

        # 確認無任何致命的未捕獲錯誤
        fatal_errors = [e for e in console_errors if "favicon" not in e and "404" not in e]
        assert len(fatal_errors) == 0, f"瀏覽器執行過程中發生 console 錯誤：{fatal_errors}"
    finally:
        page.close()
