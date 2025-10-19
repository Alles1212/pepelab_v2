import axios from 'axios';

export function createClient(baseUrl) {
  const instance = axios.create({
    baseURL: baseUrl.replace(/\/$/, ''),
    timeout: 8000,
  });

  async function request(config) {
    try {
      const response = await instance.request(config);
      return { ok: true, data: response.data };
    } catch (error) {
      if (error.response) {
        return {
          ok: false,
          status: error.response.status,
          detail: error.response.data?.detail ?? error.response.data,
        };
      }
      return { ok: false, status: 0, detail: error.message };
    }
  }

  return {
    issueWithData: (payload, token) =>
      request({
        url: '/api/qrcode/data',
        method: 'POST',
        data: payload,
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    issueWithoutData: (payload, token) =>
      request({
        url: '/api/qrcode/nodata',
        method: 'POST',
        data: payload,
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    getNonce: (transactionId) =>
      request({
        url: '/api/credential/nonce',
        method: 'GET',
        params: { transactionId },
      }),
    actOnCredential: (credentialId, actionPayload) =>
      request({
        url: `/api/credential/${credentialId}/action`,
        method: 'PUT',
        data: actionPayload,
      }),
    revokeCredential: (credentialId, token) =>
      request({
        url: `/api/credentials/${credentialId}/revoke`,
        method: 'POST',
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    deleteCredential: (credentialId, token) =>
      request({
        url: `/api/credentials/${credentialId}`,
        method: 'DELETE',
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    listHolderCredentials: (holderDid) =>
      request({
        url: `/api/wallet/${encodeURIComponent(holderDid)}/credentials`,
        method: 'GET',
      }),
    forgetHolder: (holderDid) =>
      request({
        url: `/api/wallet/${encodeURIComponent(holderDid)}/forget`,
        method: 'DELETE',
      }),
    createVerificationCode: (params, token) =>
      request({
        url: '/api/did/vp/code',
        method: 'GET',
        params,
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    submitPresentation: (payload, token) =>
      request({
        url: '/api/did/vp/result',
        method: 'POST',
        data: payload,
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    purgeSession: (sessionId, token) =>
      request({
        url: `/api/did/vp/session/${sessionId}`,
        method: 'DELETE',
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
  };
}
