# MedSSI Sandbox v2 – FHIR 病歷授權與領藥流程

本版本依照最新需求重構了 API 與前端介面，並整合實務場景與法規需求：

* **身份保證等級（IAL）近似 MyData / 健保規範**：提供 `MYDATA_LIGHT`、`NHI_CARD_PIN`、`MOICA_CERT` 三個層級，不再使用生物辨識。
* **FHIR 結構化 Payload**：Credential 內含 `Condition` 與 `MedicationDispense` 摘要，並以 FHIR path 定義選擇性揭露欄位。
* **病歷授權與領藥流程完全分流**：後端以 `DisclosureScope`（`MEDICAL_RECORD`、`MEDICATION_PICKUP`）區分流程，前端用大字體與按鈕導覽兩條路徑。
* **可遞忘權與 Session 清除**：錢包可呼叫 `/api/wallet/{holder_did}/forget` 一鍵清除持有資料，驗證端可刪除 session。
* **長老友善介面**：採分步點面板、範例按鈕、自動填入日期、ARIA live 區域，降低操作複雜度並方便陪同家屬示範。
* **Access Token 與 QR 有效期**：所有發行端、驗證端 API 需附帶 `Authorization: Bearer <token>`，並強制 QR code 於 5 分鐘內使用。

## 系統架構

```
Issuer (Hospital) ──QR──> Wallet (Patient) ──VP──> Verifier (Research / Pharmacy)
             │                        │                           │
             │                        │                           ├─ AI Insight Engine
             │                        └─ 可遞忘權 API                │
             └─ FastAPI Issuance ─────┘─ Verification Session Store
```

後端採 FastAPI + in-memory store (`backend/main.py`、`backend/store.py`)。選擇性揭露政策以 `DisclosurePolicy` 列表儲存，欄位使用 FHIR 路徑；驗證流程檢查 IAL、scope、欄位範圍與資料一致性，再交由 `InsightEngine` 輸出胃炎趨勢或領藥提醒。

## API 說明

| Method   | Path                                      | 說明                                       |
| -------- | ----------------------------------------- | ---------------------------------------- |
| `POST`   | `/api/qrcode/data`                        | 發行含 FHIR 資料的憲證，需提供 disclosure policies。  |
| `POST`   | `/api/qrcode/nodata`                      | 發行空白憲證（僅含 scope 與欄位），供錢包後補資料。            |
| `GET`    | `/api/credential/nonce?transactionId=...` | 錢包以交易 ID 取得 nonce、模式與各 scope 的揭露欄位。      |
| `PUT`    | `/api/credential/{credential_id}/action`  | 錢包接受、拒絕、撤銷或更新憲證資料。                       |
| `GET`    | `/api/wallet/{holder_did}/credentials`    | 查詢某 Holder DID 持有的憲證列表。                  |
| `POST`   | `/api/credentials/{credential_id}/revoke` | 醫院主動撤銷憲證。                                |
| `DELETE` | `/api/credentials/{credential_id}`        | 從系統移除指定憲證（可配合遞忘權）。                       |
| `DELETE` | `/api/wallet/{holder_did}/forget`         | 清除某 Holder 的所有憲證、VP、驗證結果。                |
| `GET`    | `/api/did/vp/code`                        | 驗證端取得 QR Code，必須指定 scope 與欄位。            |
| `POST`   | `/api/did/vp/result`                      | 接收 VP，驗證 scope、欄位與 FHIR 值後回傳 AI insight。 |
| `DELETE` | `/api/did/vp/session/{session_id}`        | 清除驗證 session 及其結果。                       |

> ⚠️ 發行端 API 需附帶 `Authorization: Bearer issuer-sandbox-token`（可用環境變數 `MEDSSI_ISSUER_TOKEN` 覆寫）；驗證端則為 `Authorization: Bearer verifier-sandbox-token`。

## 快速啟動

1. 啟動後端

   ```bash
   uvicorn backend.main:app --reload
   ```

2. 開啟前端

   ```bash
   python -m http.server 5173 --directory frontend
   ```

   或直接打開 `frontend/index.html`

3. 示範流程：

   * 發卡 → 接收憲證 → 驗證 → 查看 AI 結果 → 執行可遞忘權
