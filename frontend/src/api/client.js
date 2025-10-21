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

  const prefix = '/v2';

  return {
    issueWithData: (payload, token) =>
      request({
        url: `${prefix}/api/qrcode/data`,
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
        url: `${prefix}/api/qrcode/nodata`,
        method: 'POST',
        data: payload,
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    getNonce: (transactionId, token) =>
      request({
        url: `${prefix}/api/credential/nonce`,
        method: 'GET',
        params: { transactionId },
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    actOnCredential: (credentialId, actionPayload, token) =>
      request({
        url: `${prefix}/api/credential/${credentialId}/action`,
        method: 'PUT',
        data: actionPayload,
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    revokeCredential: (credentialId, token) =>
      request({
        url: `${prefix}/api/credentials/${credentialId}/revoke`,
        method: 'POST',
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    deleteCredential: (credentialId, token) =>
      request({
        url: `${prefix}/api/credentials/${credentialId}`,
        method: 'DELETE',
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    listHolderCredentials: (holderDid, token) =>
      request({
        url: `${prefix}/api/wallet/${encodeURIComponent(holderDid)}/credentials`,
        method: 'GET',
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    forgetHolder: (holderDid, token) =>
      request({
        url: `${prefix}/api/wallet/${encodeURIComponent(holderDid)}/forget`,
        method: 'DELETE',
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    createVerificationCode: (params, token) =>
      request({
        url: `${prefix}/api/did/vp/code`,
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
        url: `${prefix}/api/did/vp/result`,
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
        url: `${prefix}/api/did/vp/session/${sessionId}`,
        method: 'DELETE',
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
    resetSandbox: (token) =>
      request({
        url: `${prefix}/api/system/reset`,
        method: 'POST',
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      }),
  };
}
