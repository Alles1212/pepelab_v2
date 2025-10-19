import React, { useMemo, useState } from 'react';
import { IssuerPanel } from './components/IssuerPanel.jsx';
import { WalletPanel } from './components/WalletPanel.jsx';
import { VerifierPanel } from './components/VerifierPanel.jsx';
import { createClient } from './api/client.js';

const DEFAULT_BASE_URL = import.meta.env.VITE_MEDSSI_API || 'http://localhost:8000';

export default function App() {
  const [baseUrl, setBaseUrl] = useState(DEFAULT_BASE_URL);
  const [issuerToken, setIssuerToken] = useState('issuer-sandbox-token');
  const [verifierToken, setVerifierToken] = useState('verifier-sandbox-token');

  const client = useMemo(() => createClient(baseUrl), [baseUrl]);

  return (
    <div>
      <header style={{ marginBottom: '2rem' }}>
        <h1>MedSSI Sandbox – FHIR 病歷授權與領藥驗證</h1>
        <p>
          將政府數位皮夾流程、MyData 身份保證（IAL）與 FHIR 可驗證憑證整合，示範跨院病歷授權、領藥驗證與 AI 風險分析。以下介面以高對比與大字體呈現，方便長者與陪同家屬操作。
        </p>
        <div className="card">
          <label htmlFor="base-url">API Base URL</label>
          <input
            id="base-url"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
          />
          <div className="grid two">
            <div>
              <label htmlFor="issuer-token-input">發行端 Access Token</label>
              <input
                id="issuer-token-input"
                value={issuerToken}
                onChange={(event) => setIssuerToken(event.target.value)}
              />
              <small className="helper">預設 issuer-sandbox-token，可依環境替換。</small>
            </div>
            <div>
              <label htmlFor="verifier-token-input">驗證端 Access Token</label>
              <input
                id="verifier-token-input"
                value={verifierToken}
                onChange={(event) => setVerifierToken(event.target.value)}
              />
              <small className="helper">預設 verifier-sandbox-token。</small>
            </div>
          </div>
        </div>
      </header>

      <main>
        <IssuerPanel client={client} issuerToken={issuerToken} baseUrl={baseUrl} />
        <WalletPanel client={client} baseUrl={baseUrl} />
        <VerifierPanel client={client} verifierToken={verifierToken} />
      </main>
    </div>
  );
}
