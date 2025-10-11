# MedSSI v2 – 病歷授權與 AI 分析原型

本版本重新架構 MedSSI 原型，聚焦在三個角色的互動：發行端（醫院）、驗證端（需要醫療資料的單位）以及拿卡人（病患）。系統以 FastAPI 後端模擬 Verifiable Credential (VC) 的發卡、選擇性揭露、可遺忘權與 IAL（Identity Assurance Level）檢核流程，並提供簡化的胃炎風險分析模組，展示在符合法規與隱私前提下的跨院協作。

## 系統架構重點
- **發行端 API**：醫院經 HIS 審核後呼叫 `/api/issuers/{issuer_id}/issue` 發卡，內容僅包含就診摘要與鏈上雜湊指標，敏感報告仍儲存於院內或 MyData 平台。
- **驗證端流程**：驗證端透過 `/api/verifiers/requests` 建立具體資料需求（含 IAL 等級、目的、可揭露欄位），請求有效期預設 30 分鐘以支持短期領藥或 AI 模型訓練。
- **拿卡人授權**：病患於錢包前端（可沿用第一版樣板）檢視請求，透過 `/api/wallet/consents` 選擇揭露範圍或拒絕。系統自動挑選符合 IAL 的 VC 並生成僅含必要欄位的 Verifiable Presentation。
- **AI 分析模組**：驗證端提交 VP 至 `/api/verifiers/verify` 後，後端以 deterministic 的胃炎趨勢引擎回傳風險分數與支援指標，可延伸至流感監測或反詐騙告警。
- **可遺忘權**：病患可透過 `/api/wallet/{holder_did}/forget` 刪除快取的 VC 與 VP，驗證端需重新取得授權方能存取資料。

## 目標情境
1. 病患於 A 醫院完成診斷，醫院發行 VC 並設定領藥有效期三日。
2. B 醫院或研究單位需要驗證病患特定診斷，建立一筆限定欄位、限定期限的驗證請求。
3. 病患檢視請求，選擇揭露「診斷碼 + 就醫日期」範圍並授權一次性存取。
4. 驗證端取得 VP 後，後端校驗憑證真偽、IAL 等級與未過期狀態，最後輸出胃炎趨勢風險評估。
5. 若病患撤銷授權或到期，驗證端需重新提交請求，避免長期留存個資。

## FastAPI Endpoints
| Method | Path | 說明 |
| --- | --- | --- |
| `POST` | `/api/issuers/{issuer_id}/issue?holder_did=...&ial=IAL2` | 發行醫療 VC，回傳憑證識別碼與內容摘要。 |
| `POST` | `/api/credentials/{credential_id}/revoke` | 醫院撤銷 VC（例如領藥完成或診斷更新）。 |
| `GET` | `/api/wallet/{holder_did}/credentials` | 病患查看錢包內有效 VC。 |
| `POST` | `/api/wallet/{holder_did}/forget` | 病患啟動可遺忘權，刪除快取 VC 與 VP。 |
| `POST` | `/api/verifiers/requests` | 驗證端提出資料需求，需提供目的、IAL 與可選擇性揭露欄位。 |
| `GET` | `/api/verifiers/{verifier_id}/requests` | 查看尚未到期的驗證請求。 |
| `POST` | `/api/wallet/consents` | 病患對特定請求做出決策，並在同意時產生 VP。 |
| `POST` | `/api/verifiers/verify` | 驗證端送交 VP，取得胃炎風險洞察與揭露欄位。 |

所有資料皆以 in-memory store 模擬，可依需求改寫成資料庫或上鏈儲存，並可整合 Trust Registry、FHIR Gateway 等模組以符合實際醫療法規。

## 快速體驗
1. **啟動後端**
   ```bash
   uvicorn backend.main:app --reload
   ```
2. **模擬流程**
   - 透過 `POST /api/issuers/{issuer}/issue` 為病患 DID 發卡。
   - 驗證端使用 `POST /api/verifiers/requests` 建立資料需求，包含多組 `allowed_scopes`（例如僅揭露診斷碼或加上醫師代碼）。
   - 病患以 `POST /api/wallet/consents` 同意並指定要揭露的 scope，系統自動檢查 IAL 並生成 VP。
   - 驗證端將 VP 丟給 `POST /api/verifiers/verify`，可獲得胃炎風險分數與指標。
   - 若病患想撤銷，呼叫 `POST /api/wallet/{holder}/forget` 立即刪除快取紀錄。

## 後續延伸方向
- **持續驗證**：支援驗證端在有效期限內多次呼叫並產生審計紀錄，或使用 OAuth 互通串接 NHI 雲端。
- **IAL 政策**：擴充 IAL 判斷邏輯，涵蓋生物辨識、FIDO2 等多因子驗證，並提供政策模組供衛福部審核。
- **AI 模組**：替換成真實的 SVM/深度學習模型或串接醫療大數據平台，加入異常偵測以協助反詐騙。
- **法規合規**：引入審計 API、MyData 授權通知與資料存取日誌，完整對應醫療法與個資法要求。

> 本原型著重流程設計與 API 互動示例，未包含前端畫面，可沿用先前版本或自行設計 React/Vue 錢包介面。
