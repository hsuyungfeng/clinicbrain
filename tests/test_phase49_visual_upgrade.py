"""
Phase 49：398 筆臨床動畫深度升級驗收測試 (test_phase49_visual_upgrade.py)。

驗證項目：
1. blueprints.py 選填進階參數（contrast_layout, anatomy_region）向後相容驗證。
2. Scene 1 解剖位置相對性（u < 0.14 呈現宏觀人體輪廓定位；u >= 0.14 切換至純局部解剖）。
3. Scene 2 治療方式差異性結果（4 種臨床範式：outcome_fork, tradeoff_matrix, layered_scan, side_by_side）。
4. Scene 3 治療好處細膩呈現（生理機轉微動畫＋非量化功能舒適度趨勢帶，嚴禁百分比）。
"""

from __future__ import annotations

from pathlib import Path
import pytest

from src.visual.blueprints import merge_defaults, validate_params

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE_JS_PATH = PROJECT_ROOT / "src" / "web" / "static" / "visual_engine.js"


def _setup_page(playwright_page, tmp_path: Path) -> list[str]:
    errors: list[str] = []
    playwright_page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    html_file = tmp_path / "phase49_test.html"
    html_file.write_text(
        f"""<!DOCTYPE html><html lang="zh-TW"><head><meta charset="utf-8"></head>
        <body><svg id="testSvg" width="800" height="510" viewBox="0 0 800 510"></svg>
        <script src="{ENGINE_JS_PATH.as_uri()}"></script></body></html>""",
        encoding="utf-8",
    )
    playwright_page.goto(html_file.as_uri())
    playwright_page.wait_for_function("typeof window.ClinicVisual !== 'undefined'")
    return errors


def test_optional_phase49_params_backward_compatible():
    """選填進階參數僅在提供時驗證，不影響既有 merge_defaults 輸出。"""
    ok, code = validate_params("contrast", {"contrast_layout": "outcome_fork"})
    assert ok and code == "ok"

    ok_bad, code_bad = validate_params("contrast", {"contrast_layout": "invalid_layout"})
    assert not ok_bad and code_bad == "param_error"

    ok_anat, code_anat = validate_params("pathology_mechanism", {"anatomy_region": "neck_cervical"})
    assert ok_anat and code_anat == "ok"

    # 預設合併不包含選填鍵，維持既有 IR 零遷移
    assert "contrast_layout" not in merge_defaults("contrast", None)
    assert "anatomy_region" not in merge_defaults("pathology_mechanism", None)


def test_scene1_macro_to_micro_locator(playwright_page, tmp_path):
    """Scene 1 開頭顯示宏觀解剖相對定位，u >= 0.14 後切換回純局部解剖（不留常駐小地圖）。"""
    errors = _setup_page(playwright_page, tmp_path)
    res = playwright_page.evaluate("""() => {
        const svg = document.getElementById('testSvg');
        const inst = window.ClinicVisual.mount(svg, [
            { blueprint: 'pathology_mechanism', title: '落枕筋膜', params: { organ_system: 'joint_spine', organ_label: '頸椎筋膜' } }
        ]);
        inst.renderAt(0.4); // u = 0.05 (< 0.14)
        const earlyHtml = svg.outerHTML;
        inst.renderAt(2.4); // u = 0.30 (>= 0.14)
        const laterHtml = svg.outerHTML;
        return { earlyHtml, laterHtml };
    }""")
    assert "【解剖相對位置定位】" in res["earlyHtml"]
    assert "組織深淺相對層次" in res["earlyHtml"]
    assert "【解剖相對位置定位】" not in res["laterHtml"]
    assert "【器官病理機轉】" in res["laterHtml"]
    assert errors == []


def test_scene2_four_contrast_paradigms(playwright_page, tmp_path):
    """Scene 2 支援 4 種治療差異性結果範式，皆無 NaN/undefined。"""
    errors = _setup_page(playwright_page, tmp_path)
    layouts = [
        ("outcome_fork", "【處置路徑與病程分叉演進】"),
        ("tradeoff_matrix", "【治療方式臨床權衡指標比較】"),
        ("layered_scan", "【同解剖組織分層掃描對比】"),
        ("side_by_side", "VS"),
    ]
    for layout, expected_marker in layouts:
        html = playwright_page.evaluate(f"""() => {{
            const svg = document.getElementById('testSvg');
            const inst = window.ClinicVisual.mount(svg, [
                {{ blueprint: 'contrast', title: '差異比較', params: {{ contrast_layout: '{layout}' }} }}
            ]);
            inst.renderAt(4.0);
            return svg.outerHTML;
        }}""")
        assert expected_marker in html, f"{layout} 應包含 {expected_marker}"
        assert '="NaN"' not in html and '="undefined"' not in html
    assert errors == []


def test_scene3_benefit_curve_and_compliance(playwright_page, tmp_path):
    """Scene 3 繪製平滑修復趨勢帶與生理微動畫，且不含百分比字樣。"""
    errors = _setup_page(playwright_page, tmp_path)
    res = playwright_page.evaluate("""() => {
        const svg = document.getElementById('testSvg');
        const inst = window.ClinicVisual.mount(svg, [
            { blueprint: 'timeline', title: '修復歷程', params: { connectors: 'nerve_regeneration' } }
        ]);
        inst.renderAt(4.0);
        return { html: svg.outerHTML, text: svg.textContent || '' };
    }""")
    assert 'M 110 364 C 260 362, 430 345, 690 338' in res["html"]
    assert "%" not in res["text"] and "％" not in res["text"]
    assert errors == []


def test_narrative_subtitle_and_dynamic_labels_sync(playwright_page, tmp_path):
    """驗證 scene.caption 分段同步字幕條與 scene.labels 動態標籤融入畫布（含警訊色標）。"""
    errors = _setup_page(playwright_page, tmp_path)
    res = playwright_page.evaluate("""() => {
        const svg = document.getElementById('testSvg');
        const inst = window.ClinicVisual.mount(svg, [{
            blueprint: 'pathology_mechanism',
            title: '病理機轉解說',
            caption: '幽門螺旋桿菌定殖於胃竇黏膜，破壞胃黏膜屏障，胃酸侵蝕形成黏膜潰瘍缺損。進食後上腹灼痛，嚴重時出現黑便柏油便，為消化道出血警訊，應儘速就醫檢查。',
            labels: [
                { text: '幽門螺旋桿菌', tone: 'warning' },
                { text: '胃黏膜屏障', tone: 'neutral' }
            ],
            params: { organ_system: 'gi_tract', organ_label: '胃竇黏膜' }
        }]);
        inst.renderAt(0.8); // seg 1 (u = 0.1)
        const s1 = svg.outerHTML;
        inst.renderAt(6.4); // seg 4 (u = 0.8)
        const s2 = svg.outerHTML;
        return { s1, s2 };
    }""")
    assert "1/4" in res["s1"]
    assert "幽門螺旋桿菌定殖於胃竇黏膜" in res["s1"]
    assert "4/4" in res["s2"]
    assert "為消化道出血警訊" in res["s2"]
    assert 'data-subtitle="1"' in res["s2"]
    assert "幽門螺旋桿菌" in res["s2"]
    assert "胃黏膜屏障" in res["s2"]
    assert errors == []


def test_single_period_comma_caption_auto_balances(playwright_page, tmp_path):
    """真實 IR 常見「句內全逗號、結尾單句號」長文應自動平衡切分為 2~3 段且無截斷。"""
    errors = _setup_page(playwright_page, tmp_path)
    res = playwright_page.evaluate("""() => {
        const svg = document.getElementById('testSvg');
        const inst = window.ClinicVisual.mount(svg, [{
            blueprint: 'contrast',
            title: '照護處置對照',
            caption: '延誤就醫持續刺激，潰瘍可能加深並併發出血穿孔，正規處置則根除幽門螺旋桿菌並抑制胃酸，戒菸酒並規律飲食有助減輕胃部負擔。',
            labels: [
                { text: '不良習慣', tone: 'warning' },
                { text: '正規照護', tone: 'optimal' }
            ],
            params: null
        }]);
        inst.renderAt(0.8);  // u = 0.10
        const s1 = svg.outerHTML;
        inst.renderAt(4.0);  // u = 0.50
        const s2 = svg.outerHTML;
        inst.renderAt(7.0);  // u = 0.875
        const s3 = svg.outerHTML;
        return { s1, s2, s3 };
    }""")
    assert "1/3" in res["s1"]
    assert "2/3" in res["s2"]
    assert "3/3" in res["s3"]
    assert "…" not in res["s1"] and "…" not in res["s2"] and "…" not in res["s3"]
    assert errors == []


