const API_BASE =
  window.location.origin.includes('localhost') || window.location.origin.includes('127.0.0.1')
    ? 'http://localhost:8000'
    : window.location.origin;

const STORAGE_AVAILABLE = (() => {
  try {
    const key = '__medssi_storage_test__';
    window.localStorage.setItem(key, '1');
    window.localStorage.removeItem(key);
    return true;
  } catch (error) {
    return false;
  }
})();

const TOKEN_STORAGE_KEYS = {
  issuer: 'medssiIssuerToken',
  verifier: 'medssiVerifierToken',
};

function loadToken(role, fallback) {
  if (STORAGE_AVAILABLE) {
    const stored = window.localStorage.getItem(TOKEN_STORAGE_KEYS[role]);
    if (stored) return stored;
  }
  return fallback;
}

function persistToken(role, value) {
  if (STORAGE_AVAILABLE) {
    window.localStorage.setItem(TOKEN_STORAGE_KEYS[role], value);
  }
}

const tokens = {
  issuer: loadToken('issuer', 'issuer-sandbox-token'),
  verifier: loadToken('verifier', 'verifier-sandbox-token'),
};

const today = new Date();
const iso = (date) => date.toISOString().split('T')[0];
const plusDays = (date, days) => {
  const result = new Date(date);
  result.setDate(result.getDate() + days);
  return result;
};

const defaultRecordedDate = iso(today);
const defaultIssuedOn = iso(today);
const defaultConsent = iso(plusDays(today, 180));
const defaultPickup = iso(plusDays(today, 7));

const setIfExists = (selector, value) => {
  const el = document.querySelector(selector);
  if (el && value !== undefined && value !== null) {
    el.value = value;
  }
};

setIfExists('#issuer-token-form input[name="issuerToken"]', tokens.issuer);
setIfExists('#verifier-token-form input[name="verifierToken"]', tokens.verifier);
setIfExists('input[name="recordedDate"]', defaultRecordedDate);
setIfExists('input[name="issuedOn"]', defaultIssuedOn);
setIfExists('input[name="consentExpires"]', defaultConsent);
setIfExists('input[name="pickupWindow"]', defaultPickup);
setIfExists('#presentation-medical-form input[name="field-condition.recordedDate"]', defaultRecordedDate);
setIfExists('#presentation-medication-form input[name="field-medication_dispense[0].pickup_window_end"]', defaultPickup);

async function requestJson(url, options = {}) {
  const { accessToken, headers: customHeaders, ...rest } = options;
  const headers = { ...(customHeaders || {}) };
  if (rest.body !== undefined && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }
  const response = await fetch(url, { ...rest, headers });
  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch (err) {
    data = { raw: text };
  }
  if (!response.ok) {
    throw { status: response.status, data };
  }
  return data;
}

function renderJson(targetId, payload) {
  const el = document.getElementById(targetId);
  if (!el) return;
  el.textContent = JSON.stringify(payload, null, 2);
}

function bindForm(formId, handler) {
  const form = document.getElementById(formId);
  if (!form) return;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submitButton = form.querySelector('button[type="submit"]');
    const original = submitButton ? submitButton.textContent : '';
    if (submitButton) submitButton.textContent = '處理中...';
    try {
      await handler(new FormData(form), form);
    } catch (error) {
      console.error(error);
    } finally {
      if (submitButton) submitButton.textContent = original || '送出';
    }
  });
}

function bindTokenForm(formId, role, statusId) {
  const form = document.getElementById(formId);
  if (!form) return;
  const input = form.querySelector('input[type="password"]');
  const status = statusId ? document.getElementById(statusId) : null;
  const stored =
    STORAGE_AVAILABLE && window.localStorage.getItem(TOKEN_STORAGE_KEYS[role]) ? true : false;
  if (status) {
    status.textContent = stored ? '已載入儲存的 Token。' : '使用預設 Token。';
  }
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!input) return;
    const value = input.value.trim();
    if (!value) {
      if (status) status.textContent = 'Token 不可為空值。';
      input.focus();
      return;
    }
    tokens[role] = value;
    persistToken(role, value);
    if (status) status.textContent = 'Token 已更新並儲存。';
  });
}

function gatherPolicies(form) {
  const policies = [];
  form.querySelectorAll('fieldset[data-scope]').forEach((fieldset) => {
    const scope = fieldset.dataset.scope;
    const description = fieldset.dataset.description || '';
    const fields = Array.from(fieldset.querySelectorAll('input[type="checkbox"]:checked'))
      .map((input) => input.value.trim())
      .filter(Boolean);
    if (scope && fields.length) {
      policies.push({ scope, fields, description });
    }
  });
  return policies;
}

function buildCredentialPayload(formData) {
  const conditionCode = formData.get('conditionCode');
  const conditionSystem = formData.get('conditionCodeSystem');
  const conditionDisplay = formData.get('conditionDisplay');

  const payload = {
    condition: {
      resourceType: 'Condition',
      id: formData.get('conditionId'),
      code: {
        coding: [
          {
            system: conditionSystem,
            code: conditionCode,
            display: conditionDisplay || undefined,
          },
        ].filter((item) => item.code),
        text: conditionDisplay || undefined,
      },
      recordedDate: formData.get('recordedDate'),
      encounter: {
        system: formData.get('encounterSystem'),
        value: formData.get('encounterId'),
      },
      subject: {
        system: formData.get('subjectSystem'),
        value: formData.get('subjectId'),
      },
    },
    encounter_summary_hash: formData.get('encounterHash'),
    managing_organization: {
      system: formData.get('orgSystem'),
      value: formData.get('orgId'),
      assigner: formData.get('orgAssigner') || undefined,
    },
    issued_on: formData.get('issuedOn'),
    consent_expires_on: formData.get('consentExpires') || null,
    medication_dispense: [],
  };

  const medCode = formData.get('medicationCode');
  const medDays = formData.get('medicationDays');
  if (medCode && medDays) {
    const medicationEntry = {
      resourceType: 'MedicationDispense',
      id: formData.get('medicationId') || 'disp-001',
      medicationCodeableConcept: {
        coding: [
          {
            system: formData.get('medicationSystem') || 'http://www.whocc.no/atc',
            code: medCode,
            display: formData.get('medicationDisplay') || undefined,
          },
        ].filter((item) => item.code),
        text: formData.get('medicationDisplay') || undefined,
      },
      quantity_text: formData.get('medicationQuantity') || '30 錠',
      days_supply: Number(medDays),
      pickup_window_end: formData.get('pickupWindow') || null,
    };
    const performerSystem = formData.get('performerSystem');
    const performerValue = formData.get('performerValue');
    if (performerSystem && performerValue) {
      medicationEntry.performer = {
        system: performerSystem,
        value: performerValue,
      };
    }
    payload.medication_dispense.push(medicationEntry);
  }

  return payload;
}

function collectFields(form) {
  return Array.from(form.querySelectorAll('input[type="checkbox"]:checked'))
    .map((input) => input.value.trim())
    .filter(Boolean);
}

function gatherDisclosedFields(formData) {
  const disclosed = {};
  for (const [key, value] of formData.entries()) {
    if (key.startsWith('field-') && value) {
      const path = key.replace('field-', '');
      disclosed[path] = value;
    }
  }
  return disclosed;
}

function populateWalletPayloadSample() {
  const issueForm = document.getElementById('issue-data-form');
  if (!issueForm) return;
  const formData = new FormData(issueForm);
  const payload = buildCredentialPayload(formData);
  const textarea = document.querySelector('#credential-action-form textarea[name="payload"]');
  if (textarea) {
    textarea.value = JSON.stringify(payload, null, 2);
  }
}

function populateIssueSample() {
  const form = document.getElementById('issue-data-form');
  if (!form) return;
  const set = (name, value) => {
    const input = form.querySelector(`[name="${name}"]`);
    if (input) input.value = value;
  };
  set('issuerId', 'hospital-nhi-001');
  set('holderDid', 'did:example:patient123');
  set('conditionId', 'cond-20240501');
  set('conditionCodeSystem', 'http://hl7.org/fhir/sid/icd-10');
  set('conditionCode', 'K29.70');
  set('conditionDisplay', '慢性胃炎');
  set('recordedDate', defaultRecordedDate);
  set('encounterSystem', 'urn:oid:2.16.886.101.20003');
  set('encounterId', 'enc-874563');
  set('subjectSystem', 'urn:tw.gov.mohw:nhiid');
  set('subjectId', 'A123456789');
  set('encounterHash', 'hash-visit-001');
  set('orgSystem', 'urn:tw.gov.mohw:hospital');
  set('orgId', '1234567890');
  set('orgAssigner', '臺北綜合醫院');
  set('issuedOn', defaultIssuedOn);
  set('consentExpires', defaultConsent);
  set('medicationId', 'disp-001');
  set('medicationSystem', 'http://www.whocc.no/atc');
  set('medicationCode', 'A02BC');
  set('medicationDisplay', 'Proton Pump Inhibitor');
  set('medicationQuantity', '30 錠');
  set('medicationDays', '14');
  set('pickupWindow', defaultPickup);
  set('performerSystem', 'urn:tw.gov.mohw:pharmacy');
  set('performerValue', 'pharm-7788');
}

function populatePresentationSample(scope) {
  const issueForm = document.getElementById('issue-data-form');
  if (!issueForm) return;
  const formData = new FormData(issueForm);
  if (scope === 'MEDICAL_RECORD') {
    setIfExists('#presentation-medical-form input[name="field-condition.code.coding[0].code"]', formData.get('conditionCode'));
    setIfExists('#presentation-medical-form input[name="field-condition.recordedDate"]', formData.get('recordedDate'));
    setIfExists('#presentation-medical-form input[name="field-managing_organization.value"]', formData.get('orgId'));
  }
  if (scope === 'MEDICATION_PICKUP') {
    setIfExists('#presentation-medication-form input[name="field-medication_dispense[0].medicationCodeableConcept.coding[0].code"]', formData.get('medicationCode'));
    setIfExists('#presentation-medication-form input[name="field-medication_dispense[0].days_supply"]', formData.get('medicationDays'));
    setIfExists('#presentation-medication-form input[name="field-medication_dispense[0].pickup_window_end"]', formData.get('pickupWindow'));
  }
}

bindTokenForm('issuer-token-form', 'issuer', 'issuer-token-status');
bindTokenForm('verifier-token-form', 'verifier', 'verifier-token-status');

bindForm('issue-data-form', async (formData, form) => {
  const disclosurePolicies = gatherPolicies(form);
  if (!disclosurePolicies.length) {
    renderJson('issue-data-response', { error: '請至少勾選一個揭露欄位' });
    return;
  }
  const payload = buildCredentialPayload(formData);
  const requestPayload = {
    issuer_id: formData.get('issuerId'),
    holder_did: formData.get('holderDid'),
    ial: formData.get('ial'),
    holder_hint: formData.get('holderHint') || null,
    payload,
    disclosure_policies: disclosurePolicies,
  };
  try {
    const data = await requestJson(`${API_BASE}/api/qrcode/data`, {
      method: 'POST',
      body: JSON.stringify(requestPayload),
      accessToken: tokens.issuer,
    });
    renderJson('issue-data-response', data);
  } catch (error) {
    renderJson('issue-data-response', error);
  }
});

bindForm('issue-nodata-form', async (formData, form) => {
  const disclosurePolicies = gatherPolicies(form);
  if (!disclosurePolicies.length) {
    renderJson('issue-nodata-response', { error: '請至少勾選一個揭露欄位' });
    return;
  }
  const requestPayload = {
    issuer_id: formData.get('issuerId'),
    ial: formData.get('ial'),
    holder_hint: formData.get('holderHint') || null,
    disclosure_policies: disclosurePolicies,
  };
  try {
    const data = await requestJson(`${API_BASE}/api/qrcode/nodata`, {
      method: 'POST',
      body: JSON.stringify(requestPayload),
      accessToken: tokens.issuer,
    });
    renderJson('issue-nodata-response', data);
  } catch (error) {
    renderJson('issue-nodata-response', error);
  }
});

bindForm('nonce-form', async (formData) => {
  const transactionId = formData.get('transactionId');
  try {
    const data = await requestJson(
      `${API_BASE}/api/credential/nonce?transactionId=${encodeURIComponent(transactionId)}`
    );
    renderJson('nonce-response', data);
  } catch (error) {
    renderJson('nonce-response', error);
  }
});

bindForm('credential-action-form', async (formData) => {
  const credentialId = formData.get('credentialId');
  const payload = {
    action: formData.get('action'),
  };
  const holderDid = formData.get('holderDid');
  if (holderDid) payload.holder_did = holderDid;
  const payloadJson = formData.get('payload');
  if (payloadJson) {
    try {
      payload.payload = JSON.parse(payloadJson);
    } catch (error) {
      renderJson('credential-action-response', { error: 'Payload JSON 格式錯誤' });
      throw error;
    }
  }
  try {
    const data = await requestJson(
      `${API_BASE}/api/credential/${encodeURIComponent(credentialId)}/action`,
      {
        method: 'PUT',
        body: JSON.stringify(payload),
      }
    );
    renderJson('credential-action-response', data);
  } catch (error) {
    renderJson('credential-action-response', error);
  }
});

bindForm('list-credentials-form', async (formData) => {
  const holderDid = formData.get('holderDidList');
  try {
    const data = await requestJson(
      `${API_BASE}/api/wallet/${encodeURIComponent(holderDid)}/credentials`
    );
    renderJson('list-credentials-response', data);
  } catch (error) {
    renderJson('list-credentials-response', error);
  }
});

bindForm('forget-form', async (formData) => {
  const holderDid = formData.get('holderDidForget');
  try {
    const data = await requestJson(
      `${API_BASE}/api/wallet/${encodeURIComponent(holderDid)}/forget`,
      { method: 'DELETE' }
    );
    renderJson('forget-response', data);
  } catch (error) {
    renderJson('forget-response', error);
  }
});

bindForm('verifier-medical-form', async (formData, form) => {
  const scope = form.dataset.scope || 'MEDICAL_RECORD';
  const fields = collectFields(form);
  const params = new URLSearchParams({
    verifier_id: formData.get('verifierId'),
    verifier_name: formData.get('verifierName'),
    purpose: formData.get('purpose'),
    ial: formData.get('ial'),
    scope,
  });
  if (fields.length) {
    params.set('fields', fields.join(','));
  }
  try {
    const data = await requestJson(`${API_BASE}/api/did/vp/code?${params.toString()}`, {
      accessToken: tokens.verifier,
    });
    renderJson('verifier-medical-response', data);
  } catch (error) {
    renderJson('verifier-medical-response', error);
  }
});

bindForm('verifier-medication-form', async (formData, form) => {
  const scope = form.dataset.scope || 'MEDICATION_PICKUP';
  const fields = collectFields(form);
  const params = new URLSearchParams({
    verifier_id: formData.get('verifierId'),
    verifier_name: formData.get('verifierName'),
    purpose: formData.get('purpose'),
    ial: formData.get('ial'),
    scope,
  });
  if (fields.length) {
    params.set('fields', fields.join(','));
  }
  try {
    const data = await requestJson(`${API_BASE}/api/did/vp/code?${params.toString()}`, {
      accessToken: tokens.verifier,
    });
    renderJson('verifier-medication-response', data);
  } catch (error) {
    renderJson('verifier-medication-response', error);
  }
});

bindForm('presentation-medical-form', async (formData, form) => {
  const scope = form.dataset.scope || 'MEDICAL_RECORD';
  const disclosedFields = gatherDisclosedFields(formData);
  try {
    const data = await requestJson(`${API_BASE}/api/did/vp/result`, {
      method: 'POST',
      body: JSON.stringify({
        session_id: formData.get('sessionId'),
        credential_id: formData.get('credentialId'),
        holder_did: formData.get('holderDid'),
        scope,
        disclosed_fields: disclosedFields,
      }),
      accessToken: tokens.verifier,
    });
    renderJson('presentation-medical-response', data);
  } catch (error) {
    renderJson('presentation-medical-response', error);
  }
});

bindForm('presentation-medication-form', async (formData, form) => {
  const scope = form.dataset.scope || 'MEDICATION_PICKUP';
  const disclosedFields = gatherDisclosedFields(formData);
  try {
    const data = await requestJson(`${API_BASE}/api/did/vp/result`, {
      method: 'POST',
      body: JSON.stringify({
        session_id: formData.get('sessionId'),
        credential_id: formData.get('credentialId'),
        holder_did: formData.get('holderDid'),
        scope,
        disclosed_fields: disclosedFields,
      }),
      accessToken: tokens.verifier,
    });
    renderJson('presentation-medication-response', data);
  } catch (error) {
    renderJson('presentation-medication-response', error);
  }
});

bindForm('purge-session-form', async (formData) => {
  const sessionId = formData.get('sessionId');
  try {
    const data = await requestJson(
      `${API_BASE}/api/did/vp/session/${encodeURIComponent(sessionId)}`,
      { method: 'DELETE', accessToken: tokens.verifier }
    );
    renderJson('purge-session-response', data);
  } catch (error) {
    renderJson('purge-session-response', error);
  }
});

const sampleButtons = document.querySelectorAll('[data-fill-sample]');
sampleButtons.forEach((button) => {
  button.addEventListener('click', (event) => {
    event.preventDefault();
    const type = button.dataset.fillSample;
    if (type === 'issue') {
      populateIssueSample();
    } else if (type === 'wallet') {
      populateIssueSample();
      populateWalletPayloadSample();
    } else if (type === 'presentation-medical') {
      populateIssueSample();
      populatePresentationSample('MEDICAL_RECORD');
    } else if (type === 'presentation-medication') {
      populateIssueSample();
      populatePresentationSample('MEDICATION_PICKUP');
    }
  });
});
