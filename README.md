# MedSSI Sandbox v2 – FHIR 病歷授權與領藥流程

本版本依照最新需求重構了 API 與前端介面：

- **身份保證等級（IAL）貼近 MyData / 健保規範**：提供 `MYDATA_LIGHT`、`NHI_CARD_PIN`、`MOICA_CERT` 三個層級，不再使用生物辨識。
- **FHIR 結構化 Payload**：Credential 內含 `Condition` 與 `MedicationDispense` 摘要，並以 FHIR path 定義選擇性揭露欄位。
- **病歷授權與領藥流程完全分流**：後端以 `DisclosureScope`（`MEDICAL_RECORD`、`MEDICATION_PICKUP`）區分流程，前端用大字體與按鈕導覽兩條路徑。
- **可遺忘權與 Session 清除**：錢包可呼叫 `/api/wallet/{holder_did}/forget` 一鍵清除持有資料，驗證端可刪除 session。
- **長者友善介面**：採分步驟面板、示例按鈕、自動填入日期、ARIA live 區域，降低操作複雜度並方便陪同家屬示範。
- **Access Token 與 5 分鐘 QR 有效期**：所有發行端／驗證端 API 需附帶 `Authorization: Bearer <token>`，並強制 5 分鐘內使用 QR code。

## 系統架構
```
Issuer (Hospital) ──QR──> Wallet (Patient) ──VP──> Verifier (Research / Pharmacy)
             │                        │                           │
             │                        │                           ├─ AI Insight Engine
             │                        └─ 可遺忘權 API                │
             └─ FastAPI Issuance ──────┴─ Verification Session Store
```

後端採 FastAPI + in-memory store（`backend/main.py`、`backend/store.py`）。選擇性揭露政策以 `DisclosurePolicy` 列表儲存，欄位使用 FHIR 路徑；驗證流程檢查 IAL、scope、欄位範圍與資料一致性，再交由 `InsightEngine` 輸出胃炎趨勢或領藥提醒。

前端（`frontend/index.html`）提供三步驟導覽：
1. **發行端**：填寫 FHIR Condition / MedicationDispense，設定兩種 scope 的揭露欄位，可先發空白 QR Code。
2. **病患錢包**：查詢 nonce、接受或更新憑證、查看列表、執行可遺忘權。
3. **驗證端**：分為 A. 病歷授權、B. 領藥通知，個別產生 QR Code 與送出 VP，並支援清除 session。

## 後端 API
| Method | Path | 說明 |
| --- | --- | --- |
| `POST` | `/api/qrcode/data` | 發行含 FHIR 資料的憑證，需提供 disclosure policies。 |
| `POST` | `/api/qrcode/nodata` | 發行空白憑證（僅含 scope 與欄位），供錢包後補資料。 |
| `GET` | `/api/credential/nonce?transactionId=...` | 錢包以交易 ID 取得 nonce、模式與各 scope 的揭露欄位。 |
| `PUT` | `/api/credential/{credential_id}/action` | 錢包接受、拒絕、撤銷或更新憑證資料。 |
| `GET` | `/api/wallet/{holder_did}/credentials` | 查詢某 Holder DID 持有的憑證列表。 |
| `POST` | `/api/credentials/{credential_id}/revoke` | 醫院主動撤銷憑證。 |
| `DELETE` | `/api/credentials/{credential_id}` | 從系統移除指定憑證（可配合遺忘權）。 |
| `DELETE` | `/api/wallet/{holder_did}/forget` | 清除某 Holder 的所有憑證／VP／驗證結果。 |
| `GET` | `/api/did/vp/code` | 驗證端取得 QR Code，必須指定 scope 與欄位。 |
| `POST` | `/api/did/vp/result` | 接收 VP，驗證 scope、欄位與 FHIR 值後回傳 AI insight。 |
| `DELETE` | `/api/did/vp/session/{session_id}` | 清除驗證 session 及其結果。 |

> ℹ️ 發行端端點需附帶 `Authorization: Bearer issuer-sandbox-token`（可用環境變數 `MEDSSI_ISSUER_TOKEN` 覆寫）；驗證端端點則使用 `Authorization: Bearer verifier-sandbox-token`。

## 快速操作
1. **啟動後端**
   ```bash
   uvicorn backend.main:app --reload
   ```
2. **開啟前端**
   - 直接開啟 `frontend/index.html` 或使用 `python -m http.server 5173 --directory frontend`。
   - 介面會自動判斷是否使用 `http://localhost:8000`。
3. **建議 demo 流程**
   1. 在 Step 1 按「載入示例」，使用預設的 FHIR Condition 與 MedicationDispense，送出「含資料」發卡。
   2. Step 2 先輸入 `transaction_id` 取得 nonce，按「載入示例 Payload」再執行 `ACCEPT` 將憑證綁定到錢包。
   3. Step 3A 先於驗證端面板輸入 Access Token，再產生病歷授權 QR Code，照示例填入 VP（診斷碼、紀錄日期、院所代碼）送出，觀察 AI 風險指標。
   4. Step 3B 產生領藥 QR Code，送出藥品代碼、給藥天數與領藥期限，可示範提醒視窗。
   5. 回到 Step 2 使用「清除我的資料」，驗證可遺忘權會移除憑證、VP 與結果。

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
目前沙盒僅輸出 `medssi://` payload 字串，尚未產生實際 QR 圖像。可將回傳的 `qr_payload` 貼入外部 QR 產生器或共用連結，再由錢包掃描使用。【F:README.md†L148-L150】

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
