import React, { useMemo, useState } from 'react';
import { useSamplePayload } from '../hooks/useSamplePayload.js';

const ACTION_LABELS = {
  ACCEPT: '接受並寫入錢包',
  DECLINE: '拒絕此憑證',
  REVOKE: '撤銷（持卡者）',
  UPDATE: '更新 Payload',
};

export function WalletPanel({ client, baseUrl }) {
  const [transactionId, setTransactionId] = useState('');
  const [nonceInfo, setNonceInfo] = useState(null);
  const [nonceError, setNonceError] = useState(null);
  const [holderDid, setHolderDid] = useState('did:example:patient-001');
  const [action, setAction] = useState('ACCEPT');
  const [payloadDraft, setPayloadDraft] = useState('');
  const [actionResult, setActionResult] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [credentials, setCredentials] = useState([]);
  const [listError, setListError] = useState(null);
  const [forgetResult, setForgetResult] = useState(null);
  const samplePayloadBuilder = useSamplePayload(holderDid);

  const credentialId = useMemo(() => nonceInfo?.credential_id ?? '', [nonceInfo]);

  async function fetchNonce() {
    setNonceError(null);
    setNonceInfo(null);
    if (!transactionId) {
      setNonceError('請輸入交易編號');
      return;
    }
    const response = await client.getNonce(transactionId);
    if (!response.ok) {
      setNonceError(`(${response.status}) ${response.detail}`);
      return;
    }
    setNonceInfo(response.data);
  }

  async function runAction() {
    if (!credentialId) {
      setActionError('請先取得 nonce');
      return;
    }
    setLoading(true);
    setActionError(null);
    setActionResult(null);

    let payload = undefined;
    if (action === 'ACCEPT' || action === 'UPDATE') {
      if (nonceInfo?.mode === 'WITHOUT_DATA' || action === 'UPDATE') {
        if (!payloadDraft) {
          setLoading(false);
          setActionError('此憑證需要提供 FHIR Payload');
          return;
        }
        try {
          payload = JSON.parse(payloadDraft);
        } catch (error) {
          setLoading(false);
          setActionError('Payload 不是合法的 JSON');
          return;
        }
      }
    }

    const response = await client.actOnCredential(credentialId, {
      action,
      holder_did: holderDid,
      payload,
    });

    setLoading(false);
    if (!response.ok) {
      setActionError(`(${response.status}) ${response.detail}`);
      return;
    }
    setActionResult(response.data);
  }

  async function loadSamplePayload() {
    const sample = samplePayloadBuilder();
    setPayloadDraft(JSON.stringify(sample, null, 2));
  }

  async function listWalletCredentials() {
    setListError(null);
    const response = await client.listHolderCredentials(holderDid);
    if (!response.ok) {
      setListError(`(${response.status}) ${response.detail}`);
      setCredentials([]);
      return;
    }
    setCredentials(response.data);
  }

  async function forgetHolderData() {
    setForgetResult(null);
    const response = await client.forgetHolder(holderDid);
    if (!response.ok) {
      setForgetResult({ error: `(${response.status}) ${response.detail}` });
      return;
    }
    setForgetResult(response.data);
    setCredentials([]);
    setNonceInfo(null);
    setActionResult(null);
    setPayloadDraft('');
  }

  return (
    <section aria-labelledby="wallet-heading">
      <h2 id="wallet-heading">Step 2 – 病患錢包</h2>
      <p className="badge">API Base URL：{baseUrl}</p>
      <div className="alert info">
        錢包先以交易編號查詢 nonce 與揭露政策，再決定是否接受。此區亦示範可遺忘權與憑證列表。
      </div>

      <div className="grid two">
        <div className="card">
          <label htmlFor="transaction-id">交易編號 (transaction_id)</label>
          <input
            id="transaction-id"
            value={transactionId}
            onChange={(event) => setTransactionId(event.target.value)}
            placeholder="輸入發卡後回傳的 transaction_id"
          />
          <button type="button" onClick={fetchNonce}>
            取得 nonce
          </button>
          {nonceError ? <div className="alert error">{nonceError}</div> : null}

          {nonceInfo ? (
            <div className="alert success" role="status">
              已取得憑證 {nonceInfo.credential_id}，狀態：{nonceInfo.status}
            </div>
          ) : null}

          <label htmlFor="holder-did-wallet">我的 DID</label>
          <input
            id="holder-did-wallet"
            value={holderDid}
            onChange={(event) => setHolderDid(event.target.value)}
          />

          <label htmlFor="action-select">操作</label>
          <select
            id="action-select"
            value={action}
            onChange={(event) => setAction(event.target.value)}
          >
            {Object.entries(ACTION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>

          <label htmlFor="payload-draft">FHIR Payload (必要時填寫)</label>
          <textarea
            id="payload-draft"
            value={payloadDraft}
            onChange={(event) => setPayloadDraft(event.target.value)}
            placeholder="需要補資料時請貼上 FHIR JSON"
          />
          <button type="button" className="secondary" onClick={loadSamplePayload}>
            載入示例 Payload
          </button>

          <button type="button" onClick={runAction} disabled={loading}>
            {loading ? '送出中…' : ACTION_LABELS[action]}
          </button>

          {actionError ? <div className="alert error">{actionError}</div> : null}
          {actionResult ? (
            <div className="alert success" role="status">
              操作完成，最新狀態：{actionResult.status}
            </div>
          ) : null}
        </div>

        <div className="card">
          <h3>已揭露欄位</h3>
          {nonceInfo ? (
            <>
              <p>模式：{nonceInfo.mode}</p>
              <p>身份保證等級：{nonceInfo.ial}</p>
              <p>到期：{new Date(nonceInfo.expires_at).toLocaleString()}</p>
              {nonceInfo.disclosure_policies.map((policy) => (
                <div key={policy.scope} className="alert info">
                  <strong>{policy.scope}</strong>
                  <ul>
                    {policy.fields.map((field) => (
                      <li key={field}>{field}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </>
          ) : (
            <p>尚未取得 nonce</p>
          )}

          <h3>錢包工具</h3>
          <button type="button" onClick={listWalletCredentials}>
            查看我的憑證
          </button>
          <button type="button" className="secondary" onClick={forgetHolderData}>
            清除我的資料（可遺忘權）
          </button>
          {listError ? <div className="alert error">{listError}</div> : null}
          {forgetResult ? (
            forgetResult.error ? (
              <div className="alert error">{forgetResult.error}</div>
            ) : (
              <div className="alert success">
                已刪除 {forgetResult.credentials_removed} 筆憑證與 {forgetResult.presentations_removed} 筆 VP。
              </div>
            )
          ) : null}
        </div>
      </div>

      {credentials.length ? (
        <div className="card">
          <h3>錢包憑證列表</h3>
          <pre>{JSON.stringify(credentials, null, 2)}</pre>
        </div>
      ) : null}

      {actionResult ? (
        <div className="card">
          <h3>最新憑證狀態</h3>
          <pre>{JSON.stringify(actionResult, null, 2)}</pre>
        </div>
      ) : null}
    </section>
  );
}
