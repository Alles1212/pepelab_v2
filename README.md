# MedSSI Sandbox v2 – FHIR 病歷授權與領藥流程

本版本依照最新需求重構了 API 與前端介面：

- **身份保證等級（IAL）貼近 MyData / 健保規範**：提供 `MYDATA_LIGHT`、`NHI_CARD_PIN`、`MOICA_CERT` 三個層級，不再使用生物辨識。
- **FHIR 結構化 Payload**：Credential 內含 `Condition` 與 `MedicationDispense` 摘要，並以 FHIR path 定義選擇性揭露欄位。
- **病歷授權與領藥流程完全分流**：後端以 `DisclosureScope`（`MEDICAL_RECORD`、`MEDICATION_PICKUP`）區分流程，前端用大字體與按鈕導覽兩條路徑。
- **可遺忘權與 Session 清除**：錢包可呼叫 `/api/wallet/{holder_did}/forget` 一鍵清除持有資料，驗證端可刪除 session。
- **長者友善介面**：採分步驟面板、示例按鈕、自動填入日期、ARIA live 區域，降低操作複雜度並方便陪同家屬示範。

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
   3. Step 3A 產生病歷授權 QR Code，照示例填入 VP（診斷碼、紀錄日期、院所代碼）送出，觀察 AI 風險指標。
   4. Step 3B 產生領藥 QR Code，送出藥品代碼、給藥天數與領藥期限，可示範提醒視窗。
   5. 回到 Step 2 使用「清除我的資料」，驗證可遺忘權會移除憑證、VP 與結果。

## 延伸與實務考量
- **Trust Registry**：可在 `get_verification_code` 之前檢查 verifier 是否於政府註冊。
- **MyData 串接**：`CredentialPayload` 已保留 hash 與 Profile 欄位，可改以 MyData API 取得實際報告。
- **長期領藥**：可透過 `pickup_window_end` 與 `days_supply` 延伸為慢性處方續領提醒。
- **合規紀錄**：若需上鏈或寫入審計系統，可擴充 `store.py` 的持久化與稽核欄位。
