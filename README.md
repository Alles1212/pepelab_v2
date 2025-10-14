# MedSSI Sandbox v2 – FHIR 病歷授權與領藥流程

本版本依照最新需求重構了 API 與前端介面，並整合實務場景與法規需求：

- **身份保證等級（IAL）貼近 MyData / 健保規範**：提供 `MYDATA_LIGHT`、`NHI_CARD_PIN`、`MOICA_CERT` 三個層級，不再使用生物辨識。
- **FHIR 結構化 Payload**：Credential 內含 `Condition` 與 `MedicationDispense` 摘要，並以 FHIR path 定義選擇性揭露欄位。
- **病歷授權與領藥流程完全分流**：後端以 `DisclosureScope`（`MEDICAL_RECORD`、`MEDICATION_PICKUP`）區分流程，前端用大字體與按鈕導覽兩條路徑。
- **可遺忘權與 Session 清除**：錢包可呼叫 `/api/wallet/{holder_did}/forget` 一鍵清除持有資料，驗證端可刪除 session。
- **長者友善介面**：採分步驟面板、示例按鈕、自動填入日期、ARIA live 區域，降低操作複雜度並方便陪同家屬示範。
- **Access Token 與 QR 有效期**：所有發行端／驗證端 API 需附帶 `Authorization: Bearer <token>`，並強制 QR code 於 5 分鐘內使用。

## 系統架構
```
Issuer (Hospital) ──QR──> Wallet (Patient) ──VP──> Verifier (Research / Pharmacy)
             │                        │                           │
             │                        │                           ├─ AI Insight Engine
             │                        └─ 可遺忘權 API                │
             └─ FastAPI Issuance ──────┴─ Verification Session Store
```

後端採 FastAPI + in-memory store（`backend/main.py`、`backend/store.py`）。選擇性揭露政策以 `DisclosurePolicy` 列表儲存，欄位使用 FHIR 路徑；驗證流程檢查 IAL、scope、欄位與資料一致性，再交由 `InsightEngine` 輸出胃炎趨勢或領藥提醒。

## API 說明（部分）

| Method | Path | 說明 |
|--------|------|------|
| `POST` | `/api/qrcode/data` | 發行含 FHIR 資料的憑證，需提供 disclosure policies。 |
| `POST` | `/api/qrcode/nodata` | 發行空白憑證（僅含 scope 與欄位），供錢包後補資料。 |
| `GET` | `/api/credential/nonce?transactionId=...` | 錢包以交易 ID 取得 nonce、模式與各 scope 的揭露欄位。 |
| `PUT` | `/api/credential/{credential_id}/action` | 錢包接受、拒絕、撤銷或更新憑證資料。 |
| `DELETE` | `/api/wallet/{holder_did}/forget` | 清除某 Holder 的所有憑證／VP／驗證結果。 |
| `POST` | `/api/did/vp/result` | 接收 VP，驗證 scope、欄位與 FHIR 值後回傳 AI insight。 |
| `DELETE` | `/api/did/vp/session/{session_id}` | 清除驗證 session 及其結果。 |

## 實務情境範例

1. 病患於 A 醫院完成診斷，醫院發行 VC 並設定領藥有效期三日。
2. B 醫院或研究單位需驗證診斷資訊，建立一筆限定欄位的驗證請求。
3. 病患查詢請求後僅揭露診斷碼與就診日期授權一次性存取。
4. 驗證端提交 VP 至 `/verify`，取得胃炎趨勢分析與風險分數。
5. 病患可隨時執行遺忘權，清除錢包資料，驗證端需重新申請授權。

## 快速啟動

1. 啟動後端：
   ```bash
   python -m uvicorn backend.main:app --reload
   ```
2. 開啟前端：
   ```bash
   python -m http.server 5173 --directory frontend
   ```
   或直接開啟 `frontend/index.html`

3. 示範流程：
   - 發卡 → 接收憑證 → 驗證 → 查看 AI 結果 → 執行可遺忘權
