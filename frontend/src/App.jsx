import React, { useMemo, useState } from 'react';
import { IssuerPanel } from './components/IssuerPanel.jsx';
import { WalletPanel } from './components/WalletPanel.jsx';
import { VerifierPanel } from './components/VerifierPanel.jsx';
import { createClient } from './api/client.js';

const DEFAULT_BASE_URL = import.meta.env.VITE_MEDSSI_API || 'http://localhost:8000';

export default function App() {
  const [baseUrl, setBaseUrl] = useState(DEFAULT_BASE_URL);
  const [issuerToken, setIssuerToken] = useState('koreic2ZEFZ2J4oo2RaZu58yGVXiqDQy');
  const [walletToken, setWalletToken] = useState('wallet-sandbox-token');
  const [verifierToken, setVerifierToken] = useState('J3LdHEiVxmHBYJ6iStnmATLblzRkz2AC');
  const [resetMessage, setResetMessage] = useState(null);

  const client = useMemo(() => createClient(baseUrl), [baseUrl]);

  async function resetSandbox() {
    const response = await client.resetSandbox(issuerToken);
    if (!response.ok) {
      setResetMessage(`重設失敗：(${response.status}) ${response.detail}`);
      return;
    }
    setResetMessage(`已於 ${new Date(response.data.timestamp).toLocaleString()} 重設沙盒資料。`);
  }

  return (
    <div>
      <header style={{ marginBottom: '2rem' }}>
        <h1>MedSSI Sandbox – FHIR 病歷授權與領藥驗證</h1>
        <p>
          整合 MyData IAL2、FHIR Verifiable Credential 與選擇性揭露，示範醫院發卡、病患授權、
          藥局 / 研究單位驗證的端到端流程，並支援可遺忘權與 AI Insight。
        </p>
        <div className="card">
          <label htmlFor="base-url">API Base URL</label>
          <input
            id="base-url"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
          />
          <div className="grid three">
            <div>
              <label htmlFor="issuer-token-input">發行端 Access Token</label>
              <input
                id="issuer-token-input"
                value={issuerToken}
                onChange={(event) => setIssuerToken(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="wallet-token-input">錢包 Access Token</label>
              <input
                id="wallet-token-input"
                value={walletToken}
                onChange={(event) => setWalletToken(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="verifier-token-input">驗證端 Access Token</label>
              <input
                id="verifier-token-input"
                value={verifierToken}
                onChange={(event) => setVerifierToken(event.target.value)}
              />
            </div>
          </div>
          <button type="button" className="secondary" onClick={resetSandbox}>
            重設沙盒資料（清除憑證與 Session）
          </button>
          {resetMessage ? <div className="alert info">{resetMessage}</div> : null}
        </div>
      </header>

      <main>
        <IssuerPanel client={client} issuerToken={issuerToken} baseUrl={baseUrl} />
        <WalletPanel client={client} baseUrl={baseUrl} walletToken={walletToken} />
        <VerifierPanel client={client} verifierToken={verifierToken} />
      </main>
    </div>
  );
}
