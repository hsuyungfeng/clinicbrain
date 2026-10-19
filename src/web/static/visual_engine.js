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

    // 右側離心容器
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
  function drawContrast(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    // 中線分隔
    ctx.line({ x1: 400, y1: 50, x2: 400, y2: 430, stroke: "#334155", "stroke-width": 2, "stroke-dasharray": "6 6" });

    // 左側面板（對照側）
    ctx.text({ x: 210, y: 65, "text-anchor": "middle", "font-size": 18, "font-weight": "bold", fill: PALETTE.warn }, params.left.title);
    ctx.text({ x: 210, y: 92, "text-anchor": "middle", "font-size": 13, fill: "#94a3b8" }, params.left.note);
    ctx.rect({ x: 50, y: 115, width: 320, height: 250, rx: 12, fill: "#273549", stroke: "#384a62" });

    if (params.left.mode === "mass") {
      const growScale = Math.min(1, u * 2);
      const rad = 56 * growScale;
      ctx.circle({ cx: 210, cy: 235, r: rad, fill: PALETTE.fat, stroke: "#d97706", "stroke-width": 2 });
      if (u >= 0.38) {
        const coreU = Math.min(1, (u - 0.38) / 0.35);
        const pulse = 0.75 + 0.25 * Math.sin(u * Math.PI * 6);
        ctx.circle({ cx: 210, cy: 235, r: 38 * coreU, fill: "#451a03", opacity: 0.85 * pulse });
        if (coreU > 0.6) {
          ctx.text({ x: 210, y: 240, "text-anchor": "middle", "font-size": 13, "font-weight": "bold", fill: "#ffffff" }, "中心缺血");
        }
      }
    } else {
      // scattered mode
      for (let i = 0; i < 6; i++) {
        const hx = deterministicHash(i, 3);
        const hy = deterministicHash(i, 7);
        const cx = 90 + hx * 240;
        const cy = 145 + hy * 190;
        ctx.circle({ cx: cx, cy: cy, r: 16, fill: PALETTE.fat, stroke: "#d97706", "stroke-width": 1.5 });
      }
    }
    ctx.text({ x: 210, y: 395, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: PALETTE.warn }, "單處集中：不易獲取充足養分");

    // 右側面板（推薦側）
    ctx.text({ x: 590, y: 65, "text-anchor": "middle", "font-size": 18, "font-weight": "bold", fill: PALETTE.ok }, params.right.title);
    ctx.text({ x: 590, y: 92, "text-anchor": "middle", "font-size": 13, fill: "#94a3b8" }, params.right.note);
    ctx.rect({ x: 430, y: 115, width: 320, height: 250, rx: 12, fill: "#273549", stroke: "#384a62" });

    if (params.right.mode === "layered") {
      const rows = params.right.rows;
      const perRow = params.right.per_row;
      const totalUnits = rows * perRow;

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
            ctx.circle({ cx: unitX, cy: rowY, r: 7 * unitProgress, fill: PALETTE.fat });
          }
        }
      }
    } else {
      ctx.circle({ cx: 590, cy: 235, r: 50, fill: PALETTE.fat, stroke: "#d97706", "stroke-width": 2 });
    }
    ctx.text({ x: 590, y: 395, "text-anchor": "middle", "font-size": 14, "font-weight": "bold", fill: PALETTE.ok }, "多層分散：接觸周圍健康組織");
  }

  // Blueprint 3: 時間軸進程（逐步穩定）
  function drawTimeline(ctx, params, u) {
    ctx.rect({ x: 0, y: 0, width: 800, height: 510, fill: "#0f172a", "data-bg": "1" });
    ctx.rect({ x: 24, y: 24, width: 752, height: 462, rx: 16, fill: "#1e293b", stroke: "#334155", "stroke-width": 2 });

    // 頂部說明（y <= 410）
    ctx.text({ x: 400, y: 62, "text-anchor": "middle", "font-size": 14, fill: "#94a3b8" }, "實際結果因人而異，須由醫師當面評估");

    // 組織基質
    ctx.rect({ x: 60, y: 90, width: 680, height: 230, rx: 14, fill: "#273549", stroke: "#384a62" });

    // 血管生長（純函式進度，使用 pathLength 搭配 stroke-dashoffset，不使用 getTotalLength）
    const unitCount = params.units;
    if (params.connectors === "vessels") {
      const vesselProgress = Math.max(0, Math.min(1, u * 1.25));
      const dashOffset = String(100 * (1 - vesselProgress));

      for (let i = 0; i < unitCount; i++) {
        const ux = 160 + (480 / (unitCount - 1 || 1)) * i;
        const uy = 190 + (i % 2 === 0 ? -16 : 16);

        const d1 = "M " + (ux - 28) + " 95 Q " + (ux - 16) + " 140 " + (ux - 8) + " " + (uy - 12);
        ctx.path({
          d: d1,
          fill: "none",
          stroke: PALETTE.blood,
          "stroke-width": 3,
          "stroke-linecap": "round",
          pathLength: "100",
          "stroke-dasharray": "100",
          "stroke-dashoffset": dashOffset
        });

        const d2 = "M " + (ux + 28) + " 95 Q " + (ux + 16) + " 142 " + (ux + 8) + " " + (uy - 8);
        ctx.path({
          d: d2,
          fill: "none",
          stroke: PALETTE.blood,
          "stroke-width": 2.5,
          "stroke-linecap": "round",
          pathLength: "100",
          "stroke-dasharray": "100",
          "stroke-dashoffset": dashOffset
        });
      }
    }

    // 組織單元
    for (let i = 0; i < unitCount; i++) {
      const ux = 160 + (480 / (unitCount - 1 || 1)) * i;
      const uy = 190 + (i % 2 === 0 ? -16 : 16);

      let unitOpacity = 0.85;
      if (params.unit_effect === "mature") {
        unitOpacity = 0.45 + 0.55 * u;
      } else if (params.unit_effect === "fade") {
        unitOpacity = 1.0 - 0.55 * u;
      }

      ctx.circle({ cx: ux, cy: uy, r: 35, fill: PALETTE.fat, stroke: "#d97706", "stroke-width": 2, opacity: unitOpacity });
      ctx.circle({ cx: ux, cy: uy, r: 22, fill: "#fef08a", opacity: unitOpacity * 0.7 });
    }

    // 底部時間軸進度線條
    ctx.line({ x1: 110, y1: 355, x2: 690, y2: 355, stroke: "#334155", "stroke-width": 6, "stroke-linecap": "round" });
    const currentProgX = 110 + (690 - 110) * u;
    ctx.line({ x1: 110, y1: 355, x2: currentProgX, y2: 355, stroke: PALETTE.accent, "stroke-width": 6, "stroke-linecap": "round" });

    // 三個里程碑點與標籤（全部 y <= 410）
    const nodePositions = [110, 400, 690];
    const thresholds = [0.05, 0.48, 0.92];
    for (let mIdx = 0; mIdx < 3; mIdx++) {
      const nx = nodePositions[mIdx];
      const isReached = u >= thresholds[mIdx];
      ctx.circle({ cx: nx, cy: 355, r: 10, fill: isReached ? PALETTE.accent : "#334155", stroke: "#ffffff", "stroke-width": 2 });

      const milestoneText = params.milestones && params.milestones[mIdx] ? params.milestones[mIdx] : "";
      ctx.text(
        {
          x: nx,
          y: 395,
          "text-anchor": "middle",
          "font-size": 14,
          "font-weight": isReached ? "bold" : "normal",
          fill: isReached ? "#ffffff" : "#64748b",
          opacity: isReached ? 1.0 : 0.5
        },
        milestoneText
      );
    }
  }

  // 註冊表
  const blueprints = {
    process_diagram: {
      params: ["source", "particles", "container_layers", "step_labels"],
      defaults: {
        source: { label: "皮下脂肪", fill: "skin" },
        particles: 5,
        container_layers: [
          { label: "油滴", fill: "oil", weight: 2, keep: false },
          { label: "純化脂肪", fill: "fat", weight: 3, keep: true },
          { label: "血水", fill: "blood", weight: 2, keep: false }
        ],
        step_labels: ["微創抽取", "離心分層", "保留純化脂肪"]
      },
      draw: drawProcessDiagram
    },
    contrast: {
      params: ["left", "right"],
      defaults: {
        left: {
          title: "單處過量",
          note: "較易出現硬塊",
          mode: "mass"
        },
        right: {
          title: "分層少量",
          note: "接觸周圍組織",
          mode: "layered",
          rows: 3,
          per_row: 5
        }
      },
      draw: drawContrast
    },
    timeline: {
      params: ["milestones", "unit_effect", "connectors", "units"],
      defaults: {
        milestones: ["術後初期", "微血管長入", "狀態穩定"],
        unit_effect: "mature",
        connectors: "vessels",
        units: 3
      },
      draw: drawTimeline
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
      if (out.left.mode !== "mass" && out.left.mode !== "scattered") out.left.mode = "mass";

      if (!out.right || typeof out.right !== "object") out.right = cloneObject(def.right);
      out.right.title = String(out.right.title || "").slice(0, 8);
      out.right.note = String(out.right.note || "").slice(0, 14);
      if (out.right.mode !== "layered" && out.right.mode !== "mass") out.right.mode = "layered";
      out.right.rows = clampNumber(Math.round(out.right.rows), 1, 4);
      out.right.per_row = clampNumber(Math.round(out.right.per_row), 3, 8);
    } else if (blueprint === "timeline") {
      if (!Array.isArray(out.milestones) || out.milestones.length !== 3) {
        out.milestones = cloneObject(def.milestones);
      } else {
        out.milestones = out.milestones.map(function (m) {
          return String(m || "").slice(0, 8);
        });
      }
      if (out.unit_effect !== "mature" && out.unit_effect !== "fade" && out.unit_effect !== "steady") {
        out.unit_effect = "mature";
      }
      if (out.connectors !== "vessels" && out.connectors !== "none") {
        out.connectors = "vessels";
      }
      out.units = clampNumber(Math.round(out.units), 2, 5);
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
