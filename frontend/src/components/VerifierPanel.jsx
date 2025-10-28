import React, { useEffect, useMemo, useState } from 'react';
import { QRCodeCanvas } from 'qrcode.react';
import dayjs from 'dayjs';

const DEFAULT_FIELDS = {
  MEDICAL_RECORD: [
    'condition.code.coding[0].code',
    'condition.recordedDate',
    'managing_organization.value',
  ],
  MEDICATION_PICKUP: [
    'medication_dispense[0].medicationCodeableConcept.coding[0].code',
    'medication_dispense[0].days_supply',
    'medication_dispense[0].pickup_window_end',
  ],
  RESEARCH_ANALYTICS: ['condition.code.coding[0].code', 'encounter_summary_hash'],
};

function buildSamplePresentation(scope) {
  switch (scope) {
    case 'MEDICATION_PICKUP':
      return {
        'medication_dispense[0].medicationCodeableConcept.coding[0].code': 'A02BC05',
        'medication_dispense[0].days_supply': '30',
        'medication_dispense[0].pickup_window_end': dayjs().add(7, 'day').format('YYYY-MM-DD'),
      };
    case 'RESEARCH_ANALYTICS':
      return {
        'condition.code.coding[0].code': 'K29.7',
        'encounter_summary_hash': 'urn:sha256:samplehash123',
      };
    default:
      return {
        'condition.code.coding[0].code': 'K29.7',
        'condition.recordedDate': dayjs().format('YYYY-MM-DD'),
        'managing_organization.value': 'org:tph-001',
      };
  }
}

export function VerifierPanel({ client, verifierToken }) {
  const [verifierId, setVerifierId] = useState('did:example:research-lab');
  const [verifierName, setVerifierName] = useState('成大 AI 實驗室');
  const [purpose, setPurpose] = useState('胃炎風險研究');
  const [ial, setIal] = useState('NHI_CARD_PIN');
  const [scope, setScope] = useState('MEDICAL_RECORD');
  const [fieldsText, setFieldsText] = useState(DEFAULT_FIELDS.MEDICAL_RECORD.join(', '));
  const [validMinutes, setValidMinutes] = useState(5);
  const [session, setSession] = useState(null);
  const [qrPayload, setQrPayload] = useState(null);
  const [sessionError, setSessionError] = useState(null);
  const [presentationFields, setPresentationFields] = useState({});
  const [credentialId, setCredentialId] = useState('');
  const [holderDid, setHolderDid] = useState('did:example:patient-001');
  const [result, setResult] = useState(null);
  const [resultError, setResultError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setFieldsText(DEFAULT_FIELDS[scope].join(', '));
    setPresentationFields(buildSamplePresentation(scope));
  }, [scope]);

  const allowedFields = useMemo(
    () => fieldsText.split(',').map((field) => field.trim()).filter(Boolean),
    [fieldsText]
  );

  async function createSession() {
    setSessionError(null);
    setResult(null);
    setQrPayload(null);
    const response = await client.createVerificationCode(
      {
        verifierId,
        verifierName,
        purpose,
        ial_min: ial,
        scope,
        fields: allowedFields,
        validMinutes,
      },
      verifierToken
    );

    if (!response.ok) {
      setSessionError(`(${response.status}) ${response.detail}`);
      setSession(null);
      return;
    }

    setSession(response.data.session);
    setQrPayload(response.data.qr_payload);
    setPresentationFields(buildSamplePresentation(scope));
    setResult(null);
  }

  function updatePresentationField(field, value) {
    setPresentationFields((prev) => ({ ...prev, [field]: value }));
  }

  async function submitPresentation() {
    if (!session) {
      setResultError('請先建立驗證 Session');
      return;
    }
    if (!credentialId) {
      setResultError('請提供憑證 ID');
      return;
    }

    setLoading(true);
    setResultError(null);
    setResult(null);

    const response = await client.submitPresentation(
      {
        session_id: session.session_id,
        credential_id: credentialId,
        holder_did: holderDid,
        disclosed_fields: presentationFields,
      },
      verifierToken
    );

    setLoading(false);

    if (!response.ok) {
      setResultError(`(${response.status}) ${response.detail}`);
      return;
    }

    setResult(response.data);
  }

  async function purgeSession() {
    if (!session) {
      return;
    }
    await client.purgeSession(session.session_id, verifierToken);
    setSession(null);
    setQrPayload(null);
    setResult(null);
    setSessionError(null);
  }

  return (
    <section aria-labelledby="verifier-heading">
      <h2 id="verifier-heading">Step 3 – 驗證端</h2>
      <div className="alert info">
        驗證端需以 Access Token 產生一次性的掃碼 Session，支援病歷、領藥與研究三種範疇。
        提交 VP 後會同步回傳 AI Insight 與稽核資訊。
      </div>

      <div className="grid two">
        <div className="card">
          <label htmlFor="verifier-token">驗證端 Access Token</label>
          <input id="verifier-token" type="text" value={verifierToken} readOnly aria-readonly="true" />
          <small className="helper">沙盒預設 J3LdHEiVxmHBYJ6iStnmATLblzRkz2AC。</small>

          <label htmlFor="verifier-id">驗證者 DID</label>
          <input
            id="verifier-id"
            value={verifierId}
            onChange={(event) => setVerifierId(event.target.value)}
          />

          <label htmlFor="verifier-name">顯示名稱</label>
          <input
            id="verifier-name"
            value={verifierName}
            onChange={(event) => setVerifierName(event.target.value)}
          />

          <label htmlFor="purpose">用途說明</label>
          <input id="purpose" value={purpose} onChange={(event) => setPurpose(event.target.value)} />

          <label htmlFor="scope">驗證範圍</label>
          <select id="scope" value={scope} onChange={(event) => setScope(event.target.value)}>
            <option value="MEDICAL_RECORD">病歷摘要授權</option>
            <option value="MEDICATION_PICKUP">領藥流程驗證</option>
            <option value="RESEARCH_ANALYTICS">研究合作（匿名摘要）</option>
          </select>

          <label htmlFor="ial-required">所需 IAL</label>
          <select
            id="ial-required"
            value={ial}
            onChange={(event) => setIal(event.target.value)}
          >
            <option value="MYDATA_LIGHT">MYDATA_LIGHT</option>
            <option value="NHI_CARD_PIN">NHI_CARD_PIN</option>
            <option value="MOICA_CERT">MOICA_CERT</option>
          </select>

          <label htmlFor="allowed-fields">可揭露欄位</label>
          <textarea
            id="allowed-fields"
            value={fieldsText}
            onChange={(event) => setFieldsText(event.target.value)}
          />

          <label htmlFor="valid-minutes">QR 有效分鐘數</label>
          <input
            id="valid-minutes"
            type="number"
            min="1"
            max="5"
            value={validMinutes}
            onChange={(event) => setValidMinutes(event.target.value)}
          />

          <button type="button" onClick={createSession}>
            產生驗證 QR Code
          </button>
          <button type="button" className="secondary" onClick={purgeSession}>
            取消 Session
          </button>

          {sessionError ? <div className="alert error">{sessionError}</div> : null}
        </div>

        <div className="card">
          <h3>掃碼資訊</h3>
          {qrPayload ? (
            <div className="qr-container" aria-label="Verifier QR">
              <QRCodeCanvas value={qrPayload} size={192} includeMargin />
              <p>Session ID：{session.session_id}</p>
              <p>到期：{new Date(session.expires_at).toLocaleString()}</p>
            </div>
          ) : (
            <p>尚未建立驗證 Session。</p>
          )}
        </div>
      </div>

      <div className="card">
        <h3>提交 Verifiable Presentation</h3>
        <label htmlFor="credential-id">Credential ID</label>
        <input
          id="credential-id"
          value={credentialId}
          onChange={(event) => setCredentialId(event.target.value)}
          placeholder="例如 cred-xxxx"
        />

        <label htmlFor="holder-did">持卡者 DID</label>
        <input
          id="holder-did"
          value={holderDid}
          onChange={(event) => setHolderDid(event.target.value)}
        />

        <label>揭露欄位內容</label>
        {allowedFields.map((field) => (
          <div key={field} className="field-row">
            <span>{field}</span>
            <input
              value={presentationFields[field] ?? ''}
              onChange={(event) => updatePresentationField(field, event.target.value)}
            />
          </div>
        ))}

        <button type="button" onClick={submitPresentation} disabled={loading}>
          {loading ? '驗證中…' : '提交 VP'}
        </button>

        {resultError ? <div className="alert error">{resultError}</div> : null}
        {result ? (
          <div className="alert success" role="status">
            <p>驗證結果：{result.result.verified ? '通過' : '未通過'}</p>
            <p>AI 風險分數：{result.insight.gastritis_risk_score}</p>
            <details>
              <summary>完整回應</summary>
              <pre>{JSON.stringify(result, null, 2)}</pre>
            </details>
          </div>
        ) : null}
      </div>
    </section>
  );
}
