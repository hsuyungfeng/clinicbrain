// clinicbrain 診所 Web 管理系統 JavaScript 核心邏輯

document.addEventListener("DOMContentLoaded", () => {
    initAuth();
    initClinicSelectors();
    initTabNavigation();
    initDashboard();
    initReviewSection();
    initTreesSection();
    initVisualsSection();
    initUploadSection();
    initSoapSection();
    initAskSection();
});

// 1. 認證機制管理
function getApiKey() {
    return sessionStorage.getItem("admin_api_key") || "";
}

function setApiKey(key) {
    sessionStorage.setItem("admin_api_key", key.trim());
    updateAuthBadge();
}

function updateAuthBadge() {
    const badge = document.getElementById("authStatusBadge");
    const key = getApiKey();
    if (key) {
        badge.textContent = "已設定 API Key";
        badge.className = "text-xs bg-green-600 text-green-100 px-2.5 py-1 rounded-full font-medium";
    } else {
        badge.textContent = "未設定 API Key (開發模式)";
        badge.className = "text-xs bg-yellow-600 text-yellow-100 px-2.5 py-1 rounded-full font-medium";
    }
}

function initAuth() {
    updateAuthBadge();

    const authModal = document.getElementById("authModal");
    const btnOpen = document.getElementById("btnOpenAuthModal");
    const btnClose = document.getElementById("btnCloseAuthModal");
    const btnSave = document.getElementById("btnSaveApiKey");
    const inputKey = document.getElementById("inputApiKey");

    btnOpen.addEventListener("click", () => {
        inputKey.value = getApiKey();
        authModal.classList.remove("hidden");
    });

    btnClose.addEventListener("click", () => {
        authModal.classList.add("hidden");
    });

    btnSave.addEventListener("click", () => {
        setApiKey(inputKey.value);
        authModal.classList.add("hidden");
        // 重新整理各區塊
        loadDashboardSummary();
        loadReviewFaqs();
        loadTrees();
    });
}

function getAuthHeaders() {
    const headers = {};
    const key = getApiKey();
    if (key) {
        headers["X-API-Key"] = key;
    }
    return headers;
}

// 2. 頁籤切換
function initTabNavigation() {
    const tabs = document.querySelectorAll(".nav-tab");
    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            tabs.forEach(t => t.classList.remove("active", "border-indigo-600", "text-indigo-600"));
            tabs.forEach(t => t.classList.add("border-transparent", "text-gray-500"));

            tab.classList.add("active", "border-indigo-600", "text-indigo-600");
            tab.classList.remove("border-transparent", "text-gray-500");

            const targetId = tab.getAttribute("data-tab");
            document.querySelectorAll(".tab-content").forEach(c => c.classList.add("hidden"));
            const targetEl = document.getElementById(targetId);
            if (targetEl) {
                targetEl.classList.remove("hidden");
            }

            if (targetId === "tab-dashboard") loadDashboardSummary();
            if (targetId === "tab-review") loadReviewFaqs();
            if (targetId === "tab-trees") loadTrees();
            if (targetId === "tab-visuals") {
                loadVisuals();
                loadApprovedTreesForVisualSelect();
            }
            if (targetId === "tab-soap") loadSoapRecords();
        });
    });
}

// 3. 儀表板
function initDashboard() {
    loadDashboardSummary();
}

async function loadDashboardSummary() {
    try {
        const resp = await fetch("/api/v1/admin/review/summary", {
            headers: getAuthHeaders()
        });
        if (!resp.ok) return;
        const data = await resp.json();

        document.getElementById("statPendingTotal").textContent = data.pending_total ?? 0;
        const elTreePend = document.getElementById("statTreesPendingTotal");
        if (elTreePend) elTreePend.textContent = data.trees_pending_total ?? 0;
        const elVisPend = document.getElementById("statVisualsPendingTotal");
        if (elVisPend) elVisPend.textContent = data.visuals_pending_total ?? 0;
        document.getElementById("statApprovedTotal").textContent = data.approved_total ?? 0;
        const elTreeApp = document.getElementById("statTreesApprovedTotal");
        if (elTreeApp) elTreeApp.textContent = data.trees_approved_total ?? 0;
        document.getElementById("statRejectedTotal").textContent = data.rejected_total ?? 0;
        document.getElementById("statSoapTotal").textContent = data.soap_records_total ?? 0;

        document.getElementById("statPendingSoapDistilled").textContent = data.pending_soap_distilled ?? 0;
        document.getElementById("statPendingSpecial").textContent = data.pending_special ?? 0;
        document.getElementById("statPendingGeneral").textContent = data.pending_general ?? 0;
    } catch (e) {
        console.error("載入儀表板統計失敗", e);
    }
}

// 4. 待審草稿簽核（Phase 19：全選／反選／批量／AI 生成／內聯編輯）
// 安全：所有來自伺服器或使用者的文字一律以 textContent 寫入，不以 HTML 字串拼接任何資料。
const reviewState = {
    selected: new Set(),
    cards: new Map(),   // id -> { card, checkbox }
    busy: false,
};

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

// 將後端錯誤回應轉為可讀文字：detail 為字串直接顯示；FastAPI 驗證錯誤（陣列）取第一筆 msg
function apiErrorText(data, fallback) {
    const d = data && data.detail;
    if (typeof d === "string" && d.trim()) return d;
    if (Array.isArray(d) && d.length && d[0] && typeof d[0].msg === "string") return d[0].msg;
    return fallback;
}

function showToast(message, kind) {
    const t = document.getElementById("toast");
    t.textContent = message;
    t.className = "toast show " + (kind || "info");
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => { t.className = "toast"; }, 4500);
}

function setStatusBox(container, text, kind) {
    container.replaceChildren(el("div", "status-box " + (kind || ""), text));
}

function initReviewSection() {
    document.getElementById("btnRefreshReview").addEventListener("click", loadReviewFaqs);
    document.getElementById("reviewFilterCategory").addEventListener("change", loadReviewFaqs);
    document.getElementById("reviewFilterSource").addEventListener("change", loadReviewFaqs);
    document.getElementById("btnSelectAll").addEventListener("click", () => {
        reviewState.cards.forEach((entry, id) => { if (isCardVisible(entry)) reviewState.selected.add(id); });
        syncSelectionUi();
    });
    document.getElementById("btnInvertSelect").addEventListener("click", () => {
        reviewState.cards.forEach((entry, id) => {
            if (!isCardVisible(entry)) return;
            if (reviewState.selected.has(id)) reviewState.selected.delete(id);
            else reviewState.selected.add(id);
        });
        syncSelectionUi();
    });
    document.getElementById("reviewView").addEventListener("change", applyViewFilter);
    document.getElementById("btnBatchGenerate").addEventListener("click", startBatchGenerate);
    document.getElementById("btnCancelBatchGen").addEventListener("click", cancelBatchGenerate);
    const btnAutoFill = document.getElementById("btnAutoFillAll");
    if (btnAutoFill) btnAutoFill.addEventListener("click", startAutoFillAll);
    const btnCancelAuto = document.getElementById("btnCancelAutoFill");
    if (btnCancelAuto) btnCancelAuto.addEventListener("click", cancelBatchGenerate);
    const btnBatchSelected = document.getElementById("btnBatchGenerateSelected");
    if (btnBatchSelected) btnBatchSelected.addEventListener("click", startBatchGenerateSelected);
    pollBatchGenerate(true);   // 重新整理頁面後，若伺服器仍有作業進行中，接續顯示進度
    document.getElementById("btnClearSelect").addEventListener("click", () => {
        reviewState.selected.clear();
        syncSelectionUi();
    });
    document.getElementById("btnBatchApprove").addEventListener("click", () => runBatch("approve"));
    document.getElementById("btnBatchReject").addEventListener("click", () => runBatch("reject"));
}

function syncSelectionUi() {
    reviewState.cards.forEach(({ card, checkbox }, id) => {
        const on = reviewState.selected.has(id);
        checkbox.checked = on;
        card.classList.toggle("selected", on);
    });
    const n = reviewState.selected.size;
    let visibleCount = 0;
    reviewState.cards.forEach(entry => { if (isCardVisible(entry)) visibleCount++; });
    document.getElementById("selectionCounter").textContent = `已選取 ${n} / ${visibleCount} 筆`;
    let needs = 0;
    reviewState.cards.forEach(entry => { if (entry.state && entry.state.needsAnswer && isCardVisible(entry)) needs++; });
    document.getElementById("btnBatchGenerate").textContent = needs > 0 ? `🤖 批量補齊答案 (${needs})` : "🤖 批量補齊答案";
    document.getElementById("actionBarCount").textContent = `已選取 ${n} 筆草稿`;
    const btnGenSel = document.getElementById("btnBatchGenerateSelected");
    if (btnGenSel) btnGenSel.textContent = n > 0 ? `🤖 批量生成所選答案 (${n})` : "🤖 批量生成所選答案";
    document.getElementById("btnBatchApprove").textContent = `✅ 批量核准 (${n})`;
    document.getElementById("btnBatchReject").textContent = `❌ 批量駁回 (${n})`;
    document.getElementById("actionBar").classList.toggle("show", n > 0);
}

async function loadReviewFaqs() {
    const container = document.getElementById("reviewCardsContainer");
    reviewState.selected.clear();
    reviewState.cards.clear();
    syncSelectionUi();
    container.replaceChildren(el("div", "skeleton"), el("div", "skeleton"), el("div", "skeleton"));

    const category = document.getElementById("reviewFilterCategory").value;
    const source = document.getElementById("reviewFilterSource").value;

    const clinic = document.getElementById("reviewFilterClinic").value;

    let url = "/api/v1/admin/review/faqs?status=pending&limit=200";
    if (clinic) url += `&clinic_id=${encodeURIComponent(clinic)}`;
    if (category) url += `&category=${encodeURIComponent(category)}`;
    if (source) url += `&source_type=${encodeURIComponent(source)}`;

    try {
        const resp = await fetch(url, { headers: getAuthHeaders() });
        if (!resp.ok) {
            setStatusBox(container, `無法載入待審列表 (HTTP ${resp.status})，請確認 API Key`, "error");
            return;
        }
        const data = await resp.json();
        const faqs = data.faqs || [];
        if (faqs.length === 0) {
            setStatusBox(container, "🎉 當前無任何待簽核衛教草稿。", "empty");
            return;
        }
        container.replaceChildren();
        // 後端為 id 降冪；簽核時依 id 升冪（文件原順序）較直覺
        faqs.slice().sort((a, b) => a.id - b.id).forEach(faq => {
            const card = createFaqReviewCard(faq);
            container.appendChild(card);
        });
        if (data.total > faqs.length) {
            showToast(`僅顯示前 ${faqs.length} 筆（共 ${data.total} 筆），處理後請重新整理`, "info");
        }
        applyViewFilter();
    } catch (e) {
        setStatusBox(container, "連線失敗", "error");
    }
}

function badge(text, cls) {
    return el("span", "badge " + cls, text);
}

function createFaqReviewCard(faq) {
    const card = el("div", "faq-card");
    card.dataset.faqId = String(faq.id);

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "faq-check";
    checkbox.setAttribute("aria-label", `選取草稿 ${faq.id}`);
    checkbox.addEventListener("change", () => {
        if (checkbox.checked) reviewState.selected.add(faq.id);
        else reviewState.selected.delete(faq.id);
        syncSelectionUi();
    });
    const entry = { card, checkbox, state: null };
    reviewState.cards.set(faq.id, entry);

    const body = el("div", "faq-body");

    const header = el("div", "faq-header");
    const tags = el("div", "faq-tags");
    tags.appendChild(badge(`ID ${faq.id}`, "badge-id"));
    tags.appendChild(badge(
        faq.source_type === "soap_distilled" ? "SOAP 提煉" :
        faq.source_type === "llm_generated" ? "LLM 預生成" :
        faq.source_type === "web_upload" ? "網頁上傳" : (faq.source_type || "未知"),
        faq.source_type === "soap_distilled" ? "badge-soap" :
        faq.source_type === "llm_generated" ? "badge-llm" : "badge-upload"
    ));
    tags.appendChild(badge(faq.category === "general" ? "通用醫學" : "診所專屬",
        faq.category === "general" ? "badge-general" : "badge-special"));
    const warn = badge("⚠️ 答案待補齊", "badge-warn");
    tags.appendChild(warn);
    const aiBadge = badge("🤖 本機 LLM 生成・待醫師確認", "badge-ai");
    tags.appendChild(aiBadge);
    header.appendChild(tags);
    header.appendChild(el("span", "faq-time", faq.created_at ? faq.created_at.substring(0, 16) : ""));
    body.appendChild(header);

    const qEl = el("h3", "faq-question");
    const aEl = el("p", "faq-answer");
    body.appendChild(qEl);
    body.appendChild(aEl);

    const state = { question: faq.question, answer: faq.answer, needsAnswer: !!faq.needs_answer,
                    aiGenerated: !!(faq.metadata && faq.metadata.answer_source === "local_llm") };
    entry.state = state;
    function paint() {
        qEl.textContent = `【問】${state.question}`;
        aEl.textContent = state.answer;
        warn.classList.toggle("hidden", !state.needsAnswer);
        aiBadge.classList.toggle("hidden", !state.aiGenerated);
        btnGen.textContent = state.needsAnswer ? "🤖 本地 LLM 生成解答" : "🔄 重新生成解答";
        btnGen.classList.toggle("primary-soft", state.needsAnswer);
        if (reviewState.cards.has(faq.id)) applyViewFilter();
    }

    // 內聯編輯區
    const editBox = el("div", "edit-box hidden");
    const qIn = document.createElement("input");
    qIn.type = "text"; qIn.maxLength = 200; qIn.className = "edit-input";
    const aIn = document.createElement("textarea");
    aIn.rows = 6; aIn.maxLength = 3000; aIn.className = "edit-input";
    const editBtns = el("div", "btn-row");
    const btnSave = el("button", "btn btn-primary", "💾 儲存修訂");
    const btnCancel = el("button", "btn btn-ghost", "取消");
    editBtns.appendChild(btnCancel);
    editBtns.appendChild(btnSave);
    editBox.appendChild(qIn);
    editBox.appendChild(aIn);
    editBox.appendChild(editBtns);
    body.appendChild(editBox);

    // 若有 SOAP 溯源細節
    if (faq.metadata && typeof faq.metadata === "object" && (faq.metadata.condition || faq.metadata.record_count)) {
        const metaDiv = el("div", "faq-meta");
        metaDiv.appendChild(el("div", "meta-title", "🩺 臨床病歷溯源資訊"));
        if (faq.metadata.condition) metaDiv.appendChild(el("div", "", `• 標的疾病：${faq.metadata.condition}`));
        if (faq.metadata.record_count) metaDiv.appendChild(el("div", "", `• 參考臨床病歷數：${faq.metadata.record_count} 筆`));
        body.appendChild(metaDiv);
    }

    const btnArea = el("div", "btn-row faq-actions");
    const btnGen = el("button", "btn btn-soft");
    const btnEdit = el("button", "btn btn-ghost", "✏️ 編輯");
    const btnReject = el("button", "btn btn-danger-soft", "❌ 駁回");
    const btnApprove = el("button", "btn btn-success", "✅ 核准發布");
    btnArea.appendChild(btnGen);
    btnArea.appendChild(btnEdit);
    btnArea.appendChild(btnReject);
    btnArea.appendChild(btnApprove);
    body.appendChild(btnArea);

    function setBusy(button, busyText, on) {
        button.disabled = on;
        if (on) { button._label = button.textContent; button.textContent = ""; button.appendChild(el("span", "spinner")); button.appendChild(document.createTextNode(" " + busyText)); }
        else if (button._label) { button.textContent = button._label; }
    }

    btnEdit.addEventListener("click", () => {
        qIn.value = state.question;
        aIn.value = state.answer;
        editBox.classList.remove("hidden");
    });
    btnCancel.addEventListener("click", () => editBox.classList.add("hidden"));
    btnSave.addEventListener("click", async () => {
        setBusy(btnSave, "儲存中", true);
        try {
            const resp = await fetch(`/api/v1/admin/review/faqs/${faq.id}`, {
                method: "PATCH",
                headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
                body: JSON.stringify({ question: qIn.value, answer: aIn.value }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) { showToast(`修訂失敗：${typeof data.detail === "string" ? data.detail : "格式不正確"}`, "error"); return; }
            const f = data.faq || {};
            state.question = f.question ?? qIn.value;
            state.answer = f.answer ?? aIn.value;
            state.needsAnswer = false;
            state.aiGenerated = false;
            paint();
            editBox.classList.add("hidden");
            showToast("已儲存修訂（仍為待審，需醫師核准才會生效）", "success");
        } catch (e) {
            showToast("網路請求失敗", "error");
        } finally {
            setBusy(btnSave, "", false);
        }
    });

    btnGen.addEventListener("click", async () => {
        const overwrite = !state.needsAnswer;
        if (overwrite && !window.confirm("此草稿已有答案，重新生成會覆蓋目前內容。確定要重新生成嗎？")) return;
        setBusy(btnGen, "本機模型生成中（約 1～3 分鐘，請勿關閉頁面）", true);
        card.classList.add("working");
        try {
            const resp = await fetch(`/api/v1/admin/review/faqs/${faq.id}/generate-answer`, {
                method: "POST",
                headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
                body: JSON.stringify({ overwrite }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) { showToast(`生成失敗：${typeof data.detail === "string" ? data.detail : "請稍後再試"}`, "error"); return; }
            state.question = data.question;
            state.answer = data.answer;
            state.needsAnswer = false;
            state.aiGenerated = true;
            paint();
            showToast("已由本機 LLM 生成解答，請醫師確認內容後再核准", "success");
        } catch (e) {
            showToast("網路請求失敗", "error");
        } finally {
            card.classList.remove("working");
            setBusy(btnGen, "", false);
            paint();
        }
    });

    btnReject.addEventListener("click", () => processReview(faq.id, "reject"));
    btnApprove.addEventListener("click", () => processReview(faq.id, "approve"));

    card.addEventListener("click", (ev) => {
        // 點擊卡片空白處切換選取（互動元件除外）
        if (ev.target.closest("button, input, textarea, a, .edit-box")) return;
        if (window.getSelection && String(window.getSelection())) return;
        checkbox.checked = !checkbox.checked;
        checkbox.dispatchEvent(new Event("change"));
    });

    card.appendChild(checkbox);
    card.appendChild(body);
    paint();
    return card;
}

function isCardVisible(entry) {
    return !entry.card.classList.contains("hidden");
}

function applyViewFilter() {
    const mode = document.getElementById("reviewView").value;
    reviewState.cards.forEach((entry, id) => {
        const st = entry.state || {};
        const show = mode === "all" || (mode === "needs" && st.needsAnswer) || (mode === "ai" && st.aiGenerated);
        entry.card.classList.toggle("hidden", !show);
        if (!show) reviewState.selected.delete(id);   // 被隱藏的卡片不可留在選取集合中，避免誤批量操作
    });
    syncSelectionUi();
}

// ---- 批量補齊答案：伺服器背景作業，逐題由本機 LLM 處理；完成後再由醫師一起審核 ----
const batchGen = { timer: null, lastState: "idle" };

async function startBatchGenerate() {
    const selectedNeeds = [];
    const allNeeds = [];
    reviewState.cards.forEach((entry, id) => {
        if (!(entry.state && entry.state.needsAnswer) || !isCardVisible(entry)) return;
        allNeeds.push(id);
        if (reviewState.selected.has(id)) selectedNeeds.push(id);
    });
    const ids = (selectedNeeds.length > 0 ? selectedNeeds : allNeeds).slice(0, 100);
    if (ids.length === 0) { showToast("目前沒有「答案待補齊」的草稿", "info"); return; }
    const mins = Math.round(ids.length * 5);
    const scope = selectedNeeds.length > 0 ? "所選" : "全部";
    if (!window.confirm(`將由本機 LLM 逐題補齊${scope} ${ids.length} 筆「答案待補齊」的草稿（約需 ${mins} 分鐘，可先離開此頁）。\n補齊後仍為待審，不會自動核准；完成後再一起審核。\n確定開始嗎？`)) return;
    try {
        const resp = await fetch("/api/v1/admin/review/batch-generate", {
            method: "POST",
            headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
            body: JSON.stringify({ faq_ids: ids }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) { showToast(`無法開始：${typeof data.detail === "string" ? data.detail : "格式不正確"}`, "error"); return; }
        showToast(`已開始批量補齊 ${ids.length} 筆，進度見上方面板`, "success");
        batchGen.lastState = "running";
        pollBatchGenerate(false);
    } catch (e) {
        showToast("網路請求失敗", "error");
    }
}

async function startBatchGenerateSelected() {
    const selected = Array.from(reviewState.selected);
    if (selected.length === 0) {
        showToast("請先勾選欲補齊答案的草稿", "info");
        return;
    }
    const ids = selected.slice(0, 100);
    let alreadyFull = 0;
    ids.forEach(id => {
        const entry = reviewState.cards.get(id);
        if (entry && entry.state && !entry.state.needsAnswer) alreadyFull++;
    });
    let overwrite = false;
    if (alreadyFull > 0) {
        if (alreadyFull === ids.length) {
            if (!window.confirm(
                `所選 ${ids.length} 筆草稿皆「已有完整答案」（非待補齊狀態）。\n\n` +
                `• 若您是要直接核准發布，請按「取消」並改點右側綠色的「✅ 批量核准 (${ids.length})」。\n` +
                `• 若您確定要由本機 LLM 重新生成並覆寫這 ${ids.length} 筆答案，請按「確定」。`
            )) return;
            overwrite = true;
        } else {
            overwrite = window.confirm(
                `所選 ${ids.length} 筆草稿中，有 ${alreadyFull} 筆已有完整答案。\n` +
                `按「確定」將一併重新生成並覆寫；按「取消」則僅補齊空白或過短的草稿（略過已有答案者）。`
            );
        }
    } else {
        const mins = Math.round(ids.length * 5);
        if (!window.confirm(`將由本機 LLM 逐題補齊所選 ${ids.length} 筆草稿的答案（約需 ${mins} 分鐘，可先離開此頁）。\n補齊後仍為待審，不會自動核准；完成後再一起審核。\n確定開始嗎？`)) return;
    }
    try {
        const resp = await fetch("/api/v1/admin/review/batch-generate", {
            method: "POST",
            headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
            body: JSON.stringify({ faq_ids: ids, overwrite }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) { showToast(`無法開始：${typeof data.detail === "string" ? data.detail : "格式不正確"}`, "error"); return; }
        showToast(`已開始批量生成所選 ${ids.length} 筆答案，進度見上方面板`, "success");
        batchGen.lastState = "running";
        pollBatchGenerate(false);
    } catch (e) {
        showToast("網路請求失敗", "error");
    }
}

async function startAutoFillAll() {
    if (!window.confirm("將在背景自動掃描所有「答案待補齊」的待審草稿，並由本機 LLM 逐題補齊答案。\n此作業在伺服器背景進行，補齊後仍為待審（pending），需由醫師審核核准。\n確定開始背景自動補齊嗎？")) return;
    try {
        const resp = await fetch("/api/v1/admin/review/autofill/all", {
            method: "POST",
            headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
            body: JSON.stringify({}),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            showToast(`無法啟動背景補齊：${typeof data.detail === "string" ? data.detail : "伺服器錯誤"}`, "error");
            return;
        }
        if (data.status === "noop") {
            showToast(data.message || "目前無待補齊答案之草稿", "info");
            return;
        }
        showToast(`已成功啟動背景自動補齊，共排入 ${data.scheduled_count || 0} 筆草稿！`, "success");
        batchGen.lastState = "running";
        pollBatchGenerate(false);
    } catch (e) {
        showToast("網路請求失敗", "error");
    }
}

async function cancelBatchGenerate() {
    if (!window.confirm("確定取消？目前這一題完成後會停止，已補齊的答案會保留。")) return;
    try {
        await fetch("/api/v1/admin/review/batch-generate/cancel", { method: "POST", headers: getAuthHeaders() });
        showToast("已要求取消，目前題目完成後停止", "info");
    } catch (e) {
        showToast("網路請求失敗", "error");
    }
}

function renderBatchGenPanel(s) {
    const panel = document.getElementById("batchGenPanel");
    const banner = document.getElementById("autofillProgressBanner");

    if (!s || s.state === "idle") {
        if (panel) panel.classList.add("hidden");
        if (banner) banner.classList.add("hidden");
        return;
    }

    if (panel) panel.classList.remove("hidden");
    if (banner) banner.classList.remove("hidden");

    const running = s.state === "running";
    const names = { running: "批量補齊進行中", done: "批量補齊完成", cancelled: "批量補齊已取消", aborted: "批量補齊已中止" };
    const progressPercent = s.total ? Math.round((s.processed / s.total) * 100) : 0;

    // 更新舊 batchGenPanel
    const batchGenText = document.getElementById("batchGenText");
    if (batchGenText) {
        batchGenText.textContent =
            `${names[s.state] || s.state}：${s.processed} / ${s.total}　成功 ${s.ok}・失敗 ${s.failed.length}・略過 ${s.skipped}` +
            (running && s.current_id ? `（處理中：ID ${s.current_id}）` : "");
    }
    const batchGenBar = document.getElementById("batchGenBar");
    if (batchGenBar) batchGenBar.style.width = `${progressPercent}%`;

    const btnCancel = document.getElementById("btnCancelBatchGen");
    if (btnCancel) btnCancel.classList.toggle("hidden", !running);

    const detail = document.getElementById("batchGenDetail");
    if (detail) {
        detail.replaceChildren();
        if (s.message) detail.appendChild(el("div", "", s.message));
        s.failed.slice(0, 8).forEach(f => detail.appendChild(el("div", "batchgen-fail", `ID ${f.id}：${f.reason}`)));
        if (s.failed.length > 8) detail.appendChild(el("div", "", `…另有 ${s.failed.length - 8} 筆失敗`));
    }

    // 更新新 autofillProgressBanner (Phase 20)
    const autoStatus = document.getElementById("autofillStatusText");
    if (autoStatus) {
        autoStatus.textContent = running
            ? `🚀 背景自動補齊進行中${s.current_id ? `（處理中：ID ${s.current_id}）` : "..."}`
            : `🏁 ${names[s.state] || s.state}`;
    }
    const autoCount = document.getElementById("autofillCountText");
    if (autoCount) {
        autoCount.textContent = `${s.processed} / ${s.total} (成功 ${s.ok}・失敗 ${s.failed.length}・略過 ${s.skipped || 0})`;
    }
    const autoBar = document.getElementById("autofillProgressBar");
    if (autoBar) autoBar.style.width = `${progressPercent}%`;

    const btnCancelAuto = document.getElementById("btnCancelAutoFill");
    if (btnCancelAuto) btnCancelAuto.classList.toggle("hidden", !running);

    const autoDetail = document.getElementById("autofillDetailText");
    if (autoDetail) {
        if (s.message) {
            autoDetail.textContent = s.message;
        } else if (s.failed.length > 0) {
            autoDetail.textContent = `失敗 ${s.failed.length} 筆：${s.failed.map(f => `ID ${f.id} (${f.reason})`).slice(0, 3).join(", ")}`;
        } else if (!running && s.ok === 0 && s.skipped > 0) {
            autoDetail.textContent = `此 ${s.skipped} 筆草稿皆已有完整答案（無須補齊），可直接勾選後點右下角「✅ 批量核准」發布。`;
        } else {
            autoDetail.textContent = "";
        }
    }
}

async function pollBatchGenerate(silent) {
    clearTimeout(batchGen.timer);
    let s;
    try {
        const resp = await fetch("/api/v1/admin/review/batch-generate/status", { headers: getAuthHeaders() });
        if (!resp.ok) return;
        s = await resp.json();
    } catch (e) { return; }
    renderBatchGenPanel(s);
    if (s.state === "running") {
        batchGen.lastState = "running";
        batchGen.timer = setTimeout(() => pollBatchGenerate(false), 3000);
        return;
    }
    if (batchGen.lastState === "running" && s.state !== "idle") {
        batchGen.lastState = s.state;
        const reviewView = document.getElementById("reviewView");
        if (s.ok > 0) {
            // 有新生成的項目：切到「AI 生成待確認」，方便最後一起審
            if (reviewView) reviewView.value = "ai";
        } else if (reviewView && reviewView.value === "ai") {
            // 0 成功（例如全數略過）：切回「全部」，避免因「AI 生成待確認」為空導致畫面全部消失
            reviewView.value = "all";
        }
        await loadReviewFaqs();
        loadDashboardSummary();
        if (s.ok === 0 && s.skipped > 0 && s.failed.length === 0) {
            showToast(`所選 ${s.skipped} 筆草稿皆已有完整答案（略過 ${s.skipped} 筆），請直接勾選並按「✅ 批量核准」發布`, "info");
        } else {
            showToast(
                `${s.state === "done" ? "批量補齊完成" : "批量補齊結束"}：成功 ${s.ok}、失敗 ${s.failed.length}、略過 ${s.skipped || 0}。` +
                (s.ok > 0 ? "已切換到「AI 生成待確認」，請逐筆檢視後批量核准" : ""),
                s.failed.length ? "info" : "success"
            );
        }
    }
}

function removeCard(id) {
    const entry = reviewState.cards.get(id);
    if (!entry) return;
    entry.card.classList.add("leaving");
    setTimeout(() => entry.card.remove(), 180);
    reviewState.cards.delete(id);
    reviewState.selected.delete(id);
}

async function processReview(faqId, action) {
    try {
        const resp = await fetch(`/api/v1/admin/review/faqs/${faqId}/${action}`, {
            method: "POST",
            headers: getAuthHeaders(),
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            removeCard(faqId);
            syncSelectionUi();
            loadDashboardSummary();
        } else {
            showToast(apiErrorText(data, "操作失敗"), "error");
        }
    } catch (e) {
        console.error("審核操作網路異常:", e);
        showToast("審核操作網路異常", "error");
    }
}

async function runBatch(action) {
    if (reviewState.busy) return;
    const ids = Array.from(reviewState.selected);
    if (ids.length === 0) return;
    const label = action === "approve" ? "核准發布" : "駁回";
    if (!window.confirm(`確定要批量${label}所選的 ${ids.length} 筆草稿嗎？`)) return;
    reviewState.busy = true;
    document.getElementById("btnBatchApprove").disabled = true;
    document.getElementById("btnBatchReject").disabled = true;
    let ok = 0, failed = 0;
    const reasons = new Set();
    try {
        for (let k = 0; k < ids.length; k += 100) {   // 後端單次上限 100 筆
            const chunk = ids.slice(k, k + 100);
            const resp = await fetch("/api/v1/admin/review/batch", {
                method: "POST",
                headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
                body: JSON.stringify({ action, faq_ids: chunk }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                showToast(`批量${label}失敗：${apiErrorText(data, "格式不正確")}`, "error");
                failed += chunk.length;
                continue;
            }
            ok += data.success_count || 0;
            failed += data.failed_count || 0;
            (data.processed_ids || []).forEach(removeCard);
            Object.values(data.failed_reasons || {}).forEach(r => reasons.add(String(r).split(":")[0]));
        }
    } catch (e) {
        console.error("審核操作網路異常:", e);
        showToast("審核操作網路異常", "error");
    } finally {
        reviewState.busy = false;
        document.getElementById("btnBatchApprove").disabled = false;
        document.getElementById("btnBatchReject").disabled = false;
        syncSelectionUi();
        loadDashboardSummary();
    }
    const tail = failed ? `；${failed} 筆未通過（${Array.from(reasons).join("、") || "請逐筆檢視"}），仍保留於清單` : "";
    showToast(`批量${label}完成：成功 ${ok} 筆${tail}`, failed ? "info" : "success");
}

// 5. 文件拖曳上傳
// 上傳佇列（支援多選檔案、整個資料夾、拖曳資料夾；逐檔送出，各檔獨立回報）
const UPLOAD_EXTS = [".docx", ".xlsx", ".pdf"];
const UPLOAD_MAX_BYTES = 15 * 1024 * 1024;
const UPLOAD_MAX_FILES = 200;
const uploadState = { queue: [], busy: false };

function fileStem(name) {
    const base = name.split("/").pop();
    const dot = base.lastIndexOf(".");
    return (dot > 0 ? base.slice(0, dot) : base).toLowerCase();
}

// Plan 24-03 純輔助函式（純資料轉換，不在載入時存取 DOM）
function uploadNameFieldState(queueLength, fileStem) {
    if (queueLength === 1) {
        return { readOnly: false, prefill: fileStem || null, hint: "" };
    }
    if (queueLength > 1) {
        return { readOnly: true, prefill: null, hint: "多檔將自動以檔名命名" };
    }
    return { readOnly: false, prefill: null, hint: "" };
}

function uploadNameForSubmit(queueLength, nameValue) {
    if (queueLength === 1) {
        const trimmed = (nameValue || "").trim();
        return trimmed ? trimmed : null;
    }
    return null;
}

function pickUniqueStemEntries(existingStems, incomingStems) {
    const existingSet = new Set((existingStems || []).map(s => (s || "").toLowerCase()));
    const seen = new Set();
    const result = [];
    for (const stem of (incomingStems || [])) {
        const lower = (stem || "").toLowerCase();
        if (existingSet.has(lower)) {
            continue;
        }
        if (!seen.has(lower)) {
            seen.add(lower);
            result.push(stem);
        }
    }
    return result;
}

function missingFieldsLabels(keys) {
    const mapping = {
        address: "地址",
        phone: "電話",
        business_hours: "營業時間",
        doctors: "醫師",
    };
    const labels = [];
    for (const k of (keys || [])) {
        if (mapping[k]) {
            labels.push(mapping[k]);
        }
    }
    return labels;
}

function uploadDetailText(data, fallback) {
    if (data && typeof data === "object" && typeof data.detail === "string") {
        return data.detail;
    }
    return fallback;
}

function updateUploadNameOnQueueChange() {
    const nameInput = document.getElementById("uploadName");
    const nameHint = document.getElementById("uploadNameHint");
    if (!nameInput || !nameHint) return;
    const sourceMode = document.querySelector("input[name=uploadSource]:checked")?.value || "file";
    if (sourceMode === "url") return;
    const valid = uploadState.queue.filter(q => q.status !== "skip");
    const firstStem = valid.length > 0 ? fileStem(valid[0].path) : null;
    const st = uploadNameFieldState(valid.length, firstStem);
    nameInput.readOnly = st.readOnly;
    if (st.prefill && !nameInput.value.trim()) {
        nameInput.value = st.prefill;
    }
    nameHint.textContent = st.hint;
}

function addUploadFiles(entries) {
    // entries: [{file, path}]
    let skippedType = 0;
    entries.forEach(({ file, path }) => {
        const name = file.name || "";
        const lower = name.toLowerCase();
        if (name.startsWith("~$") || name.startsWith(".")) { return; }          // Office 暫存鎖檔、隱藏檔
        if (!UPLOAD_EXTS.some(ext => lower.endsWith(ext))) { skippedType++; return; }
        if (uploadState.queue.length >= UPLOAD_MAX_FILES) { return; }
        const item = { file, path: path || name, status: "wait", note: "" };
        if (file.size > UPLOAD_MAX_BYTES) { item.status = "skip"; item.note = "超過 15MB"; }
        else if (file.size === 0) { item.status = "skip"; item.note = "檔案為空"; }
        else if (uploadState.queue.some(q => q.path === item.path && q.file.size === file.size)) { return; }
        else if (uploadState.queue.some(q => q.status !== "skip" && fileStem(q.path) === fileStem(item.path))) {
            // 後端以檔名（不含副檔名）作為主題鍵，同名檔會互相覆蓋，故只收第一個
            item.status = "skip"; item.note = "檔名重複（後端以檔名為主題鍵，會互相覆蓋）";
        }
        uploadState.queue.push(item);
    });
    if (skippedType > 0) showToast(`已略過 ${skippedType} 個非 .docx／.xlsx／.pdf 的檔案`, "info");
    if (uploadState.queue.length >= UPLOAD_MAX_FILES) showToast(`清單上限 ${UPLOAD_MAX_FILES} 個檔案，其餘未加入`, "info");
    renderUploadQueue();
    updateUploadNameOnQueueChange();
}

function renderUploadQueue() {
    const box = document.getElementById("uploadQueue");
    const labels = { wait: "待上傳", busy: "處理中", ok: "完成", err: "失敗", skip: "略過" };
    const cls = { wait: "badge-id", busy: "badge-llm", ok: "badge-ai", err: "badge-warn", skip: "badge-upload" };
    box.replaceChildren();
    uploadState.queue.forEach(item => {
        const row = el("div", "upload-row");
        const st = badge(labels[item.status], cls[item.status]);
        if (item.status === "busy") st.prepend(el("span", "spinner"), document.createTextNode(" "));
        row.appendChild(st);
        row.appendChild(el("span", "upload-name", item.path));
        row.appendChild(el("span", "upload-size", `${(item.file.size / 1024).toFixed(0)} KB`));
        if (item.note) row.appendChild(el("span", "upload-note", item.note));
        box.appendChild(row);
    });
    const ready = uploadState.queue.filter(q => q.status === "wait").length;
    const ok = uploadState.queue.filter(q => q.status === "ok").length;
    const err = uploadState.queue.filter(q => q.status === "err").length;
    const skip = uploadState.queue.filter(q => q.status === "skip").length;
    document.getElementById("uploadSummary").textContent = uploadState.queue.length === 0
        ? "尚未加入檔案"
        : `共 ${uploadState.queue.length} 個：待上傳 ${ready}・完成 ${ok}・失敗 ${err}・略過 ${skip}`;
}

// 遞迴讀取拖曳進來的資料夾（readEntries 一次最多回 100 筆，需迴圈讀到空為止）
function readAllEntries(reader) {
    return new Promise((resolve, reject) => {
        const all = [];
        const pump = () => reader.readEntries(batch => {
            if (batch.length === 0) resolve(all);
            else { all.push(...batch); pump(); }
        }, reject);
        pump();
    });
}

async function collectFromEntry(entry, out) {
    if (entry.isFile) {
        const file = await new Promise((res, rej) => entry.file(res, rej));
        out.push({ file, path: entry.fullPath.replace(/^\//, "") });
    } else if (entry.isDirectory) {
        const children = await readAllEntries(entry.createReader());
        for (const child of children) {
            if (out.length >= UPLOAD_MAX_FILES * 3) return;   // 防止誤拖超大目錄
            await collectFromEntry(child, out);
        }
    }
}

function initUploadSection() {
    const dropZone = document.getElementById("dropZone");
    const fileInput = document.getElementById("fileInput");
    const folderInput = document.getElementById("folderInput");
    const form = document.getElementById("uploadForm");
    const sourceRadios = document.querySelectorAll("input[name=uploadSource]");
    const fileArea = document.getElementById("fileSourceArea");
    const urlArea = document.getElementById("urlSourceField");
    const uploadNameInput = document.getElementById("uploadName");
    const uploadUrlInput = document.getElementById("uploadUrl");
    const uploadNameHint = document.getElementById("uploadNameHint");

    function updateSourceMode() {
        const mode = document.querySelector("input[name=uploadSource]:checked")?.value || "file";
        if (mode === "url") {
            if (fileArea) fileArea.classList.add("hidden");
            if (urlArea) urlArea.classList.remove("hidden");
            if (uploadNameInput) {
                uploadNameInput.required = true;
                uploadNameInput.readOnly = false;
            }
            if (uploadNameHint) uploadNameHint.textContent = "";
        } else {
            if (urlArea) urlArea.classList.add("hidden");
            if (fileArea) fileArea.classList.remove("hidden");
            if (uploadNameInput) {
                uploadNameInput.required = false;
            }
            updateUploadNameOnQueueChange();
        }
    }

    sourceRadios.forEach(radio => radio.addEventListener("change", updateSourceMode));

    const targetRadios = document.querySelectorAll("input[name=uploadTarget]");
    const urlRadio = document.querySelector("input[name=uploadSource][value=url]");
    const urlRadioLabel = urlRadio?.parentElement?.querySelector("span");

    function updateTargetMode() {
        const target = document.querySelector("input[name=uploadTarget]:checked")?.value;
        const treeField = document.getElementById("treeTitleField");
        if (target === "tree") {
            if (treeField) treeField.classList.remove("hidden");
            if (urlRadio) urlRadio.disabled = true;
            if (urlRadioLabel) urlRadioLabel.textContent = "網站解析（僅支援 FAQ 草稿）";
            const currentSource = document.querySelector("input[name=uploadSource]:checked")?.value;
            if (currentSource === "url") {
                const fileRadio = document.querySelector("input[name=uploadSource][value=file]");
                if (fileRadio) {
                    fileRadio.checked = true;
                    updateSourceMode();
                }
            }
        } else {
            if (treeField) treeField.classList.add("hidden");
            if (urlRadio) urlRadio.disabled = false;
            if (urlRadioLabel) urlRadioLabel.textContent = "網站解析（貼入網址）";
        }
    }

    targetRadios.forEach(radio => radio.addEventListener("change", updateTargetMode));

    dropZone.addEventListener("click", () => fileInput.click());
    document.getElementById("btnPickFolder").addEventListener("click", () => folderInput.click());
    document.getElementById("btnClearQueue").addEventListener("click", () => {
        if (uploadState.busy) return;
        uploadState.queue = [];
        document.getElementById("uploadResultArea").classList.add("hidden");
        renderUploadQueue();
        if (uploadNameInput && uploadNameHint) {
            const st = uploadNameFieldState(0, null);
            uploadNameInput.readOnly = st.readOnly;
            uploadNameHint.textContent = st.hint;
        }
    });

    fileInput.addEventListener("change", () => {
        addUploadFiles(Array.from(fileInput.files).map(f => ({ file: f, path: f.name })));
        fileInput.value = "";
    });
    folderInput.addEventListener("change", () => {
        addUploadFiles(Array.from(folderInput.files).map(f => ({ file: f, path: f.webkitRelativePath || f.name })));
        folderInput.value = "";
    });

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("border-indigo-500", "bg-indigo-50");
    });
    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("border-indigo-500", "bg-indigo-50");
    });
    dropZone.addEventListener("drop", async (e) => {
        e.preventDefault();
        dropZone.classList.remove("border-indigo-500", "bg-indigo-50");
        // webkitGetAsEntry 必須在事件處理器同步階段取得，之後才能非同步遞迴
        const items = Array.from(e.dataTransfer.items || []);
        const entries = items.map(it => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null)).filter(Boolean);
        const plainFiles = Array.from(e.dataTransfer.files || []);
        try {
            const collected = [];
            if (entries.length > 0) {
                for (const entry of entries) await collectFromEntry(entry, collected);
            } else {
                plainFiles.forEach(f => collected.push({ file: f, path: f.name }));
            }
            addUploadFiles(collected);
        } catch (err) {
            showToast("讀取拖曳內容失敗，請改用「選擇資料夾」按鈕", "error");
        }
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (uploadState.busy) return;

        const sourceMode = document.querySelector("input[name=uploadSource]:checked")?.value || "file";
        if (sourceMode === "url") {
            const urlVal = uploadUrlInput ? uploadUrlInput.value.trim() : "";
            const nameVal = uploadNameInput ? uploadNameInput.value.trim() : "";
            if (!urlVal) {
                showToast("請輸入要解析的網站網址", "error");
                return;
            }
            if (!nameVal) {
                showToast("網站解析模式必須填寫名稱", "error");
                return;
            }
            const clinicId = document.getElementById("uploadClinicId").value.trim();
            const preview = document.getElementById("chkPreviewOnly").checked;
            const btn = document.getElementById("btnSubmitUpload");
            const resultArea = document.getElementById("uploadResultArea");
            const resultContent = document.getElementById("uploadResultContent");

            uploadState.busy = true;
            btn.disabled = true;
            btn.textContent = "網址解析與萃取中…";
            resultArea.classList.remove("hidden");
            resultContent.textContent = "正在連線網站並解析內容，請稍候…";

            const formData = new FormData();
            formData.append("url", urlVal);
            formData.append("clinic_id", clinicId);
            formData.append("name", nameVal);
            formData.append("target", "faq");
            formData.append("preview_only", preview ? "true" : "false");

            try {
                const resp = await fetch("/api/v1/admin/upload-url", {
                    method: "POST",
                    headers: getAuthHeaders(),
                    body: formData,
                });
                const data = await resp.json().catch(() => ({}));
                if (resp.ok) {
                    const lines = [];
                    lines.push(`✅ 網站解析成功：${nameVal}`);
                    if (data.source_url) {
                        lines.push(`來源網址：${data.source_url}`);
                    }
                    if (Array.isArray(data.missing_fields) && data.missing_fields.length > 0) {
                        const labels = missingFieldsLabels(data.missing_fields);
                        if (labels.length > 0) {
                            lines.push(`⚠️ 解析不完整：缺少 ${labels.join("、")}`);
                        }
                    }
                    if (preview) {
                        const count = Array.isArray(data.faqs_preview) ? data.faqs_preview.length : 0;
                        lines.push(`\n預覽生成 ${count} 筆 FAQ 草稿` + (data.rejected_paragraphs ? `，剔除 ${data.rejected_paragraphs} 段` : ""));
                        lines.push("（僅預覽模式，未寫入資料庫）");
                    } else {
                        lines.push(`\n已成功建立 ${data.total_faqs || 0} 筆 FAQ 草稿（新增 ${data.inserted || 0}、更新 ${data.updated || 0}）`);
                        if (data.rejected_paragraphs) {
                            lines.push(`剔除不合規段落 ${data.rejected_paragraphs} 段`);
                        }
                        lines.push("狀態：待醫師審核（pending）；請至「待審衛教草稿簽核」檢視");
                        loadDashboardSummary();
                    }
                    resultContent.textContent = lines.join("\n");
                    showToast(preview ? "網址預覽解析完成" : "網址草稿上傳成功，待審核", "success");
                } else {
                    const errDetail = uploadDetailText(data, "網站解析失敗，請稍後再試");
                    resultContent.textContent = `❌ 解析失敗：${errDetail} (HTTP ${resp.status})`;
                    showToast(`網站解析失敗：${errDetail}`, "error");
                }
            } catch (err) {
                resultContent.textContent = "❌ 連線失敗，無法連接伺服器";
                showToast("連線失敗，請檢查網路狀態", "error");
            } finally {
                uploadState.busy = false;
                btn.disabled = false;
                btn.textContent = "開始上傳與解析";
            }
            return;
        }

        const todo = uploadState.queue.filter(q => q.status === "wait" || q.status === "err");
        if (todo.length === 0) {
            showToast("清單中沒有可上傳的檔案，請先選擇或拖曳檔案／資料夾", "error");
            return;
        }
        const clinicId = document.getElementById("uploadClinicId").value.trim();
        const preview = document.getElementById("chkPreviewOnly").checked;
        const btn = document.getElementById("btnSubmitUpload");
        const resultArea = document.getElementById("uploadResultArea");
        const resultContent = document.getElementById("uploadResultContent");
        uploadState.busy = true;
        btn.disabled = true;
        resultArea.classList.remove("hidden");
        resultContent.textContent = "";
        const lines = [];
        let inserted = 0, rejected = 0, okCount = 0, errCount = 0;

        for (const item of todo) {
            item.status = "busy"; item.note = "";
            renderUploadQueue();
            btn.textContent = `上傳與解析中… (${okCount + errCount + 1}/${todo.length})`;
            const formData = new FormData();
            formData.append("file", item.file);
            formData.append("clinic_id", clinicId);
            formData.append("preview_only", preview ? "true" : "false");
            const nameToSubmit = uploadNameForSubmit(todo.length, uploadNameInput ? uploadNameInput.value : "");
            if (nameToSubmit) {
                formData.append("name", nameToSubmit);
            }
            try {
                const resp = await fetch("/api/v1/admin/upload", { method: "POST", headers: getAuthHeaders(), body: formData });
                const data = await resp.json().catch(() => ({}));
                if (resp.ok) {
                    item.status = "ok";
                    const n = preview ? (data.faqs_preview || []).length : (data.total_faqs || 0);
                    inserted += preview ? 0 : (data.inserted || 0) + (data.updated || 0);
                    rejected += data.rejected_paragraphs || 0;
                    item.note = `${preview ? "預覽" : "草稿"} ${n} 段` + (data.rejected_paragraphs ? `，剔除 ${data.rejected_paragraphs} 段` : "");
                    okCount++;
                } else {
                    item.status = "err";
                    item.note = typeof data.detail === "string" ? data.detail : `HTTP ${resp.status}`;
                    errCount++;
                }
            } catch (err) {
                item.status = "err"; item.note = "連線失敗"; errCount++;
            }
            lines.push(`${item.status === "ok" ? "✅" : "❌"} ${item.path} — ${item.note}`);
            resultContent.textContent = lines.join("\n");
            renderUploadQueue();
        }

        resultContent.textContent = lines.join("\n") +
            `\n\n合計：成功 ${okCount} 個、失敗 ${errCount} 個` +
            (preview ? "（僅預覽，未寫入資料庫）" : `；新增／更新草稿 ${inserted} 筆，剔除 ${rejected} 段；請至「待審衛教草稿簽核」檢視`);
        uploadState.busy = false;
        btn.disabled = false;
        btn.textContent = "開始上傳與解析";
        if (!preview) loadDashboardSummary();
        showToast(`上傳完成：成功 ${okCount}、失敗 ${errCount}`, errCount ? "info" : "success");
    });
    renderUploadQueue();
}

// 6. SOAP 瀏覽
function initSoapSection() {
    document.getElementById("btnSearchSoap").addEventListener("click", loadSoapRecords);
}

async function loadSoapRecords() {
    const container = document.getElementById("soapRecordsContainer");
    const keyword = document.getElementById("soapSearchKeyword").value.trim();
    container.innerHTML = '<div class="text-center py-8 text-gray-500">載入 SOAP 紀錄中...</div>';

    if (!keyword) {
        container.innerHTML = '<div class="text-center py-8 text-gray-500">請輸入診斷或主訴關鍵字後查詢。</div>';
        return;
    }
    const clinicId = document.getElementById("soapClinicId").value.trim();

    try {
        // SOAP 檢索為 POST，且需管理者金鑰；問句置於請求主體
        const resp = await fetch("/api/v1/soap/search", {
            method: "POST",
            headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
            body: JSON.stringify({ query: keyword, clinic_id: clinicId, limit: 20 })
        });
        if (!resp.ok) {
            container.innerHTML = '<div class="text-center py-8 text-gray-500">尚無 SOAP 紀錄或查詢失敗（請確認 API Key 與機構代碼）</div>';
            return;
        }
        const data = await resp.json();
        const records = data.records || data.results || [];

        if (records.length === 0) {
            container.innerHTML = '<div class="text-center py-12 text-gray-500 bg-white rounded-lg border border-gray-200">查無相符之 SOAP 紀錄。</div>';
            return;
        }

        container.innerHTML = "";
        records.forEach(r => {
            const card = document.createElement("div");
            card.className = "bg-white p-5 rounded-lg shadow-sm border border-gray-200 text-sm space-y-2";

            const title = document.createElement("div");
            title.className = "font-bold text-indigo-900 border-b pb-1 flex justify-between";
            const extId = document.createElement("span");
            extId.textContent = `病歷 ID: ${r.external_id || r.id}`;
            const diag = document.createElement("span");
            diag.className = "text-gray-500 font-normal";
            diag.textContent = `診斷: ${r.assessment || "未詳細註明"}`;
            title.appendChild(extId);
            title.appendChild(diag);
            card.appendChild(title);

            const sPart = document.createElement("div");
            sPart.textContent = `S (主訴): ${r.subjective || "--"}`;
            card.appendChild(sPart);

            const oPart = document.createElement("div");
            oPart.textContent = `O (客觀): ${r.objective || "--"}`;
            card.appendChild(oPart);

            const aPart = document.createElement("div");
            aPart.textContent = `A (評估): ${r.assessment || "--"}`;
            card.appendChild(aPart);

            const pPart = document.createElement("div");
            pPart.textContent = `P (計畫): ${r.plan || "--"}`;
            card.appendChild(pPart);

            container.appendChild(card);
        });
    } catch (e) {
        container.innerHTML = '<div class="text-center py-8 text-red-500">連線失敗</div>';
    }
}


// 7. 向 LLM 提問（Phase 20）— 所有文字一律 textContent，不拼接 HTML
const askState = { history: [], busy: false };
const ASK_EXAMPLES = [
    "海芙音波拉提術後要注意什麼？",
    "甲溝炎要怎麼照護？",
    "Endolift與其他非手術治療眼袋有何不同？",
    "診所的營業時間是什麼時候？",
    "高血壓可以喝咖啡嗎？",
];

function initAskSection() {
    const box = document.getElementById("askExamples");
    ASK_EXAMPLES.forEach(q => {
        const chip = el("button", "ask-chip", q);
        chip.type = "button";
        chip.addEventListener("click", () => { document.getElementById("askQuestion").value = q; });
        box.appendChild(chip);
    });
    document.getElementById("btnAsk").addEventListener("click", submitAsk);
    document.getElementById("askQuestion").addEventListener("keydown", (ev) => {
        if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") submitAsk();
    });
}

// 目前顯示中的提問動畫播放器停止函式；每次重繪前先停掉，避免舊的 rAF 迴圈殘留
let askVisualStop = null;

// 播放回答所引用的已核准動畫（僅 textContent 寫入；場景資料來自後端已整形的公開結構）
function buildAskVisualPlayer(visual) {
    const wrap = el("div", "ask-visual");
    wrap.appendChild(el("div", "ask-visual-title", `🎬 引用動畫解說：${visual.title || visual.topic_key || ""}`));

    const scenes = Array.isArray(visual.scenes) ? visual.scenes : [];
    if (scenes.length === 0 || !window.ClinicVisual || typeof window.ClinicVisual.mount !== "function") {
        wrap.appendChild(el("div", "ask-src-empty", "動畫引擎無法載入，已略過動畫播放。"));
        return wrap;
    }

    const playerBox = el("div", "visual-review-player");
    const svgEl = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svgEl.setAttribute("viewBox", "0 0 800 510");
    svgEl.classList.add("visual-review-svg");
    playerBox.appendChild(svgEl);

    const controls = el("div", "visual-review-controls");
    const btnPlay = el("button", "btn-visual-play px-3 py-1 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium rounded transition", "▶ 播放");
    const scrubber = document.createElement("input");
    scrubber.type = "range";
    scrubber.min = "0";
    scrubber.max = "1000";
    scrubber.value = "0";
    scrubber.className = "visual-review-scrubber";
    const timeDisplay = el("span", "text-xs text-gray-300 font-mono select-none", "0.0s / 0.0s");
    controls.appendChild(btnPlay);
    controls.appendChild(scrubber);
    controls.appendChild(timeDisplay);
    playerBox.appendChild(controls);
    wrap.appendChild(playerBox);

    const captionEl = el("p", "ask-visual-caption", "");
    wrap.appendChild(captionEl);

    let ctrl = null;
    try {
        ctrl = window.ClinicVisual.mount(svgEl, scenes);
    } catch (err) {
        console.error("ClinicVisual.mount 失敗", err);
    }
    if (!ctrl) {
        wrap.appendChild(el("div", "ask-src-empty", "動畫渲染失敗，已略過動畫播放。"));
        return wrap;
    }

    const totalDur = ctrl.totalDuration;
    let isPlaying = false;
    let animId = null;
    let lastTs = null;
    let currentT = 0;

    function stopPlayback() {
        isPlaying = false;
        btnPlay.textContent = "▶ 播放";
        if (animId) cancelAnimationFrame(animId);
        animId = null;
        lastTs = null;
    }

    function renderFrame(t) {
        currentT = Math.max(0, Math.min(t, totalDur));
        const safeT = Math.min(currentT, Math.max(0, totalDur - 0.001));
        ctrl.renderAt(safeT);
        scrubber.value = String(Math.floor((currentT / Math.max(0.001, totalDur)) * 1000));
        timeDisplay.textContent = `${currentT.toFixed(1)}s / ${totalDur.toFixed(1)}s`;
        const idx = ctrl.sceneIndexAt(safeT);
        const sc = scenes[idx] || {};
        captionEl.textContent = `場景 ${idx + 1}：${sc.title || ""}｜${sc.caption || ""}`;
    }

    function animStep(ts) {
        if (!isPlaying) return;
        if (lastTs === null) lastTs = ts;
        currentT += (ts - lastTs) / 1000;
        lastTs = ts;
        if (currentT >= totalDur) currentT = 0;
        renderFrame(currentT);
        animId = requestAnimationFrame(animStep);
    }

    btnPlay.addEventListener("click", () => {
        if (isPlaying) {
            stopPlayback();
            return;
        }
        isPlaying = true;
        btnPlay.textContent = "⏸ 暫停";
        lastTs = null;
        animId = requestAnimationFrame(animStep);
    });

    scrubber.addEventListener("input", () => {
        stopPlayback();
        renderFrame((parseFloat(scrubber.value) || 0) / 1000 * totalDur);
    });

    askVisualStop = stopPlayback;
    renderFrame(0);
    return wrap;
}

function renderAskResult(data, container) {
    if (askVisualStop) {
        askVisualStop();
        askVisualStop = null;
    }
    container.replaceChildren();
    const head = el("div", "ask-head");
    const modeText = { answered: "依據系統資料作答", no_evidence: "資料中沒有相關內容（未呼叫模型）", red_flag: "急重症紅旗（未呼叫模型）" }[data.mode] || data.mode;
    head.appendChild(badge(modeText, data.mode === "answered" ? "badge-ai" : data.mode === "red_flag" ? "badge-warn" : "badge-id"));
    if (data.used_llm) {
        const c = data.compliance || {};
        head.appendChild(badge(c.ok ? "✅ 通過合規檢視" : "⚠️ 合規檢視未通過", c.ok ? "badge-ai" : "badge-warn"));
    }
    container.appendChild(head);
    container.appendChild(el("div", "ask-q", `【問】${data.question}`));

    // 結構化段落呈現：依段落分拆，針對【標題】加上專屬樣式標籤
    const ansWrap = el("div", "faq-answer ask-answer-structured");
    const paragraphs = (data.answer || "").split(/\n+/).map(p => p.trim()).filter(Boolean);
    if (paragraphs.length === 0) {
        ansWrap.textContent = data.answer || "";
    } else {
        paragraphs.forEach(pText => {
            const pEl = el("p", "ask-para");
            const match = pText.match(/^(【[^】]+】)(.*)$/s);
            if (match) {
                pEl.appendChild(el("span", "ask-section-tag", match[1]));
                if (match[2].trim()) {
                    pEl.appendChild(document.createTextNode(" " + match[2].trim()));
                }
            } else {
                pEl.textContent = pText;
            }
            ansWrap.appendChild(pEl);
        });
    }
    container.appendChild(ansWrap);

    if (data.compliance && !data.compliance.ok) {
        container.appendChild(el("div", "ask-warn", `合規檢視原因：${data.compliance.reason}（此為管理端檢視，對外端點不會輸出此內容）`));
    }
    // 回答所引用推理樹之已核准動畫（後端已依引用來源過濾，無則不顯示）
    (Array.isArray(data.visuals) ? data.visuals : []).forEach(v => {
        container.appendChild(buildAskVisualPlayer(v));
    });
    const srcTitle = el("div", "ask-src-title", `模型可見的資料來源（${(data.sources || []).length} 筆）`);
    container.appendChild(srcTitle);
    if (!data.sources || data.sources.length === 0) {
        container.appendChild(el("div", "ask-src-empty", "無（此問題在已核准資料中找不到相關內容）"));
    } else {
        const ul = el("ul", "ask-src-list ask-src-grid");
        data.sources.forEach(s => {
            const li = el("li", "ask-src-item");
            li.appendChild(badge(s.ref, "badge-id"));
            const typeLabel = ({ faq: "常見問答", tree: "臨床推理樹", note: "診所備註", clinic_info: "診所資料" })[s.type] || s.type;
            const desc = el("span", "ask-src-desc", ` ${typeLabel}・${s.level}：${s.title}`);
            li.appendChild(desc);
            ul.appendChild(li);
        });
        container.appendChild(ul);
    }
    container.classList.remove("hidden");
}

function renderAskHistory() {
    const box = document.getElementById("askHistory");
    if (askState.history.length === 0) return;
    box.replaceChildren();
    askState.history.slice().reverse().forEach(item => {
        const d = el("details", "ask-hist-item");
        d.appendChild(el("summary", "", `${item.question}（${item.mode === "answered" ? "已作答" : item.mode === "red_flag" ? "紅旗" : "無資料"}）`));
        const inner = el("div", "ask-hist-body");
        renderAskResult(item, inner);
        d.appendChild(inner);
        box.appendChild(d);
    });
}

async function submitAsk() {
    if (askState.busy) return;
    const question = document.getElementById("askQuestion").value.trim();
    const clinicId = document.getElementById("askClinicId").value.trim();
    const result = document.getElementById("askResult");
    const btn = document.getElementById("btnAsk");
    if (!question) { showToast("請先輸入問題", "error"); return; }
    askState.busy = true;
    btn.disabled = true;
    btn.replaceChildren(el("span", "spinner"), document.createTextNode(" 本機模型思考中（約 1～3 分鐘）"));
    result.classList.add("hidden");
    try {
        const resp = await fetch("/api/v1/admin/ask", {
            method: "POST",
            headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
            body: JSON.stringify({ question, clinic_id: clinicId }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            showToast(`提問失敗：${typeof data.detail === "string" ? data.detail : "格式不正確"}`, "error");
            return;
        }
        renderAskResult(data, result);
        if (data.mode === "no_evidence") autoGeneralDraft(data.question, result);
        askState.history.push(data);
        renderAskHistory();
    } catch (e) {
        console.error("submitAsk 網路請求異常:", e);
        showToast("網路請求失敗", "error");
    } finally {
        askState.busy = false;
        btn.disabled = false;
        btn.textContent = "💬 送出提問";
    }
}

// =============================================================================
// Phase 21: 臨床決策推理樹簽核與管理前端邏輯
// =============================================================================

function initTreesSection() {
    const btnRefresh = document.getElementById("btnRefreshTrees");
    if (btnRefresh) btnRefresh.addEventListener("click", loadTrees);

    const selStatus = document.getElementById("treesFilterStatus");
    if (selStatus) selStatus.addEventListener("change", loadTrees);

    const selCat = document.getElementById("treesFilterCategory");
    if (selCat) selCat.addEventListener("change", loadTrees);

    const btnCancelModal = document.getElementById("btnCancelTreeModal");
    if (btnCancelModal) {
        btnCancelModal.addEventListener("click", () => {
            document.getElementById("treeEditModal").classList.add("hidden");
        });
    }

    const editForm = document.getElementById("treeEditForm");
    if (editForm) {
        editForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const treeId = document.getElementById("treeEditId").value;
            const payload = {
                title: document.getElementById("treeEditTitle").value.trim(),
                pre_op: document.getElementById("treeEditPreOp").value.trim(),
                pre_op_physician_notes: document.getElementById("treeEditPreOpNotes").value.trim() || null,
                procedure: document.getElementById("treeEditProcedure").value.trim(),
                procedure_physician_notes: document.getElementById("treeEditProcedureNotes").value.trim() || null,
                post_op_short: document.getElementById("treeEditPostOp").value.trim(),
                post_op_short_physician_notes: document.getElementById("treeEditPostOpNotes").value.trim() || null,
                maintenance: document.getElementById("treeEditMaintenance").value.trim(),
                maintenance_physician_notes: document.getElementById("treeEditMaintenanceNotes").value.trim() || null,
                summary_text: document.getElementById("treeEditSummary").value.trim(),
            };

            try {
                const resp = await fetch(`/api/v1/admin/trees/${treeId}`, {
                    method: "PUT",
                    headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) {
                    showToast(`更新失敗：${data.detail || "格式錯誤"}`, "error");
                    return;
                }
                document.getElementById("treeEditModal").classList.add("hidden");
                showToast("推理樹內容與醫師醫囑已成功更新", "success");
                loadTrees();
            } catch (err) {
                showToast("網路連線失敗", "error");
            }
        });
    }

    // 上傳目標單選切換
    const targetRadios = document.querySelectorAll('input[name="uploadTarget"]');
    targetRadios.forEach(r => {
        r.addEventListener("change", (e) => {
            const isTree = e.target.value === "tree";
            const field = document.getElementById("treeTitleField");
            if (field) field.classList.toggle("hidden", !isTree);
        });
    });
}

async function loadTrees() {
    const container = document.getElementById("treesContainer");
    if (!container) return;
    container.replaceChildren(el("div", "skeleton"), el("div", "skeleton"));

    const status = document.getElementById("treesFilterStatus").value;
    const category = document.getElementById("treesFilterCategory").value;

    const clinic = document.getElementById("treesFilterClinic").value;

    let url = `/api/v1/admin/trees?status=${encodeURIComponent(status)}&limit=100`;
    if (clinic) url += `&clinic_id=${encodeURIComponent(clinic)}`;
    if (category) url += `&category=${encodeURIComponent(category)}`;

    try {
        const resp = await fetch(url, { headers: getAuthHeaders() });
        if (!resp.ok) {
            setStatusBox(container, `無法載入推理樹列表 (HTTP ${resp.status})，請確認 API Key`, "error");
            return;
        }
        const data = await resp.json();
        const trees = data.trees || [];
        if (trees.length === 0) {
            setStatusBox(container, "🌱 目前無相符之臨床決策推理樹草稿。", "empty");
            return;
        }
        container.replaceChildren();
        trees.forEach(tree => {
            container.appendChild(createTreeCard(tree));
        });
    } catch (e) {
        setStatusBox(container, "連線失敗，請檢查網路或服務狀態", "error");
    }
}

function createTreeCard(tree) {
    const card = el("div", "tree-card");

    // Header
    const head = el("div", "tree-card-header");
    const titleBox = el("div", "tree-card-title");
    titleBox.appendChild(document.createTextNode(tree.title || tree.doc_id));
    titleBox.appendChild(el("span", "tree-card-slug", tree.doc_id));

    const statusMap = {
        pending: { text: "⏳ 待審核", cls: "bg-amber-100 text-amber-800" },
        approved: { text: "✅ 已發布", cls: "bg-green-100 text-green-800" },
        rejected: { text: "❌ 已駁回", cls: "bg-rose-100 text-rose-800" },
    };
    const st = statusMap[tree.review_status] || { text: tree.review_status, cls: "bg-gray-100 text-gray-800" };
    const badge = el("span", `text-xs px-2.5 py-1 rounded-full font-bold ${st.cls}`, st.text);

    head.appendChild(titleBox);
    head.appendChild(badge);
    card.appendChild(head);

    // 4 Sections Grid
    const grid = el("div", "tree-sections-grid");

    const sections = [
        { name: "1. 術前評估 (Pre-Op)", content: tree.pre_op, notes: tree.pre_op_physician_notes },
        { name: "2. 療程原理 (Procedure)", content: tree.procedure, notes: tree.procedure_physician_notes },
        { name: "3. 術後照護 (Post-Op Short)", content: tree.post_op_short, notes: tree.post_op_short_physician_notes },
        { name: "4. 長期維持 (Maintenance)", content: tree.maintenance, notes: tree.maintenance_physician_notes },
    ];

    sections.forEach(s => {
        const box = el("div", "tree-section-box");
        box.appendChild(el("div", "tree-section-name", s.name));
        box.appendChild(el("div", "tree-section-content", s.content || "（無內容）"));
        if (s.notes) {
            const noteEl = el("div", "tree-physician-note");
            noteEl.appendChild(el("div", "tree-physician-badge", "👨‍⚕️ 醫師特約指令"));
            noteEl.appendChild(document.createTextNode(s.notes));
            box.appendChild(noteEl);
        }
        grid.appendChild(box);
    });
    card.appendChild(grid);

    // Summary Box
    if (tree.summary_text) {
        const sumBox = el("div", "tree-summary-box");
        sumBox.appendChild(el("span", "font-bold text-gray-600 mr-2", "檢索摘要:"));
        sumBox.appendChild(document.createTextNode(tree.summary_text));
        card.appendChild(sumBox);
    }

    // Actions
    const actions = el("div", "tree-card-actions");

    const btnEdit = el("button", "btn btn-soft", "✏️ 編輯 / 填寫醫囑");
    btnEdit.addEventListener("click", () => openTreeEditModal(tree));
    actions.appendChild(btnEdit);

    if (tree.review_status !== "approved") {
        const btnApprove = el("button", "btn btn-success", "✅ 簽核發布");
        btnApprove.addEventListener("click", async () => {
            if (!confirm(`確定簽核並發布「${tree.title || tree.doc_id}」臨床決策樹嗎？發布後將立即納入 RAG 檢索。`)) return;
            try {
                const resp = await fetch(`/api/v1/admin/trees/${tree.id}/approve`, {
                    method: "POST",
                    headers: getAuthHeaders(),
                });
                if (resp.ok) {
                    const okData = await resp.json().catch(() => ({}));
                    showToast(okData.message || "簽核發布成功！", "success");
                    loadTrees();
                    loadDashboardSummary();
                    if (okData.auto_visual_drafting) {
                        setTimeout(() => loadVisuals(), 2500);
                    }
                } else {
                    const errData = await resp.json().catch(() => ({}));
                    showToast(apiErrorText(errData, "簽核失敗"), "error");
                }
            } catch (err) {
                showToast("連線異常", "error");
            }
        });
        actions.appendChild(btnApprove);
    }

    if (tree.review_status !== "rejected") {
        const btnReject = el("button", "btn btn-danger-soft", "❌ 駁回");
        btnReject.addEventListener("click", async () => {
            if (!confirm(`確定駁回「${tree.title || tree.doc_id}」草稿嗎？`)) return;
            try {
                const resp = await fetch(`/api/v1/admin/trees/${tree.id}/reject`, {
                    method: "POST",
                    headers: getAuthHeaders(),
                });
                if (resp.ok) {
                    showToast("已駁回該草稿", "info");
                    loadTrees();
                    loadDashboardSummary();
                } else {
                    const errData = await resp.json().catch(() => ({}));
                    showToast(apiErrorText(errData, "駁回失敗"), "error");
                }
            } catch (err) {
                showToast("連線異常", "error");
            }
        });
        actions.appendChild(btnReject);
    }

    card.appendChild(actions);
    return card;
}

function openTreeEditModal(tree) {
    document.getElementById("treeEditId").value = tree.id;
    document.getElementById("treeModalTitle").textContent = `編輯：${tree.title || tree.doc_id}`;
    document.getElementById("treeModalSlug").textContent = tree.doc_id;
    document.getElementById("treeEditTitle").value = tree.title || "";
    document.getElementById("treeEditPreOp").value = tree.pre_op || "";
    document.getElementById("treeEditPreOpNotes").value = tree.pre_op_physician_notes || "";
    document.getElementById("treeEditProcedure").value = tree.procedure || "";
    document.getElementById("treeEditProcedureNotes").value = tree.procedure_physician_notes || "";
    document.getElementById("treeEditPostOp").value = tree.post_op_short || "";
    document.getElementById("treeEditPostOpNotes").value = tree.post_op_short_physician_notes || "";
    document.getElementById("treeEditMaintenance").value = tree.maintenance || "";
    document.getElementById("treeEditMaintenanceNotes").value = tree.maintenance_physician_notes || "";
    document.getElementById("treeEditSummary").value = tree.summary_text || "";

    document.getElementById("treeEditModal").classList.remove("hidden");
}


// =============================================================================
// Phase 31: 待簽核視覺解說動畫審核與管理前端邏輯
// =============================================================================

const visualState = {
    selected: new Set(),
    cards: new Map(),
    busy: false,
};

function initVisualsSection() {
    const btnRefresh = document.getElementById("btnRefreshVisuals");
    if (btnRefresh) btnRefresh.addEventListener("click", loadVisuals);

    const selStatus = document.getElementById("visualsFilterStatus");
    if (selStatus) selStatus.addEventListener("change", loadVisuals);

    const selScope = document.getElementById("visualsFilterScope");
    if (selScope) selScope.addEventListener("change", loadVisuals);

    const btnAutodraft = document.getElementById("btnAutodraftVisual");
    if (btnAutodraft) btnAutodraft.addEventListener("click", handleAutodraftVisual);

    document.getElementById("btnVisualSelectAll")?.addEventListener("click", () => {
        visualState.cards.forEach((entry, id) => {
            visualState.selected.add(id);
        });
        syncVisualSelectionUi();
    });

    document.getElementById("btnVisualInvertSelect")?.addEventListener("click", () => {
        visualState.cards.forEach((entry, id) => {
            if (visualState.selected.has(id)) visualState.selected.delete(id);
            else visualState.selected.add(id);
        });
        syncVisualSelectionUi();
    });

    document.getElementById("btnVisualClearSelect")?.addEventListener("click", () => {
        visualState.selected.clear();
        syncVisualSelectionUi();
    });

    document.getElementById("btnVisualBatchApprove")?.addEventListener("click", () => runVisualBatch("approve"));
    document.getElementById("btnVisualBatchReject")?.addEventListener("click", () => runVisualBatch("reject"));
}

function syncVisualSelectionUi() {
    visualState.cards.forEach(({ card, checkbox }, id) => {
        const on = visualState.selected.has(id);
        if (checkbox) checkbox.checked = on;
        if (card) card.classList.toggle("selected", on);
    });
    const n = visualState.selected.size;
    const total = visualState.cards.size;
    const counterEl = document.getElementById("visualSelectionCounter");
    if (counterEl) counterEl.textContent = `已選取 ${n} / ${total} 筆`;
    const btnApprove = document.getElementById("btnVisualBatchApprove");
    if (btnApprove) {
        btnApprove.textContent = `✅ 批量核准 (${n})`;
        btnApprove.disabled = n === 0 || visualState.busy;
    }
    const btnReject = document.getElementById("btnVisualBatchReject");
    if (btnReject) {
        btnReject.textContent = `❌ 批量駁回 (${n})`;
        btnReject.disabled = n === 0 || visualState.busy;
    }
}

async function runVisualBatch(action) {
    if (visualState.busy) return;
    const ids = Array.from(visualState.selected);
    if (ids.length === 0) return;
    const label = action === "approve" ? "核准發布" : "駁回";
    if (!window.confirm(`確定要批量${label}所選的 ${ids.length} 筆視覺解說動畫嗎？`)) return;
    visualState.busy = true;
    syncVisualSelectionUi();
    let ok = 0;
    let failed = 0;
    try {
        for (const id of ids) {
            try {
                const resp = await fetch(`/api/v1/admin/visuals/${id}/${action}`, {
                    method: "POST",
                    headers: getAuthHeaders(),
                });
                if (resp.ok) ok++;
                else failed++;
            } catch (e) {
                failed++;
            }
        }
        if (ok > 0) {
            showToast(`已成功批量${label} ${ok} 筆動畫${failed > 0 ? `（${failed} 筆失敗）` : ""}`, "success");
        } else {
            showToast(`批量${label}失敗`, "error");
        }
        await loadVisuals();
        loadDashboardSummary();
    } finally {
        visualState.busy = false;
        syncVisualSelectionUi();
    }
}


async function loadApprovedTreesForVisualSelect() {
    const sel = document.getElementById("visualsTreeSelect");
    if (!sel) return;

    try {
        const resp = await fetch("/api/v1/admin/trees?status=approved&limit=100", {
            headers: getAuthHeaders(),
        });
        if (!resp.ok) return;
        const data = await resp.json();
        const trees = data.trees || [];

        // 保留預設第一項
        while (sel.options.length > 1) {
            sel.remove(1);
        }

        trees.forEach((t) => {
            const opt = document.createElement("option");
            opt.value = t.id;
            opt.textContent = `#${t.id} ${t.title || t.doc_id} (${t.doc_id || ""})`;
            sel.appendChild(opt);
        });
    } catch (e) {
        console.error("載入已核准推理樹失敗", e);
    }
}

async function handleAutodraftVisual() {
    const sel = document.getElementById("visualsTreeSelect");
    const treeId = parseInt(sel ? sel.value : "", 10);
    if (!treeId) {
        showToast("請先選擇一筆已核准推理樹", "error");
        return;
    }

    const btn = document.getElementById("btnAutodraftVisual");
    const origText = btn ? btn.textContent : "";
    if (btn) {
        btn.disabled = true;
        btn.textContent = "⏳ 正在生成動畫草稿...";
    }

    try {
        const resp = await fetch("/api/v1/admin/visuals/autodraft", {
            method: "POST",
            headers: {
                ...getAuthHeaders(),
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ tree_id: treeId }),
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            showToast("動畫草稿已由推理樹成功生成！", "success");
            loadVisuals();
            loadDashboardSummary();
        } else {
            showToast(apiErrorText(data, "自動生成失敗"), "error");
        }
    } catch (e) {
        showToast("連線異常，無法生成動畫草稿", "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = origText;
        }
    }
}

async function loadVisuals() {
    const container = document.getElementById("visualsContainer");
    if (!container) return;
    visualState.selected.clear();
    visualState.cards.clear();
    syncVisualSelectionUi();
    container.replaceChildren(el("div", "skeleton"), el("div", "skeleton"));

    const status = document.getElementById("visualsFilterStatus")?.value || "pending";
    const scope = document.getElementById("visualsFilterScope")?.value || "all";
    const clinic = document.getElementById("visualsFilterClinic")?.value || "";

    const params = new URLSearchParams({ status, scope, limit: "100" });
    if (clinic) params.set("clinic_id", clinic);

    try {
        const resp = await fetch(`/api/v1/admin/visuals?${params.toString()}`, {
            headers: getAuthHeaders(),
        });
        if (!resp.ok) {
            setStatusBox(container, `無法載入動畫列表 (HTTP ${resp.status})，請確認 API Key`, "error");
            return;
        }
        const data = await resp.json();
        const items = data.visuals || data.items || [];
        if (items.length === 0) {
            setStatusBox(container, "🎬 目前無相符之視覺解說卡資產。", "empty");
            return;
        }

        container.replaceChildren();
        items.forEach((item) => {
            const card = createVisualReviewCard(item);
            container.appendChild(card);
        });
        syncVisualSelectionUi();
    } catch (e) {
        setStatusBox(container, "連線失敗，無法取得動畫列表", "error");
    }
}

let visualBlueprintsCache = null;

async function loadVisualBlueprints() {
    if (visualBlueprintsCache) return visualBlueprintsCache;
    const resp = await fetch("/api/v1/admin/visual-blueprints", { headers: getAuthHeaders() });
    if (!resp.ok) throw new Error(`模板清單載入失敗（HTTP ${resp.status}）`);
    const data = await resp.json();
    visualBlueprintsCache = Array.isArray(data.blueprints) ? data.blueprints : [];
    return visualBlueprintsCache;
}

// 場景 1 模板下拉：醫師可指定模板，覆寫值優先於關鍵字推斷；變更後需重新生成並簽核
function buildTemplateOverrideRow(asset) {
    const row = el("div", "flex flex-wrap items-center gap-2 text-xs text-slate-600");
    row.appendChild(el("span", "", "場景 1 模板："));
    const select = document.createElement("select");
    select.className = "text-xs border border-slate-300 rounded px-1 py-0.5";
    select.appendChild(new Option("（沿用關鍵字推斷）", ""));
    select.value = "";
    select.disabled = true;
    row.appendChild(select);
    const note = el("span", "text-slate-500", "");
    row.appendChild(note);

    loadVisualBlueprints()
        .then((list) => {
            list.forEach((bp) => select.appendChild(new Option(bp, bp)));
            select.value = asset.template_override || "";
            select.disabled = false;
        })
        .catch((err) => {
            note.textContent = err.message;
        });

    select.addEventListener("change", async () => {
        select.disabled = true;
        note.textContent = "儲存中...";
        try {
            const resp = await fetch(`/api/v1/admin/visuals/${asset.id}/template-override`, {
                method: "PUT",
                headers: Object.assign({ "Content-Type": "application/json" }, getAuthHeaders()),
                body: JSON.stringify({ template: select.value || null }),
            });
            if (!resp.ok) {
                const data = await resp.json().catch(() => ({}));
                throw new Error(data.detail || `儲存失敗（HTTP ${resp.status}）`);
            }
            note.textContent = "已儲存：草稿已回到待審，請重新生成以套用新模板";
            await loadVisuals();
        } catch (err) {
            note.textContent = err.message;
            select.disabled = false;
        }
    });
    return row;
}

function createVisualReviewCard(asset) {
    const card = el("div", "visual-review-card");

    // 1. 頂部資訊與標籤
    const header = el("div", "flex justify-between items-start flex-wrap gap-2");
    const metaLeft = el("div", "space-y-1");

    const badgesRow = el("div", "flex flex-wrap items-center gap-1.5");
    const checkLabel = el("label", "flex items-center cursor-pointer mr-1");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "visual-card-checkbox";
    checkbox.checked = visualState.selected.has(asset.id);
    checkbox.addEventListener("change", (e) => {
        e.stopPropagation();
        if (checkbox.checked) visualState.selected.add(asset.id);
        else visualState.selected.delete(asset.id);
        syncVisualSelectionUi();
    });
    checkLabel.appendChild(checkbox);
    badgesRow.appendChild(checkLabel);

    const idBadge = el("span", "text-xs font-mono font-bold bg-gray-100 text-gray-700 px-2 py-0.5 rounded", `#${asset.id}`);
    const keyBadge = el("span", "text-xs font-mono bg-slate-100 text-slate-700 px-2 py-0.5 rounded", asset.topic_key || "");
    badgesRow.appendChild(idBadge);
    badgesRow.appendChild(keyBadge);

    // 診所範圍標籤
    if (asset.clinic_id) {
        badgesRow.appendChild(el("span", "text-xs font-medium bg-amber-100 text-amber-800 px-2 py-0.5 rounded", `🏥 診所專屬 (${asset.clinic_id})`));
    } else {
        badgesRow.appendChild(el("span", "text-xs font-medium bg-blue-100 text-blue-800 px-2 py-0.5 rounded", "🌐 一般醫學 (共用)"));
    }

    // 來源標籤
    const srcText = asset.source_type === "llm_generated" ? "🤖 AI 生成" : (asset.source_type === "manual" ? "✍️ 人工手寫" : asset.source_type);
    badgesRow.appendChild(el("span", "text-xs font-medium bg-purple-100 text-purple-800 px-2 py-0.5 rounded", srcText));

    // 審核狀態標籤
    let statusClass = "bg-amber-100 text-amber-800";
    let statusText = "⏳ 待簽核";
    if (asset.review_status === "approved") {
        statusClass = "bg-emerald-100 text-emerald-800";
        statusText = "✅ 已發布";
    } else if (asset.review_status === "rejected") {
        statusClass = "bg-rose-100 text-rose-800";
        statusText = "❌ 已駁回";
    }
    badgesRow.appendChild(el("span", `text-xs font-medium px-2 py-0.5 rounded ${statusClass}`, statusText));

    // 驗證標籤
    const isValOk = asset.validation && asset.validation.ok;
    const valClass = isValOk ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800";
    const valText = isValOk ? "✅ 驗證通過" : "⚠️ 驗證未過";
    badgesRow.appendChild(el("span", `text-xs font-medium px-2 py-0.5 rounded ${valClass}`, valText));

    metaLeft.appendChild(badgesRow);

    const titleEl = el("h3", "text-lg font-bold text-gray-800 mt-1", asset.title || "未命名動畫");
    metaLeft.appendChild(titleEl);

    // 關鍵字標籤
    if (Array.isArray(asset.keywords) && asset.keywords.length > 0) {
        const kwRow = el("div", "flex flex-wrap gap-1 text-xs text-gray-500 mt-1");
        asset.keywords.forEach((kw) => {
            kwRow.appendChild(el("span", "bg-gray-50 text-gray-600 px-1.5 py-0.5 rounded border border-gray-200", `#${kw}`));
        });
        metaLeft.appendChild(kwRow);
    }
    header.appendChild(metaLeft);

    metaLeft.appendChild(buildTemplateOverrideRow(asset));
    card.appendChild(header);

    // 2. 播放器區塊
    const playerBox = el("div", "visual-review-player");
    const svgEl = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svgEl.setAttribute("viewBox", "0 0 800 510");
    svgEl.classList.add("visual-review-svg");
    playerBox.appendChild(svgEl);

    // 控制列
    const controls = el("div", "visual-review-controls");
    const btnPlay = el("button", "btn-visual-play px-3 py-1 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium rounded transition", "▶ 播放");
    controls.appendChild(btnPlay);

    const scrubber = document.createElement("input");
    scrubber.type = "range";
    scrubber.min = "0";
    scrubber.max = "1000";
    scrubber.value = "0";
    scrubber.className = "visual-review-scrubber";
    controls.appendChild(scrubber);

    const timeDisplay = el("span", "text-xs text-gray-300 font-mono select-none", "0.0s / 0.0s");
    controls.appendChild(timeDisplay);

    const scenesNav = el("div", "flex items-center gap-1 ml-auto");
    const btnScene1 = el("button", "btn-scene-jump px-2 py-0.5 text-xs text-gray-200 bg-slate-700 hover:bg-slate-600 rounded transition", "場景 1");
    const btnScene2 = el("button", "btn-scene-jump px-2 py-0.5 text-xs text-gray-200 bg-slate-700 hover:bg-slate-600 rounded transition", "場景 2");
    const btnScene3 = el("button", "btn-scene-jump px-2 py-0.5 text-xs text-gray-200 bg-slate-700 hover:bg-slate-600 rounded transition", "場景 3");
    scenesNav.appendChild(btnScene1);
    scenesNav.appendChild(btnScene2);
    scenesNav.appendChild(btnScene3);
    controls.appendChild(scenesNav);

    playerBox.appendChild(controls);
    card.appendChild(playerBox);

    // 3. 場景說明清單與內聯編輯區
    const scenes = Array.isArray(asset.scenes) ? asset.scenes : [];
    const scenesGrid = el("div", "visual-scene-list");
    const sceneItemEls = [];

    scenes.forEach((sc, i) => {
        const itemBox = el("div", "visual-scene-item");
        const headRow = el("div", "visual-scene-badge");
        headRow.appendChild(el("span", "font-bold text-gray-700", `場景 ${i + 1}: ${sc.title || ""}`));
        headRow.appendChild(el("span", "text-gray-400 font-mono text-xs", `${sc.blueprint || ""} (${sc.duration_sec || 8}s)`));
        itemBox.appendChild(headRow);

        const captionP = el("p", "text-xs text-gray-600 leading-relaxed", sc.caption || "");
        itemBox.appendChild(captionP);

        if (Array.isArray(sc.labels) && sc.labels.length > 0) {
            const labelsRow = el("div", "flex flex-wrap gap-1 mt-1");
            sc.labels.forEach((lb) => {
                let toneBadge = "bg-gray-100 text-gray-700";
                if (lb.tone === "optimal") toneBadge = "bg-emerald-100 text-emerald-700";
                else if (lb.tone === "warning") toneBadge = "bg-amber-100 text-amber-700";
                labelsRow.appendChild(el("span", `text-[10px] px-1.5 py-0.5 rounded font-medium ${toneBadge}`, lb.text || ""));
            });
            itemBox.appendChild(labelsRow);
        }

        sceneItemEls.push(itemBox);
        scenesGrid.appendChild(itemBox);
    });

    card.appendChild(scenesGrid);

    // 編輯區塊（展開前隱藏）
    const editBox = el("div", "visual-edit-box hidden");
    const editHead = el("h4", "text-sm font-bold text-gray-800", "✏️ 編輯動畫說明文字（儲存後將重置為待簽核）");
    editBox.appendChild(editHead);

    const titleField = el("div", "space-y-1");
    titleField.appendChild(el("label", "block text-xs font-medium text-gray-700", "動畫整體標題："));
    const titleInput = document.createElement("input");
    titleInput.type = "text";
    titleInput.className = "w-full text-sm border border-gray-300 rounded px-3 py-1.5 bg-white";
    titleInput.value = asset.title || "";
    titleField.appendChild(titleInput);
    editBox.appendChild(titleField);

    const sceneInputs = [];
    scenes.forEach((sc, i) => {
        const scBox = el("div", "bg-white p-3 rounded border border-gray-200 space-y-2");
        scBox.appendChild(el("div", "text-xs font-bold text-gray-700", `場景 ${i + 1} (${sc.blueprint || ""})`));

        const stField = el("div", "space-y-0.5");
        stField.appendChild(el("label", "block text-[11px] text-gray-500", "場景標題："));
        const stInput = document.createElement("input");
        stInput.type = "text";
        stInput.className = "w-full text-xs border border-gray-300 rounded px-2 py-1";
        stInput.value = sc.title || "";
        stField.appendChild(stInput);
        scBox.appendChild(stField);

        const capField = el("div", "space-y-0.5");
        capField.appendChild(el("label", "block text-[11px] text-gray-500", "場景說明（禁止阿拉伯數字、禁止保證療效禁詞）："));
        const capTextarea = document.createElement("textarea");
        capTextarea.rows = 2;
        capTextarea.className = "w-full text-xs border border-gray-300 rounded px-2 py-1 leading-relaxed";
        capTextarea.value = sc.caption || "";
        capField.appendChild(capTextarea);
        scBox.appendChild(capField);

        sceneInputs.push({ title: stInput, caption: capTextarea });
        editBox.appendChild(scBox);
    });

    const editBtnRow = el("div", "flex justify-end items-center gap-2 pt-2");
    const btnCancelEdit = el("button", "text-xs px-3 py-1.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50", "取消");
    const btnSaveEdit = el("button", "text-xs px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-700 text-white font-medium", "💾 儲存修訂");
    editBtnRow.appendChild(btnCancelEdit);
    editBtnRow.appendChild(btnSaveEdit);
    editBox.appendChild(editBtnRow);

    card.appendChild(editBox);

    // 4. 卡片操作按鈕列
    const actionsRow = el("div", "flex justify-between items-center pt-2 border-t border-gray-100 flex-wrap gap-2");
    const btnToggleEdit = el("button", "text-xs text-indigo-600 hover:text-indigo-800 font-medium py-1 px-2 rounded hover:bg-indigo-50 transition", "✏️ 編輯說明文字");
    actionsRow.appendChild(btnToggleEdit);

    btnToggleEdit.addEventListener("click", () => {
        const isHidden = editBox.classList.contains("hidden");
        editBox.classList.toggle("hidden", !isHidden);
        btnToggleEdit.textContent = isHidden ? "關閉編輯" : "✏️ 編輯說明文字";
    });

    btnCancelEdit.addEventListener("click", () => {
        editBox.classList.add("hidden");
        btnToggleEdit.textContent = "✏️ 編輯說明文字";
    });

    btnSaveEdit.addEventListener("click", async () => {
        const newTitle = titleInput.value.trim();
        const newScenes = sceneInputs.map((item) => ({
            title: item.title.value.trim(),
            caption: item.caption.value.trim(),
        }));

        btnSaveEdit.disabled = true;
        btnSaveEdit.textContent = "儲存中...";

        try {
            const resp = await fetch(`/api/v1/admin/visuals/${asset.id}`, {
                method: "PATCH",
                headers: {
                    ...getAuthHeaders(),
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    title: newTitle,
                    scenes: newScenes,
                }),
            });
            const resData = await resp.json().catch(() => ({}));
            if (resp.ok) {
                showToast("動畫說明文字已修訂，狀態重置為待簽核", "success");
                loadVisuals();
                loadDashboardSummary();
            } else {
                showToast(apiErrorText(resData, "修訂失敗"), "error");
            }
        } catch (e) {
            showToast("連線異常，無法儲存修訂", "error");
        } finally {
            btnSaveEdit.disabled = false;
            btnSaveEdit.textContent = "💾 儲存修訂";
        }
    });

    const statusActions = el("div", "flex items-center gap-2 ml-auto");
    if (asset.review_status !== "approved") {
        const btnApprove = el("button", "btn btn-success text-xs px-3 py-1.5", "✅ 核准發布");
        btnApprove.addEventListener("click", async () => {
            if (!confirm(`確定核准發布動畫「${asset.title || asset.topic_key}」嗎？核准後將對外提供觀看。`)) return;
            try {
                const resp = await fetch(`/api/v1/admin/visuals/${asset.id}/approve`, {
                    method: "POST",
                    headers: getAuthHeaders(),
                });
                const resData = await resp.json().catch(() => ({}));
                if (resp.ok) {
                    showToast("動畫已成功核准發布！", "success");
                    loadVisuals();
                    loadDashboardSummary();
                } else {
                    showToast(apiErrorText(resData, "核准失敗"), "error");
                }
            } catch (e) {
                showToast("連線異常，核准失敗", "error");
            }
        });
        statusActions.appendChild(btnApprove);
    }

    if (asset.review_status !== "rejected") {
        const btnReject = el("button", "btn btn-danger-soft text-xs px-3 py-1.5", "❌ 駁回");
        btnReject.addEventListener("click", async () => {
            if (!confirm(`確定駁回動畫「${asset.title || asset.topic_key}」草稿嗎？`)) return;
            try {
                const resp = await fetch(`/api/v1/admin/visuals/${asset.id}/reject`, {
                    method: "POST",
                    headers: getAuthHeaders(),
                });
                const resData = await resp.json().catch(() => ({}));
                if (resp.ok) {
                    showToast("動畫已駁回", "info");
                    loadVisuals();
                    loadDashboardSummary();
                } else {
                    showToast(apiErrorText(resData, "駁回失敗"), "error");
                }
            } catch (e) {
                showToast("連線異常，駁回失敗", "error");
            }
        });
        statusActions.appendChild(btnReject);
    }

    actionsRow.appendChild(statusActions);
    card.appendChild(actionsRow);

    // 5. 動畫播放控制與事件綁定
    let ctrl = null;
    let isPlaying = false;
    let animId = null;
    let lastTs = null;
    let currentT = 0;
    let totalDur = 0;
    const sceneStarts = [];
    const sceneButtons = [btnScene1, btnScene2, btnScene3];

    function updateActiveSceneUI(idx) {
        sceneButtons.forEach((b, i) => {
            if (i === idx) {
                b.className = "btn-scene-jump px-2 py-0.5 text-xs text-white bg-indigo-600 font-bold rounded transition";
            } else {
                b.className = "btn-scene-jump px-2 py-0.5 text-xs text-gray-200 bg-slate-700 hover:bg-slate-600 rounded transition";
            }
        });
        sceneItemEls.forEach((it, i) => {
            if (i === idx) {
                it.classList.add("ring-2", "ring-indigo-500", "bg-indigo-50/50");
            } else {
                it.classList.remove("ring-2", "ring-indigo-500", "bg-indigo-50/50");
            }
        });
    }

    if (typeof window !== "undefined" && window.ClinicVisual && typeof window.ClinicVisual.mount === "function") {
        try {
            ctrl = window.ClinicVisual.mount(svgEl, scenes);
            if (ctrl) {
                totalDur = ctrl.totalDuration;
                timeDisplay.textContent = `0.0s / ${totalDur.toFixed(1)}s`;
                let acc = 0;
                for (let i = 0; i < scenes.length; i++) {
                    sceneStarts.push(acc);
                    const d = window.ClinicVisual.sceneDuration(scenes[i]);
                    acc += d;
                }
                ctrl.renderAt(0);
                updateActiveSceneUI(0);
            }
        } catch (err) {
            console.error("ClinicVisual.mount 失敗", err);
        }
    }

    function renderFrame(t) {
        if (!ctrl) return;
        currentT = Math.max(0, Math.min(t, totalDur));
        const safeT = Math.min(currentT, Math.max(0, totalDur - 0.001));
        ctrl.renderAt(safeT);
        scrubber.value = Math.floor((currentT / Math.max(0.001, totalDur)) * 1000);
        timeDisplay.textContent = `${currentT.toFixed(1)}s / ${totalDur.toFixed(1)}s`;
        updateActiveSceneUI(ctrl.sceneIndexAt(safeT));
    }

    function animStep(ts) {
        if (!isPlaying) return;
        if (lastTs === null) lastTs = ts;
        const dt = (ts - lastTs) / 1000;
        lastTs = ts;
        currentT += dt;
        if (currentT >= totalDur) {
            currentT = 0;
        }
        renderFrame(currentT);
        animId = requestAnimationFrame(animStep);
    }

    btnPlay.addEventListener("click", () => {
        isPlaying = !isPlaying;
        if (isPlaying) {
            btnPlay.textContent = "⏸ 暫停";
            lastTs = null;
            animId = requestAnimationFrame(animStep);
        } else {
            btnPlay.textContent = "▶ 播放";
            if (animId) cancelAnimationFrame(animId);
            animId = null;
            lastTs = null;
        }
    });

    scrubber.addEventListener("input", () => {
        if (isPlaying) {
            isPlaying = false;
            btnPlay.textContent = "▶ 播放";
            if (animId) cancelAnimationFrame(animId);
            animId = null;
            lastTs = null;
        }
        const val = parseFloat(scrubber.value) || 0;
        const targetT = (val / 1000) * totalDur;
        renderFrame(targetT);
    });

    sceneButtons.forEach((b, i) => {
        b.addEventListener("click", () => {
            if (isPlaying) {
                isPlaying = false;
                btnPlay.textContent = "▶ 播放";
                if (animId) cancelAnimationFrame(animId);
                animId = null;
                lastTs = null;
            }
            const t = sceneStarts[i] !== undefined ? sceneStarts[i] : 0;
            renderFrame(t);
        });
    });

    visualState.cards.set(asset.id, { card, checkbox, asset });
    return card;
}


// ── 機構代碼下拉選單（上傳／SOAP／提問共用）與新增診所 ──
const CLINIC_SELECT_IDS = ["uploadClinicId", "soapClinicId", "askClinicId"];
const CLINIC_NEW_VALUE = "__new__";
const clinicState = { list: [] };

function initClinicSelectors() {
    CLINIC_SELECT_IDS.forEach((id) => {
        const sel = document.getElementById(id);
        if (sel) sel.addEventListener("change", () => onClinicSelectChange(sel));
    });
    const headerClinic = document.getElementById("headerClinicSelect");
    if (headerClinic) headerClinic.addEventListener("change", () => setGlobalClinic(headerClinic.value));
    const reviewClinic = document.getElementById("reviewFilterClinic");
    if (reviewClinic) reviewClinic.addEventListener("change", () => loadReviewFaqs());
    const treesClinic = document.getElementById("treesFilterClinic");
    if (treesClinic) treesClinic.addEventListener("change", () => loadTrees());
    const visualsClinic = document.getElementById("visualsFilterClinic");
    if (visualsClinic) visualsClinic.addEventListener("change", () => loadVisuals());
    document.getElementById("btnClinicCreateCancel").addEventListener("click", closeClinicCreateModal);
    document.getElementById("clinicCreateForm").addEventListener("submit", submitClinicCreate);
    document.getElementById("clinicCreateModal").addEventListener("click", (e) => {
        if (e.target.id === "clinicCreateModal") closeClinicCreateModal();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeClinicCreateModal();
    });
    loadClinicOptions();
}

async function loadClinicOptions(preferredId) {
    let list = [];
    let failedMessage = "";
    try {
        const res = await fetch("/api/v1/admin/clinics", { headers: getAuthHeaders() });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
            list = Array.isArray(data.clinics) ? data.clinics : [];
        } else {
            failedMessage = apiErrorText(data, `無法載入診所清單 (HTTP ${res.status})`);
        }
    } catch (err) {
        failedMessage = "無法連線至伺服器，無法載入診所清單";
    }
    if (failedMessage) showToast(failedMessage, "error");
    clinicState.list = list;
    renderClinicSelects(list, preferredId);
    populateClinicFilters(list);
}

// 審核頁籤的診所篩選：選項為「全部診所」加上已建檔診所，切換時重新載入列表
const CLINIC_FILTER_IDS = ["reviewFilterClinic", "treesFilterClinic", "visualsFilterClinic"];

function populateClinicFilters(list) {
    const header = document.getElementById("headerClinicSelect");
    if (header) {
        const current = header.value;
        header.textContent = "";
        list.forEach((c) => header.appendChild(new Option(`${c.name}（${c.clinic_id}）`, c.clinic_id)));
        const fallback = CLINIC_SELECT_IDS.map((id) => document.getElementById(id)?.value).find((v) => v);
        const wanted = [current, fallback].find((v) => v && list.some((c) => c.clinic_id === v));
        header.value = wanted || (list[0] ? list[0].clinic_id : "");
        header.dataset.prev = header.value;
    }
    CLINIC_FILTER_IDS.forEach((id) => {
        const sel = document.getElementById(id);
        if (!sel) return;
        const previous = sel.value;
        sel.textContent = "";
        sel.appendChild(new Option("全部診所", ""));
        list.forEach((c) => sel.appendChild(new Option(`${c.name}（${c.clinic_id}）`, c.clinic_id)));
        sel.value = list.some((c) => c.clinic_id === previous) ? previous : "";
    });
}

function renderClinicSelects(list, preferredId) {
    CLINIC_SELECT_IDS.forEach((id) => {
        const sel = document.getElementById(id);
        if (!sel) return;
        const previous = sel.dataset.prev || sel.value;
        sel.textContent = "";
        sel.appendChild(new Option("請選擇診所", ""));
        list.forEach((c) => sel.appendChild(new Option(`${c.name}（${c.clinic_id}）`, c.clinic_id)));
        sel.appendChild(new Option("＋ 新增診所…", CLINIC_NEW_VALUE));
        const wanted = [preferredId, previous].find((v) => v && list.some((c) => c.clinic_id === v));
        sel.value = wanted || (list[0] ? list[0].clinic_id : "");
        sel.dataset.prev = sel.value;
    });
}

function onClinicSelectChange(sel) {
    if (sel.value === CLINIC_NEW_VALUE) {
        sel.value = sel.dataset.prev || "";
        openClinicCreateModal();
        return;
    }
    if (!sel.value) return;
    setGlobalClinic(sel.value);
}

// 全站目前診所：頂部選單、三個頁籤的機構代碼、兩個審核篩選同步為同一個值，並重新載入目前開著的審核列表
function setGlobalClinic(clinicId) {
    const targets = [...CLINIC_SELECT_IDS, ...CLINIC_FILTER_IDS, "headerClinicSelect"];
    targets.forEach((id) => {
        const node = document.getElementById(id);
        if (!node) return;
        if (!Array.from(node.options).some((o) => o.value === clinicId)) return;
        node.value = clinicId;
        node.dataset.prev = clinicId;
    });
    const reviewVisible = !document.getElementById("tab-review").classList.contains("hidden");
    const treesVisible = !document.getElementById("tab-trees").classList.contains("hidden");
    const visualsVisible = document.getElementById("tab-visuals") && !document.getElementById("tab-visuals").classList.contains("hidden");
    if (reviewVisible) loadReviewFaqs();
    if (treesVisible) loadTrees();
    if (visualsVisible) loadVisuals();
}

function openClinicCreateModal() {
    const form = document.getElementById("clinicCreateForm");
    form.reset();
    setClinicCreateError("");
    document.getElementById("clinicCreateModal").classList.remove("hidden");
    document.getElementById("newClinicId").focus();
}

function closeClinicCreateModal() {
    document.getElementById("clinicCreateModal").classList.add("hidden");
}

function setClinicCreateError(text) {
    const p = document.getElementById("clinicCreateError");
    p.textContent = text;
    p.classList.toggle("hidden", !text);
}

async function submitClinicCreate(e) {
    e.preventDefault();
    const form = document.getElementById("clinicCreateForm");
    if (!form.reportValidity()) return;

    const optional = (id) => document.getElementById(id).value.trim() || null;
    const body = {
        clinic_id: document.getElementById("newClinicId").value.trim(),
        name: document.getElementById("newClinicName").value.trim(),
        clinic_type: optional("newClinicType"),
        phone: optional("newClinicPhone"),
        address: optional("newClinicAddress"),
        website: optional("newClinicWebsite"),
    };
    if (!/^\d{10}$/.test(body.clinic_id)) {
        setClinicCreateError("醫事機構代碼須為 10 碼數字");
        return;
    }

    const btn = document.getElementById("btnClinicCreateSubmit");
    btn.disabled = true;
    setClinicCreateError("");
    try {
        const res = await fetch("/api/v1/admin/clinics", {
            method: "POST",
            headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 201) {
            closeClinicCreateModal();
            showToast(`已建立診所：${data.name}`, "success");
            await loadClinicOptions(data.clinic_id);
        } else if (res.status === 422) {
            setClinicCreateError("欄位格式有誤：代碼須為 10 碼數字、官網須為 https 網址，名稱不可空白");
        } else {
            setClinicCreateError(apiErrorText(data, `建立失敗 (HTTP ${res.status})`));
        }
    } catch (err) {
        setClinicCreateError("無法連線至伺服器，請稍後再試");
    } finally {
        btn.disabled = false;
    }
}


// 無診所資料時：自動由本機 LLM 生成一般醫學草稿，存入「待簽核衛教草稿」的一般分類（待醫師審核，核准前不對外可見）
async function autoGeneralDraft(question, container) {
    const status = el("p", "text-sm text-gray-600 mt-2", "已自動交由本機 LLM 生成一般醫學草稿（約 1～3 分鐘），完成後會列於「待簽核衛教草稿」→ 一般分類。");
    container.appendChild(status);
    try {
        const resp = await fetch("/api/v1/admin/ask/general-draft", {
            method: "POST",
            headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
            body: JSON.stringify({ question }),
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            status.textContent = `已存入待簽核衛教草稿（一般）：${data.question}，請至「待簽核衛教草稿」核准。`;
            status.className = "text-sm text-emerald-700 mt-2";
        } else {
            status.textContent = `一般草稿未存入：${apiErrorText(data, `失敗 (HTTP ${resp.status})`)}`;
            status.className = "text-sm text-red-600 mt-2";
        }
    } catch (err) {
        status.textContent = "一般草稿未存入：網路請求失敗，請稍後再試";
        status.className = "text-sm text-red-600 mt-2";
    }
}
