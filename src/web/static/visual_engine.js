(function (root) {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

  // 固定調色盤常數（代號至色碼對照表，鍵集合與 Python PALETTE_TOKENS 完全一致）
  const PALETTE = Object.freeze({
    fat: "#f6b93b",
    oil: "#fde9a8",
    blood: "#e25555",
    skin: "#f7d9c4",
    neutral: "#64748b",
    accent: "#2b6cb0",
    warn: "#d9534f",
    ok: "#2f9e6b",
    gel: "#6ee7b7",
    pale: "#f1f5f9"
  });

  function cloneObject(obj) {
    if (obj === null || typeof obj !== "object") return obj;
    return JSON.parse(JSON.stringify(obj));
  }

  function clampNumber(val, min, max) {
    const num = Number(val);
    if (!Number.isFinite(num)) return min;
    return Math.max(min, Math.min(max, num));
  }

  // 確定性雜湊函式（以索引與種子推導數值，純數學計算無亂數）
  function deterministicHash(seed, idx) {
    const s = Number(seed) || 1;
    const i = Number(idx) || 0;
    const v = Math.sin(s * 12.9898 + i * 78.233) * 43758.5453;
    return v - Math.floor(v);
  }

  function createCtx(parentGroup) {
    function makeElement(name, attrs, parent) {
      const el = document.createElementNS(SVG_NS, name);
      if (attrs) {
        for (const k of Object.keys(attrs)) {
          const val = attrs[k];
          if (val !== undefined && val !== null) {
            el.setAttribute(k, String(val));
          }
        }
      }
      const targetParent = parent || parentGroup;
      if (targetParent) {
        targetParent.appendChild(el);
      }
      return el;
    }

    return {
      svg: parentGroup,
      rect: function (attrs, parent) {
        return makeElement("rect", attrs, parent);
      },
      circle: function (attrs, parent) {
        return makeElement("circle", attrs, parent);
      },
      line: function (attrs, parent) {
        return makeElement("line", attrs, parent);
      },
      path: function (attrs, parent) {
        return makeElement("path", attrs, parent);
      },
      polygon: function (attrs, parent) {
        return makeElement("polygon", attrs, parent);
      },
      ellipse: function (attrs, parent) {
        return makeElement("ellipse", attrs, parent);
      },
      group: function (attrs, parent) {
        return makeElement("g", attrs, parent);
      },
      text: function (attrs, textString, parent) {
        const el = makeElement("text", attrs, parent);
        el.textContent = textString != null ? String(textString) : "";
        return el;
      },
      palette: function (token, fallback) {
        return PALETTE[token] || fallback || PALETTE.neutral;
      },
      clamp: clampNumber,
      hash: deterministicHash
    };
  }

  // 醫療專業狀態步驟膠囊（安全渲染於 y <= 410）
  function drawStepPills(ctx, steps, u) {
    if (!Array.isArray(steps) || steps.length === 0) return;
    const sx = [180, 400, 620];
    const st = [0.05, 0.38, 0.72];
    for (let s = 0; s < 3; s++) {
      const text = steps[s];
      if (!text) continue;
      const isCurrent = u >= st[s] && (s === 2 || u < st[s + 1]);
      const isPassed = u >= st[s];
      const pillX = sx[s] - 85;
      const pillY = 374;
      const pillW = 170;
      const pillH = 30;

      // 膠囊底板
      ctx.rect({
        x: pillX,
        y: pillY,
        width: pillW,
        height: pillH,
        rx: 15,
        fill: isCurrent ? "#1e3a5f" : isPassed ? "#162032" : "#0f172a",
        stroke: isCurrent ? PALETTE.ok : isPassed ? "#38bdf8" : "#334155",
        "stroke-width": isCurrent ? 2 : 1.2,
        opacity: isPassed ? 1.0 : 0.45
      });

      // 呼吸指示圓點
      const dotFill = isCurrent ? PALETTE.ok : isPassed ? "#38bdf8" : "#64748b";
      ctx.circle({
        cx: pillX + 16,
        cy: pillY + 15,
        r: isCurrent ? 4 : 3,
        fill: dotFill,
        opacity: isPassed ? 1.0 : 0.5
      });

      // 標籤文字 (安全區 y <= 410)
      ctx.text(
        {
          x: pillX + 28,
          y: pillY + 19,
          "text-anchor": "start",
          "font-size": 13,
          "font-weight": isCurrent ? "bold" : "normal",
          fill: isCurrent ? "#ffffff" : isPassed ? "#cbd5e1" : "#64748b",
          opacity: isPassed ? 1.0 : 0.5
        },
        text
      );
    }
  }

  // Blueprint 1: 流程圖解（抽取與純化）
  function drawProcessDiagram(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    // 左側組織來源
    const sourceFill = ctx.palette(params.source.fill, PALETTE.skin);
    ctx.rect({ x: 50, y: 100, width: 200, height: 250, rx: 14, fill: sourceFill, stroke: "#cbd5e1", "stroke-width": 2 });
    ctx.rect({ x: 65, y: 140, width: 170, height: 170, rx: 10, fill: "#fde9a8", stroke: "#f6b93b", "stroke-width": 1.5 });
    ctx.text({ x: 150, y: 235, "text-anchor": "middle", "font-size": 16, "font-weight": "bold", fill: "#8a6d00" }, params.source.label);

    // 抽取針管（往返伸縮由進度 u 正弦波計算，純函式）
    const shift = Math.sin(u * Math.PI * 4) * 16;
    ctx.rect({ x: 185 + shift, y: 220, width: 110, height: 10, rx: 4, fill: "#94a3b8" });
    ctx.rect({ x: 290 + shift, y: 215, width: 26, height: 20, rx: 4, fill: "#475569" });

    // 沿弧線流向右側容器的粒子
    const particleCount = params.particles;
    for (let i = 0; i < particleCount; i++) {
      const pOffset = i / particleCount;
      const progress = (u * 2.2 + pOffset) % 1.0;
      if (u < 0.65) {
        const px = 280 + progress * 290;
        const arc = Math.sin(progress * Math.PI) * 55;
        const py = 225 - arc + progress * (115 - 225);
        let alpha = 1.0;
        if (progress < 0.12) alpha = progress / 0.12;
        if (progress > 0.88) alpha = (1.0 - progress) / 0.12;
        ctx.circle({ cx: px, cy: py, r: 5.5, fill: PALETTE.fat, stroke: "#ffffff", "stroke-width": 1.5, opacity: Math.max(0, alpha) });
      }
    }

    // 右側離心容器與頂蓋
    ctx.rect({ x: 592, y: 72, width: 40, height: 16, rx: 4, fill: "#475569", stroke: "#64748b" });
    ctx.rect({ x: 570, y: 85, width: 84, height: 270, rx: 24, fill: "#0f172a", stroke: "#64748b", "stroke-width": 3 });

    // 容器分層
    const layers = params.container_layers;
    let totalWeight = 0;
    for (let i = 0; i < layers.length; i++) {
      totalWeight += layers[i].weight;
    }
    if (totalWeight <= 0) totalWeight = 1;

    const innerX = 575;
    const innerW = 74;
    const innerTotalH = 250;
    const innerBottom = 345;

    if (u < 0.4) {
      const fillHeight = innerTotalH * Math.min(1, u / 0.35);
      ctx.rect({ x: innerX, y: innerBottom - fillHeight, width: innerW, height: fillHeight, fill: "#e9a35a", opacity: 0.95 });
    } else {
      const stratProgress = Math.min(1, (u - 0.4) / 0.35);
      let currentTop = innerBottom - innerTotalH * stratProgress;
      for (let i = 0; i < layers.length; i++) {
        const layer = layers[i];
        const layerH = (layer.weight / totalWeight) * innerTotalH * stratProgress;
        const color = ctx.palette(layer.fill, PALETTE.fat);
        ctx.rect({ x: innerX, y: currentTop, width: innerW, height: layerH, fill: color });

        // 保留層 강조框（u 達 0.75 後亮起）
        if (layer.keep && u >= 0.75) {
          const pulse = 0.5 + 0.5 * Math.sin((u - 0.75) * Math.PI * 6);
          ctx.rect({
            x: innerX - 6,
            y: currentTop - 2,
            width: innerW + 12,
            height: layerH + 4,
            rx: 6,
            fill: "none",
            stroke: PALETTE.ok,
            "stroke-width": 3,
            opacity: 0.4 + 0.6 * pulse
          });
        }
        currentTop += layerH;
      }
    }

    // 步驟說明標籤（全部 y <= 410）
    const steps = params.step_labels;
    if (steps[0]) {
      const op1 = u >= 0.05 ? Math.min(1, (u - 0.05) / 0.15) : 0;
      ctx.text({ x: 150, y: 395, "text-anchor": "middle", "font-size": 15, fill: "#cfe0f5", opacity: op1 }, steps[0]);
    }
    if (steps[1]) {
      const op2 = u >= 0.42 ? Math.min(1, (u - 0.42) / 0.15) : 0;
      ctx.text({ x: 612, y: 395, "text-anchor": "middle", "font-size": 15, fill: "#cfe0f5", opacity: op2 }, steps[1]);
    }
    if (steps[2]) {
      const op3 = u >= 0.75 ? Math.min(1, (u - 0.75) / 0.15) : 0;
      ctx.text({ x: 380, y: 395, "text-anchor": "middle", "font-size": 16, "font-weight": "bold", fill: PALETTE.ok, opacity: op3 }, steps[2]);
    }
  }

  // Blueprint 2: 對照圖解（少量多層次 vs 單處過量）
  // 各調色盤代號對應的描邊色（只存引擎內，不接受外部色碼）
  const STROKE_FOR = {
    fat: "#d97706", oil: "#ca8a04", blood: "#b91c1c", skin: "#c08a6b", neutral: "#64748b",
    accent: "#2563eb", warn: "#b91c1c", ok: "#15803d", gel: "#0f766e", pale: "#94a3b8"
  };
  function strokeFor(token) {
    return STROKE_FOR[token] || STROKE_FOR.fat;
  }

  // Phase 33：專科列舉常數（與 src/visual/blueprints.py 規格一致；白名單與繪製共用）
  const CONTRAST_LEFT_SPECIALTY = ["tissue_trauma_torn_vessel", "scar_contracture_ectropion", "silicone_extrusion_erythema", "capsular_contracture_ball", "nodule_clumping"];
  const CONTRAST_RIGHT_SPECIALTY = ["ultrasonic_emulsification", "transconjunctival_fat_reposition", "cartilage_triangular_strut", "dual_plane_natural_teardrop", "micro_droplet_diffusion"];
  const TIMELINE_SPECIALTY = ["bone_healing", "bruise_metabolism", "scar_maturation", "nerve_regeneration", "skin_retraction"];
  const CONTRAST_LEFT_MODES = ["mass", "scattered", "wide_incision", "thermal_spread"].concat(CONTRAST_LEFT_SPECIALTY);
  const CONTRAST_RIGHT_MODES = ["layered", "mass", "minimal_incision", "targeted_energy"].concat(CONTRAST_RIGHT_SPECIALTY);
  const TIMELINE_CONNECTORS = ["vessels", "none", "wound_healing", "collagen_remodeling"].concat(TIMELINE_SPECIALTY);
  const TIMELINE_UNIT_EFFECTS = ["mature", "fade", "steady", "glow_restored"];

  // Phase 33 場景 2：左側（傳統處置／病理風險）專科繪製。u 為進度，皆為純函式。
  function drawContrastLeftSpecialty(ctx, mode, u) {
    if (mode === "tissue_trauma_torn_vessel") {
      // 粗鈍管盲吸：管身往返，撕裂血管發紫、皮下凹凸不平
      const sway = Math.sin(u * Math.PI * 4) * 10;
      ctx.line({ x1: 120 + sway, y1: 128, x2: 205 + sway, y2: 235, stroke: "#cbd5e1", "stroke-width": 9, "stroke-linecap": "round" });
      const tearU = Math.max(0, Math.min(1, (u - 0.2) / 0.5));
      ctx.path({ d: "M 150 230 Q 175 205 205 232", fill: "none", stroke: "#b91c1c", "stroke-width": 2.5, opacity: tearU });
      ctx.path({ d: "M 240 226 Q 262 250 236 268", fill: "none", stroke: "#b91c1c", "stroke-width": 2.5, opacity: tearU });
      ctx.circle({ cx: 200, cy: 250, r: 46 * tearU, fill: "#6d28d9", opacity: 0.32 });
      ctx.path({ d: "M 80 330 Q 110 306 140 330 T 200 330 T 260 330 T 340 330", fill: "none", stroke: "#94a3b8", "stroke-width": 2 });
    } else if (mode === "scar_contracture_ectropion") {
      // 外切口疤痕攣縮：牽拉下瞼外翻，睫毛向下偏移
      const lidY = 196 + 26 * u;
      ctx.path({ d: "M 90 " + (lidY - 18) + " Q 210 " + (lidY - 50 + 26 * u) + " 330 " + (lidY - 18), fill: "none", stroke: "#cbd5e1", "stroke-width": 4 });
      ctx.path({ d: "M 110 " + (lidY + 14) + " Q 210 " + (lidY + 36) + " 310 " + (lidY + 14), fill: "none", stroke: "#b91c1c", "stroke-width": 6, opacity: 0.4 + 0.6 * u, "stroke-linecap": "round" });
      for (let i = 0; i < 3; i++) {
        const x = 150 + i * 60;
        ctx.line({ x1: x, y1: lidY + 30, x2: x, y2: lidY + 30 + 26 * u, stroke: "#fca5a5", "stroke-width": 2, "stroke-dasharray": "4 3", opacity: u });
      }
      for (let i = 0; i < 5; i++) {
        const x = 110 + i * 40;
        ctx.line({ x1: x, y1: lidY - 16, x2: x - 3, y2: lidY - 4 + 10 * u, stroke: "#94a3b8", "stroke-width": 2, "stroke-linecap": "round" });
      }
    } else if (mode === "silicone_extrusion_erythema") {
      // L 型矽膠假體：鼻尖壓迫發紅變薄，短鼻攣縮朝天
      ctx.path({ d: "M 160 150 L 160 290 L 270 290", fill: "none", stroke: "#e2e8f0", "stroke-width": 14, "stroke-linecap": "round", "stroke-linejoin": "round" });
      ctx.circle({ cx: 160, cy: 150, r: 18 + 8 * u, fill: "#ef4444", opacity: 0.25 + 0.45 * u });
      ctx.circle({ cx: 160, cy: 150, r: 26, fill: "none", stroke: "#fca5a5", "stroke-width": 2, "stroke-dasharray": "4 4", opacity: u });
      ctx.line({ x1: 270, y1: 290, x2: 270, y2: 250, stroke: "#f87171", "stroke-width": 3 });
      ctx.line({ x1: 270, y1: 250, x2: 262, y2: 260, stroke: "#f87171", "stroke-width": 3 });
      ctx.line({ x1: 270, y1: 250, x2: 278, y2: 260, stroke: "#f87171", "stroke-width": 3 });
    } else if (mode === "capsular_contracture_ball") {
      // 包膜攣縮：厚纖維莢膜收緊，假體球狀硬化移位
      const shift = 8 * u;
      ctx.circle({ cx: 210 + shift, cy: 240, r: 54, fill: "#e2e8f0", stroke: "#94a3b8", "stroke-width": 2 });
      ctx.circle({ cx: 210 + shift, cy: 240, r: 66 - 6 * u, fill: "none", stroke: "#b91c1c", "stroke-width": 3 + 2 * u, opacity: 0.5 + 0.4 * u });
      for (let i = 0; i < 12; i++) {
        const a = i * Math.PI / 6;
        ctx.line({ x1: 210 + shift + Math.cos(a) * 56, y1: 240 + Math.sin(a) * 56, x2: 210 + shift + Math.cos(a) * (60 + 8 * u), y2: 240 + Math.sin(a) * (60 + 8 * u), stroke: "#fca5a5", "stroke-width": 1.5, opacity: u });
      }
    } else if (mode === "nodule_clumping") {
      // 大分子單點沉積：不規則硬塊微結節，表情牽動受阻
      ctx.line({ x1: 110, y1: 310, x2: 310, y2: 310, stroke: "#64748b", "stroke-width": 2, "stroke-dasharray": "5 4" });
      ctx.circle({ cx: 210, cy: 240, r: 6 + 30 * u, fill: "#fbbf24", opacity: 0.35 });
      for (let i = 0; i < 6; i++) {
        const ox = (deterministicHash(i, 17) - 0.5) * 60 * u;
        const oy = (deterministicHash(i, 19) - 0.5) * 50 * u;
        ctx.circle({ cx: 210 + ox, cy: 240 + oy, r: 4 + 6 * u * deterministicHash(i, 23), fill: "#f59e0b", stroke: "#fef3c7", "stroke-width": 1 });
      }
    }
  }

  // Phase 33 場景 2：右側（微創優勢／精準處置）專科繪製
  function drawContrastRightSpecialty(ctx, mode, u) {
    if (mode === "ultrasonic_emulsification") {
      // 超音波乳化：探頭共振波紋，脂肪乳化為微滴，保留直立結締纖維
      ctx.rect({ x: 578, y: 130, width: 24, height: 14, rx: 4, fill: "#94a3b8" });
      for (let w = 0; w < 3; w++) {
        const phase = (u * 2 + w / 3) % 1;
        ctx.circle({ cx: 590, cy: 144, r: 10 + 30 * phase, fill: "none", stroke: "#38bdf8", "stroke-width": 1.5, opacity: 0.6 * (1 - phase) });
      }
      for (let i = 0; i < 14; i++) {
        const x = 470 + deterministicHash(i, 29) * 240;
        const y = 220 + deterministicHash(i, 31) * 90;
        const appear = Math.min(1, Math.max(0, u * 1.6 - i / 20));
        ctx.circle({ cx: x, cy: y, r: 2.2 * appear, fill: "#fde68a", opacity: 0.9 * appear });
      }
      for (let f = 0; f < 6; f++) {
        const x = 460 + f * 50;
        ctx.line({ x1: x, y1: 190, x2: x, y2: 330, stroke: "#94a3b8", "stroke-width": 1.2, opacity: 0.6 });
      }
    } else if (mode === "transconjunctival_fat_reposition") {
      // 經結膜內切：眶隔脂肪滑移平鋪於淚溝，表面平順無外疤
      ctx.line({ x1: 520, y1: 196, x2: 556, y2: 196, stroke: "#4ade80", "stroke-width": 2.5, "stroke-linecap": "round" });
      ctx.circle({ cx: 610 - 30 * u, cy: 300 - 52 * u, r: 26, fill: "#fde68a", stroke: "#eab308", "stroke-width": 2, opacity: 0.85 });
      ctx.path({ d: "M 460 240 Q 520 " + (300 + 40 * (1 - u)) + " 600 290", fill: "none", stroke: "#94a3b8", "stroke-width": 2.5 });
    } else if (mode === "cartilage_triangular_strut") {
      // 自體軟骨三角支架：海鷗線支撐與力學分散
      ctx.path({ d: "M 590 150 L 530 300 L 650 300 Z", fill: "#fde68a", opacity: 0.2 + 0.35 * u, stroke: "#fde68a", "stroke-width": 2 });
      ctx.path({ d: "M 520 282 Q 590 230 660 282", fill: "none", stroke: "#facc15", "stroke-width": 3, opacity: u });
      for (let i = 0; i < 3; i++) {
        const x = 560 + i * 30;
        ctx.line({ x1: x, y1: 330, x2: x, y2: 340 + 10 * u, stroke: "#94a3b8", "stroke-width": 2, opacity: u });
      }
    } else if (mode === "dual_plane_natural_teardrop") {
      // 雙平面：胸大肌上緣平順過渡，下極如自然水滴垂墜
      ctx.path({ d: "M 440 300 Q 590 268 740 300", fill: "none", stroke: "#94a3b8", "stroke-width": 2, "stroke-dasharray": "6 4" });
      const w = 40 + 30 * u;
      ctx.path({
        d: "M 590 190 C " + (590 + w * 0.6) + " 200 " + (590 + w) + " 270 " + (590 + w) + " 300 C " + (590 + w) + " 340 " + (590 + w * 0.5) + " 355 590 355 C " + (590 - w * 0.5) + " 355 " + (590 - w) + " 340 " + (590 - w) + " 300 C " + (590 - w) + " 270 " + (590 - w * 0.6) + " 200 590 190 Z",
        fill: "#e2e8f0", opacity: 0.35 + 0.5 * u, stroke: "#cbd5e1", "stroke-width": 2
      });
    } else if (mode === "micro_droplet_diffusion") {
      // 鈍針多層微滴：由聚集散佈為均勻分布，與周圍組織平順融合
      for (let i = 0; i < 24; i++) {
        const sx = 470 + deterministicHash(i, 37) * 240;
        const sy = 150 + deterministicHash(i, 41) * 160;
        const gx = 480 + (i % 6) * 40;
        const gy = 170 + Math.floor(i / 6) * 40;
        ctx.circle({ cx: sx + (gx - sx) * u, cy: sy + (gy - sy) * u, r: 3, fill: "#a5f3fc", opacity: 0.4 + 0.5 * u });
      }
    }
  }

  // Phase 33 & 升級：場景 3 動態階段解說詞表（文字隨進度動態切換，杜絕無圖文變化）
  const TIMELINE_STAGE_DESC = {
    bone_healing: [
      "斷端初期纖維血腫連接，純鈦板釘剛性維持穩定",
      "骨痂雲霧狀萌發橋接，骨小樑緻密網狀交織生長",
      "骨性剛性癒合完全融合，咬合線骨質完全穩固"
    ],
    nerve_regeneration: [
      "末梢感覺神經暫時鈍化麻木，保護性低刺激照護",
      "神經軸突沿導引鞘管發芽萌生，微管向感受點伸展",
      "感覺受體完全接合傳導，神經敏銳度逐步恢復正常"
    ],
    bruise_metabolism: [
      "皮下微血管滲血與暗紫血腫聚集，局部微溫反應",
      "巨噬細胞吞噬代謝，血紅素轉化為墨綠黃褐色素",
      "色素完全代謝吸收，組織循環暢通、膚色透亮復原"
    ],
    scar_maturation: [
      "微創切口邊緣緊密對合，閉合初期局部微凸潮紅",
      "水合保濕與張力平衡，微血管消退並漸進褪紅撫平",
      "膠原排列成熟規則，淡化為細微平整之隱痕白線"
    ],
    skin_retraction: [
      "皮下微水腫與局部鬆弛，彈性加壓帶輔助貼合",
      "深層基質修復收縮，成纖維細胞拉緊組織微間隙",
      "皮下空隙完全貼合，深層輪廓平整回彈、緊緻對稱"
    ],
    wound_healing: [
      "術後初期加壓保護傷口，冰敷輔助抑制組織腫脹",
      "切口表皮移行對合密閉，新生肉芽組織填補癒合",
      "上皮完全角化重塑，切口平整隱痕、組織自然貼合"
    ],
    collagen_remodeling: [
      "深層能量溫熱刺激，啟動自體修復連鎖生理反應",
      "成纖維細胞大量活化，新生三股螺旋膠原交聯增生",
      "彈力纖維網格緻密交織，肌膚深層結構緊緻提拉"
    ],
    vessels: [
      "移植物置入初期，依賴周圍組織液維持初期滋養",
      "微血管主幹萌生並向移植物新生分支長入血管網絡",
      "血液循環網絡完整建立，細胞血氧充沛存活穩定"
    ]
  };

  // Phase 33 場景 3：五種專科生理修復歷程繪圖（大畫布立體呈現，圖文強烈呼應）
  function drawTimelineSpecialty(ctx, connector, u, unitFill) {
    if (connector === "bone_healing") {
      // 截骨剛性癒合：斷端對合 -> 骨痂雲霧橋接與骨小樑生長 -> 骨性完全癒合
      // 左側下顎骨端 (x: 90..340, y: 160..270)
      ctx.rect({ x: 90, y: 160, width: 250, height: 110, rx: 8, fill: "#334155", stroke: "#94a3b8", "stroke-width": 2 });
      ctx.rect({ x: 90, y: 160, width: 250, height: 18, rx: 4, fill: "#e2e8f0" });
      ctx.text({ x: 215, y: 225, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#94a3b8" }, "近心穩定骨端");
      // 鬆質骨網紋
      ctx.line({ x1: 140, y1: 195, x2: 290, y2: 255, stroke: "#475569", "stroke-width": 1.5, "stroke-dasharray": "4 4" });

      // 右側截骨滑移骨端 (x: 460..710, y: 160..270)
      ctx.rect({ x: 460, y: 160, width: 250, height: 110, rx: 8, fill: "#334155", stroke: "#94a3b8", "stroke-width": 2 });
      ctx.rect({ x: 460, y: 160, width: 250, height: 18, rx: 4, fill: "#e2e8f0" });
      ctx.text({ x: 585, y: 225, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#94a3b8" }, "滑移重塑骨端");
      ctx.line({ x1: 510, y1: 195, x2: 660, y2: 255, stroke: "#475569", "stroke-width": 1.5, "stroke-dasharray": "4 4" });

      // 純鈦固定接骨板 (跨接兩端)
      ctx.rect({ x: 280, y: 135, width: 240, height: 18, rx: 4, fill: "#64748b", stroke: "#cbd5e1", "stroke-width": 1.5 });
      // 4 顆純鈦螺釘固定孔 (使用 unitFill)
      const screwXs = [310, 360, 440, 490];
      for (let s = 0; s < screwXs.length; s++) {
        ctx.circle({ cx: screwXs[s], cy: 144, r: 5, fill: PALETTE[unitFill] || "#cbd5e1", stroke: "#1e293b", "stroke-width": 1.5 });
      }

      // 中央骨縫 (x: 340..460, 寬 120)
      if (u < 0.35) {
        // 階段一：初期血腫與微創固定
        ctx.rect({ x: 340, y: 160, width: 120, height: 110, rx: 6, fill: "#7f1d1d", opacity: 0.85 });
        ctx.text({ x: 400, y: 220, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#fca5a5" }, "纖維血腫凝塊");
      } else if (u < 0.70) {
        // 階段二：骨痂雲霧生長與骨小樑交織
        const prog2 = (u - 0.35) / 0.35;
        ctx.rect({ x: 340, y: 160, width: 120, height: 110, rx: 6, fill: "#451a03", opacity: 0.6 });
        // 米黃色骨痂
        ctx.rect({ x: 350, y: 170, width: 100, height: 90, rx: 10, fill: "#fde68a", opacity: 0.5 + 0.4 * prog2 });
        // 骨小樑橋接線
        for (let i = 0; i < 7; i++) {
          const yPos = 175 + i * 12;
          ctx.line({ x1: 340, y1: yPos, x2: 460, y2: yPos + (i % 2 === 0 ? 8 : -8), stroke: "#fef3c7", "stroke-width": 2.2, opacity: prog2 });
        }
        ctx.text({ x: 400, y: 220, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#fef08a" }, "骨痂生長橋接");
      } else {
        // 階段三：骨性完全融合
        ctx.rect({ x: 340, y: 160, width: 120, height: 110, rx: 6, fill: "#e2e8f0", opacity: 0.95 });
        ctx.rect({ x: 340, y: 160, width: 120, height: 18, rx: 4, fill: "#f1f5f9" });
        // 剛性癒合金色光芒
        ctx.circle({ cx: 400, cy: 215, r: 60, fill: "none", stroke: "#facc15", "stroke-width": 3, opacity: 0.85 });
        ctx.text({ x: 400, y: 220, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#1e293b" }, "骨性融合完成");
      }
    } else if (connector === "bruise_metabolism") {
      // 退瘀色譜：暗紫血腫 -> 墨綠青色膽綠素 -> 橙黃褐色膽紅素 -> 色素消散恢復膚色
      ctx.rect({ x: 90, y: 140, width: 620, height: 26, rx: 6, fill: "#fed7aa", opacity: 0.9 });
      ctx.text({ x: 150, y: 158, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#7c2d12" }, "表皮層");
      ctx.rect({ x: 90, y: 170, width: 620, height: 140, rx: 10, fill: "#1e293b", stroke: "#334155", "stroke-width": 1.5 });
      ctx.text({ x: 150, y: 196, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#64748b" }, "真皮微血管層");

      if (u < 0.35) {
        // 階段一：暗紫血腫塊
        ctx.circle({ cx: 400, cy: 240, r: 68, fill: "#4c1d95", opacity: 0.85 });
        ctx.circle({ cx: 400, cy: 240, r: 90, fill: "#701a75", opacity: 0.35 });
        ctx.text({ x: 400, y: 245, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#f3e8ff" }, "深層暗紫血腫");
      } else if (u < 0.70) {
        // 階段二：墨綠青色 -> 橙黃褐色轉化
        const p2 = (u - 0.35) / 0.35;
        const col = p2 < 0.5 ? "#15803d" : "#b45309";
        const txt = p2 < 0.5 ? "膽綠素代謝 (青綠色)" : "膽紅素轉化 (黃褐色)";
        ctx.circle({ cx: 400, cy: 240, r: 52 - 12 * p2, fill: col, opacity: 0.75 });
        ctx.circle({ cx: 400, cy: 240, r: 75 - 15 * p2, fill: col, opacity: 0.3 });
        // 巨噬細胞吞噬顆粒
        for (let k = 0; k < 6; k++) {
          const ang = k * Math.PI / 3;
          const kx = 400 + Math.cos(ang) * (42 * (1 - p2 * 0.4));
          const ky = 240 + Math.sin(ang) * (42 * (1 - p2 * 0.4));
          ctx.circle({ cx: kx, cy: ky, r: 4, fill: PALETTE[unitFill] || "#fef08a", opacity: 0.8 });
        }
        ctx.text({ x: 400, y: 245, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#fef3c7" }, txt);
      } else {
        // 階段三：完全消退，自然透亮
        const p3 = (u - 0.70) / 0.30;
        ctx.circle({ cx: 400, cy: 240, r: 35, fill: "#fef08a", opacity: 0.15 * (1 - p3) });
        // 健康潤白光環
        ctx.circle({ cx: 400, cy: 240, r: 55, fill: "none", stroke: "#fde68a", "stroke-width": 2.5, opacity: 0.75 });
        ctx.circle({ cx: 400, cy: 240, r: 75, fill: "none", stroke: "#67e8f9", "stroke-width": 1.5, opacity: 0.6 });
        ctx.text({ x: 400, y: 245, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#ffffff" }, "膚色透亮復原");
      }
    } else if (connector === "scar_maturation") {
      // 疤痕隱痕歷程：初期微凸潮紅 -> 矽膠加壓漸進褪紅 -> 平整隱痕白線
      ctx.rect({ x: 90, y: 145, width: 620, height: 165, rx: 12, fill: "#1e293b", stroke: "#334155", "stroke-width": 1.5 });
      // 左右兩側正常表皮
      ctx.rect({ x: 90, y: 145, width: 230, height: 28, rx: 6, fill: "#fed7aa", opacity: 0.85 });
      ctx.text({ x: 190, y: 164, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#7c2d12" }, "正常皮膚");
      ctx.rect({ x: 480, y: 145, width: 230, height: 28, rx: 6, fill: "#fed7aa", opacity: 0.85 });
      ctx.text({ x: 610, y: 164, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#7c2d12" }, "正常皮膚");

      if (u < 0.35) {
        // 階段一：切口微凸潮紅 + 縫線對合
        ctx.rect({ x: 320, y: 145, width: 160, height: 28, rx: 6, fill: "#ef4444", opacity: 0.85 });
        ctx.line({ x1: 320, y1: 159, x2: 480, y2: 159, stroke: "#dc2626", "stroke-width": 5 });
        // 對合縫合線與節點
        for (let s = 0; s < 4; s++) {
          const sx = 340 + s * 33;
          ctx.line({ x1: sx, y1: 148, x2: sx, y2: 170, stroke: "#38bdf8", "stroke-width": 2 });
          ctx.circle({ cx: sx, cy: 159, r: 3, fill: PALETTE[unitFill] || "#38bdf8" });
        }
        ctx.text({ x: 400, y: 220, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#fca5a5" }, "切口微凸潮紅對合");
      } else if (u < 0.70) {
        // 階段二：水合保濕加壓，漸進褪紅
        const p2 = (u - 0.35) / 0.35;
        // 矽膠加壓保護層
        ctx.rect({ x: 300, y: 135, width: 200, height: 48, rx: 8, fill: "#7dd3fc", opacity: 0.35 });
        ctx.line({ x1: 320, y1: 159, x2: 480, y2: 159, stroke: "#f472b6", "stroke-width": 3.5 - 1.5 * p2 });
        ctx.text({ x: 400, y: 220, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#fbcfe8" }, "水合加壓漸進褪紅");
      } else {
        // 階段三：平整隱痕細白線
        ctx.rect({ x: 320, y: 145, width: 160, height: 28, rx: 6, fill: "#fed7aa", opacity: 0.85 });
        ctx.line({ x1: 320, y1: 159, x2: 480, y2: 159, stroke: "#f8fafc", "stroke-width": 1.2, "stroke-dasharray": "2 1" });
        // 金色隱痕修復光環
        ctx.circle({ cx: 400, cy: 159, r: 28, fill: "none", stroke: "#facc15", "stroke-width": 2, opacity: 0.8 });
        ctx.text({ x: 400, y: 220, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#ffffff" }, "膠原重整平整隱痕");
      }
    } else if (connector === "nerve_regeneration") {
      // 感覺神經重生：暫時麻木遲滯 -> 軸突萌發延伸 -> 感覺受體完全接合傳導
      ctx.rect({ x: 90, y: 140, width: 620, height: 170, rx: 12, fill: "#1e293b", stroke: "#334155", "stroke-width": 1.5 });
      // 左側神經幹
      ctx.line({ x1: 120, y1: 225, x2: 240, y2: 225, stroke: "#eab308", "stroke-width": 7, "stroke-linecap": "round" });
      ctx.circle({ cx: 120, cy: 225, r: 8, fill: "#ca8a04" });
      ctx.text({ x: 180, y: 205, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#fde047" }, "感覺神經主幹");

      // 右側 4 個感覺感受小體
      const receptorYs = [170, 205, 245, 280];
      for (let r = 0; r < receptorYs.length; r++) {
        const ry = receptorYs[r];
        const isConnected = u >= 0.70;
        ctx.circle({ cx: 640, cy: ry, r: 8, fill: isConnected ? (PALETTE[unitFill] || "#facc15") : "#475569", stroke: "#ffffff", "stroke-width": 1.5 });
      }

      if (u < 0.35) {
        // 階段一：神經鈍化與麻木同心光圈
        ctx.circle({ cx: 240, cy: 225, r: 24, fill: "none", stroke: "#64748b", "stroke-width": 2, "stroke-dasharray": "4 4" });
        ctx.circle({ cx: 240, cy: 225, r: 42, fill: "none", stroke: "#64748b", "stroke-width": 1.5, "stroke-dasharray": "6 6" });
        ctx.text({ x: 420, y: 230, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#94a3b8" }, "神經暫時鈍化 (局部麻木)");
      } else if (u < 0.70) {
        // 階段二：鮮黃軸突發芽生長
        const p2 = (u - 0.35) / 0.35;
        const curX = 240 + (640 - 240) * p2;
        for (let r = 0; r < receptorYs.length; r++) {
          const ry = receptorYs[r];
          const midY = (225 + ry) / 2;
          ctx.path({ d: "M 240 225 Q " + (240 + (curX - 240) * 0.5) + " " + midY + " " + curX + " " + (225 + (ry - 225) * p2), fill: "none", stroke: "#facc15", "stroke-width": 2.5, "stroke-linecap": "round" });
          ctx.circle({ cx: curX, cy: 225 + (ry - 225) * p2, r: 3.5, fill: "#fef08a" });
        }
        ctx.text({ x: 420, y: 230, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#fef08a" }, "神經軸突萌芽延伸生長");
      } else {
        // 階段三：完全接合，電位傳導脈衝流動
        for (let r = 0; r < receptorYs.length; r++) {
          const ry = receptorYs[r];
          const midY = (225 + ry) / 2;
          ctx.path({ d: "M 240 225 Q 440 " + midY + " 640 " + ry, fill: "none", stroke: "#facc15", "stroke-width": 2.5, "stroke-linecap": "round" });
          // 電位脈衝光點
          const pulseX = 240 + 380 * ((u * 4 + r * 0.25) % 1);
          ctx.circle({ cx: pulseX, cy: midY, r: 4, fill: "#38bdf8" });
        }
        ctx.text({ x: 420, y: 230, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#ffffff" }, "感覺受體接通 傳導敏銳復原");
      }
    } else if (connector === "skin_retraction") {
      // 組織緊緻回縮：水腫下垂鬆弛 -> 纖維網格收縮拉提 -> 緊緻平整回彈
      ctx.rect({ x: 90, y: 140, width: 620, height: 170, rx: 12, fill: "#1e293b", stroke: "#334155", "stroke-width": 1.5 });
      // 深層筋膜基底
      ctx.rect({ x: 120, y: 280, width: 560, height: 16, rx: 4, fill: "#334155" });
      ctx.text({ x: 400, y: 293, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#64748b" }, "深層筋膜骨架固定層");

      if (u < 0.35) {
        // 階段一：下垂波浪線與水腫層
        let d = "M 120 180";
        for (let i = 1; i <= 14; i++) {
          const x = 120 + i * 40;
          const y = 180 + 24 * Math.sin(i * 0.9);
          d += " L " + x + " " + y.toFixed(1);
        }
        ctx.path({ d: d, fill: "none", stroke: "#f9a8d4", "stroke-width": 4 });
        // 水腫液層
        ctx.rect({ x: 140, y: 215, width: 520, height: 50, rx: 8, fill: "#0284c7", opacity: 0.35 });
        ctx.text({ x: 400, y: 245, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#7dd3fc" }, "皮下微水腫與局部鬆弛");
      } else if (u < 0.70) {
        // 階段二：纖維隔膜收縮，向上拉提
        const p2 = (u - 0.35) / 0.35;
        let d = "M 120 180";
        for (let i = 1; i <= 14; i++) {
          const x = 120 + i * 40;
          const y = 180 + (24 - 16 * p2) * Math.sin(i * 0.9);
          d += " L " + x + " " + y.toFixed(1);
        }
        ctx.path({ d: d, fill: "none", stroke: "#f472b6", "stroke-width": 3.5 });
        // 向上收縮拉力箭頭
        for (let k = 0; k < 5; k++) {
          const kx = 180 + k * 110;
          ctx.line({ x1: kx, y1: 270, x2: kx, y2: 210, stroke: "#fbbf24", "stroke-width": 2 });
          ctx.line({ x1: kx - 5, y1: 220, x2: kx, y2: 210, stroke: "#fbbf24", "stroke-width": 2 });
          ctx.line({ x1: kx + 5, y1: 220, x2: kx, y2: 210, stroke: "#fbbf24", "stroke-width": 2 });
        }
        ctx.text({ x: 400, y: 245, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#fde047" }, "深層基質修復 垂直纖維收縮拉提");
      } else {
        // 階段三：平整緊緻，輪廓回彈
        ctx.line({ x1: 120, y1: 180, x2: 680, y2: 180, stroke: "#ec4899", "stroke-width": 3.5 });
        // 緊緻金色光弧
        ctx.circle({ cx: 400, cy: 180, r: 40, fill: "none", stroke: "#facc15", "stroke-width": 2.5, opacity: 0.85 });
        ctx.text({ x: 400, y: 240, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#ffffff" }, "皮下空隙緊密貼合 輪廓平整回彈");
      }
    }
  }

  function drawContrast(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    // 中線分隔
    ctx.line({ x1: 400, y1: 50, x2: 400, y2: 430, stroke: "#334155", "stroke-width": 2, "stroke-dasharray": "6 6" });

    // 左側面板（對照側）
    ctx.text({ x: 210, y: 65, "text-anchor": "middle", "font-size": 18, "font-weight": "bold", fill: PALETTE.warn }, params.left.title);
    ctx.text({ x: 210, y: 92, "text-anchor": "middle", "font-size": 13, fill: "#94a3b8" }, params.left.note);
    ctx.rect({ x: 50, y: 115, width: 320, height: 250, rx: 12, fill: "#273549", stroke: "#384a62" });

    const leftFill = PALETTE[params.left.unit_fill] || PALETTE.fat;
    const leftStroke = strokeFor(params.left.unit_fill);
    const rightFill = PALETTE[params.right.unit_fill] || PALETTE.fat;
    const rightStroke = strokeFor(params.right.unit_fill);

    if (params.left.mode === "mass") {
      const growScale = Math.min(1, u * 2);
      const rad = 56 * growScale;
      ctx.circle({ cx: 210, cy: 235, r: rad, fill: leftFill, stroke: leftStroke, "stroke-width": 2 });
      if (params.left.core_effect === "dim" && u >= 0.38) {
        const coreU = Math.min(1, (u - 0.38) / 0.35);
        const pulse = 0.75 + 0.25 * Math.sin(u * Math.PI * 6);
        ctx.circle({ cx: 210, cy: 235, r: 38 * coreU, fill: "#451a03", opacity: 0.85 * pulse });
        if (coreU > 0.6) {
          ctx.text({ x: 210, y: 240, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#ffffff" }, params.left.core_label);
        }
      }
    } else if (params.left.mode === "wide_incision") {
      // 寬切口：切口隨進度張開、皮瓣牽開，神經附近以紅色光暈標示壓迫風險（對照組警示）
      const openU = Math.min(1, u * 2);
      const gap = 6 + 22 * openU;
      ctx.rect({ x: 110, y: 230 - gap / 2, width: 200, height: gap, rx: 6, fill: "#7f1d1d", opacity: 0.85 });
      ctx.line({ x1: 110, y1: 230 - gap / 2, x2: 92, y2: 218 - gap / 2, stroke: "#94a3b8", "stroke-width": 2.5, "stroke-linecap": "round" });
      ctx.line({ x1: 110, y1: 230 + gap / 2, x2: 92, y2: 242 + gap / 2, stroke: "#94a3b8", "stroke-width": 2.5, "stroke-linecap": "round" });
      ctx.line({ x1: 310, y1: 230 - gap / 2, x2: 328, y2: 218 - gap / 2, stroke: "#94a3b8", "stroke-width": 2.5, "stroke-linecap": "round" });
      ctx.line({ x1: 310, y1: 230 + gap / 2, x2: 328, y2: 242 + gap / 2, stroke: "#94a3b8", "stroke-width": 2.5, "stroke-linecap": "round" });
      if (u >= 0.4) {
        const pressU = Math.min(1, (u - 0.4) / 0.4);
        const pulse = 0.8 + 0.2 * Math.sin(u * Math.PI * 6);
        ctx.circle({ cx: 210, cy: 300, r: (14 + 10 * pulse) * pressU, fill: "#ef4444", opacity: 0.35 });
        ctx.circle({ cx: 210, cy: 300, r: 4, fill: "#fde047" });
        if (pressU > 0.6) {
          ctx.text({ x: 210, y: 326, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#fca5a5" }, params.left.core_label);
        }
      }
    } else if (params.left.mode === "thermal_spread") {
      // 熱能擴散：由中心向外的同心熱暈，代表組織受熱範圍逐步擴大（對照組）
      for (let ring = 0; ring < 4; ring++) {
        const ringU = Math.max(0, Math.min(1, u * 1.6 - ring * 0.18));
        ctx.circle({ cx: 210, cy: 235, r: 18 + 68 * ringU, fill: "none", stroke: PALETTE.warn, "stroke-width": 2.5, opacity: 0.7 * (1 - ringU * 0.6) });
      }
      ctx.circle({ cx: 210, cy: 235, r: 22, fill: leftFill, stroke: leftStroke, "stroke-width": 2 });
    } else if (CONTRAST_LEFT_SPECIALTY.indexOf(params.left.mode) >= 0) {
      drawContrastLeftSpecialty(ctx, params.left.mode, u);
    } else {
      // scattered mode
      for (let i = 0; i < 6; i++) {
        const hx = deterministicHash(i, 3);
        const hy = deterministicHash(i, 7);
        const cx = 90 + hx * 240;
        const cy = 145 + hy * 190;
        ctx.circle({ cx: cx, cy: cy, r: 16, fill: leftFill, stroke: leftStroke, "stroke-width": 1.5 });
      }
    }
    ctx.text({ x: 210, y: 395, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: PALETTE.warn }, params.left.footnote);

    // 右側面板（推薦側）
    ctx.text({ x: 590, y: 65, "text-anchor": "middle", "font-size": 18, "font-weight": "bold", fill: PALETTE.ok }, params.right.title);
    ctx.text({ x: 590, y: 92, "text-anchor": "middle", "font-size": 13, fill: "#94a3b8" }, params.right.note);
    ctx.rect({ x: 430, y: 115, width: 320, height: 250, rx: 12, fill: "#273549", stroke: "#384a62" });

    if (params.right.mode === "layered") {
      const rows = params.right.rows;
      const perRow = params.right.per_row;
      const totalUnits = rows * perRow;

      // 注射套管（微幅往返）
      const cannulaX = 420 + Math.sin(u * Math.PI * 4) * 8;
      ctx.rect({ x: cannulaX, y: 135, width: 36, height: 6, rx: 3, fill: "#94a3b8" });

      for (let r = 0; r < rows; r++) {
        const rowY = 150 + (180 / (rows + 1)) * (r + 1);
        ctx.line({ x1: 450, y1: rowY, x2: 730, y2: rowY, stroke: "#38bdf8", "stroke-width": 1.5, "stroke-dasharray": "4 4", opacity: 0.45 });

        for (let c = 0; c < perRow; c++) {
          const uIdx = r * perRow + c;
          const popThreshold = (uIdx / totalUnits) * 0.75;
          if (u >= popThreshold) {
            const unitProgress = Math.min(1, (u - popThreshold) / 0.12);
            const unitX = 475 + (230 / (perRow - 1 || 1)) * c;
            // 光圈
            ctx.circle({ cx: unitX, cy: rowY, r: 12 * unitProgress, fill: "none", stroke: PALETTE.ok, "stroke-width": 1.5, opacity: 0.6 });
            // 微粒
            ctx.circle({ cx: unitX, cy: rowY, r: 7 * unitProgress, fill: rightFill });
          }
        }
      }
    } else if (params.right.mode === "minimal_incision") {
      // 隱密切口：短切口在導板安全邊界內完成，並以虛線標示安全邊距（推薦組）
      const cutU = Math.min(1, u * 2.2);
      ctx.line({ x1: 548, y1: 235, x2: 548 + 44 * cutU, y2: 235, stroke: PALETTE.ok, "stroke-width": 3, "stroke-linecap": "round" });
      ctx.line({ x1: 520, y1: 200, x2: 660, y2: 200, stroke: "#94a3b8", "stroke-width": 1.5, "stroke-dasharray": "4 4", opacity: 0.6 });
      ctx.line({ x1: 520, y1: 270, x2: 660, y2: 270, stroke: "#94a3b8", "stroke-width": 1.5, "stroke-dasharray": "4 4", opacity: 0.6 });
      if (u >= 0.5) {
        ctx.circle({ cx: 590, cy: 235, r: 56, fill: "none", stroke: PALETTE.ok, "stroke-width": 1.5, opacity: 0.4 });
      }
    } else if (params.right.mode === "targeted_energy") {
      // 聚焦能量：多層光圈向單一焦點收斂，能量只作用於目標深度（推薦組）
      const focusU = Math.min(1, u * 1.5);
      for (let k = 0; k < 3; k++) {
        const r = (46 - k * 12) * (1 - 0.6 * focusU) + 6;
        ctx.circle({ cx: 590, cy: 235, r: r, fill: "none", stroke: PALETTE.accent, "stroke-width": 2, opacity: 0.5 + 0.2 * k });
      }
      ctx.circle({ cx: 590, cy: 235, r: 3 + 5 * focusU, fill: rightFill });
    } else if (CONTRAST_RIGHT_SPECIALTY.indexOf(params.right.mode) >= 0) {
      drawContrastRightSpecialty(ctx, params.right.mode, u);
    } else {
      ctx.circle({ cx: 590, cy: 235, r: 50, fill: rightFill, stroke: rightStroke, "stroke-width": 2 });
    }
    ctx.text({ x: 590, y: 395, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: PALETTE.ok }, params.right.footnote);
  }

  // Blueprint 3: 時間軸進程（逐步穩定）
  function drawTimeline(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    // 頂部解剖專科標題與法規免責小字（y <= 55）
    ctx.text({ x: 50, y: 52, "font-size": 13, "font-weight": "bold", fill: "#94a3b8" }, "【生理修復歷程與組織成熟】");
    ctx.text({ x: 750, y: 52, "text-anchor": "end", "font-size": 11, fill: "#64748b" }, "實際結果因人而異，須由醫師當面評估");

    // 計算當前進度階段（三階段切換，圖文緊密呼應）
    const stageIdx = u < 0.35 ? 0 : (u < 0.70 ? 1 : 2);
    const STAGE_CONFIGS = [
      { badge: "階段一·初期防護", fill: "#1e3a5f", stroke: "#38bdf8", textFill: "#93c5fd" },
      { badge: "階段二·修復重塑", fill: "#451a03", stroke: "#f59e0b", textFill: "#fbbf24" },
      { badge: "階段三·穩定隱痕", fill: "#064e3b", stroke: "#10b981", textFill: "#6ee7b7" }
    ];
    const sc = STAGE_CONFIGS[stageIdx];

    // 動態階段徽章與當前里程碑膠囊（y: 66..92）
    ctx.rect({ x: 50, y: 66, width: 130, height: 26, rx: 6, fill: sc.fill, stroke: sc.stroke, "stroke-width": 1.5 });
    ctx.text({ x: 115, y: 83, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: sc.textFill }, sc.badge);

    const curMilestone = (params.milestones && params.milestones[stageIdx]) ? params.milestones[stageIdx] : "";
    ctx.rect({ x: 190, y: 66, width: 105, height: 26, rx: 6, fill: "#334155", stroke: "#64748b", "stroke-width": 1.5 });
    ctx.text({ x: 242, y: 83, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#ffffff" }, curMilestone);

    // 動態圖文解說文字（大字清晰隨進度切換，杜絕無圖文變化）
    const descs = TIMELINE_STAGE_DESC[params.connectors] || TIMELINE_STAGE_DESC.vessels;
    const stageDescText = descs[stageIdx] || "";
    ctx.text({ x: 310, y: 84, "font-size": 13, "font-weight": "bold", fill: "#f1f5f9" }, stageDescText);

    // 中央組織基質主畫布（y: 102..332，高 230）
    ctx.rect({ x: 50, y: 102, width: 700, height: 230, rx: 14, fill: "#273549", stroke: "#384a62" });

    // 專科修復歷程繪製
    const isSpecialty = TIMELINE_SPECIALTY.indexOf(params.connectors) >= 0;
    if (isSpecialty) {
      drawTimelineSpecialty(ctx, params.connectors, u, params.unit_fill);
    } else {
      // 通用血管網絡
      const unitCount = params.units;
      if (params.connectors === "vessels") {
        const clamp01 = function (x) { return Math.max(0, Math.min(1, x)); };
        const trunkP = clamp01(u * 2.2);
        const vesselPath = function (d, progress, width) {
          ctx.path({
            d: d,
            fill: "none",
            stroke: PALETTE.blood,
            "stroke-width": width,
            "stroke-linecap": "round",
            pathLength: "100",
            "stroke-dasharray": "100",
            "stroke-dashoffset": String(100 * (1 - progress))
          });
        };
        // 上、下兩條主幹，各自從左右兩端向中央延伸
        vesselPath("M 70 120 L 400 120", trunkP, 4);
        vesselPath("M 730 120 L 400 120", trunkP, 4);
        vesselPath("M 70 310 L 400 310", trunkP, 4);
        vesselPath("M 730 310 L 400 310", trunkP, 4);
        // 由主幹分支到各單元（上下交替，依序長出）
        for (let i = 0; i < unitCount; i++) {
          const ux = 160 + (480 / (unitCount - 1 || 1)) * i;
          const uy = 205 + (i % 2 === 0 ? -16 : 16);
          const fromTop = i % 2 === 0;
          const startY = fromTop ? 120 : 310;
          const endY = fromTop ? uy - 36 : uy + 36;
          const midY = (startY + endY) / 2;
          const branchP = clamp01((u - 0.2 - 0.08 * i) * 3);
          vesselPath("M " + ux + " " + startY + " Q " + (ux + 10) + " " + midY + " " + ux + " " + endY, branchP, 3);
        }
      }

      // 傷口癒合連接：急性期彈性加壓帶（淡藍色）與冰敷雪花，隨進度淡出
      if (params.connectors === "wound_healing") {
        const bandOpacity = Math.max(0, 1 - u * 1.3);
        ctx.rect({ x: 80, y: 228, width: 640, height: 30, rx: 8, fill: "#7dd3fc", opacity: 0.3 * bandOpacity });
        for (let s = 0; s < 4; s++) {
          const bx = 120 + 480 * (s / 3);
          ctx.line({ x1: bx, y1: 228, x2: bx + 8, y2: 258, stroke: "#bae6fd", "stroke-width": 1.5, opacity: 0.5 * bandOpacity });
        }
        const flakeOpacity = Math.max(0, 0.9 - u * 1.2);
        for (let s = 0; s < 6; s++) {
          const sx = 120 + deterministicHash(s, 11) * 560;
          const sy = 120 + deterministicHash(s, 13) * 110;
          for (let arm = 0; arm < 3; arm++) {
            const ang = arm * Math.PI / 3;
            const dx = Math.cos(ang) * 9;
            const dy = Math.sin(ang) * 9;
            ctx.line({ x1: sx - dx, y1: sy - dy, x2: sx + dx, y2: sy + dy, stroke: "#bae6fd", "stroke-width": 1.5, opacity: flakeOpacity });
          }
        }
      }

      // 膠原重組：單元之間的纖維由波浪狀逐步拉直並沿組織排列
      if (params.connectors === "collagen_remodeling") {
        const straighten = 1 - Math.min(1, u);
        const spacing = 480 / (unitCount - 1 || 1);
        for (let i = 0; i + 1 < unitCount; i++) {
          const ax = 160 + spacing * i;
          const ay = 205 + (i % 2 === 0 ? -16 : 16);
          const bx = 160 + spacing * (i + 1);
          const by = 205 + ((i + 1) % 2 === 0 ? -16 : 16);
          const mx = (ax + bx) / 2;
          const my = (ay + by) / 2 + 26 * straighten * (i % 2 === 0 ? 1 : -1);
          ctx.path({
            d: "M " + ax + " " + ay + " Q " + mx + " " + my + " " + bx + " " + by,
            fill: "none",
            stroke: "#e2e8f0",
            "stroke-width": 2.5,
            "stroke-linecap": "round",
            opacity: 0.4 + 0.5 * u
          });
        }
      }

      // 組織單元（通用/血管模式下渲染）
      for (let i = 0; i < unitCount; i++) {
        const ux = 160 + (480 / (unitCount - 1 || 1)) * i;
        const uy = 205 + (i % 2 === 0 ? -16 : 16);

        let unitOpacity = 0.85;
        if (params.unit_effect === "mature") {
          unitOpacity = 0.45 + 0.55 * u;
        } else if (params.unit_effect === "fade") {
          unitOpacity = 1.0 - 0.55 * u;
        }

        const tlFill = PALETTE[params.unit_fill] || PALETTE.fat;
        if (params.unit_effect === "glow_restored") {
          ctx.circle({ cx: ux, cy: uy, r: 42, fill: "none", stroke: "#fde68a", "stroke-width": 3, opacity: 0.7 * u });
        }
        ctx.circle({ cx: ux, cy: uy, r: 35, fill: tlFill, stroke: strokeFor(params.unit_fill), "stroke-width": 2, opacity: unitOpacity });
        ctx.circle({ cx: ux, cy: uy, r: 22, fill: params.unit_fill === "fat" || !params.unit_fill ? "#fef08a" : "#ffffff", opacity: unitOpacity * (params.unit_fill === "fat" || !params.unit_fill ? 0.7 : 0.35) });
      }
    }

    // 底部時間軸進度線條（y: 355）
    ctx.line({ x1: 110, y1: 355, x2: 690, y2: 355, stroke: "#334155", "stroke-width": 6, "stroke-linecap": "round" });
    const currentProgX = 110 + (690 - 110) * u;
    ctx.line({ x1: 110, y1: 355, x2: currentProgX, y2: 355, stroke: PALETTE.accent, "stroke-width": 6, "stroke-linecap": "round" });

    // 三個里程碑點與標籤（全部 y <= 405，嚴格在安全區內）
    const nodePositions = [110, 400, 690];
    const thresholds = [0.05, 0.48, 0.92];
    const stageTimes = ["術後 1~3 天", "術後 1~4 週", "長期穩定"];

    for (let mIdx = 0; mIdx < 3; mIdx++) {
      const nx = nodePositions[mIdx];
      const isReached = u >= thresholds[mIdx];
      const isActive = (mIdx === stageIdx);

      // 當前活躍階段動態脈動光環
      if (isActive) {
        ctx.circle({ cx: nx, cy: 355, r: 15, fill: "none", stroke: sc.stroke, "stroke-width": 2, opacity: 0.85 });
      }

      ctx.circle({ cx: nx, cy: 355, r: 10, fill: isReached ? PALETTE.accent : "#334155", stroke: "#ffffff", "stroke-width": 2 });

      const milestoneText = params.milestones && params.milestones[mIdx] ? params.milestones[mIdx] : "";
      ctx.text(
        {
          x: nx,
          y: 382,
          "text-anchor": "middle",
          "font-size": isActive ? 14 : 13,
          "font-weight": isReached ? "bold" : "normal",
          fill: isReached ? (isActive ? "#ffffff" : "#93c5fd") : "#64748b",
          opacity: isReached ? 1.0 : 0.6
        },
        milestoneText
      );

      ctx.text(
        {
          x: nx,
          y: 398,
          "text-anchor": "middle",
          "font-size": 11,
          fill: isReached ? (isActive ? sc.textFill : "#94a3b8") : "#475569",
          opacity: isReached ? 0.95 : 0.5
        },
        stageTimes[mIdx]
      );
    }
  }

// Blueprint 4: 皮膚分層能量傳遞（音波聚焦 SMAS 筋膜層 / 電波容積加熱真皮層）
  function drawSkinEnergy(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    const layers = params.layer_labels || ["表皮層", "真皮膠原層", "筋膜層"];
    const eColor = ctx.palette(params.energy_fill, PALETTE.accent);

    // 皮膚三層解剖橫切面（x: 90..710）
    // 1. 表皮層 (y: 130..180)
    ctx.rect({ x: 90, y: 130, width: 620, height: 50, rx: 6, fill: "#f7d9c4", opacity: 0.9 });
    ctx.text({ x: 145, y: 160, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#5c3a21" }, layers[0] || "表皮層");

    // 2. 真皮膠原層 (y: 182..282)
    ctx.rect({ x: 90, y: 182, width: 620, height: 100, rx: 6, fill: "#3b2f35", stroke: "#64748b", "stroke-width": 1.5 });
    ctx.text({ x: 145, y: 236, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#fde9a8" }, layers[1] || "真皮膠原層");

    // 真皮層內膠原蛋白波浪纖維（隨 u 緊縮拉提）
    const tighten = Math.min(1, Math.max(0, (u - 0.3) / 0.6));
    for (let r = 0; r < 2; r++) {
      const baseY = 212 + r * 38 - tighten * 6;
      const amp = 12 - tighten * 5;
      const dStr =
        "M 210 " + baseY +
        " Q 260 " + (baseY - amp) + " 310 " + baseY +
        " T 410 " + baseY +
        " T 510 " + baseY +
        " T 610 " + baseY +
        " T 685 " + baseY;
      ctx.path({
        d: dStr,
        fill: "none",
        stroke: tighten > 0.4 ? PALETTE.ok : "#f6b93b",
        "stroke-width": 2.5 + tighten * 1.5,
        opacity: 0.8
      });
    }

    // 3. SMAS 筋膜層 (y: 284..348)
    ctx.rect({ x: 90, y: 284, width: 620, height: 64, rx: 6, fill: "#1e3a5f", stroke: eColor, "stroke-width": 2 });
    ctx.text({ x: 145, y: 321, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#e2e8f0" }, layers[2] || "筋膜層");

    // 探頭隨進度 u 沿表皮上方水平移動 (x: 240..620)
    const probeX = 240 + Math.min(1, u / 0.8) * 380;
    ctx.rect({ x: probeX - 48, y: 66, width: 96, height: 42, rx: 8, fill: "#475569", stroke: "#cbd5e1", "stroke-width": 2 });
    ctx.rect({ x: probeX - 36, y: 108, width: 72, height: 18, rx: 4, fill: eColor });
    ctx.text({ x: probeX, y: 92, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#ffffff" }, params.probe_label);

    const nPoints = params.focal_points || 5;
    if (params.mode === "volumetric") {
      // 電波容積式加熱：由探頭向真皮層發散扇形熱場波弧
      for (let w = 1; w <= 3; w++) {
        const wy = 165 + w * 32;
        const spread = 45 + w * 22;
        ctx.path({
          d: "M " + (probeX - spread) + " " + wy + " Q " + probeX + " " + (wy + 24) + " " + (probeX + spread) + " " + wy,
          fill: "none",
          stroke: PALETTE.warn,
          "stroke-width": 3,
          opacity: 0.75
        });
      }
      // 已掃過的真皮層均勻溫熱區
      for (let i = 0; i < nPoints; i++) {
        const fx = 240 + (380 / (nPoints - 1 || 1)) * i;
        const threshold = (i / nPoints) * 0.75;
        if (u >= threshold) {
          const glow = Math.min(1, (u - threshold) / 0.15);
          ctx.circle({ cx: fx, cy: 232, r: 22 * glow, fill: PALETTE.fat, opacity: 0.35 * glow });
          ctx.circle({ cx: fx, cy: 232, r: 9 * glow, fill: PALETTE.warn, opacity: 0.85 * glow });
        }
      }
    } else {
      // 音波聚焦模式：穿透表皮與真皮，精準匯聚於 SMAS 筋膜層形成熱凝結點
      ctx.path({
        d: "M " + (probeX - 30) + " 126 L " + probeX + " 316 L " + (probeX + 30) + " 126 Z",
        fill: eColor,
        opacity: 0.28,
        stroke: eColor,
        "stroke-width": 1.5,
        "stroke-dasharray": "4 3"
      });
      for (let i = 0; i < nPoints; i++) {
        const fx = 240 + (380 / (nPoints - 1 || 1)) * i;
        const threshold = (i / nPoints) * 0.75;
        if (u >= threshold) {
          const p = Math.min(1, (u - threshold) / 0.12);
          ctx.circle({ cx: fx, cy: 316, r: 15 * p, fill: "none", stroke: PALETTE.ok, "stroke-width": 2, opacity: 0.8 });
          ctx.circle({ cx: fx, cy: 316, r: 7 * p, fill: "#fde9a8", stroke: PALETTE.warn, "stroke-width": 1.5 });
        }
      }
    }

    // 底部三階段步驟說明（全部 y <= 410）
    const steps = params.step_labels || [];
    const sx = [180, 400, 620];
    const st = [0.05, 0.38, 0.72];
    for (let s = 0; s < 3; s++) {
      if (steps[s]) {
        const op = u >= st[s] ? Math.min(1, (u - st[s]) / 0.15) : 0.25;
        ctx.text(
          { x: sx[s], y: 395, "text-anchor": "middle", "font-size": 15, "font-weight": u >= st[s] ? "bold" : "normal", fill: s === 2 && u >= st[s] ? PALETTE.ok : "#cfe0f5", opacity: op },
          steps[s]
        );
      }
    }
  }

  // Blueprint 5: 雷射皮膚作用（皮秒光震波擊碎黑色素 / 飛梭分段微創光柱）
  function drawLaserAction(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    const layers = params.layer_labels || ["表皮角質層", "真皮基底層"];
    const bColor = ctx.palette(params.beam_fill, PALETTE.accent);

    // 皮膚雙層橫切面
    ctx.rect({ x: 90, y: 145, width: 620, height: 65, rx: 6, fill: "#f7d9c4", opacity: 0.9 });
    ctx.text({ x: 150, y: 182, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#5c3a21" }, layers[0] || "表皮角質層");

    ctx.rect({ x: 90, y: 212, width: 620, height: 135, rx: 6, fill: "#33272a", stroke: "#64748b", "stroke-width": 1.5 });
    ctx.text({ x: 150, y: 285, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#fde9a8" }, layers[1] || "真皮基底層");

    // 頂部雷射發射器
    ctx.rect({ x: 350, y: 58, width: 140, height: 38, rx: 8, fill: "#475569", stroke: "#cbd5e1", "stroke-width": 2 });
    ctx.text({ x: 420, y: 82, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#ffffff" }, params.beam_label);

    if (params.mode === "fractional") {
      // 飛梭分段微創模式：發射多道平行微創光柱，保留柱間健康組織橋樑
      const cols = 6;
      for (let c = 0; c < cols; c++) {
        const cx = 250 + c * 68;
        const fireP = Math.max(0, Math.min(1, (u - c * 0.08) / 0.25));
        if (fireP > 0) {
          const beamH = 175 * fireP;
          ctx.rect({ x: cx - 5, y: 98, width: 10, height: beamH, rx: 3, fill: bColor, opacity: 0.75 });
          // 真皮新生修復光圈
          if (u >= 0.45) {
            const healP = Math.min(1, (u - 0.45) / 0.4);
            ctx.circle({ cx: cx, cy: 255, r: 16 * healP, fill: PALETTE.ok, opacity: 0.45 * healP });
          }
        }
      }
      ctx.text({ x: 420, y: 332, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: PALETTE.ok }, params.target_label);
    } else {
      // 皮秒光震波擊碎色素模式
      // 脈衝光束 (u: 0.1..0.65)
      if (u >= 0.08 && u <= 0.72) {
        const pulseOp = Math.sin(((u - 0.08) / 0.64) * Math.PI);
        ctx.rect({ x: 412, y: 96, width: 16, height: 155, fill: bColor, opacity: 0.85 * pulseOp });
        ctx.circle({ cx: 420, cy: 255, r: 28 + (u - 0.08) * 65, fill: "none", stroke: "#fde9a8", "stroke-width": 2.5, opacity: pulseOp });
      }

      // 黑色素團塊 (u < 0.35 完整團塊 -> u >= 0.35 震碎為 14 顆微細粉塵向外散開並淡化)
      const shatterP = Math.max(0, Math.min(1, (u - 0.32) / 0.58));
      if (shatterP < 0.45) {
        const bigScale = 1 - shatterP * 1.4;
        ctx.circle({ cx: 420, cy: 255, r: Math.max(8, 36 * bigScale), fill: "#78350f", stroke: "#f6b93b", "stroke-width": 2, opacity: 1 - shatterP });
      }
      for (let i = 0; i < 14; i++) {
        const ang = (i / 14) * Math.PI * 2;
        const dist = 14 + shatterP * (55 + deterministicHash(i, 5) * 35);
        const px = 420 + Math.cos(ang) * dist;
        const py = 255 + Math.sin(ang) * dist * 0.65;
        const r = Math.max(2.5, 9 * (1 - shatterP * 0.55));
        const fadeOp = u > 0.75 ? Math.max(0.25, 1 - (u - 0.75) * 2.5) : 0.95;
        ctx.circle({ cx: px, cy: py, r: r, fill: "#b45309", stroke: "#fde9a8", "stroke-width": 1, opacity: fadeOp });
      }
      ctx.text({ x: 420, y: 332, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#fde9a8" }, params.target_label);
    }

    const steps = params.step_labels || [];
    const sx = [180, 420, 640];
    const st = [0.05, 0.35, 0.7];
    for (let s = 0; s < 3; s++) {
      if (steps[s]) {
        const op = u >= st[s] ? Math.min(1, (u - st[s]) / 0.15) : 0.25;
        ctx.text(
          { x: sx[s], y: 395, "text-anchor": "middle", "font-size": 15, "font-weight": u >= st[s] ? "bold" : "normal", fill: s === 2 && u >= st[s] ? PALETTE.ok : "#cfe0f5", opacity: op },
          steps[s]
        );
      }
    }
  }

  // Blueprint 6: 神經肌肉傳導阻斷與動態紋放鬆（肉毒桿菌素注射）
  function drawNeuromuscular(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    const relaxP = Math.max(0, Math.min(1, (u - 0.25) / 0.65));
    const bColor = ctx.palette(params.blocker_fill, PALETTE.ok);

    // 1. 頂部表皮動態紋曲線（隨 relaxP 逐漸撫平）
    const foldDepth = 24 * (1 - 0.82 * relaxP);
    const skinPath =
      "M 120 98 L 280 98 Q 310 " + (98 + foldDepth) + " 340 98 " +
      "Q 400 " + (98 + foldDepth * 1.2) + " 460 98 " +
      "Q 490 " + (98 + foldDepth) + " 520 98 L 680 98";
    ctx.path({ d: skinPath, fill: "none", stroke: "#f7d9c4", "stroke-width": 6, "stroke-linecap": "round" });
    ctx.text({ x: 615, y: 82, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#f7d9c4" }, params.surface_label);

    // 2. 中央運動神經末梢（軸突終端球體）
    ctx.rect({ x: 382, y: 118, width: 36, height: 42, fill: "#64748b" });
    ctx.circle({ cx: 400, cy: 175, r: 38, fill: "#334155", stroke: "#94a3b8", "stroke-width": 2.5 });
    ctx.text({ x: 265, y: 178, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#cfe0f5" }, params.nerve_label);

    // 神經傳導訊號點 vs 阻斷保護層
    for (let i = 0; i < 5; i++) {
      const sx = 330 + i * 35;
      if (u < 0.45) {
        const dropY = 205 + ((u * 3 + i * 0.2) % 1) * 45;
        ctx.circle({ cx: sx, cy: dropY, r: 5, fill: PALETTE.warn, opacity: 1 - relaxP * 0.7 });
      }
      if (u >= 0.25) {
        const shieldP = Math.min(1, (u - 0.25) / 0.3);
        ctx.rect({ x: sx - 12, y: 232, width: 24, height: 8, rx: 4, fill: bColor, opacity: shieldP });
      }
    }

    // 3. 底部表情肌肉束（由緊繃收縮轉為舒張平順）
    const muscleW = 360 + relaxP * 120;
    const muscleX = 400 - muscleW / 2;
    const muscleColor = relaxP > 0.5 ? PALETTE.ok : PALETTE.blood;
    ctx.rect({ x: muscleX, y: 268, width: muscleW, height: 64, rx: 28, fill: muscleColor, opacity: 0.85, stroke: "#ffffff", "stroke-width": 2 });
    ctx.text({ x: 400, y: 306, "text-anchor": "middle", "font-size": 15, "font-weight": "bold", fill: "#ffffff" }, params.muscle_label);

    const steps = params.step_labels || [];
    const sx = [180, 400, 620];
    const st = [0.05, 0.35, 0.7];
    for (let s = 0; s < 3; s++) {
      if (steps[s]) {
        const op = u >= st[s] ? Math.min(1, (u - st[s]) / 0.15) : 0.25;
        ctx.text(
          { x: sx[s], y: 395, "text-anchor": "middle", "font-size": 15, "font-weight": u >= st[s] ? "bold" : "normal", fill: s === 2 && u >= st[s] ? PALETTE.ok : "#cfe0f5", opacity: op },
          steps[s]
        );
      }
    }
  }

  // Blueprint 7: 皮下凹陷分層支撐（玻尿酸填充）
  function drawDermalSupport(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    const layers = params.layer_labels || ["表皮輪廓層", "真皮皮下層"];
    const fColor = ctx.palette(params.filler_fill, PALETTE.gel);
    const liftP = Math.max(0, Math.min(1, (u - 0.15) / 0.7));

    // 真皮與皮下組織基底框
    ctx.rect({ x: 90, y: 155, width: 620, height: 190, rx: 10, fill: "#273549", stroke: "#475569", "stroke-width": 1.5 });
    ctx.text({ x: 155, y: 325, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#94a3b8" }, layers[1] || "真皮皮下層");

    // 頂部表皮輪廓線（初始中央凹陷，隨凝膠支撐平順隆起）
    const dipY = 215 - liftP * 62;
    ctx.path({
      d: "M 90 150 L 230 150 Q 400 " + dipY + " 570 150 L 710 150",
      fill: "none",
      stroke: "#f7d9c4",
      "stroke-width": 8,
      "stroke-linecap": "round"
    });
    ctx.text({ x: 155, y: 132, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: "#f7d9c4" }, layers[0] || "表皮輪廓層");

    // 分層凝膠微滴支撐點
    const count = params.droplets || 6;
    for (let i = 0; i < count; i++) {
      const row = i % 2;
      const col = Math.floor(i / 2);
      const totalCols = Math.ceil(count / 2);
      const gx = 290 + (220 / (totalCols - 1 || 1)) * col;
      const gy = row === 0 ? 235 : 285;
      const appearP = Math.max(0, Math.min(1, (u - i * 0.09) / 0.2));
      if (appearP > 0) {
        ctx.circle({ cx: gx, cy: gy, r: 20 * appearP, fill: fColor, opacity: 0.35 * appearP });
        ctx.circle({ cx: gx, cy: gy, r: 12 * appearP, fill: fColor, stroke: "#ffffff", "stroke-width": 1.5, opacity: 0.9 * appearP });
      }
    }

    ctx.text({ x: 635, y: 255, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: fColor }, params.filler_label);

    const steps = params.step_labels || [];
    const sx = [180, 400, 620];
    const st = [0.05, 0.35, 0.7];
    for (let s = 0; s < 3; s++) {
      if (steps[s]) {
        const op = u >= st[s] ? Math.min(1, (u - st[s]) / 0.15) : 0.25;
        ctx.text(
          { x: sx[s], y: 395, "text-anchor": "middle", "font-size": 15, "font-weight": u >= st[s] ? "bold" : "normal", fill: s === 2 && u >= st[s] ? PALETTE.ok : "#cfe0f5", opacity: op },
          steps[s]
        );
      }
    }
  }

// Blueprint 8: 粉瘤與皮下囊腫微創切除 (Punch / 旋轉切除、排空減壓、完整囊袋剝離)
  function drawCystExcision(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    const layers = params.layer_labels || ["表皮層", "皮下真皮層"];
    const sFill = ctx.palette(params.sac_fill, PALETTE.accent);

    // 1. 表皮層 (y: 125..175)
    ctx.rect({ x: 80, y: 125, width: 640, height: 50, rx: 6, fill: "#fed7aa", opacity: 0.95 });
    ctx.line({ x1: 80, y1: 125, x2: 720, y2: 125, stroke: "#d4a373", "stroke-width": 2.5 });
    ctx.text({ x: 140, y: 155, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#7c2d12" }, layers[0] || "表皮層");

    // 2. 皮下真皮層 (y: 177..345)
    ctx.rect({ x: 80, y: 177, width: 640, height: 168, rx: 6, fill: "#272228", stroke: "#475569", "stroke-width": 1.5 });
    ctx.text({ x: 140, y: 220, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#fde9a8" }, layers[1] || "皮下真皮層");

    // 皮下正常脂肪細胞球 (背景襯托)
    for (let row = 0; row < 3; row++) {
      for (let col = 0; col < 6; col++) {
        const ax = col < 3 ? 180 + col * 45 : 490 + (col - 3) * 45;
        const ay = 205 + row * 45;
        ctx.circle({ cx: ax, cy: ay, r: 16, fill: PALETTE.fat, opacity: 0.25, stroke: "#ca8a04", "stroke-width": 1 });
      }
    }

    // 中央微創切口 (Punch Opening: x=388..412, y=123)
    ctx.rect({ x: 388, y: 123, width: 24, height: 54, fill: "#1e293b", stroke: PALETTE.accent, "stroke-width": 2 });

    const cx = 400;
    const baseCy = 255;

    if (u < 0.35) {
      // 階段 1：微創切口定位與局部麻醉浸潤，飽滿囊腫與完整包膜
      const p1 = u / 0.35;
      const toolY = 60 + p1 * 55;
      // 微創打孔刀具
      ctx.rect({ x: 393, y: toolY, width: 14, height: 45, rx: 3, fill: "#94a3b8", stroke: "#ffffff", "stroke-width": 1.5 });
      ctx.polygon({ points: "393," + (toolY + 45) + " 407," + (toolY + 45) + " 400," + (toolY + 54), fill: sFill });
      ctx.text({ x: 400, y: toolY - 8, "text-anchor": "middle", "font-size": 12, fill: "#e2e8f0" }, "微旋轉打孔");

      // 飽滿粉瘤囊腫 (r=62)
      ctx.circle({ cx: cx, cy: baseCy, r: 62, fill: "#332220", stroke: sFill, "stroke-width": 3.5 });
      // 內部角質碎屑核
      for (let k = 0; k < 9; k++) {
        const ang = (k / 9) * Math.PI * 2;
        const dist = 18 + (k % 3) * 12;
        ctx.circle({ cx: cx + Math.cos(ang) * dist, cy: baseCy + Math.sin(ang) * dist, r: 5, fill: "#fef08a", opacity: 0.85 });
      }
      ctx.text({ x: cx, y: baseCy + 5, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#ffffff" }, params.cyst_label);
      ctx.text({ x: cx + 75, y: baseCy - 30, "text-anchor": "start", "font-size": 11, fill: sFill }, params.sac_label);
      ctx.line({ x1: cx + 45, y1: baseCy - 20, x2: cx + 72, y2: baseCy - 28, stroke: sFill, "stroke-width": 1.2 });
    } else if (u < 0.70) {
      // 階段 2：減壓排空與引流，角質碎屑經微創孔流暢抽吸，囊壁塌陷
      const p2 = (u - 0.35) / 0.35;
      const rNow = 62 - p2 * 32;

      // 負壓引流管
      ctx.rect({ x: 395, y: 80, width: 10, height: 80, fill: "#38bdf8", opacity: 0.85, stroke: "#ffffff", "stroke-width": 1 });
      ctx.text({ x: 400, y: 72, "text-anchor": "middle", "font-size": 11, fill: "#38bdf8" }, "負壓吸引");

      // 兩側向內加壓箭頭
      ctx.path({ d: "M 315 255 L 345 255 M 340 250 L 345 255 L 340 260", fill: "none", stroke: PALETTE.ok, "stroke-width": 2.5 });
      ctx.path({ d: "M 485 255 L 455 255 M 460 250 L 455 255 L 460 260", fill: "none", stroke: PALETTE.ok, "stroke-width": 2.5 });

      // 縮小塌陷中的囊腫
      ctx.circle({ cx: cx, cy: baseCy, r: rNow, fill: "#271c1b", stroke: sFill, "stroke-width": 2.5 });
      // 角質碎屑沿中心軸向上噴湧抽吸
      const flowCount = 6;
      for (let k = 0; k < flowCount; k++) {
        const fy = 240 - k * 22;
        ctx.circle({ cx: cx + Math.sin(k + p2 * 8) * 4, cy: fy, r: 4, fill: "#fef08a", opacity: 0.9 });
      }
      ctx.text({ x: cx, y: baseCy + 4, "text-anchor": "middle", "font-size": 11, fill: "#fde047" }, params.core_label);
    } else {
      // 階段 3：完整薄膜囊袋剝離抽出，傷口極小密合，防復發
      const p3 = (u - 0.70) / 0.30;
      // 微創鑷子
      ctx.path({ d: "M 390 50 L 398 120 M 410 50 L 402 120", fill: "none", stroke: "#94a3b8", "stroke-width": 2 });

      // 被完整夾出開口的囊膜
      const sacY = 180 - p3 * 65;
      ctx.circle({ cx: cx, cy: sacY, r: 18, fill: "none", stroke: PALETTE.ok, "stroke-width": 3 });
      ctx.text({ x: cx + 40, y: sacY + 4, "text-anchor": "start", "font-size": 12, "font-weight": "bold", fill: PALETTE.ok }, "完整囊壁已剝離");

      // 原皮下囊腔淨空
      ctx.circle({ cx: cx, cy: baseCy, r: 35, fill: "#1e1e24", stroke: "#475569", "stroke-width": 1.5, "stroke-dasharray": "4 4" });
      ctx.text({ x: cx, y: baseCy + 4, "text-anchor": "middle", "font-size": 11, fill: "#94a3b8" }, "乾淨囊腔無殘留");

      // 微創傷口細線密合 (y=125)
      ctx.line({ x1: 395, y1: 125, x2: 405, y2: 125, stroke: PALETTE.ok, "stroke-width": 3 });
      ctx.circle({ cx: 400, cy: 125, r: 4, fill: PALETTE.ok });
    }

    drawStepPills(ctx, params.step_labels, u);
  }

  // Blueprint 9: 甲溝炎嵌甲側切與甲床基質重整 (縱切移除嵌甲刺、甲床根部重整)
  function drawNailMatrix(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    const mFill = ctx.palette(params.matrix_fill, PALETTE.warn);

    // 趾端整體輪廓 (俯視視角)
    ctx.rect({ x: 220, y: 80, width: 360, height: 275, rx: 45, fill: "#fed7aa", stroke: "#d4a373", "stroke-width": 2 });

    // 側甲襞與近端甲襞標示
    ctx.text({ x: 255, y: 220, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#7c2d12" }, params.fold_label);
    ctx.text({ x: 400, y: 105, "text-anchor": "middle", "font-size": 12, fill: "#9a3412" }, "近端甲襞");

    // 甲床基底 (y: 120..315)
    ctx.rect({ x: 275, y: 120, width: 250, height: 195, rx: 10, fill: "#f43f5e", opacity: 0.28 });

    // 主體健康趾甲板 (x: 320..525)
    ctx.rect({ x: 320, y: 120, width: 205, height: 190, rx: 6, fill: "#e2e8f0", opacity: 0.92, stroke: "#cbd5e1", "stroke-width": 1.5 });
    ctx.text({ x: 425, y: 220, "text-anchor": "middle", "font-size": 15, "font-weight": "bold", fill: "#334155" }, params.nail_label);

    // 左側嵌甲條 (x: 280..320)
    const spiculeX = 280;
    const spiculeW = 40;

    if (u < 0.35) {
      // 階段 1：嵌甲刺入紅腫肉芽，游離探針探查
      const p1 = u / 0.35;
      // 發炎紅腫暈
      const flareR = 24 + Math.sin(p1 * Math.PI * 4) * 4;
      ctx.circle({ cx: 282, cy: 260, r: flareR, fill: PALETTE.blood, opacity: 0.65 });
      ctx.circle({ cx: 282, cy: 260, r: 10, fill: PALETTE.warn, opacity: 0.85 });
      ctx.text({ x: 190, y: 265, "text-anchor": "end", "font-size": 11, "font-weight": "bold", fill: PALETTE.blood }, "嵌甲紅腫肉芽");

      // 嵌甲條尚連在甲板上
      ctx.rect({ x: spiculeX, y: 120, width: spiculeW, height: 190, rx: 4, fill: "#e2e8f0", opacity: 0.95, stroke: PALETTE.warn, "stroke-width": 2 });
      ctx.text({ x: 300, y: 200, "text-anchor": "middle", "font-size": 11, fill: PALETTE.warn }, params.spicule_label);

      // 游離探針
      const probeY = 320 - p1 * 50;
      ctx.line({ x1: 275, y1: probeY + 30, x2: 282, y2: probeY, stroke: "#38bdf8", "stroke-width": 3, "stroke-linecap": "round" });
    } else if (u < 0.70) {
      // 階段 2：縱向直線切開，整條嵌甲刺垂直夾除抽出
      const p2 = (u - 0.35) / 0.35;
      // 縱向垂直切割手術線 (x=320)
      ctx.line({ x1: 320, y1: 110, x2: 320, y2: 315, stroke: "#38bdf8", "stroke-width": 2.5, "stroke-dasharray": "4 3" });

      // 嵌甲條被鑷子夾出向左上方移出
      const liftX = spiculeX - p2 * 50;
      const liftY = 120 - p2 * 25;
      ctx.rect({ x: liftX, y: liftY, width: spiculeW, height: 190, rx: 4, fill: "#cbd5e1", opacity: 0.9, stroke: PALETTE.accent, "stroke-width": 1.5 });
      ctx.text({ x: liftX + 20, y: liftY + 95, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: PALETTE.accent }, "夾除");

      // 發炎紅腫縮小
      ctx.circle({ cx: 282, cy: 260, r: 16 * (1 - p2 * 0.5), fill: PALETTE.blood, opacity: 0.4 });
      ctx.text({ x: 300, y: 200, "text-anchor": "middle", "font-size": 11, fill: "#38bdf8" }, "縱向側切");
    } else {
      // 階段 3：甲根基質破壞重整 (Matrixectomy)，避免復發，甲溝平復
      const p3 = (u - 0.70) / 0.30;
      // 左側基質深層生長角 (x: 280..320, y: 115..135)
      ctx.rect({ x: 280, y: 115, width: 40, height: 26, rx: 4, fill: mFill, opacity: 0.85 });
      // 治療探頭施加微熱/化學修復光芒
      const pulse = 0.5 + 0.5 * Math.sin(p3 * Math.PI * 6);
      ctx.circle({ cx: 300, cy: 128, r: 14 * pulse, fill: "none", stroke: PALETTE.ok, "stroke-width": 2.5 });
      ctx.text({ x: 235, y: 132, "text-anchor": "end", "font-size": 11, "font-weight": "bold", fill: PALETTE.ok }, "甲母質重整");

      // 左側甲溝平整，無紅腫
      ctx.path({ d: "M 280 145 Q 285 240 285 310", fill: "none", stroke: PALETTE.ok, "stroke-width": 3 });
      ctx.text({ x: 245, y: 270, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: PALETTE.ok }, "平整甲溝");
      ctx.text({ x: 300, y: 220, "text-anchor": "middle", "font-size": 11, fill: "#94a3b8" }, "不再向內生長");
    }

    drawStepPills(ctx, params.step_labels, u);
  }

  // Blueprint 10: 微創螺旋刀刮除抽吸／皮下脂肪抽吸與鬆解
  function drawSubdermalCurettage(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    const layers = params.layer_labels || ["真皮深層", "皮下脂肪層"];
    const tFill = ctx.palette(params.tool_fill, PALETTE.accent);

    // 1. 表皮與真皮深層 (y: 120..195)
    ctx.rect({ x: 80, y: 120, width: 640, height: 75, rx: 6, fill: "#fed7aa", opacity: 0.95 });
    ctx.line({ x1: 80, y1: 120, x2: 720, y2: 120, stroke: "#d4a373", "stroke-width": 2.5 });
    // 微細毛囊示意
    for (let h = 0; h < 6; h++) {
      const hx = 180 + h * 85;
      ctx.path({ d: "M " + (hx - 3) + " 110 L " + hx + " 165", fill: "none", stroke: "#475569", "stroke-width": 2 });
    }
    ctx.text({ x: 135, y: 155, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#7c2d12" }, layers[0] || "真皮深層");

    // 2. 皮下脂肪與頂漿腺目標層 (y: 197..345)
    ctx.rect({ x: 80, y: 197, width: 640, height: 148, rx: 6, fill: "#272228", stroke: "#475569", "stroke-width": 1.5 });
    ctx.text({ x: 135, y: 235, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#fde9a8" }, layers[1] || "皮下層次");

    // 真皮下微血管網 (保護層 y=197)
    ctx.line({ x1: 80, y1: 197, x2: 720, y2: 197, stroke: "#ef4444", "stroke-width": 1.8, "stroke-dasharray": "6 4" });
    ctx.text({ x: 650, y: 192, "text-anchor": "middle", "font-size": 10, fill: "#fca5a5" }, "真皮微血管網(保留)");

    // 左側微創小切口 (y=265)
    ctx.rect({ x: 76, y: 255, width: 12, height: 24, rx: 2, fill: "#1e293b", stroke: PALETTE.accent, "stroke-width": 2 });

    // 腺體顆粒陣列 (頂漿腺 / 脂肪腺球)
    const nGlands = 10;
    const sweepLimit = u >= 0.35 ? Math.min(nGlands, Math.floor(((u - 0.35) / 0.35) * nGlands)) : 0;

    for (let g = 0; g < nGlands; g++) {
      const gx = 210 + g * 48;
      const gy = 245 + (g % 2) * 26;
      if (g >= sweepLimit) {
        // 未刮除之腺體 (金黃色腺體球群)
        ctx.circle({ cx: gx, cy: gy, r: 12, fill: PALETTE.fat, stroke: "#d97706", "stroke-width": 1.5 });
        ctx.circle({ cx: gx - 3, cy: gy - 3, r: 4, fill: "#fef08a" });
      } else {
        // 已刮除抽吸區域：乾淨平復
        ctx.circle({ cx: gx, cy: gy, r: 6, fill: "none", stroke: PALETTE.ok, "stroke-width": 1, opacity: 0.4 });
      }
    }

    // 螺旋旋轉刮刀導管 (Cannula)
    let tipX = 140;
    if (u < 0.35) {
      tipX = 120 + (u / 0.35) * 80;
    } else if (u < 0.70) {
      tipX = 200 + ((u - 0.35) / 0.35) * 460;
    } else {
      tipX = 660;
    }

    // 導管金屬管身
    ctx.rect({ x: 80, y: 256, width: tipX - 80, height: 16, rx: 4, fill: "#94a3b8", stroke: "#cbd5e1", "stroke-width": 1.5 });
    // 刀頭旋轉窗口
    ctx.rect({ x: tipX - 22, y: 254, width: 22, height: 20, rx: 3, fill: "#0f172a", stroke: tFill, "stroke-width": 2 });

    if (u >= 0.35 && u < 0.70) {
      // 刀頭高速旋轉光弧
      ctx.circle({ cx: tipX - 11, cy: 264, r: 14, fill: "none", stroke: tFill, "stroke-width": 2.5, "stroke-dasharray": "6 4" });
      // 碎屑沿導管向左真空抽吸
      for (let s = 0; s < 4; s++) {
        const sx = tipX - 45 - s * 55;
        if (sx > 85) {
          ctx.circle({ cx: sx, cy: 264, r: 3, fill: "#fef08a", opacity: 0.85 });
        }
      }
      ctx.text({ x: tipX, y: 240, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: tFill }, "旋轉刮吸中");
    } else if (u >= 0.70) {
      ctx.text({ x: 420, y: 265, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: PALETTE.ok }, "頂漿腺全數清除，平整清爽");
    }

    drawStepPills(ctx, params.step_labels, u);
  }

// Blueprint 11: 中下臉 SMAS 筋膜深層拉皮手術 (Deep Plane Facelift & Periosteum Anchoring)
  function drawDeepPlaneFacelift(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    const layers = params.layer_labels || ["表皮輪廓層", "SMAS筋膜層", "堅韌骨膜基底"];
    const sFill = ctx.palette(params.suture_fill, PALETTE.accent);
    const smasLabel = params.smas_label || "SMAS筋膜瓣";
    const anchorLabel = params.anchor_label || "骨膜錨定點";
    const ligLabel = params.ligament_label || "維持韌帶";

    // 頂部解剖圖層標籤
    ctx.text({ x: 50, y: 56, "font-size": 13, "font-weight": "bold", fill: "#94a3b8" }, "【顏面深層解剖縱深】");
    ctx.rect({ x: 190, y: 42, width: 100, height: 22, rx: 4, fill: "#fed7aa", opacity: 0.9 });
    ctx.text({ x: 240, y: 57, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#7c2d12" }, layers[0]);
    ctx.rect({ x: 300, y: 42, width: 100, height: 22, rx: 4, fill: "#d97706", opacity: 0.85 });
    ctx.text({ x: 350, y: 57, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#ffffff" }, layers[1]);
    ctx.rect({ x: 410, y: 42, width: 100, height: 22, rx: 4, fill: "#334155", stroke: "#64748b", "stroke-width": 1.5 });
    ctx.text({ x: 460, y: 57, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#93c5fd" }, layers[2]);

    // 1. 深層骨骼基底 (顳骨與顴骨弓堅韌骨膜)
    ctx.path({
      d: "M 400 130 Q 480 125 550 145 L 565 295 Q 490 310 420 330 Z",
      fill: "#182234",
      stroke: "#475569",
      "stroke-width": 2
    });
    ctx.text({ x: 505, y: 155, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#93c5fd" }, anchorLabel);

    // 耳朵外廓 (耳前切口標定線與耳垂)
    ctx.path({
      d: "M 525 180 Q 565 175 565 220 Q 565 260 540 270 Q 530 285 520 285 Q 515 270 525 255 Z",
      fill: "#334155",
      stroke: "#64748b",
      "stroke-width": 1.5
    });
    ctx.circle({ cx: 526, cy: 275, r: 8, fill: "#fbcfe8", stroke: "#e879f9", "stroke-width": 1.5 });
    ctx.text({ x: 575, y: 278, "font-size": 10, fill: "#f0abfc" }, "耳垂(無拉扯)");

    // 耳屏前天然輪廓隱痕切口線
    ctx.line({ x1: 512, y1: 170, x2: 512, y2: 270, stroke: PALETTE.accent, "stroke-width": 2.5, "stroke-dasharray": "4 3" });
    ctx.text({ x: 512, y: 160, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: PALETTE.accent }, "微創隱痕切口");

    // 計算筋膜上提與緊實位移 (45度向量提拉)
    let liftX = 0;
    let liftY = 0;
    if (u >= 0.35 && u < 0.70) {
      const p2 = (u - 0.35) / 0.35;
      liftX = p2 * 32;
      liftY = -p2 * 32;
    } else if (u >= 0.70) {
      liftX = 32;
      liftY = -32;
    }

    // 2. SMAS 筋膜瓣與面頰組織 (琥珀金色筋膜層)
    const cheekX = 260 + liftX;
    const cheekY = 240 + liftY;
    const jowlX = 320 + liftX * 0.8;
    const jowlY = 325 + liftY * 0.8;

    ctx.path({
      d: "M " + (cheekX + 30) + " 170 Q " + (cheekX - 60) + " " + cheekY + " " + jowlX + " " + jowlY + " Q 410 " + (330 + liftY * 0.5) + " 490 285 L 490 190 Z",
      fill: "#d97706",
      opacity: 0.45,
      stroke: "#fbbf24",
      "stroke-width": 2
    });
    ctx.text({ x: cheekX - 10, y: cheekY - 10, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#fde68a" }, smasLabel);

    // 3. 面部維持韌帶 (顴骨韌帶與咬肌韌帶)
    const lig1X = 385;
    const lig1Y = 210;
    const lig2X = 415;
    const lig2Y = 290;

    if (u < 0.35) {
      // 階段 1：維持韌帶緊繃束縛，解離刀具進入深層間隙鬆解
      const p1 = u / 0.35;
      ctx.line({ x1: 460, y1: 190, x2: lig1X, y2: lig1Y, stroke: "#ef4444", "stroke-width": 3 });
      ctx.line({ x1: 470, y1: 275, x2: lig2X, y2: lig2Y, stroke: "#ef4444", "stroke-width": 3 });
      ctx.text({ x: lig1X - 10, y: lig1Y - 8, "font-size": 11, "font-weight": "bold", fill: "#fca5a5" }, ligLabel + "(束縛)");

      // 微創解離指示箭頭深入深層間隙
      const cutX = 505 - p1 * 85;
      const cutY = 205 + p1 * 30;
      ctx.circle({ cx: cutX, cy: cutY, r: 7, fill: PALETTE.accent, stroke: "#ffffff", "stroke-width": 1.5 });
      ctx.line({ x1: cutX + 15, y1: cutY - 10, x2: cutX, y2: cutY, stroke: PALETTE.accent, "stroke-width": 2 });
      ctx.text({ x: 390, y: 150, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: PALETTE.accent }, "深層間隙解離維持韌帶");
    } else {
      // 階段 2 & 3：韌帶已徹底鬆解，釋放拘束
      ctx.line({ x1: 460, y1: 190, x2: lig1X + 10, y2: lig1Y - 5, stroke: PALETTE.ok, "stroke-width": 1.5, "stroke-dasharray": "3 3" });
      ctx.line({ x1: 470, y1: 275, x2: lig2X + 10, y2: lig2Y - 5, stroke: PALETTE.ok, "stroke-width": 1.5, "stroke-dasharray": "3 3" });
      ctx.text({ x: lig1X - 20, y: lig1Y - 8, "font-size": 11, fill: PALETTE.ok }, "韌帶已徹底鬆解");
    }

    if (u >= 0.35 && u < 0.70) {
      // 階段 2：45度立體向後上方提拉，堅韌骨膜剛性縫合錨定
      ctx.line({ x1: 340, y1: 270, x2: 460, y2: 150, stroke: sFill, "stroke-width": 3.5 });
      ctx.polygon({ points: "460,150 445,155 455,165", fill: sFill });
      ctx.text({ x: 420, y: 195, "font-size": 12, "font-weight": "bold", fill: sFill }, "45°向量提拉");

      // 骨膜錨定縫線針腳 (三道高張力固定縫線)
      for (let s = 0; s < 3; s++) {
        const sy = 180 + s * 38;
        ctx.circle({ cx: 495, cy: sy, r: 6, fill: sFill, stroke: "#ffffff", "stroke-width": 1.5 });
        ctx.line({ x1: 475, y1: sy, x2: 505, y2: sy, stroke: sFill, "stroke-width": 2.5 });
      }
      ctx.text({ x: 500, y: 325, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: sFill }, "剛性鎖定骨膜");
    } else if (u >= 0.70) {
      // 階段 3：骨膜承載全部張力，表皮零張力順應覆蓋
      for (let s = 0; s < 3; s++) {
        const sy = 180 + s * 38;
        ctx.circle({ cx: 495, cy: sy, r: 5, fill: PALETTE.ok, stroke: "#ffffff", "stroke-width": 1.5 });
      }
      // 表皮輪廓線緊實飽滿
      ctx.path({
        d: "M 230 140 Q 280 200 290 280 Q 350 330 480 305",
        fill: "none",
        stroke: PALETTE.ok,
        "stroke-width": 3
      });
      ctx.text({ x: 300, y: 360, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: PALETTE.ok }, "輪廓緊緻拉提，動態表情自然");
      ctx.text({ x: 500, y: 325, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: PALETTE.ok }, "骨膜承受全部拉力");
      ctx.text({ x: 512, y: 300, "text-anchor": "middle", "font-size": 10, fill: "#94a3b8" }, "表皮零張力無壓縫合");
    }

    drawStepPills(ctx, params.step_labels, u);
  }

  // Blueprint 12: 天鵝頸闊頸肌馬甲對縫拉皮術 (Corset Platysmaplasty & Submental Cervicoplasty)
  function drawCorsetPlatysmaplasty(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    const layers = params.layer_labels || ["表皮與皮下層", "闊頸肌與深層墊", "頸前筋膜深層"];
    const sFill = ctx.palette(params.suture_fill, PALETTE.accent);
    const mLabel = params.muscle_label || "兩側闊頸肌";
    const fLabel = params.fat_label || "深層脂肪墊";
    const sutLabel = params.suture_label || "馬甲式對縫";

    // 頂部解剖圖層標籤
    ctx.text({ x: 50, y: 56, "font-size": 13, "font-weight": "bold", fill: "#94a3b8" }, "【下顎頸部解剖架構】");
    ctx.rect({ x: 190, y: 42, width: 105, height: 22, rx: 4, fill: "#fed7aa", opacity: 0.9 });
    ctx.text({ x: 242, y: 57, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#7c2d12" }, layers[0]);
    ctx.rect({ x: 305, y: 42, width: 105, height: 22, rx: 4, fill: "#dc2626", opacity: 0.85 });
    ctx.text({ x: 357, y: 57, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#ffffff" }, layers[1]);
    ctx.rect({ x: 420, y: 42, width: 105, height: 22, rx: 4, fill: "#334155", stroke: "#64748b", "stroke-width": 1.5 });
    ctx.text({ x: 472, y: 57, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#93c5fd" }, layers[2]);

    // 主圖：下顎與前頸前視解剖區 (x: 60..510)
    const midX = 285;

    // 下巴骨弓 (Mandible Arch)
    ctx.path({
      d: "M 130 135 Q " + midX + " 105 440 135 L 430 155 Q " + midX + " 125 140 155 Z",
      fill: "#475569",
      stroke: "#94a3b8",
      "stroke-width": 1.5
    });
    ctx.text({ x: midX, y: 100, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#e2e8f0" }, "下巴骨下緣");

    // 下巴天然皮摺 2cm 微創切口
    ctx.line({ x1: midX - 25, y1: 125, x2: midX + 25, y2: 125, stroke: PALETTE.accent, "stroke-width": 3 });
    ctx.text({ x: midX, y: 140, "text-anchor": "middle", "font-size": 10, "font-weight": "bold", fill: PALETTE.accent }, "2cm微創隱痕切口");

    // 兩側闊頸肌分離寬度 (Diastasis Gap)
    let halfGap = 36;
    if (u >= 0.35 && u < 0.70) {
      const p2 = (u - 0.35) / 0.35;
      halfGap = 36 * (1 - p2);
    } else if (u >= 0.70) {
      halfGap = 0;
    }

    // 左側闊頸肌肌束 (Platysma Left)
    const leftEdge = midX - halfGap;
    ctx.path({
      d: "M 140 160 L " + leftEdge + " 160 L " + leftEdge + " 340 L 150 340 Z",
      fill: "#991b1b",
      opacity: 0.8,
      stroke: "#ef4444",
      "stroke-width": 1.5
    });
    // 肌纖維條紋
    for (let f = 0; f < 3; f++) {
      ctx.line({ x1: 160 + f * 30, y1: 170, x2: 155 + f * 30, y2: 330, stroke: "#b91c1c", "stroke-width": 1 });
    }

    // 右側闊頸肌肌束 (Platysma Right)
    const rightEdge = midX + halfGap;
    ctx.path({
      d: "M " + rightEdge + " 160 L 430 160 L 420 340 L " + rightEdge + " 340 Z",
      fill: "#991b1b",
      opacity: 0.8,
      stroke: "#ef4444",
      "stroke-width": 1.5
    });
    for (let f = 0; f < 3; f++) {
      ctx.line({ x1: 340 + f * 30, y1: 170, x2: 345 + f * 30, y2: 330, stroke: "#b91c1c", "stroke-width": 1 });
    }
    ctx.text({ x: 190, y: 240, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#fca5a5" }, mLabel);
    ctx.text({ x: 380, y: 240, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#fca5a5" }, mLabel);

    // 中央間隙與深層脂肪墊
    if (halfGap > 5) {
      let fatOpacity = 0.9;
      if (u < 0.35) {
        fatOpacity = 0.9 * (1 - (u / 0.35) * 0.7);
      } else {
        fatOpacity = 0.2;
      }
      for (let k = 0; k < 6; k++) {
        const fy = 180 + k * 26;
        ctx.circle({ cx: midX, cy: fy, r: 10, fill: PALETTE.fat, opacity: fatOpacity, stroke: "#d97706", "stroke-width": 1 });
      }
      if (u < 0.35) {
        ctx.text({ x: midX, y: 260, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#fef08a" }, fLabel);
        ctx.text({ x: midX, y: 355, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: PALETTE.accent }, "直視微創修整深層脂肪墊");
      }
    }

    // 階段 2 & 3：馬甲式交疊對縫 (Corset Sutures)
    if (u >= 0.35) {
      const nStitches = 6;
      const progressStitches = u < 0.70 ? Math.floor(((u - 0.35) / 0.35) * nStitches) : nStitches;
      for (let i = 0; i < progressStitches; i++) {
        const sy = 175 + i * 27;
        const lx = midX - halfGap - 6;
        const rx = midX + halfGap + 6;
        // 馬甲交叉穿線
        ctx.line({ x1: lx, y1: sy - 10, x2: rx, y2: sy + 10, stroke: sFill, "stroke-width": 2.5 });
        ctx.line({ x1: lx, y1: sy + 10, x2: rx, y2: sy - 10, stroke: sFill, "stroke-width": 2.5 });
        ctx.circle({ cx: lx, cy: sy, r: 3, fill: "#ffffff" });
        ctx.circle({ cx: rx, cy: sy, r: 3, fill: "#ffffff" });
      }
      if (u < 0.70) {
        ctx.text({ x: midX, y: 355, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: sFill }, sutLabel + "：雙向交疊收緊");
      } else {
        ctx.text({ x: midX, y: 355, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: PALETTE.ok }, "闊頸肌馬甲吊帶完全成型");
      }
    }

    // 右側側顏頸角對比視圖 (x: 535..750)
    ctx.rect({ x: 535, y: 95, width: 215, height: 265, rx: 12, fill: "#111827", stroke: "#374151", "stroke-width": 1.5 });
    ctx.text({ x: 642, y: 125, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: "#94a3b8" }, "下顎頸角 (側顏透視)");

    if (u < 0.70) {
      // 術前/術中：火雞脖鈍角 > 120 度
      ctx.path({
        d: "M 560 160 Q 640 160 670 170 Q 630 220 625 280 L 625 320",
        fill: "none",
        stroke: "#f87171",
        "stroke-width": 3,
        "stroke-dasharray": "4 3"
      });
      ctx.circle({ cx: 640, cy: 195, r: 6, fill: "#ef4444" });
      ctx.text({ x: 642, y: 245, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#f87171" }, "術前：>120° 鈍角");
      ctx.text({ x: 642, y: 268, "text-anchor": "middle", "font-size": 10, fill: "#9ca3af" }, "脂肪下垂＋肌肉分離");
    } else {
      // 術後：俐落 90 度天鵝頸夾角
      ctx.path({
        d: "M 560 160 Q 640 160 670 170 L 595 235 L 595 320",
        fill: "none",
        stroke: PALETTE.ok,
        "stroke-width": 3.5
      });
      // 90 度角標記
      ctx.rect({ x: 595, y: 220, width: 14, height: 14, fill: "none", stroke: PALETTE.ok, "stroke-width": 1.5 });
      ctx.circle({ cx: 595, cy: 235, r: 5, fill: PALETTE.ok });
      ctx.text({ x: 642, y: 245, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: PALETTE.ok }, "術後：<90° 天鵝頸");
      ctx.text({ x: 642, y: 268, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#a7f3d0" }, "俐落下顎輪廓線");
    }

    drawStepPills(ctx, params.step_labels, u);
  }


  // Blueprint 13: 專科外科截骨、剛性固定與神經保護 (Surgical Action DSL)
  function drawSurgicalAction(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    const boneLabel = params.bone_label || "下顎骨端";
    const nerveLabel = params.nerve_label || "頦神經";
    const incLabel = params.incision_label || "口內隱痕";
    const fixLabel = params.fixation_label || "純鈦板釘";
    const isProtected = params.protect_nerve !== false;
    const shiftMm = typeof params.bone_shift_mm === "number" ? params.bone_shift_mm : 6;

    // 頂部解剖專科標題與標籤膠囊
    ctx.text({ x: 50, y: 56, "font-size": 13, "font-weight": "bold", fill: "#94a3b8" }, "【專科骨骼解剖與剛性固定】");
    ctx.rect({ x: 260, y: 42, width: 105, height: 22, rx: 4, fill: "#334155", stroke: "#64748b", "stroke-width": 1.5 });
    ctx.text({ x: 312, y: 57, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#93c5fd" }, boneLabel);
    ctx.rect({ x: 375, y: 42, width: 105, height: 22, rx: 4, fill: "#1e3a5f", stroke: PALETTE.ok, "stroke-width": 1.5 });
    ctx.text({ x: 427, y: 57, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#38bdf8" }, incLabel);
    ctx.rect({ x: 490, y: 42, width: 110, height: 22, rx: 4, fill: "#451a03", stroke: "#f59e0b", "stroke-width": 1.5 });
    ctx.text({ x: 545, y: 57, "text-anchor": "middle", "font-size": 11, "font-weight": "bold", fill: "#fbbf24" }, fixLabel);

    // 1. 固定骨骼基底
    ctx.path({
      d: "M 200 130 Q 320 120 440 120 Q 560 120 600 170 L 590 220 Q 500 210 400 215 Q 300 220 200 225 Z",
      fill: "#1e293b",
      stroke: "#475569",
      "stroke-width": 2
    });
    ctx.line({ x1: 260, y1: 145, x2: 380, y2: 155, stroke: "#334155", "stroke-width": 1.5 });
    ctx.line({ x1: 420, y1: 145, x2: 540, y2: 155, stroke: "#334155", "stroke-width": 1.5 });
    ctx.text({ x: 230, y: 160, "font-size": 11, "font-weight": "bold", fill: "#64748b" }, "骨基底穩定端");

    // 2. 切口線與牽引微創箭頭
    if (u < 0.35) {
      const p1 = u / 0.35;
      ctx.line({ x1: 290, y1: 110, x2: 510, y2: 110, stroke: PALETTE.ok, "stroke-width": 2.5, "stroke-dasharray": "6 4" });
      ctx.text({ x: 400, y: 100, "text-anchor": "middle", "font-size": 12, "font-weight": "bold", fill: PALETTE.ok }, incLabel + " (微創黏膜切開)");

      const spread = p1 * 14;
      ctx.line({ x1: 340, y1: 110 - spread, x2: 340, y2: 110 - spread - 10, stroke: "#38bdf8", "stroke-width": 2 });
      ctx.line({ x1: 460, y1: 110 + spread, x2: 460, y2: 110 + spread + 10, stroke: "#38bdf8", "stroke-width": 2 });
      ctx.text({ x: 400, y: 135, "text-anchor": "middle", "font-size": 11, fill: "#93c5fd", opacity: p1 }, "骨膜下微創剝離顯露");
    }

    // 3. 截骨位移計算
    let slideX = 0;
    let slideY = 0;
    const maxSlide = shiftMm * 3.5;
    if (u >= 0.35 && u < 0.70) {
      const p2 = (u - 0.35) / 0.35;
      slideX = p2 * maxSlide;
      slideY = p2 * (maxSlide * 0.3);
    } else if (u >= 0.70) {
      slideX = maxSlide;
      slideY = maxSlide * 0.3;
    }

    const chinOriginX = 220 + slideX;
    const chinOriginY = 240 + slideY;
    ctx.path({
      d: "M " + chinOriginX + " " + chinOriginY + " Q " + (chinOriginX + 180) + " " + (chinOriginY - 15) + " " + (chinOriginX + 340) + " " + chinOriginY + " Q " + (chinOriginX + 310) + " " + (chinOriginY + 75) + " " + (chinOriginX + 170) + " " + (chinOriginY + 85) + " Q " + (chinOriginX + 30) + " " + (chinOriginY + 75) + " " + chinOriginX + " " + chinOriginY + " Z",
      fill: "#334155",
      stroke: "#60a5fa",
      "stroke-width": 2.5
    });
    ctx.text({ x: chinOriginX + 170, y: chinOriginY + 50, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#ffffff" }, boneLabel + (u >= 0.35 ? " (滑移重塑)" : ""));

    ctx.line({ x1: 210, y1: 232, x2: 570, y2: 232, stroke: "#f43f5e", "stroke-width": 2, "stroke-dasharray": "4 3" });
    if (u < 0.35) {
      ctx.text({ x: 595, y: 236, "font-size": 11, "font-weight": "bold", fill: "#fb7185" }, "超音波截骨線");
    }

    // 4. 重要神經路徑與安全保護光暈
    const nerveOriginX = 295;
    const nerveOriginY = 195;
    ctx.circle({ cx: nerveOriginX, cy: nerveOriginY, r: 7, fill: "#0f172a", stroke: "#fbbf24", "stroke-width": 2 });
    ctx.text({ x: nerveOriginX - 12, y: nerveOriginY + 4, "text-anchor": "end", "font-size": 10, "font-weight": "bold", fill: "#fde68a" }, "頦神經孔");

    const nerveEndX = 390 + slideX * 0.35;
    const nerveEndY = 270 + slideY * 0.35;

    if (isProtected) {
      const glowPulse = 0.35 + 0.25 * Math.sin(u * 6.28);
      ctx.path({
        d: "M " + nerveOriginX + " " + nerveOriginY + " Q " + (nerveOriginX + 40) + " " + (nerveOriginY + 45) + " " + nerveEndX + " " + nerveEndY,
        fill: "none",
        stroke: "#38bdf8",
        "stroke-width": 10,
        opacity: glowPulse
      });
    }

    ctx.path({
      d: "M " + nerveOriginX + " " + nerveOriginY + " Q " + (nerveOriginX + 40) + " " + (nerveOriginY + 45) + " " + nerveEndX + " " + nerveEndY,
      fill: "none",
      stroke: "#facc15",
      "stroke-width": 3.5
    });
    ctx.circle({ cx: nerveEndX, cy: nerveEndY, r: 4, fill: "#facc15" });
    ctx.text({ x: nerveEndX + 10, y: nerveEndY + 4, "font-size": 11, "font-weight": "bold", fill: "#fef08a" }, nerveLabel + (isProtected ? " (安全無張力)" : ""));

    // 5. 剛性內部固定
    if (u >= 0.70) {
      const p3 = (u - 0.70) / 0.30;
      const plateFade = Math.min(1.0, p3 * 2.0);

      const plateX1 = chinOriginX + 110;
      const plateX2 = chinOriginX + 230;
      const plateYTop = 205;
      const plateYBottom = chinOriginY + 25;

      ctx.rect({
        x: plateX1 - 12,
        y: plateYTop,
        width: 24,
        height: plateYBottom - plateYTop + 14,
        rx: 5,
        fill: "#94a3b8",
        stroke: "#e2e8f0",
        "stroke-width": 1.5,
        opacity: plateFade
      });
      ctx.rect({
        x: plateX2 - 12,
        y: plateYTop,
        width: 24,
        height: plateYBottom - plateYTop + 14,
        rx: 5,
        fill: "#94a3b8",
        stroke: "#e2e8f0",
        "stroke-width": 1.5,
        opacity: plateFade
      });

      const screwCoords = [
        [plateX1, plateYTop + 8],
        [plateX1, plateYBottom + 6],
        [plateX2, plateYTop + 8],
        [plateX2, plateYBottom + 6]
      ];

      for (let s = 0; s < screwCoords.length; s++) {
        const scx = screwCoords[s][0];
        const scy = screwCoords[s][1];
        ctx.circle({ cx: scx, cy: scy, r: 5, fill: "#f8fafc", stroke: "#475569", "stroke-width": 1.2, opacity: plateFade });
        ctx.line({ x1: scx - 3, y1: scy, x2: scx + 3, y2: scy, stroke: "#334155", "stroke-width": 1.2, opacity: plateFade });
        ctx.line({ x1: scx, y1: scy - 3, x2: scx, y2: scy + 3, stroke: "#334155", "stroke-width": 1.2, opacity: plateFade });
      }

      ctx.rect({ x: 300, y: 320, width: 200, height: 32, rx: 6, fill: "#064e3b", stroke: PALETTE.ok, "stroke-width": 1.8, opacity: plateFade });
      ctx.circle({ cx: 322, cy: 336, r: 7, fill: PALETTE.ok, opacity: plateFade });
      ctx.text({ x: 338, y: 341, "font-size": 13, "font-weight": "bold", fill: "#ecfdf5", opacity: plateFade }, "剛性固定：自體骨整合癒合");
    }

    drawStepPills(ctx, params.step_labels, u);
  }


  // 註冊表
  const blueprints = {
    process_diagram: {
      params: ["source", "particles", "container_layers", "step_labels"],
      defaults: {
        "source": {
                "label": "皮下脂肪",
                "fill": "skin"
        },
        "particles": 5,
        "container_layers": [
                {
                        "label": "油滴",
                        "fill": "oil",
                        "weight": 2,
                        "keep": false
                },
                {
                        "label": "純化脂肪",
                        "fill": "fat",
                        "weight": 3,
                        "keep": true
                },
                {
                        "label": "血水",
                        "fill": "blood",
                        "weight": 2,
                        "keep": false
                }
        ],
        "step_labels": [
                "微創抽取",
                "離心分層",
                "保留純化脂肪"
        ]
},
      draw: drawProcessDiagram
    },
    contrast: {
      params: ["left", "right"],
      defaults: {
        "left": {
                "title": "單處過量",
                "note": "較易出現硬塊",
                "mode": "mass",
                "core_effect": "dim",
                "core_label": "中心缺血",
                "footnote": "單處集中：不易獲取充足養分",
                "unit_fill": "fat"
        },
        "right": {
                "title": "分層少量",
                "note": "接觸周圍組織",
                "mode": "layered",
                "rows": 3,
                "per_row": 5,
                "footnote": "多層分散：接觸周圍健康組織",
                "unit_fill": "fat"
        }
},
      draw: drawContrast
    },
    timeline: {
      params: ["milestones", "unit_effect", "connectors", "units", "unit_fill"],
      defaults: {
        "milestones": [
                "術後初期",
                "微血管長入",
                "狀態穩定"
        ],
        "unit_effect": "mature",
        "connectors": "vessels",
        "units": 3,
        "unit_fill": "fat"
},
      draw: drawTimeline
    },
    skin_energy: {
      params: ["mode", "probe_label", "layer_labels", "focal_points", "energy_fill", "step_labels"],
      defaults: {
        "mode": "focused",
        "probe_label": "聚焦探頭",
        "layer_labels": [
                "表皮層",
                "真皮膠原層",
                "筋膜層"
        ],
        "focal_points": 5,
        "energy_fill": "accent",
        "step_labels": [
                "能量精準傳遞",
                "深層熱凝結點",
                "膠原緊縮拉提"
        ]
},
      draw: drawSkinEnergy
    },
    laser_action: {
      params: ["mode", "beam_label", "target_label", "layer_labels", "beam_fill", "step_labels"],
      defaults: {
        "mode": "shatter",
        "beam_label": "皮秒光束",
        "target_label": "色素團塊",
        "layer_labels": [
                "表皮角質層",
                "真皮基底層"
        ],
        "beam_fill": "accent",
        "step_labels": [
                "短脈衝光束照射",
                "光震波擊碎色素",
                "微細粉塵代謝"
        ]
},
      draw: drawLaserAction
    },
    neuromuscular: {
      params: ["nerve_label", "muscle_label", "surface_label", "blocker_fill", "step_labels"],
      defaults: {
        "nerve_label": "運動神經末梢",
        "muscle_label": "過度收縮肌肉",
        "surface_label": "動態表情皺紋",
        "blocker_fill": "ok",
        "step_labels": [
                "精準微量注射",
                "調節神經訊號",
                "肌肉放鬆撫平"
        ]
},
      draw: drawNeuromuscular
    },
    dermal_support: {
      params: ["filler_label", "layer_labels", "droplets", "filler_fill", "step_labels"],
      defaults: {
        "filler_label": "親水凝膠",
        "layer_labels": [
                "表皮輪廓層",
                "真皮皮下層"
        ],
        "droplets": 6,
        "filler_fill": "gel",
        "step_labels": [
                "評估凹陷部位",
                "深淺分層注入",
                "立體支撐平順"
        ]
},
      draw: drawDermalSupport
    },
    cyst_excision: {
      params: ["cyst_label", "sac_label", "core_label", "layer_labels", "sac_fill", "step_labels"],
      defaults: {
        "cyst_label": "粉瘤囊腫",
        "sac_label": "完整包膜",
        "core_label": "角質分泌物",
        "layer_labels": [
                "表皮層",
                "皮下真皮層"
        ],
        "sac_fill": "accent",
        "step_labels": [
                "微創切口定位",
                "減壓排空引流",
                "完整囊袋剝離"
        ]
},
      draw: drawCystExcision
    },
    nail_matrix: {
      params: ["nail_label", "fold_label", "spicule_label", "matrix_label", "matrix_fill", "step_labels"],
      defaults: {
        "nail_label": "趾甲板",
        "fold_label": "側甲襞",
        "spicule_label": "嵌甲尖刺",
        "matrix_label": "甲基質生長板",
        "matrix_fill": "warn",
        "step_labels": [
                "嵌甲邊緣游離",
                "縱向側切移除",
                "甲床基質重整"
        ]
},
      draw: drawNailMatrix
    },
    subdermal_curettage: {
      params: ["target_label", "shaver_label", "layer_labels", "tool_fill", "step_labels"],
      defaults: {
        "target_label": "頂漿腺組織",
        "shaver_label": "微創旋轉刀",
        "layer_labels": [
                "真皮深層",
                "皮下脂肪層"
        ],
        "tool_fill": "accent",
        "step_labels": [
                "微創切口入路",
                "旋轉刮除分離",
                "負壓即時抽吸"
        ]
},
      draw: drawSubdermalCurettage
    },
    deep_plane_facelift: {
      params: ["layer_labels", "smas_label", "anchor_label", "ligament_label", "suture_fill", "step_labels"],
      defaults: {
        "layer_labels": [
                "表皮輪廓層",
                "SMAS筋膜層",
                "堅韌骨膜基底"
        ],
        "smas_label": "SMAS筋膜瓣",
        "anchor_label": "骨膜錨定點",
        "ligament_label": "維持韌帶",
        "suture_fill": "accent",
        "step_labels": [
                "微創切口解離韌帶",
                "45度提拉骨膜錨定",
                "表皮零張力無壓縫合"
        ]
},
      draw: drawDeepPlaneFacelift
    },
    corset_platysmaplasty: {
      params: ["layer_labels", "muscle_label", "fat_label", "suture_label", "suture_fill", "step_labels"],
      defaults: {
        "layer_labels": [
                "表皮與皮下層",
                "闊頸肌與深層墊",
                "頸前筋膜深層"
        ],
        "muscle_label": "兩側闊頸肌",
        "fat_label": "深層脂肪墊",
        "suture_label": "馬甲式對縫",
        "suture_fill": "accent",
        "step_labels": [
                "微創入路修整脂肪",
                "闊頸肌馬甲式對縫",
                "緊緻吊帶俐落頸角"
        ]
},
      draw: drawCorsetPlatysmaplasty
    },
    surgical_action: {
      params: ["anatomy_target", "bone_label", "nerve_label", "nerve_status", "incision_label", "fixation_label", "bone_shift_mm", "protect_nerve", "step_labels"],
      defaults: {
        "anatomy_target": "mandible",
        "bone_label": "下顎骨端",
        "nerve_label": "頦神經",
        "nerve_status": "protected",
        "incision_label": "口內隱痕",
        "fixation_label": "純鈦板釘",
        "bone_shift_mm": 6,
        "protect_nerve": true,
        "step_labels": [
                "口內隱痕切開",
                "保護神經截骨",
                "純鈦板釘固定"
        ]
},
      draw: drawSurgicalAction
    }
  };

  function sceneDuration(scene) {
    if (scene && typeof scene.duration_sec === "number" && Number.isFinite(scene.duration_sec)) {
      if (scene.duration_sec >= 4 && scene.duration_sec <= 12) {
        return Math.round(scene.duration_sec);
      }
    }
    const bp = scene ? scene.blueprint : "";
    if (bp === "process_diagram") return 8;
    if (bp === "contrast") return 9;
    if (bp === "timeline") return 7;
    return 8;
  }

  function resolveParams(blueprint, params) {
    if (!blueprints[blueprint]) return {};
    const def = blueprints[blueprint].defaults;
    const out = cloneObject(def);
    if (!params || typeof params !== "object" || Array.isArray(params)) {
  
    if (blueprint === "surgical_action") {
      out.anatomy_target = String(out.anatomy_target || "mandible");
      out.bone_label = String(out.bone_label || "").slice(0, 8);
      out.nerve_label = String(out.nerve_label || "").slice(0, 8);
      out.nerve_status = String(out.nerve_status || "protected");
      out.incision_label = String(out.incision_label || "").slice(0, 8);
      out.fixation_label = String(out.fixation_label || "").slice(0, 8);
      out.bone_shift_mm = clampNumber(Math.round(out.bone_shift_mm), 0, 15);
      out.protect_nerve = Boolean(out.protect_nerve);
      if (!Array.isArray(out.step_labels) || out.step_labels.length !== 3) {
        out.step_labels = cloneObject(def.step_labels);
      } else {
        out.step_labels = out.step_labels.map(function (s) { return String(s || "").slice(0, 10); });
      }
    } else if (blueprint === "deep_plane_facelift") {
      out.smas_label = String(out.smas_label || "").slice(0, 8);
      out.anchor_label = String(out.anchor_label || "").slice(0, 8);
      out.ligament_label = String(out.ligament_label || "").slice(0, 8);
      if (!PALETTE[out.suture_fill]) out.suture_fill = "accent";
      if (!Array.isArray(out.layer_labels) || out.layer_labels.length !== 3) {
        out.layer_labels = cloneObject(def.layer_labels);
      } else {
        out.layer_labels = out.layer_labels.map(function (s) { return String(s || "").slice(0, 8); });
      }
      if (!Array.isArray(out.step_labels) || out.step_labels.length !== 3) {
        out.step_labels = cloneObject(def.step_labels);
      } else {
        out.step_labels = out.step_labels.map(function (s) { return String(s || "").slice(0, 10); });
      }
    } else if (blueprint === "corset_platysmaplasty") {
      out.muscle_label = String(out.muscle_label || "").slice(0, 8);
      out.fat_label = String(out.fat_label || "").slice(0, 8);
      out.suture_label = String(out.suture_label || "").slice(0, 8);
      if (!PALETTE[out.suture_fill]) out.suture_fill = "accent";
      if (!Array.isArray(out.layer_labels) || out.layer_labels.length !== 3) {
        out.layer_labels = cloneObject(def.layer_labels);
      } else {
        out.layer_labels = out.layer_labels.map(function (s) { return String(s || "").slice(0, 8); });
      }
      if (!Array.isArray(out.step_labels) || out.step_labels.length !== 3) {
        out.step_labels = cloneObject(def.step_labels);
      } else {
        out.step_labels = out.step_labels.map(function (s) { return String(s || "").slice(0, 10); });
      }
    }

    return out;
    }

    function mergeDeep(target, source) {
      for (const k of Object.keys(source)) {
        const val = source[k];
        if (val === undefined || val === null) continue;
        if (Array.isArray(val)) {
          target[k] = cloneObject(val);
        } else if (typeof val === "object" && typeof target[k] === "object" && !Array.isArray(target[k])) {
          mergeDeep(target[k], val);
        } else {
          target[k] = val;
        }
      }
    }

    mergeDeep(out, params);

    if (blueprint === "process_diagram") {
      out.particles = clampNumber(Math.round(out.particles), 4, 12);
      if (!out.source || typeof out.source !== "object") out.source = cloneObject(def.source);
      out.source.label = String(out.source.label || "").slice(0, 8);
      if (!PALETTE[out.source.fill]) out.source.fill = "skin";

      if (!Array.isArray(out.container_layers) || out.container_layers.length < 2) {
        out.container_layers = cloneObject(def.container_layers);
      } else {
        out.container_layers = out.container_layers.slice(0, 4).map(function (layer) {
          return {
            label: String(layer.label || "").slice(0, 6),
            fill: PALETTE[layer.fill] ? layer.fill : "fat",
            weight: clampNumber(Math.round(layer.weight), 1, 5),
            keep: Boolean(layer.keep)
          };
        });
      }

      if (!Array.isArray(out.step_labels) || out.step_labels.length !== 3) {
        out.step_labels = cloneObject(def.step_labels);
      } else {
        out.step_labels = out.step_labels.map(function (s) {
          return String(s || "").slice(0, 10);
        });
      }
    } else if (blueprint === "contrast") {
      if (!out.left || typeof out.left !== "object") out.left = cloneObject(def.left);
      out.left.title = String(out.left.title || "").slice(0, 8);
      out.left.note = String(out.left.note || "").slice(0, 14);
      // 白名單與 src/visual/blueprints.py 的列舉完全一致（不一致會靜默退回預設）
      if (CONTRAST_LEFT_MODES.indexOf(out.left.mode) < 0) out.left.mode = "mass";
      if (out.left.core_effect !== "dim" && out.left.core_effect !== "none") out.left.core_effect = "dim";
      out.left.core_label = String(out.left.core_label || "").slice(0, 8);
      out.left.footnote = String(out.left.footnote || "").slice(0, 16);
      if (!PALETTE[out.left.unit_fill]) out.left.unit_fill = "fat";

      if (!out.right || typeof out.right !== "object") out.right = cloneObject(def.right);
      out.right.title = String(out.right.title || "").slice(0, 8);
      out.right.note = String(out.right.note || "").slice(0, 14);
      if (CONTRAST_RIGHT_MODES.indexOf(out.right.mode) < 0) out.right.mode = "layered";
      out.right.rows = clampNumber(Math.round(out.right.rows), 1, 4);
      out.right.per_row = clampNumber(Math.round(out.right.per_row), 3, 8);
      out.right.footnote = String(out.right.footnote || "").slice(0, 16);
      if (!PALETTE[out.right.unit_fill]) out.right.unit_fill = "fat";
    } else if (blueprint === "timeline") {
      if (!Array.isArray(out.milestones) || out.milestones.length !== 3) {
        out.milestones = cloneObject(def.milestones);
      } else {
        out.milestones = out.milestones.map(function (m) {
          return String(m || "").slice(0, 8);
        });
      }
      if (TIMELINE_UNIT_EFFECTS.indexOf(out.unit_effect) < 0) {
        out.unit_effect = "mature";
      }
      if (TIMELINE_CONNECTORS.indexOf(out.connectors) < 0) {
        out.connectors = "vessels";
      }
      out.units = clampNumber(Math.round(out.units), 2, 5);
      if (!PALETTE[out.unit_fill]) out.unit_fill = "fat";
    }

    return out;
  }

  function mount(svgEl, scenes) {
    if (!svgEl) return null;
    svgEl.setAttribute("viewBox", "0 0 800 510");

    const scList = Array.isArray(scenes) ? scenes : [];
    const durations = scList.map(function (sc) {
      return sceneDuration(sc);
    });
    let totalDuration = 0;
    for (let i = 0; i < durations.length; i++) {
      totalDuration += durations[i];
    }

    function sceneIndexAt(t) {
      if (scList.length === 0) return 0;
      const clampedT = clampNumber(t, 0, totalDuration);
      if (clampedT >= totalDuration) return scList.length - 1;
      let acc = 0;
      for (let i = 0; i < scList.length; i++) {
        acc += durations[i];
        if (clampedT < acc) return i;
      }
      return scList.length - 1;
    }

    function renderAt(t) {
      while (svgEl.firstChild) {
        svgEl.removeChild(svgEl.firstChild);
      }
      if (scList.length === 0) return;

      const clampedT = clampNumber(t, 0, totalDuration);
      const idx = sceneIndexAt(clampedT);
      let startT = 0;
      for (let i = 0; i < idx; i++) {
        startT += durations[i];
      }
      const dur = durations[idx];
      const u = dur > 0 ? clampNumber((clampedT - startT) / dur, 0, 1) : 0;

      const scene = scList[idx];
      const bpName = scene ? scene.blueprint : "";
      const bp = blueprints[bpName];
      const params = resolveParams(bpName, scene ? scene.params : null);

      const rootG = document.createElementNS(SVG_NS, "g");
      rootG.setAttribute("class", "scene-root");
      svgEl.appendChild(rootG);

      const ctx = createCtx(rootG);

      if (bp && typeof bp.draw === "function") {
        bp.draw(ctx, params, u);
      } else {
        // 安全降級：未知模板繪製標題
        ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
        const titleText = scene && typeof scene.title === "string" ? scene.title : "解說畫面";
        ctx.text({ x: 400, y: 240, "text-anchor": "middle", "font-size": 22, fill: "#cfe0f5", "font-weight": "bold" }, titleText);
      }
    }

    function destroy() {
      while (svgEl.firstChild) {
        svgEl.removeChild(svgEl.firstChild);
      }
    }

    return {
      totalDuration: totalDuration,
      renderAt: renderAt,
      sceneIndexAt: sceneIndexAt,
      destroy: destroy
    };
  }

  const ClinicVisual = {
    blueprints: blueprints,
    PALETTE: PALETTE,
    resolveParams: resolveParams,
    sceneDuration: sceneDuration,
    mount: mount
  };

  root.ClinicVisual = ClinicVisual;
})(typeof window !== "undefined" ? window : globalThis);
