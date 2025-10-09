# MedSSI 病歷授權與 AI 分析平台提案

## Proposal Summary
Taiwanese patients who shuttle between hospitals still rely on paper folders or repeat lab work because institutions lack a verifiable channel to exchange medical evidence. MedSSI reframes that workflow with a national digital-wallet playbook. Hospitals issue verifiable credentials (VCs) that store concise visit metadata plus an on-chain hash pointer, while detailed imaging and labs stay in clinical silos, the NHI cloud, or encrypted IPFS buckets. When a verifier—such as a regional hospital seeking a referral history or an academic AI lab—needs data, the wallet enumerates the requested scopes and runs identity assurance checks aligned with IAL2. Holder consent yields a verifiable presentation (VP) that selectively discloses only the diagnosis code, visit date, and any time-bound medication authorisations, preserving anonymity yet guaranteeing provenance. The resulting payload feeds an anonymised SVM model that tracks gastritis or influenza trends, supporting public-health surveillance and anti-fraud triggers. By combining consented sharing, selective disclosure, revocable proofs, and zero-knowledge attestations, the platform charts a privacy-preserving path to scalable cross-hospital collaboration in Taiwan.

## 構想說明／特色（500 字以內）
- **開發動機**：針對跨院就診必須重複檢查與攜帶紙本病歷的痛點，讓病患透過自主管理的健康錢包快速授權可信資料，降低病患、醫療院所與健保資源浪費。
- **創新亮點**：結合政府推動的數位皮夾與自我主權身分（SSI）政策，病患以去中心化識別碼（DID）管理自己的健康憑證，並可透過「可遺忘權」機制設定到期日或撤銷授權。
- **技術整合**：
  - 區塊鏈僅儲存病歷雜湊值或索引以確保不可竄改，敏感內容維持在院內 HIS、健保雲端或加密的 MyData/ IPFS 儲存體。
  - VC 由醫院簽章發行，VP 支援選擇性揭露、零知識證明與 IAL 風險評級；驗證端可引用信任登錄（Trust Registry）動態查詢醫療機構的簽章憑證。
  - FastAPI 後端串接 AI 模型、趨勢統計與審計日誌，對外提供可驗證 API，並支援 OAuth2 / FAPI 互操作。
- **使用者需求差異**：病患主導授權流程，可設定一次性揭露或時間窗（例如三日內領藥），醫療端仍可即時取得可信、去識別化資料片段，並紀錄審計軌跡以符合醫療法與個資法。

## 驗證端需求設計
- **資源申請流程**：驗證端（如轉診醫院或研究機構）需先經 IAL2+ 審核，確認其合法目的、資料保護員與資安措施，再由 Trust Registry 核發短期授權憑證。
- **可持續性驗證**：每筆 VP 內含時間戳與到期資訊，例如三日領藥或七日內檢驗報告有效，過期後需重新發起請求以避免過度曝光。
- **資料最小化**：驗證時僅能請求必要欄位（診斷碼、就醫日期、治療方案摘要等），並可搭配匿名化統計（如流感/胃炎趨勢）降低重新識別風險。
- **合規性檢核**：整合醫療法第 70 條、個資法與 MyData 共用規範，並透過審計 API 回傳授權紀錄，供主管機關或反詐騙小組追蹤。

## 發行端 API 與流程
1. 醫師完成診斷後，由院內 HIS 觸發 `/api/vc/issue`，內容包含患者 DID、診斷碼、就醫日期、治療摘要、可揭露欄位與授權期限。
2. 系統生成 VC，寫入鏈上雜湊並回傳給病患錢包；敏感附件（影像、檢驗報告）則儲存於 NHI 雲端或 IPFS，並以加密索引連結。
3. 發卡端可透過 `/api/vc/revoke` 或 `/api/vc/update` 處理撤銷、補發；前端顯示簽章與信任鏈，確保醫護人員與病患即時掌握狀態。

## 病患（拿卡人）體驗
- 延續既有錢包前端樣板，新增「授權期限」、「可遺忘權」與「精細欄位選擇」設定。
- 支援一次性 QR 掃描授權或遠端推播通知，並提供授權後的審計紀錄、撤銷入口與 MyData 下載連結。
- 引導式 UI 說明資料揭露風險、推薦揭露最小化範本，提升高齡族群或罕病病友的使用友善度。

## 選擇性揭露與撤銷機制
- 使用 BBS+ 或 SD-JWT 等可選擇性揭露憑證格式，讓 VP 僅透露必要欄位。
- 透過零知識證明展示「符合特定 ICD-10 類別」或「就診時間落於授權期間」，不洩漏具體身份。
- 可遺忘權由發卡端與病患共同觸發：病患在錢包端撤銷授權，系統同步更新信任登錄與審計軌跡，確保日後驗證端無法再通過驗證。

## 法規與反詐騙考量
- 對應醫療法、個資法與電信詐騙防制策略，提供機構內部稽核與主管機關查核的 API 端點。
- 引入異常偵測：AI 模型在分析流感或腸胃炎趨勢時，若發現異常請求量，透過訊息通知衛福部與數發部聯防。
- 強化多因素驗證（FIDO2 / T-Road）降低冒用風險，並支援 MyData 授權撤銷通知。

## 使用與功能說明
1. **啟動後端**：`uvicorn backend.main:app --reload`
2. **啟動前端**：於 `frontend/` 執行 `npm install`、`npm run dev`，即可透過錢包樣板操作。
3. **模擬流程**：
   - 「隱私授權」頁依序點擊發卡、發送資料請求、同意或拒絕，觀察 VC 與 VP 狀態。
   - 「驗證」頁可載入樣本 VP 並呼叫 `/api/did/vp/verify` 示範驗證流程與授權期限檢查。
   - 「AI 分析」頁於取得同意後載入匿名化特徵，呼叫 SVM 風險模型顯示胃炎/流感趨勢與反詐騙監測圖表。
4. **資料重設**：使用「隱私授權」頁的 reset API 或 `POST /api/consents/reset` 清除授權狀態，方便重複 Demo。

## 未來延伸
- 擴充 Trust Registry 與醫療機構名錄同步，支援可持續驗證與跨國醫療合作。
- 將 AI 分析模組拓展至慢性病管理與保險理賠詐欺偵測。
- 導入 FHIR / HL7 Interoperability Layer，提升與既有醫療系統整合度。
