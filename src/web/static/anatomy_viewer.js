/**
 * clinicbrain - 3D 臨床解剖 WebGL 檢視器原生組件 (<clinic-anatomy-viewer>)
 * 遵循 docs/anatomy-3d-architecture.md 規格定稿與醫療法規防線：
 * 1. 原生 Web Component 封裝 (Shadow DOM)，零全域 CSS/JS 污染
 * 2. Three.js WebGL 2.0 渲染，離線自託管，零外部網路外連
 * 3. 具備延遲載入 (Lazy Loading)、WebGL context lost 自癒與 2D 向量動畫確定性降級防線
 * 4. 監聽 `anatomy:focus-step` 事件匯流排，平滑相機導航 (Camera Fly-To) 與層次高亮 (Pulse Glow)
 * 5. 嚴格醫療法規防禦：零價格外洩過濾、法定體質差異免責聲明、台灣繁體專科術語
 */

import * as THREE from './anatomy/three.js';
import { GLTFLoader } from './anatomy/GLTFLoader.js';
import { OrbitControls } from './anatomy/OrbitControls.js';

// 法規常駐免責聲明
export const STATUTORY_DISCLAIMER_ZH_TW = '3D 解剖模型僅供衛教輔助參考，解剖結構存在個人體質差異，實際手術計畫以門診醫師親自評估為準。';

// 前端價格遮蔽防線 (雙重保險，後端已有 deep_mask_prices)
export function maskPricesClient(text) {
  if (!text || typeof text !== 'string') return text;
  // 屏蔽 NT$12,000 / $500 / 15,000元 / 3000 元 / 萬等金額
  return text
    .replace(/(?:NT\$|\$)\s*[\d,]+(?:\.\d+)?/gi, '[請致電診所確認]')
    .replace(/[\d,]+(?:\.\d+)?\s*(?:元|萬|千元|萬元)/g, '[請致電診所確認]')
    .replace(/(?:費用|價格|收費|定價)\s*[:：]?\s*[\d,]+/g, '$1：[請致電診所確認]');
}

export class ClinicAnatomyViewer extends HTMLElement {
  static get observedAttributes() {
    return ['doc-id', 'model-src', 'metadata-src', 'auto-rotate', 'force-fallback'];
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });

    // 狀態
    this._initialized = false;
    this._isLoading = false;
    this._isFallback2D = false;
    this._metadata = null;
    this._currentStep = null;
    this._animationFrameId = null;

    // Three.js 實例
    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.controls = null;
    this.modelRoot = null;
    this.highlightMaterials = new Map();

    // 相機動畫參數
    this._cameraTargetPos = null;
    this._cameraTargetLookAt = null;
    this._cameraLerpFactor = 0.08;

    // 綁定事件
    this._onFocusStep = this._onFocusStep.bind(this);
    this._onWindowResize = this._onWindowResize.bind(this);
    this._animate = this._animate.bind(this);
  }

  connectedCallback() {
    this._renderBaseLayout();
    window.addEventListener('anatomy:focus-step', this._onFocusStep);
    window.addEventListener('resize', this._onWindowResize);

    if (this.getAttribute('force-fallback') === 'true') {
      this.switchTo2DFallback('用戶手動或測試指定 2D 降級模式');
      return;
    }

    // 延遲載入 (Lazy Load)
    if ('IntersectionObserver' in window) {
      this._observer = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && !this._initialized) {
          this._initViewer();
          this._observer.disconnect();
        }
      }, { threshold: 0.1 });
      this._observer.observe(this);
    } else {
      this._initViewer();
    }
  }

  disconnectedCallback() {
    window.removeEventListener('anatomy:focus-step', this._onFocusStep);
    window.removeEventListener('resize', this._onWindowResize);
    if (this._observer) this._observer.disconnect();
    this._disposeThree();
  }

  attributeChangedCallback(name, oldValue, newValue) {
    if (oldValue === newValue) return;
    if (name === 'force-fallback') {
      if (newValue === 'true') {
        this.switchTo2DFallback('屬性切換至 2D 備援');
      } else if (oldValue === 'true' && this._initialized) {
        this._renderBaseLayout();
        this._initViewer();
      }
    } else if (name === 'doc-id' && this._initialized) {
      this.loadAnatomyForDoc(newValue);
    }
  }

  _renderBaseLayout() {
    const shadow = this.shadowRoot;
    shadow.innerHTML = `
      <style>
        :host {
          display: block;
          position: relative;
          width: 100%;
          height: 100%;
          min-height: 420px;
          background: #0f172a;
          border-radius: 12px;
          overflow: hidden;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
          color: #f8fafc;
          user-select: none;
        }
        .canvas-container {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        canvas {
          width: 100% !important;
          height: 100% !important;
          display: block;
        }
        .ui-layer {
          position: absolute;
          inset: 0;
          pointer-events: none;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          padding: 14px;
          box-sizing: border-box;
        }
        .header-bar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          pointer-events: auto;
        }
        .badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 4px 10px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 600;
          letter-spacing: 0.5px;
          background: rgba(15, 23, 42, 0.75);
          backdrop-filter: blur(8px);
          border: 1px solid rgba(255, 255, 255, 0.12);
        }
        .badge-live {
          color: #38bdf8;
          border-color: rgba(56, 189, 248, 0.3);
        }
        .controls-bar {
          display: flex;
          gap: 8px;
        }
        .btn-tool {
          background: rgba(15, 23, 42, 0.75);
          border: 1px solid rgba(255, 255, 255, 0.15);
          color: #e2e8f0;
          padding: 6px 10px;
          border-radius: 6px;
          font-size: 12px;
          cursor: pointer;
          backdrop-filter: blur(8px);
          transition: all 0.2s;
        }
        .btn-tool:hover {
          background: rgba(30, 41, 59, 0.9);
          border-color: #38bdf8;
          color: #38bdf8;
        }
        .tooltip-card {
          pointer-events: auto;
          background: rgba(15, 23, 42, 0.85);
          backdrop-filter: blur(12px);
          border: 1px solid rgba(56, 189, 248, 0.3);
          border-radius: 8px;
          padding: 12px 14px;
          max-width: 320px;
          box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
          transition: all 0.3s ease;
          opacity: 0;
          transform: translateY(10px);
        }
        .tooltip-card.visible {
          opacity: 1;
          transform: translateY(0);
        }
        .tooltip-title {
          font-size: 13px;
          font-weight: 700;
          color: #38bdf8;
          margin-bottom: 4px;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .tooltip-desc {
          font-size: 12px;
          color: #cbd5e1;
          line-height: 1.5;
        }
        .footer-disclaimer {
          pointer-events: auto;
          font-size: 11px;
          color: #94a3b8;
          background: rgba(15, 23, 42, 0.8);
          backdrop-filter: blur(8px);
          padding: 6px 10px;
          border-radius: 6px;
          border: 1px solid rgba(255, 255, 255, 0.08);
          align-self: center;
          text-align: center;
          max-width: 90%;
        }
        .loading-overlay {
          position: absolute;
          inset: 0;
          background: #0f172a;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 12px;
          z-index: 10;
          transition: opacity 0.4s ease;
        }
        .loading-overlay.hidden {
          opacity: 0;
          pointer-events: none;
        }
        .spinner {
          width: 32px;
          height: 32px;
          border: 3px solid rgba(56, 189, 248, 0.2);
          border-top-color: #38bdf8;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        .fallback-container {
          position: absolute;
          inset: 0;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          background: #090d16;
          padding: 20px;
          text-align: center;
          z-index: 5;
        }
        .fallback-canvas {
          max-width: 100%;
          max-height: 280px;
          border-radius: 8px;
          border: 1px solid rgba(255, 255, 255, 0.1);
          background: #020617;
        }
      </style>

      <div class="canvas-container" id="container">
        <!-- WebGL Canvas or Fallback -->
      </div>

      <div class="loading-overlay" id="loader">
        <div class="spinner"></div>
        <div style="font-size: 12px; color: #94a3b8;">載入 3D 臨床解剖模型中...</div>
      </div>

      <div class="ui-layer">
        <div class="header-bar">
          <div class="badge badge-live" id="targetBadge">
            <span>🧬</span>
            <span id="targetName">臨床解剖定位</span>
          </div>
          <div class="controls-bar">
            <button class="btn-tool" id="btnResetView" title="重設相機視角">⟲ 重設視角</button>
            <button class="btn-tool" id="btnToggle2D" title="切換 2D/3D 模式">⚡ 2D 備援</button>
          </div>
        </div>

        <div class="tooltip-card" id="tooltipCard">
          <div class="tooltip-title" id="tooltipTitle">解剖層次提示</div>
          <div class="tooltip-desc" id="tooltipDesc">點選臨床步驟以檢視對應立體結構與安全邊界。</div>
        </div>

        <div class="footer-disclaimer" id="disclaimer">
          ⚠️ ${STATUTORY_DISCLAIMER_ZH_TW}
        </div>
      </div>
    `;

    // 綁定 UI 按鈕
    shadow.getElementById('btnResetView')?.addEventListener('click', () => this.resetCamera());
    shadow.getElementById('btnToggle2D')?.addEventListener('click', () => {
      if (this._isFallback2D) {
        this.setAttribute('force-fallback', 'false');
        this._renderBaseLayout();
        this._initViewer();
      } else {
        this.switchTo2DFallback('使用者手動切換 2D 向量動畫視圖');
      }
    });
  }

  async _initViewer() {
    if (this._initialized || this._isFallback2D) return;
    const shadow = this.shadowRoot;
    const container = shadow.getElementById('container');
    const loader = shadow.getElementById('loader');

    // 1. 檢查 WebGL 支援
    if (!this._isWebGLAvailable()) {
      this.switchTo2DFallback('瀏覽器或環境不支援 WebGL 2.0');
      return;
    }

    try {
      this._isLoading = true;
      const width = container.clientWidth || 600;
      const height = container.clientHeight || 420;

      // 2. 建立場景與相機
      this.scene = new THREE.Scene();
      this.scene.background = new THREE.Color(0x0f172a);

      this.camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
      this.camera.position.set(0, 1.2, 5.0);

      // 3. 建立 WebGLRenderer
      this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
      this.renderer.setSize(width, height);
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      this.renderer.outputColorSpace = THREE.SRGBColorSpace;
      container.appendChild(this.renderer.domElement);

      // 4. WebGL Context Lost 監聽自癒
      const glCanvas = this.renderer.domElement;
      glCanvas.addEventListener('webglcontextlost', (e) => {
        e.preventDefault();
        console.warn('[ClinicAnatomyViewer] WebGL Context Lost 觸發！');
        this.switchTo2DFallback('WebGL 上下文丟失，自動降級至 2D 向量解說卡');
      }, false);

      glCanvas.addEventListener('webglcontextrestored', () => {
        console.info('[ClinicAnatomyViewer] WebGL Context 恢復！');
        this._disposeThree();
        this._renderBaseLayout();
        this._initViewer();
      }, false);

      // 5. 軌道控制器 (OrbitControls)
      this.controls = new OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.05;
      this.controls.maxDistance = 15;
      this.controls.minDistance = 1.0;

      // 6. 光影系統 (環境光 + 雙向主輔光)
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.85);
      this.scene.add(ambientLight);

      const keyLight = new THREE.DirectionalLight(0x38bdf8, 1.2);
      keyLight.position.set(3, 4, 3);
      this.scene.add(keyLight);

      const fillLight = new THREE.DirectionalLight(0xf43f5e, 0.6);
      fillLight.position.set(-3, -2, -2);
      this.scene.add(fillLight);

      // 7. 載入模型與配置
      await this._loadModel();

      // 8. 載入並套用元資料 (若有)
      const docId = this.getAttribute('doc-id');
      if (docId) {
        await this.loadAnatomyForDoc(docId);
      }

      this._initialized = true;
      loader.classList.add('hidden');

      // 啟動渲染迴圈
      this._animate();
    } catch (err) {
      console.error('[ClinicAnatomyViewer] 初始化渲染失敗:', err);
      this.switchTo2DFallback(`3D 模組初始化失敗: ${err.message}`);
    } finally {
      this._isLoading = false;
    }
  }

  _isWebGLAvailable() {
    try {
      const canvas = document.createElement('canvas');
      return !!(window.WebGL2RenderingContext && canvas.getContext('webgl2')) ||
             !!(window.WebGLRenderingContext && (canvas.getContext('webgl') || canvas.getContext('experimental-webgl')));
    } catch {
      return false;
    }
  }

  async _loadModel() {
    const modelSrc = this.getAttribute('model-src') || '/static/anatomy/neurovascular.glb';
    const loader = new GLTFLoader();

    return new Promise((resolve, reject) => {
      loader.load(
        modelSrc,
        (gltf) => {
          this.modelRoot = gltf.scene;

          // 自動居中與縮放標準化
          const box = new THREE.Box3().setFromObject(this.modelRoot);
          const center = box.getCenter(new THREE.Vector3());
          const size = box.getSize(new THREE.Vector3());
          const maxDim = Math.max(size.x, size.y, size.z);

          this.modelRoot.position.sub(center);
          if (maxDim > 0) {
            const scale = 2.5 / maxDim;
            this.modelRoot.scale.setScalar(scale);
          }

          // 遍歷所有網格保存原始材質備份
          this.modelRoot.traverse((child) => {
            if (child.isMesh) {
              child.castShadow = false;
              child.receiveShadow = false;
              if (child.material) {
                // 複製原材質
                child.userData.originalMaterial = child.material.clone();
              }
            }
          });

          this.scene.add(this.modelRoot);
          resolve();
        },
        undefined,
        (err) => {
          console.warn(`[ClinicAnatomyViewer] GLTF 載入失敗 (${modelSrc}):`, err);
          // 若特定模型無法載入，回退至備用輕量網格或純幾何
          this._createProceduralFallbackMesh();
          resolve();
        }
      );
    });
  }

  _createProceduralFallbackMesh() {
    const group = new THREE.Group();
    // 建立頜面 / 筋膜層示意幾何球體與神經血管層
    const jawGeo = new THREE.CylinderGeometry(1.2, 0.9, 1.8, 32);
    const jawMat = new THREE.MeshStandardMaterial({
      color: 0x334155,
      roughness: 0.4,
      metalness: 0.1,
      transparent: true,
      opacity: 0.75
    });
    const jawMesh = new THREE.Mesh(jawGeo, jawMat);
    jawMesh.name = 'mesh_smas_layer';
    group.add(jawMesh);

    // 神經血管束示意環
    const nerveGeo = new THREE.TorusGeometry(1.1, 0.05, 16, 64);
    const nerveMat = new THREE.MeshStandardMaterial({
      color: 0xef4444,
      emissive: 0x991b1b,
      emissiveIntensity: 0.5
    });
    const nerveMesh = new THREE.Mesh(nerveGeo, nerveMat);
    nerveMesh.name = 'nerve_marginal_mandibular';
    nerveMesh.rotation.x = Math.PI / 2;
    group.add(nerveMesh);

    this.modelRoot = group;
    this.scene.add(this.modelRoot);
  }

  async loadAnatomyForDoc(docId) {
    if (!docId) return;
    try {
      const metadataSrc = this.getAttribute('metadata-src') || `/api/v1/visual/anatomy/${encodeURIComponent(docId)}`;
      const resp = await fetch(metadataSrc);
      if (resp.ok) {
        const data = await resp.json();
        this.setMetadata(data);
      }
    } catch (e) {
      console.warn(`[ClinicAnatomyViewer] 無法取得 ${docId} 之解剖中繼資料:`, e);
    }
  }

  setMetadata(metadata) {
    if (!metadata) return;
    this._metadata = metadata;
    const shadow = this.shadowRoot;

    // 更新標籤
    const badgeName = shadow.getElementById('targetName');
    if (badgeName) {
      badgeName.textContent = metadata.specialty_zh || metadata.anatomy_target || '臨床解剖定位';
    }

    // 若有初始相機配置
    if (metadata.camera) {
      const cam = metadata.camera;
      if (cam.default_position) {
        this.camera.position.set(...cam.default_position);
      }
      if (cam.target) {
        this.controls.target.set(...cam.target);
      }
      this.controls.update();
    }
  }

  _onFocusStep(event) {
    const detail = event.detail || {};
    const { doc_id, step_key } = detail;
    const curDoc = this.getAttribute('doc-id');

    if (doc_id && curDoc && doc_id !== curDoc) {
      // 跨療程更新
      this.setAttribute('doc-id', doc_id);
    }

    this.focusStep(step_key, detail);
  }

  focusStep(stepKey, overrideDetail = {}) {
    if (!this._initialized && !this._isFallback2D) {
      this._currentStep = stepKey;
      return;
    }

    // 取得該步驟之解剖設定
    let stepConfig = null;
    if (this._metadata && Array.isArray(this._metadata.interactive_steps)) {
      stepConfig = this._metadata.interactive_steps.find((s) => s.step_key === stepKey);
    }

    const action = overrideDetail.action || (stepConfig ? stepConfig.action : 'highlight_layer');
    const targetMesh = overrideDetail.target_mesh || (stepConfig ? stepConfig.target_mesh : null);
    const glowColor = overrideDetail.glow_color || (stepConfig ? stepConfig.glow_color : '#38bdf8');
    const rawCaption = overrideDetail.caption || (stepConfig ? stepConfig.caption : `聚焦章節：${stepKey}`);
    const caption = maskPricesClient(rawCaption);

    // 1. 更新 Tooltip 內容
    const shadow = this.shadowRoot;
    const tooltipCard = shadow.getElementById('tooltipCard');
    const tooltipTitle = shadow.getElementById('tooltipTitle');
    const tooltipDesc = shadow.getElementById('tooltipDesc');

    if (tooltipCard && tooltipTitle && tooltipDesc) {
      const isWarning = action === 'warning_zone';
      tooltipTitle.innerHTML = isWarning
        ? `<span style="color: #f43f5e;">⚠️ 安全警告區</span>`
        : `<span style="color: #38bdf8;">🎯 解剖作用層次</span>`;
      tooltipDesc.textContent = caption;
      tooltipCard.classList.add('visible');
    }

    // 2. 若處於 2D 備援模式，直接派發 2D 場景渲染
    if (this._isFallback2D) {
      this._render2DFallbackStep(stepKey, action, caption);
      return;
    }

    // 3. 3D WebGL 模式：相機飛越 (Camera Fly-To)
    if (stepConfig && stepConfig.camera_fly_to) {
      const zoom = stepConfig.camera_fly_to.zoom || 1.8;
      this._cameraTargetPos = new THREE.Vector3(
        this.camera.position.x * (1 / zoom),
        this.camera.position.y * (1 / zoom),
        this.camera.position.z * (1 / zoom)
      );
    }

    // 4. 網格層次高亮 / 脈衝發光
    this._highlightMesh(targetMesh, glowColor, action === 'warning_zone');
  }

  _highlightMesh(targetMeshName, colorHex, isWarning = false) {
    if (!this.modelRoot) return;

    const highlightColor = new THREE.Color(colorHex || (isWarning ? 0xff4d4f : 0x38bdf8));

    this.modelRoot.traverse((child) => {
      if (child.isMesh) {
        const matches = !targetMeshName || child.name.includes(targetMeshName) || (child.name === targetMeshName);

        if (matches) {
          // 套用發光高亮材質
          child.material = new THREE.MeshStandardMaterial({
            color: highlightColor,
            emissive: highlightColor,
            emissiveIntensity: 0.8,
            roughness: 0.2,
            metalness: 0.3,
            transparent: true,
            opacity: 0.9
          });
        } else if (child.userData.originalMaterial) {
          // 非目標網格降低透明度，突顯核心
          child.material = child.userData.originalMaterial.clone();
          child.material.transparent = true;
          child.material.opacity = 0.35;
        }
      }
    });
  }

  resetCamera() {
    if (!this.camera || !this.controls) return;
    this._cameraTargetPos = new THREE.Vector3(0, 1.2, 5.0);
    this.controls.target.set(0, 0, 0);

    // 恢復所有材質
    if (this.modelRoot) {
      this.modelRoot.traverse((child) => {
        if (child.isMesh && child.userData.originalMaterial) {
          child.material = child.userData.originalMaterial.clone();
        }
      });
    }

    // 隱藏 Tooltip
    const tooltip = this.shadowRoot.getElementById('tooltipCard');
    if (tooltip) tooltip.classList.remove('visible');
  }

  switchTo2DFallback(reason = '環境降級') {
    this._isFallback2D = true;
    this._disposeThree();

    const shadow = this.shadowRoot;
    const container = shadow.getElementById('container');
    const loader = shadow.getElementById('loader');
    if (loader) loader.classList.add('hidden');

    const badge = shadow.getElementById('targetBadge');
    if (badge) {
      badge.className = 'badge';
      badge.style.color = '#eab308';
      badge.style.borderColor = 'rgba(234, 179, 8, 0.4)';
    }
    const badgeName = shadow.getElementById('targetName');
    if (badgeName) badgeName.textContent = '2D 確定性向量解說卡 (備援防線)';

    const toggleBtn = shadow.getElementById('btnToggle2D');
    if (toggleBtn) toggleBtn.textContent = '🎲 嘗試 3D 視圖';

    container.innerHTML = `
      <div class="fallback-container">
        <div style="font-size: 13px; color: #facc15; margin-bottom: 8px;">
          ⚡ 已切換至 2D 確定性向量動畫防線（${reason}）
        </div>
        <canvas class="fallback-canvas" id="fallback2DCanvas" width="640" height="360"></canvas>
      </div>
    `;

    this._render2DFallbackStep('procedure', 'highlight_layer', '以 2D 幾何向量呈現臨床治療深度與安全解剖邊界。');
  }

  _render2DFallbackStep(stepKey, action, caption) {
    const canvas = this.shadowRoot.getElementById('fallback2DCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;

    // 清空背景
    ctx.fillStyle = '#090d16';
    ctx.fillRect(0, 0, w, h);

    // 繪製解剖剖面示意圖 (表皮 -> 真皮 -> 皮下脂肪 -> SMAS筋膜 -> 肌肉)
    const layers = [
      { name: '表皮層 (Epidermis, 0.1mm)', color: '#fed7aa', y: 40, h: 25 },
      { name: '真皮層 (Dermis, 1.5mm)', color: '#fdba74', y: 70, h: 40 },
      { name: '皮下脂肪層 (Subcutaneous Fat, 3.0mm)', color: '#fef08a', y: 115, h: 55 },
      { name: '淺筋膜層 (SMAS Layer, 4.5mm)', color: '#38bdf8', y: 175, h: 30, isTarget: true },
      { name: '深層肌肉與神經走行區 (Deep Muscle & Nerve)', color: '#f87171', y: 210, h: 65, isWarning: true }
    ];

    layers.forEach((layer) => {
      ctx.fillStyle = layer.color;
      ctx.globalAlpha = layer.isTarget ? 0.95 : 0.4;
      ctx.fillRect(60, layer.y, w - 120, layer.h);

      ctx.strokeStyle = layer.isTarget ? '#38bdf8' : (layer.isWarning ? '#ef4444' : '#64748b');
      ctx.lineWidth = layer.isTarget ? 2 : 1;
      ctx.strokeRect(60, layer.y, w - 120, layer.h);

      ctx.globalAlpha = 1.0;
      ctx.fillStyle = '#f8fafc';
      ctx.font = 'bold 12px sans-serif';
      ctx.fillText(layer.name, 75, layer.y + layer.h / 2 + 4);
    });

    // 繪製治療探頭聚焦點或穿透向量
    ctx.fillStyle = '#38bdf8';
    ctx.beginPath();
    ctx.arc(w / 2, 190, 8, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = '#38bdf8';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(w / 2, 20);
    ctx.lineTo(w / 2, 190);
    ctx.stroke();
    ctx.setLineDash([]);

    // 步驟解說文字
    ctx.fillStyle = '#94a3b8';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(`【當前步驟：${stepKey}】 ${caption}`, w / 2, h - 25);
  }

  _animate() {
    if (this._isFallback2D) return;
    this._animationFrameId = requestAnimationFrame(this._animate);

    // 平滑相機 Lerp 飛躍
    if (this._cameraTargetPos && this.camera) {
      this.camera.position.lerp(this._cameraTargetPos, this._cameraLerpFactor);
      if (this.camera.position.distanceTo(this._cameraTargetPos) < 0.05) {
        this._cameraTargetPos = null;
      }
    }

    // 自動微緩旋轉 (若開啟 auto-rotate)
    if (this.getAttribute('auto-rotate') === 'true' && this.modelRoot) {
      this.modelRoot.rotation.y += 0.003;
    }

    if (this.controls) this.controls.update();
    if (this.renderer && this.scene && this.camera) {
      this.renderer.render(this.scene, this.camera);
    }
  }

  _onWindowResize() {
    if (!this._initialized || this._isFallback2D) return;
    const container = this.shadowRoot.getElementById('container');
    if (!container || !this.renderer || !this.camera) return;

    const width = container.clientWidth || 600;
    const height = container.clientHeight || 420;

    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  _disposeThree() {
    if (this._animationFrameId) {
      cancelAnimationFrame(this._animationFrameId);
      this._animationFrameId = null;
    }
    if (this.controls) {
      this.controls.dispose();
      this.controls = null;
    }
    if (this.renderer) {
      this.renderer.dispose();
      this.renderer.forceContextLoss();
      this.renderer.domElement?.remove();
      this.renderer = null;
    }
    this.scene = null;
    this.camera = null;
    this.modelRoot = null;
    this._initialized = false;
  }
}

// 註冊自定義元素
if (typeof customElements !== 'undefined' && !customElements.get('clinic-anatomy-viewer')) {
  customElements.define('clinic-anatomy-viewer', ClinicAnatomyViewer);
}
