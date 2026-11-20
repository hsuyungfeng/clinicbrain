(function () {
  "use strict";

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function makeCard(titleText) {
    const card = el("article", "edu-card");
    card.appendChild(el("h2", "text-lg font-bold text-sky-300 mb-2", titleText));
    return card;
  }

  function renderEduSections(container, edu) {
    container.innerHTML = "";
    if (!edu) {
      const card = makeCard("完整圖文衛教");
      card.appendChild(el("p", "text-sm text-slate-300", "此主題尚未產生 7 段結構化圖文，請參考上方動畫解說或洽詢診所醫師。"));
      container.appendChild(card);
      return;
    }

    // 1. 定義與結構重點
    const c1 = makeCard("一、認識這個狀況");
    c1.appendChild(el("p", "text-sm leading-relaxed mb-2", edu.definition.summary));
    c1.appendChild(el("p", "text-sm text-amber-200 mb-2", "解剖重點：" + edu.definition.anatomy_note));
    c1.appendChild(el("div", "text-xs bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-sky-200", "💡 " + edu.definition.key_point));
    container.appendChild(c1);

    // 2. 核心觀念對比表
    const c2 = makeCard("二、重要觀念對照");
    const tbl2 = el("table", "edu-table");
    const trHead = el("tr");
    trHead.appendChild(el("th", "", "項目"));
    trHead.appendChild(el("th", "", edu.comparison.left_title));
    trHead.appendChild(el("th", "", edu.comparison.right_title));
    tbl2.appendChild(trHead);
    (edu.comparison.rows || []).forEach(function (r) {
      const tr = el("tr");
      tr.appendChild(el("td", "font-semibold", r.aspect));
      tr.appendChild(el("td", "", r.left_value));
      tr.appendChild(el("td", "", r.right_value));
      tbl2.appendChild(tr);
    });
    c2.appendChild(tbl2);
    container.appendChild(c2);

    // 3. 成因與高風險因子
    const c3 = makeCard("三、成因演變與高風險因子");
    const flow = el("div", "flex flex-wrap items-center gap-2 mb-3");
    (edu.causes_risks.flow_steps || []).forEach(function (step, idx) {
      if (idx > 0) flow.appendChild(el("span", "text-sky-400 font-bold", "→"));
      flow.appendChild(el("span", "px-3 py-1 rounded-lg bg-slate-900 border border-sky-700 text-xs", step));
    });
    c3.appendChild(flow);
    const rfWrap = el("div");
    (edu.causes_risks.risk_factors || []).forEach(function (rf) {
      rfWrap.appendChild(el("span", "pill", "🎯 " + rf));
    });
    c3.appendChild(rfWrap);
    container.appendChild(c3);

    // 4. 常見症狀與併發症
    const c4 = makeCard("四、常見症狀與危險併發症");
    const symList = el("ul", "list-disc list-inside text-sm space-y-1 mb-3");
    (edu.symptoms_complications.symptoms || []).forEach(function (s) {
      symList.appendChild(el("li", "", s));
    });
    c4.appendChild(symList);
    const compGrid = el("div", "grid grid-cols-1 sm:grid-cols-2 gap-2");
    (edu.symptoms_complications.complications || []).forEach(function (comp) {
      const box = el("div", "p-2.5 rounded-lg bg-rose-950/40 border border-rose-800/70 text-xs");
      box.appendChild(el("div", "font-bold text-rose-300", "⚠️ " + comp.name));
      box.appendChild(el("div", "text-slate-200 mt-0.5", comp.description));
      compGrid.appendChild(box);
    });
    c4.appendChild(compGrid);
    container.appendChild(c4);

    // 5. 診斷方式
    const c5 = makeCard("五、常見檢查與診斷方式");
    const tbl5 = el("table", "edu-table");
    const th5 = el("tr");
    th5.appendChild(el("th", "", "檢查項目"));
    th5.appendChild(el("th", "", "臨床用途"));
    tbl5.appendChild(th5);
    (edu.diagnosis.methods || []).forEach(function (m) {
      const tr = el("tr");
      tr.appendChild(el("td", "font-semibold", m.method));
      tr.appendChild(el("td", "", m.purpose));
      tbl5.appendChild(tr);
    });
    c5.appendChild(tbl5);
    container.appendChild(c5);

    // 6. 衛教重點與迷思破解
    const c6 = makeCard("六、日常衛教重點與迷思破解");
    const tipList = el("ul", "list-disc list-inside text-sm space-y-1 mb-3");
    (edu.prevention_myth.tips || []).forEach(function (tip) {
      tipList.appendChild(el("li", "", "✅ " + tip));
    });
    c6.appendChild(tipList);
    c6.appendChild(el("div", "text-xs bg-emerald-950/40 border border-emerald-700/60 rounded-lg p-3 text-emerald-200", "💬 常見迷思破解：" + edu.prevention_myth.myth_buster));
    container.appendChild(c6);

    // 7. 何時必須急診與一句話記牢
    const c7 = makeCard("七、何時必須立即就醫？");
    const rfBox = el("div", "p-3 rounded-lg bg-red-950/50 border border-red-600 mb-3");
    const rfUl = el("ul", "list-disc list-inside text-sm text-red-100 space-y-1");
    (edu.red_flags_takeaway.red_flags || []).forEach(function (rf) {
      rfUl.appendChild(el("li", "", "🚨 " + rf));
    });
    rfBox.appendChild(rfUl);
    c7.appendChild(rfBox);
    c7.appendChild(el("div", "p-3 rounded-lg bg-amber-950/40 border border-amber-600 text-sm font-bold text-amber-200", "一句話記牢：" + edu.red_flags_takeaway.takeaway));
    container.appendChild(c7);
  }

  async function init() {
    const parts = window.location.pathname.split("/").filter(Boolean);
    const topicKey = parts[parts.length - 1] || "";
    const titleEl = document.getElementById("edu-title");
    const sectionsEl = document.getElementById("edu-sections");
    const svgEl = document.getElementById("edu-svg-stage");

    document.getElementById("btn-print").addEventListener("click", function () {
      window.print();
    });
    document.getElementById("btn-copy").addEventListener("click", function () {
      if (navigator.clipboard) {
        navigator.clipboard.writeText(window.location.href).catch(function () {});
      }
    });

    if (!topicKey) {
      titleEl.textContent = "缺少主題代碼";
      return;
    }

    try {
      const resp = await fetch("/api/v1/visual/edu/" + encodeURIComponent(topicKey));
      if (!resp.ok) {
        titleEl.textContent = "找不到此衛教主題";
        return;
      }
      const data = await resp.json();
      titleEl.textContent = data.title || topicKey;
      document.title = (data.title || topicKey) + " — 臨床雙軌衛教單張";

      if (data.video && data.video.landscape && data.video.landscape.available && data.video.landscape.download_url) {
        const mp4Btn = document.getElementById("btn-mp4");
        mp4Btn.href = data.video.landscape.download_url;
        mp4Btn.classList.remove("hidden");
      }

      if (data.ir && Array.isArray(data.ir.scenes) && window.ClinicVisual && typeof window.ClinicVisual.mount === "function") {
        const mounted = window.ClinicVisual.mount(svgEl, data.ir.scenes);
        let playing = true;
        mounted.play();
        document.getElementById("btn-play-toggle").addEventListener("click", function () {
          if (playing) { mounted.pause(); playing = false; }
          else { mounted.play(); playing = true; }
        });
        document.getElementById("btn-replay").addEventListener("click", function () {
          mounted.renderAt(0);
          mounted.play();
          playing = true;
        });
      }

      renderEduSections(sectionsEl, data.edu);
    } catch (err) {
      titleEl.textContent = "載入失敗，請稍後再試";
    }
  }

  window.ClinicEduRenderer = { renderEduSections: renderEduSections };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
