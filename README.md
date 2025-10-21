## 後端 API
| Method | Path | 說明 |
| --- | --- | --- |
| Method | Path | 說明 |
| --- | --- | --- |
| `POST` | `/v2/api/qrcode/data` | 發行含 FHIR 資料的憑證，需指定 `primary_scope` 與 disclosure policies。 |
| `POST` | `/v2/api/qrcode/nodata` | 發行空白憑證（僅含 scope 與欄位），供錢包後補資料；可附帶 payload template。 |
| `GET` | `/v2/api/credential/nonce?transactionId=...` | 錢包以交易 ID 取得 nonce、模式、揭露欄位與（若提供）FHIR template。 |
| `PUT` | `/v2/api/credential/{credential_id}/action` | 錢包接受、拒絕、撤銷或更新憑證資料，可一併送出選擇性揭露欄位。 |
| `GET` | `/v2/api/wallet/{holder_did}/credentials` | 查詢某 Holder DID 持有的憑證列表。 |
| `DELETE` | `/v2/api/wallet/{holder_did}/forget` | 清除某 Holder 的所有憑證／VP／驗證結果（可遺忘權）。 |
| `POST` | `/v2/api/credentials/{credential_id}/revoke` | 醫院主動撤銷憑證。 |
| `DELETE` | `/v2/api/credentials/{credential_id}` | 從系統移除指定憑證（搭配資料封存）。 |
| `GET` | `/v2/api/did/vp/code` | 驗證端取得 QR Code，需指定 scope、IAL 最低需求與欄位。 |
| `POST` | `/v2/api/did/vp/result` | 接收 VP，驗證欄位與 FHIR 值後回傳 AI insight。 |
| `DELETE` | `/v2/api/did/vp/session/{session_id}` | 清除驗證 session 及其結果。 |
| `POST` | `/v2/api/system/reset` | 重新初始化沙盒（清除憑證、VP、Session）。 |

> ℹ️ 發行端端點需附帶 `Authorization: Bearer issuer-sandbox-token`（可用環境變數 `MEDSSI_ISSUER_TOKEN` 覆寫）；錢包端使用 `wallet-sandbox-token`；驗證端則使用 `verifier-sandbox-token`。

## 快速操作
1. **啟動後端**
   ```bash
   uvicorn backend.main:app --reload
   ```
2. **開啟前端**
   ```bash
   cd frontend
   npm install
   npm run dev -- --host
   ```
   - 介面預設連向 `http://localhost:8000`，可在頁面頂部調整 API Base URL 與 Access Token。
   - React UI 內建 `qrcode.react`，即時顯示可掃描 QR 影像，方便實機驗證。
3. **建議 demo 流程**
   1. 在 Step 1 按「載入示例」，挑選主用途（病歷／領藥／研究），送出「含資料」發卡並掃描 QR。
   2. Step 2 以發行端回傳的 `transaction_id` 取得 nonce，按「載入示例 Payload」後執行 `ACCEPT`，錢包即會儲存憑證並顯示揭露欄位。
   3. Step 3 產生驗證 QR Code（可切換三種 scope），照欄位提示填入 VP 後送出，並觀察 AI Insight 與稽核資訊。
   4. 於 Step 2 使用「行使可遺忘權」清除資料，或在頁首按「重設沙盒資料」快速還原初始狀態。

## 身分驗證與授權對應（健保快易通 vs. MyData）
- **雙軌身分驗證**：健保快易通提供「本人月租型手機門號 + 健保卡號末四碼」或「健保卡 / 自然人憑證裝置綁定」兩種路徑，分別對應遠端 IAL2 與接近 IAL3 的強度，呼應本系統的 `MYDATA_LIGHT` 與 `NHI_CARD_PIN` 等級設計。【F:README.md†L66-L74】
- **MyData 雙因素註冊**：首次使用 MyData 需選擇兩種不同實名驗證工具（例如健保 IC 卡 + 簡訊 OTP 或自然人憑證 + 行動化驗證），達到政府規範的 IAL2 要求，也與 `MOICA_CERT` 等級相呼應。【F:README.md†L75-L83】
- **授權最小化**：兩平台皆遵循「最小必要」原則，使用者僅授權本次必要欄位，本原型亦限制每個 disclosure scope 的欄位並提供一次性 VP 驗證流程。【F:README.md†L84-L90】

| IAL 等級 | 實務對應 | 強度說明 |
| --- | --- | --- |
| `MYDATA_LIGHT` | MyData 行動化驗證（手機門號 + 健保卡號） | 遠端多因素，達 IAL2 | 
| `NHI_CARD_PIN` | 健保快易通：健保卡 + PIN 綁定裝置 | IAL2，結合政府登記資料比對 |
| `MOICA_CERT` | 自然人憑證 / 醫事人員卡臨櫃核發 | IAL3，高度身分保證 |

## FHIR 可驗證憑證模型
- **FHIR Bundle 作為 VC 主體**：Credential payload 以 FHIR Bundle（type `collection`）封裝 Patient、Condition、MedicationDispense 等資源，維持跨院互通性。【F:README.md†L94-L99】
- **最小資料集**：每張 VC 僅包含該用途必要的臨床與身份欄位，例如診斷碼、紀錄日期與院所代碼，避免曝露額外資訊。【F:README.md†L99-L103】
- **簽章與來源驗證**：Credential 透過發行端私鑰簽署，驗證端可比對 FHIR 欄位與 VP 中的選擇性揭露欄位，確保內容未被竄改並符合病患授權範圍。【F:README.md†L103-L108】

## 法規遵循重點
- **電子簽章法**：新版電子簽章法承認數位簽章與電子同意的法律效力，發行端簽章的 VC 與錢包中的授權操作視同紙本簽名。【F:README.md†L112-L117】
- **醫療法第72條**：跨院分享病歷資料必須取得病患明示授權，本原型以 VP 產出記錄病患同意，並提供可稽核的交易 ID 與撤銷機制。【F:README.md†L117-L122】
- **個資法最小蒐集**：系統限制欄位範圍、採一次性傳輸、不長期留存原始 VC，並提供遺忘權 API，符合目的限定與資料刪除要求。【F:README.md†L122-L127】

## 驗證端實務守則
- **資料用畢即刪**：驗證端僅保留驗證結果與必要稽核紀錄，不保存完整 VC 檔案，並在日誌中紀錄查閱者與時間以備稽核。【F:README.md†L131-L136】
- **信任鍊管理**：建議定期同步發行端公鑰、檢查 VC 有效期與吊銷狀態，必要時啟動金鑰輪替或撤銷流程。【F:README.md†L136-L141】
- **零信任控制**：透過角色權限、TLS、速率限制與異常偵測落實「Never Trust, Always Verify」，並提醒前端使用者勿在公開場域暴露 Access Token 或 QR 字串。【F:README.md†L141-L146】

## QR Code 產製提醒
後端仍回傳 `medssi://` payload，但 React 介面已透過 `qrcode.react` 即時產出可掃描圖像，方便於手機或藥局掃描示範。

## 安全性對齊重點
- **Bearer Access Token**：模擬數位發展部沙盒流程，需先在 Swagger Authorize 中輸入發行端或驗證端 Access Token 才能呼叫對應 API，可透過環境變數替換預設值。
- **TLS 與速率限制建議**：原型以 FastAPI 本地執行；實務部署時應透過 API Gateway 提供 TLS 1.3、每小時 3600 次限流與異常偵測。
- **QR 有效 5 分鐘**：Credential offer 與 verification session 均限定 5 分鐘內使用，逾時需重新產生，以符合沙盒規範。
- **UUIDv4 交易序號**：`transaction_id` 採標準 UUIDv4，方便稽核與跨系統追蹤。
- **稽核與清除機制**：保留遺忘權、session purge 與撤銷 API，示範異常處理與資料清除流程。

## 延伸與實務考量
- **Trust Registry**：可在 `get_verification_code` 之前檢查 verifier 是否於政府註冊。
- **MyData 串接**：`CredentialPayload` 已保留 hash 與 Profile 欄位，可改以 MyData API 取得實際報告。
- **長期領藥**：可透過 `pickup_window_end` 與 `days_supply` 延伸為慢性處方續領提醒。
- **合規紀錄**：若需上鏈或寫入審計系統，可擴充 `store.py` 的持久化與稽核欄位。
