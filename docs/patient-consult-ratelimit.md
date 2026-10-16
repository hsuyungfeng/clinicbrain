# 病人諮詢端點速率限制建議 (Rate Limiting Recommendations)

本文檔針對病人「先答後導」公開諮詢端點（`/api/v1/general/consult`）提供反向代理層（Reverse Proxy，以 Nginx 為例）之速率限制配置建議。

---

## 1. 為何需要速率限制？

1. **本機 LLM 單一 Slot 限制**：
   - 本系統後端整合之本機推理服務（`llama-server`）採用單一 slot 序列處理設計。
   - 伺服器端已實作非阻塞鎖（`_PATIENT_LLM_LOCK`），當有 LLM 生成進行中時，其他請求會迅速回傳 `busy`（「目前諮詢人數較多，請稍後再試。」），避免請求在記憶體中無限積壓排隊。
2. **防範頻繁連線與惡意耗損**：
   - 儘管急重症紅旗判定與已核准衛教查詢極快（毫秒級），但無診所既有資料時之 LLM 生成較為耗時（本機推理約需 1～3 分鐘）。
   - 透過反向代理層對每 IP 施加合理速率上限，可防止單一來源惡意刷頻耗盡本機算力，確保多數病患諮詢之服務可用性。

---

## 2. 隱私與合規注意事項

- **不記錄個資與問句**：
  - 系統架構嚴格遵循匿名衛教原則，反向代理與應用層**絕不得記錄使用者的諮詢問句原文或提問歷史**。
  - Nginx 存取日誌可關閉或過濾查詢路徑之詳細內容，避免任何使用者輸入被寫入磁碟日誌。
- **僅用於流量控制**：
  - 記憶體中之 IP 雜湊表僅供 Nginx `limit_req_zone` 短暫維護連線頻率計算，計數窗口過期即自動淘汰，不得將 IP 與任何醫療諮詢內容持久化關聯。

---

## 3. Nginx 設定範例

在 Nginx 主設定（`http` 區段）與虛擬主機（`server` 區段）加入以下設定：

```nginx
# 於 http 區段定義速率限制區（依用戶端 IP 分配，限制每 IP 每分鐘最多 5 次請求）
limit_req_zone $binary_remote_addr zone=patient_consult_limit:10m rate=5r/m;

# 自訂超過頻率限制時回應 HTTP 429 Too Many Requests
limit_req_status 429;

server {
    listen 443 ssl http2;
    server_name clinic.example.com;

    # 病人諮詢前端靜態頁面
    location /admin/consult.html {
        proxy_pass http://127.0.0.1:8000/admin/consult.html;
        proxy_set_header Host $host;
    }

    # 病人諮詢 API 端點（套用速率限制）
    location /api/v1/general/consult {
        # 套用限制：允許 burst=2，nodelay 立即處理合理突發
        limit_req zone=patient_consult_limit burst=2 nodelay;

        # 反向代理至 clinicbrain FastAPI 服務
        proxy_pass http://127.0.0.1:8000/api/v1/general/consult;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # 延長後端連線逾時（配合本機 LLM 生成耗時，一般醫學說明最長可能需 3～5 分鐘）
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;

        # 隱私保護：針對此端點停用存取日誌或僅記錄狀態碼，不留存請求內容
        access_log off;
    }

    # 其他 API 與後台路徑...
}
```

---

## 4. 參數說明與建議數值

| 參數 | 建議數值 | 說明 |
| :--- | :--- | :--- |
| `rate` | `5r/m` | 每 IP 每分鐘最多發起 5 次諮詢請求，滿足正常病患連續詢問需求，同時防範腳本狂刷。 |
| `burst` | `2` | 允許突發緩衝 2 次請求。 |
| `nodelay` | 啟用 | 突發請求不延遲排隊，若超出 `rate + burst` 則立即回傳 HTTP 429。 |
| `limit_req_status` | `429` | 明確指示 Too Many Requests，便於前端或呼叫端顯示友善提示。 |
| `proxy_read_timeout` | `300s` | 本機 LLM 推理較耗時，避免代理層過早中斷連線導致 504 Gateway Timeout。 |
