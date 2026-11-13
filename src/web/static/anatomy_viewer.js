/**
 * clinicbrain - 3D 臨床解剖 WebGL 檢視器原生組件 (<clinic-anatomy-viewer>)
 * 遵循 docs/anatomy-3d-architecture.md 規格定稿與醫療法規防線：
 * 1. 原生 Web Component 封裝 (Shadow DOM)，零全域 CSS/JS 污染
 * 2. Three.js WebGL 2.0 渲染，離線自託管，零外部網路外連
 * 3. 專科 3D 結構多樣化：依據療程自動建構專屬 3D 解剖模型（甲溝炎甲床趾骨、頂漿腺狐臭層面、粉瘤上皮囊壁、皮秒雷射黑色素、SMAS 淺筋膜神經網）
 * 4. 具備延遲載入 (Lazy Loading)、WebGL context lost 自癒與 2D 向量動畫確定性降級防線
 * 5. 監聽 `anatomy:focus-step` 事件匯流排，平滑相機導航 (Camera Fly-To) 與層次高亮 (Pulse Glow)
 * 6. 嚴格醫療法規防禦：零價格外洩過濾、法定體質差異免責聲明、台灣繁體專科術語
 */

import * as THREE from './anatomy/three.js';
import { GLTFLoader } from './anatomy/GLTFLoader.js';
import { OrbitControls } from './anatomy/OrbitControls.js';

// 法規常駐免責聲明
export const STATUTORY_DISCLAIMER_ZH_TW = '3D 解剖模型僅供衛教輔助參考，解剖結構存在個人體質差異，實際手術計畫以門診醫師親自評估為準。';

// 前端價格遮蔽防線 (雙重保險，後端已有 deep_mask_prices)
export function maskPricesClient(text) {
  if (!text || typeof text !== 'string') return text;
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
          background: #0b1120;
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
          max-width: 340px;
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
          background: #0b1120;
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

      <div class="canvas-container" id="container"></div>

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

    if (!this._isWebGLAvailable()) {
      this.switchTo2DFallback('瀏覽器或環境不支援 WebGL 2.0');
      return;
    }

    try {
      this._isLoading = true;
      const width = container.clientWidth || 600;
      const height = container.clientHeight || 420;

      this.scene = new THREE.Scene();
      this.scene.background = new THREE.Color(0x0b1120);

      this.camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
      this.camera.position.set(0, 1.2, 5.0);

      this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
      this.renderer.setSize(width, height);
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      this.renderer.outputColorSpace = THREE.SRGBColorSpace;
      container.appendChild(this.renderer.domElement);

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

      this.controls = new OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.05;
      this.controls.maxDistance = 15;
      this.controls.minDistance = 0.8;

      // 光影系統
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.9);
      this.scene.add(ambientLight);

      const keyLight = new THREE.DirectionalLight(0x38bdf8, 1.4);
      keyLight.position.set(4, 5, 4);
      this.scene.add(keyLight);

      const fillLight = new THREE.DirectionalLight(0xf43f5e, 0.7);
      fillLight.position.set(-4, -3, -2);
      this.scene.add(fillLight);

      // 1. 先載入並套用解剖中繼資料 (取得該療程特定的相機視角與解剖目標)
      const docId = this.getAttribute('doc-id');
      if (docId) {
        await this.loadAnatomyForDoc(docId);
      }

      // 2. 依據專科目標載入專屬 3D 結構模型
      await this._loadModel();

      this._initialized = true;
      loader.classList.add('hidden');

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
    const target = (this._metadata && this._metadata.anatomy_target) || 'facial_smas';

    // 專科客製 3D 解剖模型：若非顱顏大體模型，直接建構生動逼真的專屬立體器官/組織結構
    if (
      target === 'nail_germinal_matrix' ||
      target === 'apocrine_gland_dermal_junction' ||
      target === 'epidermoid_cyst_capsule' ||
      target === 'epidermal_dermal_junction' ||
      target === 'neuromuscular_junction'
    ) {
      this._createSpecialty3DAnatomyMesh(target);
      return;
    }

    // 顱顏／骨骼／神經專科模型：自本地離線載入 GLTF 網格
    let modelSrc = this.getAttribute('model-src') || (this._metadata && this._metadata.model_src);
    if (!modelSrc) {
      modelSrc = '/admin/anatomy/neurovascular.glb';
    } else if (modelSrc.startsWith('/static/')) {
      // 相容 /admin/ 與 /static/
      modelSrc = modelSrc.replace('/static/', '/admin/');
    }

    const loader = new GLTFLoader();
    return new Promise((resolve) => {
      loader.load(
        modelSrc,
        (gltf) => {
          this.modelRoot = gltf.scene;
          const box = new THREE.Box3().setFromObject(this.modelRoot);
          const center = box.getCenter(new THREE.Vector3());
          const size = box.getSize(new THREE.Vector3());
          const maxDim = Math.max(size.x, size.y, size.z);

          this.modelRoot.position.sub(center);
          if (maxDim > 0) {
            const scale = 2.6 / maxDim;
            this.modelRoot.scale.setScalar(scale);
          }

          this.modelRoot.traverse((child) => {
            if (child.isMesh && child.material) {
              child.userData.originalMaterial = child.material.clone();
            }
          });

          this.scene.add(this.modelRoot);
          resolve();
        },
        undefined,
        (err) => {
          console.warn(`[ClinicAnatomyViewer] GLTF 載入失敗 (${modelSrc})，回退至專科 3D 結構:`, err);
          this._createSpecialty3DAnatomyMesh(target);
          resolve();
        }
      );
    });
  }

  /**
   * 根據不同專科療程，動態建立高解析度 3D 臨床解剖結構。
   * 徹底告別單一的紅圓環圓柱！
   */
  _createSpecialty3DAnatomyMesh(target) {
    if (this.modelRoot) {
      this.scene.remove(this.modelRoot);
    }
    const group = new THREE.Group();

    if (target === 'nail_germinal_matrix') {
      // 💅 1. 甲溝炎：末節趾骨、甲床、甲板、發炎側甲襞與甲基質生長中心
      // 末節趾骨
      const boneGeo = new THREE.CylinderGeometry(0.55, 0.45, 2.2, 24);
      const boneMat = new THREE.MeshStandardMaterial({ color: 0xe2e8f0, roughness: 0.3, metalness: 0.1 });
      const boneMesh = new THREE.Mesh(boneGeo, boneMat);
      boneMesh.rotation.z = Math.PI / 2;
      boneMesh.position.set(0, -0.4, 0);
      boneMesh.name = 'distal_phalanx';
      group.add(boneMesh);

      // 甲床軟組織 (Nail Bed)
      const bedGeo = new THREE.BoxGeometry(1.4, 0.25, 0.9);
      const bedMat = new THREE.MeshStandardMaterial({ color: 0xfca5a5, roughness: 0.5 });
      const bedMesh = new THREE.Mesh(bedGeo, bedMat);
      bedMesh.position.set(0.1, 0.1, 0);
      bedMesh.name = 'nail_bed';
      group.add(bedMesh);

      // 甲板 (Nail Plate - 弧形半透明角質)
      const plateGeo = new THREE.CylinderGeometry(0.55, 0.55, 1.3, 24, 1, true, 0, Math.PI);
      const plateMat = new THREE.MeshStandardMaterial({
        color: 0xf1f5f9,
        transparent: true,
        opacity: 0.85,
        roughness: 0.1,
        metalness: 0.2,
        side: THREE.DoubleSide
      });
      const plateMesh = new THREE.Mesh(plateGeo, plateMat);
      plateMesh.rotation.z = Math.PI / 2;
      plateMesh.rotation.y = Math.PI / 2;
      plateMesh.position.set(0.15, 0.25, 0);
      plateMesh.name = 'nail_plate';
      group.add(plateMesh);

      // 患側嵌入發炎肉芽腫與側甲壁 (Lateral Nail Fold - 紅腫警告區)
      const granGeo = new THREE.SphereGeometry(0.28, 16, 16);
      const granMat = new THREE.MeshStandardMaterial({
        color: 0xef4444,
        emissive: 0xb91c1c,
        emissiveIntensity: 0.4,
        roughness: 0.3
      });
      const granMesh = new THREE.Mesh(granGeo, granMat);
      granMesh.position.set(0.2, 0.3, 0.45);
      granMesh.name = 'lateral_nail_fold';
      group.add(granMesh);

      // 甲基質生長中心 (Germinal Matrix - 需徹底破壞之琥珀金色目標)
      const matrixGeo = new THREE.BoxGeometry(0.35, 0.2, 0.4);
      const matrixMat = new THREE.MeshStandardMaterial({
        color: 0xf59e0b,
        emissive: 0xd97706,
        emissiveIntensity: 0.6
      });
      const matrixMesh = new THREE.Mesh(matrixGeo, matrixMat);
      matrixMesh.position.set(-0.65, 0.18, 0.2);
      matrixMesh.name = 'nail_matrix';
      group.add(matrixMesh);

      // 指固有神經走向 (Digital Nerve)
      const nerveGeo = new THREE.CylinderGeometry(0.04, 0.04, 2.0, 12);
      const nerveMat = new THREE.MeshStandardMaterial({ color: 0xfacc15, emissive: 0xca8a04, emissiveIntensity: 0.5 });
      const nerveMesh = new THREE.Mesh(nerveGeo, nerveMat);
      nerveMesh.rotation.z = Math.PI / 2;
      nerveMesh.position.set(0, -0.15, 0.42);
      nerveMesh.name = 'digital_nerve';
      group.add(nerveMesh);

    } else if (target === 'apocrine_gland_dermal_junction') {
      // 🌸 2. 頂漿腺狐臭：皮膚層面、頂漿汗腺團塊與微創旋轉刀通道
      // 真皮層與脂肪層基底
      const skinGeo = new THREE.BoxGeometry(2.4, 0.35, 1.6);
      const skinMat = new THREE.MeshStandardMaterial({ color: 0xfdba74, roughness: 0.6 });
      const skinMesh = new THREE.Mesh(skinGeo, skinMat);
      skinMesh.position.set(0, 0.5, 0);
      skinMesh.name = 'axillary_skin';
      group.add(skinMesh);

      const fatGeo = new THREE.BoxGeometry(2.4, 0.6, 1.6);
      const fatMat = new THREE.MeshStandardMaterial({ color: 0xfef08a, roughness: 0.7, transparent: true, opacity: 0.85 });
      const fatMesh = new THREE.Mesh(fatGeo, fatMat);
      fatMesh.position.set(0, 0.0, 0);
      fatMesh.name = 'subcutaneous_fat';
      group.add(fatMesh);

      // 頂漿腺體團塊（多顆金黃色腺體）
      for (let x = -0.8; x <= 0.8; x += 0.4) {
        for (let z = -0.5; z <= 0.5; z += 0.5) {
          const glandGeo = new THREE.SphereGeometry(0.14, 16, 16);
          const glandMat = new THREE.MeshStandardMaterial({
            color: 0xf59e0b,
            emissive: 0xb45309,
            emissiveIntensity: 0.5
          });
          const glandMesh = new THREE.Mesh(glandGeo, glandMat);
          glandMesh.position.set(x + (Math.random() - 0.5) * 0.1, 0.32, z);
          glandMesh.name = 'apocrine_gland';
          group.add(glandMesh);
        }
      }

      // 深層腋動脈與靜脈安全界線 (禁刮警告區)
      const arteryGeo = new THREE.CylinderGeometry(0.08, 0.08, 2.2, 16);
      const arteryMat = new THREE.MeshStandardMaterial({ color: 0xef4444, emissive: 0x991b1b, emissiveIntensity: 0.6 });
      const arteryMesh = new THREE.Mesh(arteryGeo, arteryMat);
      arteryMesh.rotation.z = Math.PI / 2;
      arteryMesh.position.set(0, -0.4, 0.3);
      arteryMesh.name = 'axillary_artery_vein';
      group.add(arteryMesh);

    } else if (target === 'epidermoid_cyst_capsule') {
      // ⚪ 3. 粉瘤微創切除：皮膚開口、完整角質上皮囊壁與皮下剝離
      const skinGeo = new THREE.BoxGeometry(2.4, 0.3, 1.6);
      const skinMat = new THREE.MeshStandardMaterial({ color: 0xfdba74, roughness: 0.5 });
      const skinMesh = new THREE.Mesh(skinGeo, skinMat);
      skinMesh.position.set(0, 0.65, 0);
      skinMesh.name = 'dermis';
      group.add(skinMesh);

      // 開口 Punctum
      const punctumGeo = new THREE.CylinderGeometry(0.08, 0.08, 0.35, 16);
      const punctumMat = new THREE.MeshStandardMaterial({ color: 0x334155 });
      const punctumMesh = new THREE.Mesh(punctumGeo, punctumMat);
      punctumMesh.position.set(0, 0.65, 0);
      punctumMesh.name = 'cyst_punctum';
      group.add(punctumMesh);

      // 完整角質囊壁 (Cyst Capsule - 外層黃色囊壁)
      const cystWallGeo = new THREE.SphereGeometry(0.72, 32, 32);
      const cystWallMat = new THREE.MeshStandardMaterial({
        color: 0xf59e0b,
        emissive: 0xd97706,
        emissiveIntensity: 0.5,
        transparent: true,
        opacity: 0.75,
        wireframe: false
      });
      const cystWallMesh = new THREE.Mesh(cystWallGeo, cystWallMat);
      cystWallMesh.position.set(0, 0.0, 0);
      cystWallMesh.name = 'cyst_wall';
      group.add(cystWallMesh);

      // 內層角質皮脂豆腐渣核心
      const coreGeo = new THREE.SphereGeometry(0.55, 24, 24);
      const coreMat = new THREE.MeshStandardMaterial({ color: 0xfef08a, roughness: 0.9 });
      const coreMesh = new THREE.Mesh(coreGeo, coreMat);
      coreMesh.position.set(0, 0.0, 0);
      coreMesh.name = 'cyst_core';
      group.add(coreMesh);

    } else if (target === 'epidermal_dermal_junction') {
      // ⚡ 4. 皮秒雷射：表皮層、黑色素團塊與聚焦光震波空泡
      const epiGeo = new THREE.BoxGeometry(2.2, 0.2, 1.6);
      const epiMat = new THREE.MeshStandardMaterial({ color: 0xfcd34d, roughness: 0.4 });
      const epiMesh = new THREE.Mesh(epiGeo, epiMat);
      epiMesh.position.set(0, 0.7, 0);
      epiMesh.name = 'epidermis';
      group.add(epiMesh);

      const dermGeo = new THREE.BoxGeometry(2.2, 0.7, 1.6);
      const dermMat = new THREE.MeshStandardMaterial({ color: 0xf472b6, roughness: 0.5, transparent: true, opacity: 0.85 });
      const dermMesh = new THREE.Mesh(dermGeo, dermMat);
      dermMesh.position.set(0, 0.25, 0);
      dermMesh.name = 'collagen_dermis';
      group.add(dermMesh);

      // 黑色素團塊 (Pigment Cluster)
      for (let x = -0.6; x <= 0.6; x += 0.3) {
        const pigGeo = new THREE.DodecahedronGeometry(0.09);
        const pigMat = new THREE.MeshStandardMaterial({ color: 0x18181b, emissive: 0x06b6d4, emissiveIntensity: 0.3 });
        const pigMesh = new THREE.Mesh(pigGeo, pigMat);
        pigMesh.position.set(x, 0.58, (Math.random() - 0.5) * 0.4);
        pigMesh.name = 'pigment_cluster';
        group.add(pigMesh);
      }

      // 雷射聚焦光錐
      const beamGeo = new THREE.ConeGeometry(0.45, 1.4, 24, 1, true);
      const beamMat = new THREE.MeshStandardMaterial({
        color: 0x06b6d4,
        emissive: 0x0891b2,
        emissiveIntensity: 0.8,
        transparent: true,
        opacity: 0.6,
        side: THREE.DoubleSide
      });
      const beamMesh = new THREE.Mesh(beamGeo, beamMat);
      beamMesh.position.set(0, 1.4, 0);
      beamMesh.rotation.x = Math.PI;
      beamMesh.name = 'laser_beam';
      group.add(beamMesh);

    } else if (target === 'neuromuscular_junction') {
      // 💉 5. 肉毒桿菌：運動神經末梢與肌肉纖維束
      const muscleGeo = new THREE.CylinderGeometry(0.7, 0.7, 2.0, 16);
      const muscleMat = new THREE.MeshStandardMaterial({ color: 0xbe123c, roughness: 0.4 });
      const muscleMesh = new THREE.Mesh(muscleGeo, muscleMat);
      muscleMesh.rotation.z = Math.PI / 2;
      muscleMesh.position.set(0, -0.4, 0);
      muscleMesh.name = 'masseter_muscle';
      group.add(muscleMesh);

      // 神經突觸主幹
      const nerveGeo = new THREE.CylinderGeometry(0.1, 0.08, 1.5, 16);
      const nerveMat = new THREE.MeshStandardMaterial({ color: 0x818cf8, emissive: 0x4f46e5, emissiveIntensity: 0.5 });
      const nerveMesh = new THREE.Mesh(nerveGeo, nerveMat);
      nerveMesh.position.set(0, 0.6, 0);
      nerveMesh.name = 'nerve_marginal_mandibular';
      group.add(nerveMesh);

      // 突觸小體末梢
      const bulbGeo = new THREE.SphereGeometry(0.28, 24, 24);
      const bulbMat = new THREE.MeshStandardMaterial({ color: 0xa855f7, emissive: 0x7e22ce, emissiveIntensity: 0.6 });
      const bulbMesh = new THREE.Mesh(bulbGeo, bulbMat);
      bulbMesh.position.set(0, 0.0, 0);
      bulbMesh.name = 'synaptic_terminal';
      group.add(bulbMesh);

    } else {
      // 預設 SMAS 筋膜幾何層次
      const fasciaGeo = new THREE.BoxGeometry(2.0, 0.15, 1.4);
      const fasciaMat = new THREE.MeshStandardMaterial({ color: 0x38bdf8, emissive: 0x0284c7, emissiveIntensity: 0.5 });
      const fasciaMesh = new THREE.Mesh(fasciaGeo, fasciaMat);
      fasciaMesh.name = 'mesh_smas_layer';
      group.add(fasciaMesh);

      const deepGeo = new THREE.BoxGeometry(2.0, 0.6, 1.4);
      const deepMat = new THREE.MeshStandardMaterial({ color: 0x475569, roughness: 0.5 });
      const deepMesh = new THREE.Mesh(deepGeo, deepMat);
      deepMesh.position.set(0, -0.4, 0);
      deepMesh.name = 'deep_muscle';
      group.add(deepMesh);
    }

    // 備份材質
    group.traverse((child) => {
      if (child.isMesh && child.material) {
        child.userData.originalMaterial = child.material.clone();
      }
    });

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

    // 若有相機配置，套用視角與位置
    if (metadata.camera) {
      const cam = metadata.camera;
      if (cam.default_position && this.camera) {
        this.camera.position.set(...cam.default_position);
      }
      if (cam.target && this.controls) {
        this.controls.target.set(...cam.target);
      }
      if (this.controls) this.controls.update();
    }
  }

  _onFocusStep(event) {
    const detail = event.detail || {};
    const { doc_id, step_key } = detail;
    const curDoc = this.getAttribute('doc-id');

    if (doc_id && curDoc && doc_id !== curDoc) {
      this.setAttribute('doc-id', doc_id);
    }

    this.focusStep(step_key, detail);
  }

  focusStep(stepKey, overrideDetail = {}) {
    if (!this._initialized && !this._isFallback2D) {
      this._currentStep = stepKey;
      return;
    }

    let stepConfig = null;
    if (this._metadata && Array.isArray(this._metadata.interactive_steps)) {
      stepConfig = this._metadata.interactive_steps.find((s) => s.step_key === stepKey);
    }

    const action = overrideDetail.action || (stepConfig ? stepConfig.action : 'highlight_layer');
    const targetMesh = overrideDetail.target_mesh || (stepConfig ? stepConfig.target_mesh : null);
    const glowColor = overrideDetail.glow_color || (stepConfig ? stepConfig.glow_color : '#38bdf8');
    const rawCaption = overrideDetail.caption || (stepConfig ? stepConfig.caption : `聚焦章節：${stepKey}`);
    const caption = maskPricesClient(rawCaption);

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

    if (this._isFallback2D) {
      this._render2DFallbackStep(stepKey, action, caption);
      return;
    }

    // 3D 相機平滑推進
    if (stepConfig && stepConfig.camera_fly_to && this.camera) {
      const zoom = stepConfig.camera_fly_to.zoom || 1.6;
      this._cameraTargetPos = new THREE.Vector3(
        this.camera.position.x * (1 / zoom),
        this.camera.position.y * (1 / zoom),
        this.camera.position.z * (1 / zoom)
      );
    }

    this._highlightMesh(targetMesh, glowColor, action === 'warning_zone');
  }

  _highlightMesh(targetMeshName, colorHex, isWarning = false) {
    if (!this.modelRoot) return;

    const highlightColor = new THREE.Color(colorHex || (isWarning ? 0xff4d4f : 0x38bdf8));

    this.modelRoot.traverse((child) => {
      if (child.isMesh) {
        const matches = !targetMeshName || child.name.includes(targetMeshName) || (child.name === targetMeshName);

        if (matches) {
          child.material = new THREE.MeshStandardMaterial({
            color: highlightColor,
            emissive: highlightColor,
            emissiveIntensity: 0.85,
            roughness: 0.2,
            metalness: 0.3,
            transparent: true,
            opacity: 0.95
          });
        } else if (child.userData.originalMaterial) {
          child.material = child.userData.originalMaterial.clone();
          child.material.transparent = true;
          child.material.opacity = 0.35;
        }
      }
    });
  }

  resetCamera() {
    if (!this.camera || !this.controls) return;
    const cam = (this._metadata && this._metadata.camera) || {};
    const pos = cam.default_position || [0, 1.2, 5.0];
    const target = cam.target || [0, 0, 0];

    this._cameraTargetPos = new THREE.Vector3(...pos);
    this.controls.target.set(...target);

    if (this.modelRoot) {
      this.modelRoot.traverse((child) => {
        if (child.isMesh && child.userData.originalMaterial) {
          child.material = child.userData.originalMaterial.clone();
        }
      });
    }

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

    ctx.fillStyle = '#090d16';
    ctx.fillRect(0, 0, w, h);

    const target = (this._metadata && this._metadata.anatomy_target) || 'facial_smas';

    if (target === 'nail_germinal_matrix') {
      this._drawNailAnatomy(ctx, w, h, stepKey, action);
    } else if (target === 'apocrine_gland_dermal_junction') {
      this._drawApocrineAnatomy(ctx, w, h, stepKey, action);
    } else if (target === 'epidermoid_cyst_capsule') {
      this._drawCystAnatomy(ctx, w, h, stepKey, action);
    } else if (target === 'epidermal_dermal_junction') {
      this._drawLaserDermisAnatomy(ctx, w, h, stepKey, action);
    } else if (target === 'neuromuscular_junction') {
      this._drawNMJAnatomy(ctx, w, h, stepKey, action);
    } else {
      this._drawFascialLayersAnatomy(ctx, w, h, stepKey, action);
    }

    ctx.fillStyle = '#94a3b8';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(`【當前步驟：${stepKey}】 ${caption}`, w / 2, h - 20);
  }

  _drawFascialLayersAnatomy(ctx, w, h, stepKey, action) {
    const layers = [
      { name: '表皮層 (Epidermis, 0.1mm)', color: '#fed7aa', y: 35, h: 25 },
      { name: '真皮層 (Dermis, 1.5mm)', color: '#fdba74', y: 65, h: 40 },
      { name: '皮下脂肪層 (Subcutaneous Fat, 3.0mm)', color: '#fef08a', y: 110, h: 50 },
      { name: '淺筋膜層 (SMAS Layer, 4.5mm)', color: '#38bdf8', y: 165, h: 32, isTarget: true },
      { name: '深層肌肉與顏面神經走行 (Muscle & Nerve Branch)', color: '#f87171', y: 202, h: 65, isWarning: true }
    ];

    layers.forEach((layer) => {
      ctx.fillStyle = layer.color;
      ctx.globalAlpha = layer.isTarget ? 0.95 : 0.4;
      ctx.fillRect(50, layer.y, w - 100, layer.h);

      ctx.strokeStyle = layer.isTarget ? '#38bdf8' : (layer.isWarning ? '#ef4444' : '#64748b');
      ctx.lineWidth = layer.isTarget ? 2 : 1;
      ctx.strokeRect(50, layer.y, w - 100, layer.h);

      ctx.globalAlpha = 1.0;
      ctx.fillStyle = '#f8fafc';
      ctx.font = 'bold 12px sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(layer.name, 65, layer.y + layer.h / 2 + 4);
    });

    ctx.fillStyle = '#38bdf8';
    ctx.beginPath();
    ctx.arc(w / 2, 180, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#38bdf8';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(w / 2, 20);
    ctx.lineTo(w / 2, 180);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  _drawNailAnatomy(ctx, w, h, stepKey, action) {
    ctx.fillStyle = '#334155';
    ctx.fillRect(50, 40, w - 100, 220);

    ctx.fillStyle = '#cbd5e1';
    ctx.beginPath();
    ctx.roundRect(100, 170, w - 200, 60, 16);
    ctx.fill();
    ctx.fillStyle = '#475569';
    ctx.font = 'bold 12px sans-serif';
    ctx.fillText('末節趾骨 (Distal Phalanx)', 120, 205);

    ctx.fillStyle = '#fca5a5';
    ctx.fillRect(140, 105, 300, 35);
    ctx.fillStyle = '#991b1b';
    ctx.fillText('甲床 (Nail Bed)', 160, 128);

    ctx.fillStyle = '#ef4444';
    ctx.beginPath();
    ctx.arc(120, 110, 22, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.fillText('卷甲嵌入/肉芽腫', 80, 85);

    ctx.fillStyle = '#f59e0b';
    ctx.fillRect(80, 105, 55, 45);
    ctx.strokeStyle = '#fbbf24';
    ctx.lineWidth = 2;
    ctx.strokeRect(80, 105, 55, 45);
    ctx.fillStyle = '#ffffff';
    ctx.fillText('甲基質生長點', 70, 162);

    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(100, 92, 340, 12);
    ctx.fillStyle = '#0f172a';
    ctx.font = 'bold 10px sans-serif';
    ctx.fillText('甲板 (Nail Plate)', 240, 101);
  }

  _drawApocrineAnatomy(ctx, w, h, stepKey, action) {
    ctx.fillStyle = '#fed7aa';
    ctx.fillRect(50, 40, w - 100, 25);
    ctx.fillStyle = '#fdba74';
    ctx.fillRect(50, 68, w - 100, 65);
    ctx.fillStyle = '#fef08a';
    ctx.fillRect(50, 136, w - 100, 95);

    ctx.fillStyle = '#1e293b';
    ctx.font = 'bold 12px sans-serif';
    ctx.fillText('表皮與真皮層 (Epidermis & Dermis)', 70, 75);
    ctx.fillText('皮下脂肪層 (Subcutaneous Layer)', 70, 160);

    ctx.fillStyle = '#eab308';
    for (let x = 120; x < w - 120; x += 36) {
      ctx.beginPath();
      ctx.arc(x, 134, 10, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#ca8a04';
      ctx.stroke();
    }
    ctx.fillStyle = '#854d0e';
    ctx.fillText('🎯 頂漿腺體分佈區 (微創旋轉刀刨除層面)', 140, 120);

    ctx.fillStyle = '#ef4444';
    ctx.fillRect(80, 205, w - 160, 20);
    ctx.fillStyle = '#ffffff';
    ctx.fillText('⚠️ 深層腋動靜脈與神經叢安全邊界', 120, 219);
  }

  _drawCystAnatomy(ctx, w, h, stepKey, action) {
    ctx.fillStyle = '#fed7aa';
    ctx.fillRect(50, 40, w - 100, 30);
    ctx.fillStyle = '#fdba74';
    ctx.fillRect(50, 72, w - 100, 170);

    ctx.fillStyle = '#1e293b';
    ctx.font = 'bold 12px sans-serif';
    ctx.fillText('皮膚真皮與皮下組織', 70, 62);

    ctx.fillStyle = '#475569';
    ctx.beginPath();
    ctx.arc(w / 2, 42, 4, 0, Math.PI * 2);
    ctx.fill();

    const cystWallGeo = new THREE.SphereGeometry(52, 32, 32);
    ctx.fillStyle = '#fef08a';
    ctx.beginPath();
    ctx.arc(w / 2, 145, 52, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 4;
    ctx.stroke();

    ctx.fillStyle = '#78350f';
    ctx.textAlign = 'center';
    ctx.font = 'bold 12px sans-serif';
    ctx.fillText('角質皮脂內容物', w / 2, 140);
    ctx.fillText('(完整微創旋轉抽吸)', w / 2, 156);

    ctx.fillStyle = '#b45309';
    ctx.fillText('圍繞之完整角質囊壁 (必須整顆剝除防復發)', w / 2, 215);
  }

  _drawLaserDermisAnatomy(ctx, w, h, stepKey, action) {
    ctx.fillStyle = '#fed7aa';
    ctx.fillRect(50, 40, w - 100, 40);
    ctx.fillStyle = '#fdba74';
    ctx.fillRect(50, 82, w - 100, 160);

    ctx.fillStyle = '#0f172a';
    ctx.font = 'bold 12px sans-serif';
    ctx.fillText('表皮基底層 (Basal Layer)', 70, 65);
    ctx.fillText('真皮乳突層與網狀層 (Papillary & Reticular Dermis)', 70, 110);

    ctx.fillStyle = '#3f3f46';
    for (let x = 100; x < w - 100; x += 28) {
      ctx.beginPath();
      ctx.arc(x, 80, 5, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = '#18181b';
    ctx.fillText('黑色素團塊 (Melanin Cluster)', 120, 96);

    ctx.strokeStyle = '#06b6d4';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(w / 2 - 20, 20);
    ctx.lineTo(w / 2 - 5, 80);
    ctx.moveTo(w / 2 + 20, 20);
    ctx.lineTo(w / 2 + 5, 80);
    ctx.stroke();

    ctx.fillStyle = '#06b6d4';
    ctx.beginPath();
    ctx.arc(w / 2, 80, 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#0891b2';
    ctx.fillText('⚡ 皮秒光震波粉碎與空泡化反應 (LIOB)', w / 2 + 18, 84);
  }

  _drawNMJAnatomy(ctx, w, h, stepKey, action) {
    ctx.fillStyle = '#1e1b4b';
    ctx.fillRect(50, 40, w - 100, 220);

    ctx.fillStyle = '#818cf8';
    ctx.beginPath();
    ctx.arc(w / 2, 90, 45, Math.PI, 0);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('運動神經末梢 (Motor Nerve Axon)', w / 2, 75);

    ctx.fillStyle = '#c084fc';
    for (let ox = -25; ox <= 25; ox += 12) {
      ctx.beginPath();
      ctx.arc(w / 2 + ox, 96, 4, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = '#f43f5e';
    ctx.fillText('🛑 肉毒桿菌素阻斷乙醯膽鹼 (ACh) 釋放', w / 2, 120);

    ctx.fillStyle = '#e11d48';
    ctx.fillRect(80, 140, w - 160, 80);
    ctx.fillStyle = '#ffffff';
    ctx.fillText('目標咀嚼肌/表情肌纖維 (放鬆微縮小)', w / 2, 185);
  }

  _animate() {
    if (this._isFallback2D) return;
    this._animationFrameId = requestAnimationFrame(this._animate);

    if (this._cameraTargetPos && this.camera) {
      this.camera.position.lerp(this._cameraTargetPos, this._cameraLerpFactor);
      if (this.camera.position.distanceTo(this._cameraTargetPos) < 0.05) {
        this._cameraTargetPos = null;
      }
    }

    if (this.getAttribute('auto-rotate') === 'true' && this.modelRoot) {
      this.modelRoot.rotation.y += 0.003;
    }

    if (this.controls) this.controls.update();
    if (this.renderer && this.scene && this.camera) {
      this.renderer.render(this.scene, this.camera);
    }
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

if (typeof customElements !== 'undefined' && !customElements.get('clinic-anatomy-viewer')) {
  customElements.define('clinic-anatomy-viewer', ClinicAnatomyViewer);
}
