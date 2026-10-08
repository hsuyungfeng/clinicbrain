// clinicbrain 診所 Web 管理系統 JavaScript 核心邏輯

document.addEventListener("DOMContentLoaded", () => {
    initAuth();
    initTabNavigation();
    initDashboard();
    initReviewSection();
    initUploadSection();
    initSoapSection();
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

// 4. 待審草稿簽核
function initReviewSection() {
    document.getElementById("btnRefreshReview").addEventListener("click", loadReviewFaqs);
    document.getElementById("reviewFilterCategory").addEventListener("change", loadReviewFaqs);
    document.getElementById("reviewFilterSource").addEventListener("change", loadReviewFaqs);
}

async function loadReviewFaqs() {
    const container = document.getElementById("reviewCardsContainer");
    container.innerHTML = '<div class="text-center py-8 text-gray-500">載入待審草稿中...</div>';

    const category = document.getElementById("reviewFilterCategory").value;
    const source = document.getElementById("reviewFilterSource").value;

    let url = "/api/v1/admin/review/faqs?status=pending";
    if (category) url += `&category=${encodeURIComponent(category)}`;
    if (source) url += `&source_type=${encodeURIComponent(source)}`;

    try {
        const resp = await fetch(url, { headers: getAuthHeaders() });
        if (!resp.ok) {
            container.innerHTML = `<div class="text-center py-8 text-red-500">無法載入待審列表 (HTTP ${resp.status})</div>`;
            return;
        }
        const data = await resp.json();
        const faqs = data.faqs || [];

        if (faqs.length === 0) {
            container.innerHTML = '<div class="text-center py-12 text-gray-500 bg-white rounded-lg border border-gray-200">🎉 當前無任何待簽核衛教草稿。</div>';
            return;
        }

        container.innerHTML = "";
        faqs.forEach(faq => {
            const card = createFaqReviewCard(faq);
            container.appendChild(card);
        });
    } catch (e) {
        container.innerHTML = '<div class="text-center py-8 text-red-500">連線失敗</div>';
    }
}

function createFaqReviewCard(faq) {
    const card = document.createElement("div");
    card.className = "bg-white p-5 rounded-lg shadow-sm border border-gray-200 hover:shadow-md transition";

    const header = document.createElement("div");
    header.className = "flex justify-between items-start mb-3";

    const tagContainer = document.createElement("div");
    tagContainer.className = "flex space-x-2 items-center";

    const idBadge = document.createElement("span");
    idBadge.className = "text-xs font-bold text-gray-500 bg-gray-100 px-2 py-0.5 rounded";
    idBadge.textContent = `ID: ${faq.id}`;
    tagContainer.appendChild(idBadge);

    const sourceBadge = document.createElement("span");
    sourceBadge.className = "badge-source " + (
        faq.source_type === "soap_distilled" ? "badge-soap" :
        faq.source_type === "llm_generated" ? "badge-llm" : "badge-upload"
    );
    sourceBadge.textContent = faq.source_type || "未知";
    tagContainer.appendChild(sourceBadge);

    const catBadge = document.createElement("span");
    catBadge.className = "text-xs px-2 py-0.5 rounded font-semibold " + (
        faq.category === "general" ? "bg-purple-100 text-purple-800" : "bg-blue-100 text-blue-800"
    );
    catBadge.textContent = faq.category || "special";
    tagContainer.appendChild(catBadge);

    header.appendChild(tagContainer);

    const timeText = document.createElement("span");
    timeText.className = "text-xs text-gray-400";
    timeText.textContent = faq.created_at ? faq.created_at.substring(0, 16) : "";
    header.appendChild(timeText);

    card.appendChild(header);

    // 問題與解答內容 (使用 textContent 防禦 XSS)
    const qEl = document.createElement("h3");
    qEl.className = "font-bold text-gray-800 text-base mb-2";
    qEl.textContent = `【問】${faq.question}`;
    card.appendChild(qEl);

    const aEl = document.createElement("p");
    aEl.className = "text-sm text-gray-700 bg-gray-50 p-3 rounded leading-relaxed mb-3 whitespace-pre-wrap";
    aEl.textContent = faq.answer;
    card.appendChild(aEl);

    // 若有 SOAP 溯源細節
    if (faq.metadata && typeof faq.metadata === "object") {
        const metaDiv = document.createElement("div");
        metaDiv.className = "text-xs bg-amber-50 border border-amber-200 text-amber-900 p-2.5 rounded mb-3 space-y-1";
        const title = document.createElement("div");
        title.className = "font-bold mb-1";
        title.textContent = "🩺 臨床病歷溯源資訊：";
        metaDiv.appendChild(title);

        if (faq.metadata.condition) {
            const cond = document.createElement("div");
            cond.textContent = `• 標的疾病：${faq.metadata.condition}`;
            metaDiv.appendChild(cond);
        }
        if (faq.metadata.record_count) {
            const cnt = document.createElement("div");
            cnt.textContent = `• 參考臨床病歷數：${faq.metadata.record_count} 筆`;
            metaDiv.appendChild(cnt);
        }
        card.appendChild(metaDiv);
    }

    // 簽核按鈕區
    const btnArea = document.createElement("div");
    btnArea.className = "flex justify-end space-x-3 pt-2 border-t border-gray-100";

    const btnReject = document.createElement("button");
    btnReject.className = "bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 text-xs px-3.5 py-1.5 rounded font-medium transition";
    btnReject.textContent = "❌ 駁回";
    btnReject.onclick = () => processReview(faq.id, "reject", card);

    const btnApprove = document.createElement("button");
    btnApprove.className = "bg-emerald-600 hover:bg-emerald-700 text-white text-xs px-4 py-1.5 rounded font-medium shadow-sm transition";
    btnApprove.textContent = "✅ 核准發布";
    btnApprove.onclick = () => processReview(faq.id, "approve", card);

    btnArea.appendChild(btnReject);
    btnArea.appendChild(btnApprove);
    card.appendChild(btnArea);

    return card;
}

async function processReview(faqId, action, cardEl) {
    try {
        const resp = await fetch(`/api/v1/admin/review/faqs/${faqId}/${action}`, {
            method: "POST",
            headers: getAuthHeaders()
        });
        const resData = await resp.json();
        if (resp.ok) {
            cardEl.remove();
            loadDashboardSummary();
        } else {
            alert(`操作失敗: ${resData.detail || "未知錯誤"}`);
        }
    } catch (e) {
        alert("網路請求失敗");
    }
}

// 5. 文件拖曳上傳
function initUploadSection() {
    const dropZone = document.getElementById("dropZone");
    const fileInput = document.getElementById("fileInput");
    const dropZoneText = document.getElementById("dropZoneText");
    const form = document.getElementById("uploadForm");

    dropZone.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) {
            dropZoneText.textContent = `已選擇檔案: ${fileInput.files[0].name}`;
        }
    });

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("border-indigo-500", "bg-indigo-50");
    });

    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("border-indigo-500", "bg-indigo-50");
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("border-indigo-500", "bg-indigo-50");
        if (e.dataTransfer.files.length > 0) {
            fileInput.files = e.dataTransfer.files;
            dropZoneText.textContent = `已選擇檔案: ${fileInput.files[0].name}`;
        }
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const file = fileInput.files[0];
        if (!file) {
            alert("請先選擇或拖曳上傳檔案");
            return;
        }

        const formData = new FormData();
        formData.append("file", file);
        formData.append("clinic_id", document.getElementById("uploadClinicId").value.trim());
        formData.append("preview_only", document.getElementById("chkPreviewOnly").checked ? "true" : "false");

        const btn = document.getElementById("btnSubmitUpload");
        btn.disabled = true;
        btn.textContent = "上傳與解析處理中...";

        const resultArea = document.getElementById("uploadResultArea");
        const resultContent = document.getElementById("uploadResultContent");

        try {
            const resp = await fetch("/api/v1/admin/upload", {
                method: "POST",
                headers: getAuthHeaders(),
                body: formData
            });
            const data = await resp.json();

            resultArea.classList.remove("hidden");
            if (resp.ok) {
                resultContent.textContent = JSON.stringify(data, null, 2);
                loadDashboardSummary();
            } else {
                resultContent.textContent = `❌ 錯誤 (HTTP ${resp.status}): ${data.detail || "上傳失敗"}`;
            }
        } catch (err) {
            resultArea.classList.remove("hidden");
            resultContent.textContent = `❌ 請求連線失敗: ${err.message}`;
        } finally {
            btn.disabled = false;
            btn.textContent = "開始上傳與解析";
        }
    });
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
