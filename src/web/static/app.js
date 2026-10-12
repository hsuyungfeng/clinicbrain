// clinicbrain 診所 Web 管理系統 JavaScript 核心邏輯

document.addEventListener("DOMContentLoaded", () => {
    initAuth();
    initTabNavigation();
    initDashboard();
    initReviewSection();
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
        document.getElementById("statApprovedTotal").textContent = data.approved_total ?? 0;
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

    let url = "/api/v1/admin/review/faqs?status=pending&limit=200";
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
    const mins = Math.round(ids.length * 5);
    if (!window.confirm(`將由本機 LLM 逐題補齊所選 ${ids.length} 筆草稿的答案（約需 ${mins} 分鐘，可先離開此頁）。\n補齊後仍為待審，不會自動核准；完成後再一起審核。\n確定開始嗎？`)) return;
    try {
        const resp = await fetch("/api/v1/admin/review/batch-generate", {
            method: "POST",
            headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
            body: JSON.stringify({ faq_ids: ids }),
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
        autoCount.textContent = `${s.processed} / ${s.total} (成功 ${s.ok}・失敗 ${s.failed.length})`;
    }
    const autoBar = document.getElementById("autofillProgressBar");
    if (autoBar) autoBar.style.width = `${progressPercent}%`;

    const btnCancelAuto = document.getElementById("btnCancelAutoFill");
    if (btnCancelAuto) btnCancelAuto.classList.toggle("hidden", !running);

    const autoDetail = document.getElementById("autofillDetailText");
    if (autoDetail) {
        autoDetail.textContent = s.message || (s.failed.length > 0 ? `失敗 ${s.failed.length} 筆：${s.failed.map(f => `ID ${f.id} (${f.reason})`).slice(0, 3).join(", ")}` : "");
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
        // 剛結束：重載清單與總覽統計，並切到「AI 生成待確認」，方便最後一起審
        batchGen.lastState = s.state;
        const reviewView = document.getElementById("reviewView");
        if (reviewView) reviewView.value = "ai";
        await loadReviewFaqs();
        loadDashboardSummary();
        showToast(`${s.state === "done" ? "批量補齊完成" : "批量補齊結束"}：成功 ${s.ok}、失敗 ${s.failed.length}。已切換到「AI 生成待確認」，請逐筆檢視後批量核准`, s.failed.length ? "info" : "success");
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
            showToast(`操作失敗：${typeof data.detail === "string" ? data.detail : "未知錯誤"}`, "error");
        }
    } catch (e) {
        showToast("網路請求失敗", "error");
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
                showToast(`批量${label}失敗：${typeof data.detail === "string" ? data.detail : "格式不正確"}`, "error");
                failed += chunk.length;
                continue;
            }
            ok += data.success_count || 0;
            failed += data.failed_count || 0;
            (data.processed_ids || []).forEach(removeCard);
            Object.values(data.failed_reasons || {}).forEach(r => reasons.add(String(r).split(":")[0]));
        }
    } catch (e) {
        showToast("網路請求失敗", "error");
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

    dropZone.addEventListener("click", () => fileInput.click());
    document.getElementById("btnPickFolder").addEventListener("click", () => folderInput.click());
    document.getElementById("btnClearQueue").addEventListener("click", () => {
        if (uploadState.busy) return;
        uploadState.queue = [];
        document.getElementById("uploadResultArea").classList.add("hidden");
        renderUploadQueue();
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

function renderAskResult(data, container) {
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
    container.appendChild(el("div", "faq-answer", data.answer));
    if (data.compliance && !data.compliance.ok) {
        container.appendChild(el("div", "ask-warn", `合規檢視原因：${data.compliance.reason}（此為管理端檢視，對外端點不會輸出此內容）`));
    }
    const srcTitle = el("div", "ask-src-title", `模型可見的資料來源（${(data.sources || []).length} 筆）`);
    container.appendChild(srcTitle);
    if (!data.sources || data.sources.length === 0) {
        container.appendChild(el("div", "ask-src-empty", "無（此問題在已核准資料中找不到相關內容）"));
    } else {
        const ul = el("ul", "ask-src-list");
        data.sources.forEach(s => {
            const li = el("li", "");
            li.appendChild(badge(s.ref, "badge-id"));
            li.appendChild(document.createTextNode(` ${({ faq: "常見問答", tree: "臨床推理樹", note: "診所備註", clinic_info: "診所資料" })[s.type] || s.type}・${s.level}：${s.title}`));
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
        askState.history.push(data);
        renderAskHistory();
    } catch (e) {
        showToast("網路請求失敗", "error");
    } finally {
        askState.busy = false;
        btn.disabled = false;
        btn.textContent = "💬 送出提問";
    }
}
