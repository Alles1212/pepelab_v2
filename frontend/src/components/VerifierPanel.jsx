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
};

function buildSamplePresentation(scope) {
  if (scope === 'MEDICAL_RECORD') {
    return {
      'condition.code.coding[0].code': 'K29.7',
      'condition.recordedDate': dayjs().format('YYYY-MM-DD'),
      'managing_organization.value': 'org:tph-001',
    };
  }
  return {
    'medication_dispense[0].medicationCodeableConcept.coding[0].code': 'A02BC05',
    'medication_dispense[0].days_supply': '30',
    'medication_dispense[0].pickup_window_end': dayjs().add(7, 'day').format('YYYY-MM-DD'),
  };
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
    const response = await client.createVerificationCode(
      {
        verifier_id: verifierId,
        verifier_name: verifierName,
        purpose,
        ial,
        scope,
        fields: allowedFields.join(','),
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
        scope,
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
    setResult(null);
    setSessionError(null);
  }

  const qrPayload = session ? `medssi://verification?token=${session.qr_token}` : null;

  return (
    <section aria-labelledby="verifier-heading">
      <h2 id="verifier-heading">Step 3 – 驗證端</h2>
      <div className="alert info">
        驗證端可依用途選擇病歷或領藥流程。系統會檢查 IAL、欄位與 FHIR Payload 是否符合授權範圍，再提供 AI Insight。
      </div>

      <div className="grid two">
        <div className="card">
          <label htmlFor="verifier-token">驗證端 Access Token</label>
          <input id="verifier-token" type="text" value={verifierToken} readOnly aria-readonly="true" />
          <small className="helper">沙盒預設為 verifier-sandbox-token，請勿在公開環境顯示實際 Token。</small>

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
            建立驗證 QR
          </button>
          <button type="button" className="secondary" onClick={purgeSession}>
            清除 Session
          </button>
          {sessionError ? <div className="alert error">{sessionError}</div> : null}
        </div>

        <div className="card">
          <h3>提交 VP</h3>
          <label htmlFor="credential-id">Credential ID</label>
          <input
            id="credential-id"
            value={credentialId}
            onChange={(event) => setCredentialId(event.target.value)}
            placeholder="請輸入錢包中的 credential_id"
          />

          <label htmlFor="holder-did-verifier">Holder DID</label>
          <input
            id="holder-did-verifier"
            value={holderDid}
            onChange={(event) => setHolderDid(event.target.value)}
          />

          {allowedFields.map((field) => (
            <div key={field}>
              <label htmlFor={`field-${field}`}>{field}</label>
              <input
                id={`field-${field}`}
                value={presentationFields[field] ?? ''}
                onChange={(event) => updatePresentationField(field, event.target.value)}
              />
            </div>
          ))}

          <button type="button" onClick={submitPresentation} disabled={loading}>
            {loading ? '送出中…' : '送出 Verifiable Presentation'}
          </button>

          <button
            type="button"
            className="secondary"
            onClick={() => setPresentationFields(buildSamplePresentation(scope))}
          >
            載入示例資料
          </button>

          {resultError ? <div className="alert error">{resultError}</div> : null}
        </div>
      </div>

      {session ? (
        <div className="card">
          <h3>驗證 QR</h3>
          <p>Session：{session.session_id}</p>
          <div className="qr-container" aria-label="驗證 QR Code">
            <QRCodeCanvas value={qrPayload} size={192} includeMargin />
          </div>
          <pre>{JSON.stringify(session, null, 2)}</pre>
        </div>
      ) : null}

      {result ? (
        <div className="card">
          <h3>AI Insight</h3>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </div>
      ) : null}
    </section>
  );
}
