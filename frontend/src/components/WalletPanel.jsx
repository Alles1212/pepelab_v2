import React, { useMemo, useState } from 'react';
import { useSamplePayload } from '../hooks/useSamplePayload.js';

const ACTION_LABELS = {
  ACCEPT: '接受並寫入錢包',
  DECLINE: '拒絕此憑證',
  REVOKE: '撤銷（持卡者）',
  UPDATE: '更新 Payload',
};

function resolvePath(source, path) {
  if (!source) return null;
  const segments = path.split('.');
  let current = source;
  for (const segment of segments) {
    if (!segment) continue;
    const match = segment.match(/^(\w+)(\[(\d+)\])?$/);
    if (!match) {
      current = current?.[segment];
      continue;
    }
    const [, key, , index] = match;
    current = current?.[key];
    if (index !== undefined) {
      const idx = Number(index);
      if (!Array.isArray(current) || idx >= current.length) {
        return null;
      }
      current = current[idx];
    }
    if (current === undefined || current === null) {
      return null;
    }
  }
  if (current === undefined || current === null) {
    return null;
  }
  if (typeof current === 'object') {
    return JSON.stringify(current);
  }
  return String(current);
}

export function WalletPanel({ client, baseUrl, walletToken }) {
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
    const response = await client.getNonce(transactionId, walletToken);
    if (!response.ok) {
      setNonceError(`(${response.status}) ${response.detail}`);
      return;
    }
    setNonceInfo(response.data);
  }

  function parsePayloadDraft() {
    if (!payloadDraft) {
      return null;
    }
    try {
      return JSON.parse(payloadDraft);
    } catch (error) {
      setActionError('Payload 不是合法的 JSON');
      return null;
    }
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
        const parsed = parsePayloadDraft();
        if (!parsed) {
          setLoading(false);
          return;
        }
        payload = parsed;
      }
    }

    const disclosures = {};
    const disclosureSource = payload || nonceInfo?.payload_template;
    if (nonceInfo?.disclosure_policies && disclosureSource) {
      nonceInfo.disclosure_policies.forEach((policy) => {
        policy.fields.forEach((field) => {
          const value = resolvePath(disclosureSource, field);
          if (value !== null && value !== undefined) {
            disclosures[field] = value;
          }
        });
      });
    }

    const response = await client.actOnCredential(
      credentialId,
      {
        action,
        holder_did: holderDid,
        payload,
        disclosures,
      },
      walletToken
    );

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
    const response = await client.listHolderCredentials(holderDid, walletToken);
    if (!response.ok) {
      setListError(`(${response.status}) ${response.detail}`);
      setCredentials([]);
      return;
    }
    setCredentials(response.data);
  }

  async function forgetHolderData() {
    setForgetResult(null);
    const response = await client.forgetHolder(holderDid, walletToken);
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
        錢包需驗證 Wallet Access Token（預設 wallet-sandbox-token），系統將記錄 selective disclosure。
        可透過下方按鈕檢視錢包內的憑證並行使可遺忘權。
      </div>

      <div className="grid two">
        <div className="card">
          <label htmlFor="wallet-token">Wallet Access Token</label>
          <input id="wallet-token" value={walletToken} readOnly aria-readonly="true" />

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
          <h3>揭露政策與範例</h3>
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
              {nonceInfo.payload_template ? (
                <details>
                  <summary>發行端提供的 FHIR Template</summary>
                  <pre>{JSON.stringify(nonceInfo.payload_template, null, 2)}</pre>
                </details>
              ) : null}
            </>
          ) : (
            <p>請先輸入交易編號取得 nonce。</p>
          )}
        </div>
      </div>

      <div className="card">
        <h3>錢包內的憑證</h3>
        <button type="button" onClick={listWalletCredentials}>
          查看我的憑證列表
        </button>
        {listError ? <div className="alert error">{listError}</div> : null}
        {credentials.length ? (
          <ul>
            {credentials.map((credential) => (
              <li key={credential.credential_id}>
                <strong>{credential.credential_id}</strong> – 狀態：{credential.status} –
                主用途：{credential.primary_scope}
              </li>
            ))}
          </ul>
        ) : (
          <p>尚無資料或尚未載入。</p>
        )}
        <button type="button" className="secondary" onClick={forgetHolderData}>
          行使可遺忘權（清除錢包資料）
        </button>
        {forgetResult ? (
          <pre>{JSON.stringify(forgetResult, null, 2)}</pre>
        ) : null}
      </div>
    </section>
  );
}
