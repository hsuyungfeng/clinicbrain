"""
tests/test_anatomy_viewer.py - Phase 45 3D 臨床解剖檢視組件與 PageIndex 聯動測試

驗證項目：
1. 解剖目錄 (anatomy_catalog) 結構契約、步驟定義與預設降級
2. 醫療法規防線：deep_mask_prices() 價格清洗、無外洩、法定免責聲明、正體中文
3. FastAPI 端點：GET /api/v1/visual/anatomy/{doc_id} 與 GET /api/v1/visual/anatomy/catalog
4. 靜態資源本地託管 (Fail-Closed Offline Security)：Three.js 核心與 GLTF 3D 網格本機伺服
5. 前端組件自定義元素標記與 2D 降級備援機制合規性
"""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import re

from src.api.app import app
from src.visual.anatomy_catalog import (
    ANATOMY_CATALOG,
    DEFAULT_ANATOMY_METADATA,
    STATUTORY_ANATOMY_DISCLAIMER_ZH_TW,
    get_anatomy_metadata,
)
from src.api.routes.query import deep_mask_prices


@pytest.fixture
def client():
    return TestClient(app)


class TestAnatomyCatalog:
    """測試 3D 解剖目錄與 PageIndex 關聯資料契約。"""

    def test_catalog_entries_completeness(self):
        """驗證專科核心療程均具備完整相機視角與四段式互動步驟。"""
        assert "hifu-lifting" in ANATOMY_CATALOG
        assert "blepharoplasty" in ANATOMY_CATALOG
        assert "rhinoplasty" in ANATOMY_CATALOG
        assert "dental-implant" in ANATOMY_CATALOG

        for doc_id, meta in ANATOMY_CATALOG.items():
            assert meta["doc_id"] == doc_id
            assert "anatomy_target" in meta
            assert "specialty_zh" in meta
            assert "camera" in meta
            assert "default_position" in meta["camera"]
            assert "target" in meta["camera"]

            steps = meta.get("interactive_steps", [])
            assert len(steps) >= 3, f"{doc_id} 步驟不足 3 步"
            step_keys = {s["step_key"] for s in steps}
            assert "procedure" in step_keys
            assert "pre_op" in step_keys

            for s in steps:
                assert "action" in s
                assert "caption" in s
                assert len(s["caption"]) > 5

    def test_get_anatomy_metadata_known(self):
        """查詢已知 doc_id 回傳結構化資料且帶有法定免責聲明。"""
        meta = get_anatomy_metadata("hifu-lifting")
        assert meta["doc_id"] == "hifu-lifting"
        assert meta["anatomy_target"] == "facial_smas"
        assert meta["disclaimer"] == STATUTORY_ANATOMY_DISCLAIMER_ZH_TW
        assert "個人體質差異" in meta["disclaimer"]

    def test_canonicalize_prefix_and_synonyms(self):
        """驗證機構代碼前綴 (如 3503264627-paronychia-matrixectomy) 與別名自動對應。"""
        meta_prefix = get_anatomy_metadata("3503264627-paronychia-matrixectomy")
        assert meta_prefix["anatomy_target"] == "nail_germinal_matrix"
        assert "甲床" in meta_prefix["specialty_zh"]

        meta_pico = get_anatomy_metadata("picosecond-laser-rejuvenation")
        assert meta_pico["anatomy_target"] == "epidermal_dermal_junction"

    def test_get_anatomy_metadata_unknown_fallback(self):
        """查詢未知 doc_id 保守回傳預設通用解剖設定（Fail-Safe）。"""
        meta = get_anatomy_metadata("non-existent-surgery-xyz")
        assert meta["doc_id"] == "default-general"
        assert meta["anatomy_target"] == "general_head_neck"
        assert meta["disclaimer"] == STATUTORY_ANATOMY_DISCLAIMER_ZH_TW
        assert len(meta["interactive_steps"]) >= 4

    def test_statutory_disclaimer_content(self):
        """驗證免責聲明符合醫療法規核心要件。"""
        disclaimer = STATUTORY_ANATOMY_DISCLAIMER_ZH_TW
        assert "3D 解剖模型僅供衛教輔助參考" in disclaimer
        assert "個人體質差異" in disclaimer
        assert "門診醫師親自評估" in disclaimer


class TestLegalComplianceAndPriceMasking:
    """測試醫療法規防禦線：零價格洩漏與繁體中文規範。"""

    def test_deep_mask_prices_on_anatomy_metadata(self):
        """驗證即使來源注入價格，經過 get_anatomy_metadata 後亦 100% 遮蔽。"""
        # 構造帶價格的假資料
        dirty_meta = {
            "doc_id": "test-price",
            "interactive_steps": [
                {"caption": "本療程定價 NT$ 38000，局部麻醉另收 5000元。"},
                {"caption": "特惠價格：$12000，維持 18 個月。"}
            ]
        }
        cleaned = deep_mask_prices(dirty_meta)
        for s in cleaned["interactive_steps"]:
            cap = s["caption"]
            assert "38000" not in cap
            assert "5000" not in cap
            assert "12000" not in cap
            assert "[請致電診所確認]" in cap

    def test_traditional_chinese_terminology(self):
        """驗證解剖目錄全部使用正體中文專有名詞，杜絕未校準簡體。"""
        simplified_pattern = re.compile(r"[医肤术挛颚脸颅]")
        for doc_id, meta in ANATOMY_CATALOG.items():
            for s in meta.get("interactive_steps", []):
                caption = s["caption"]
                match = simplified_pattern.search(caption)
                assert match is None, f"{doc_id} 發現簡體字符: {match.group(0)} in {caption}"


class TestApiEndpoints:
    """測試 FastAPI 視覺與解剖端點。"""

    def test_get_catalog_endpoint(self, client):
        """GET /api/v1/visual/anatomy/catalog"""
        resp = client.get("/api/v1/visual/anatomy/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert data["total"] >= 4
        assert "catalog" in data
        assert "disclaimer" in data
        doc_ids = [item["doc_id"] for item in data["catalog"]]
        assert "hifu-lifting" in doc_ids
        assert "dental-implant" in doc_ids

    def test_get_anatomy_by_doc_id_endpoint(self, client):
        """GET /api/v1/visual/anatomy/hifu-lifting"""
        resp = client.get("/api/v1/visual/anatomy/hifu-lifting")
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == "hifu-lifting"
        assert data["anatomy_target"] == "facial_smas"
        assert "camera" in data
        assert "interactive_steps" in data
        assert data["disclaimer"] == STATUTORY_ANATOMY_DISCLAIMER_ZH_TW

    def test_get_anatomy_empty_doc_id(self, client):
        """GET /api/v1/visual/anatomy/ 空字串回傳 400 或 404"""
        resp = client.get("/api/v1/visual/anatomy/%20")
        assert resp.status_code == 400


class TestStaticAssetsOfflineHosting:
    """測試 3D 靜態資產本地離線託管 (Fail-Closed Offline Security)。"""

    def test_static_anatomy_files_exist_on_disk(self):
        """確認核心 WebGL 腳本與 3D GLB 網格存於本地靜態目錄。"""
        static_dir = Path("src/web/static/anatomy")
        assert static_dir.exists(), "src/web/static/anatomy/ 不存在"
        assert (static_dir / "three.js").exists(), "three.js 不存在"
        assert (static_dir / "GLTFLoader.js").exists(), "GLTFLoader.js 不存在"
        assert (static_dir / "OrbitControls.js").exists(), "OrbitControls.js 不存在"
        assert (static_dir / "neurovascular.glb").exists(), "neurovascular.glb 不存在"
        assert (static_dir / "context.glb").exists(), "context.glb 不存在"

    def test_static_mesh_size_budget(self):
        """網格資產體積嚴格受控於 3MB 以內 (docs/anatomy-3d-architecture.md)。"""
        mesh1 = Path("src/web/static/anatomy/neurovascular.glb")
        mesh2 = Path("src/web/static/anatomy/context.glb")
        total_mesh_bytes = mesh1.stat().st_size + mesh2.stat().st_size
        max_budget = 3 * 1024 * 1024  # 3MB
        assert total_mesh_bytes < max_budget, f"3D 網格包超過 3MB: {total_mesh_bytes} bytes"

    def test_static_serving_via_fastapi(self, client):
        """驗證靜態資源可由 FastAPI 離線提供服務，無需外部 CDN。"""
        res_three = client.get("/static/anatomy/three.js")
        assert res_three.status_code == 200
        assert len(res_three.content) > 100_000

        res_glb = client.get("/static/anatomy/neurovascular.glb")
        assert res_glb.status_code == 200
        assert len(res_glb.content) > 100_000

        res_viewer = client.get("/static/anatomy_viewer.js")
        assert res_viewer.status_code == 200
        assert b"clinic-anatomy-viewer" in res_viewer.content


class TestWebComponentIntegrity:
    """測試 <clinic-anatomy-viewer> 組件代碼規範與 2D 降級防線。"""

    def test_viewer_js_custom_element_registration(self):
        """確認組件正確註冊 customElements 與 Shadow DOM。"""
        viewer_js = Path("src/web/static/anatomy_viewer.js").read_text(encoding="utf-8")
        assert "customElements.define('clinic-anatomy-viewer'" in viewer_js
        assert "this.attachShadow({ mode: 'open' })" in viewer_js
        assert "STATUTORY_DISCLAIMER_ZH_TW" in viewer_js

    def test_viewer_js_webgl_context_loss_and_2d_fallback(self):
        """確認組件實裝 webglcontextlost 監聽與 switchTo2DFallback 降級備援。"""
        viewer_js = Path("src/web/static/anatomy_viewer.js").read_text(encoding="utf-8")
        assert "webglcontextlost" in viewer_js
        assert "webglcontextrestored" in viewer_js
        assert "switchTo2DFallback" in viewer_js
        assert "fallback2DCanvas" in viewer_js

    def test_viewer_js_event_bus_listening(self):
        """確認組件監聽 anatomy:focus-step 事件並實施相機導航。"""
        viewer_js = Path("src/web/static/anatomy_viewer.js").read_text(encoding="utf-8")
        assert "anatomy:focus-step" in viewer_js
        assert "focusStep" in viewer_js
        assert "maskPricesClient" in viewer_js
