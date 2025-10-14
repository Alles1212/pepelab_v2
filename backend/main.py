from __future__ import annotations

import os
import secrets
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .analytics import get_risk_engine
from .models import (
    CredentialAction,
    CredentialActionRequest,
    CredentialOffer,
    CredentialPayload,
    CredentialStatus,
    DisclosurePolicy,
    DisclosureScope,
    ForgetSummary,
    IdentityAssuranceLevel,
    IssuanceMode,
    NonceResponse,
    Presentation,
    QRCodeResponse,
    RiskInsightResponse,
    VerificationCodeResponse,
    VerificationResult,
    VerificationSession,
)
from .store import store

app = FastAPI(title="MedSSI Sandbox APIs", version="0.5.0")

ISSUER_ACCESS_TOKEN = os.getenv("MEDSSI_ISSUER_TOKEN", "issuer-sandbox-token")
VERIFIER_ACCESS_TOKEN = os.getenv("MEDSSI_VERIFIER_TOKEN", "verifier-sandbox-token")

# ...（中略已整理的內容保持不變，直到 submit_presentation）

@app.post(
    "/api/did/vp/result",
    response_model=RiskInsightResponse,
    dependencies=[Depends(require_verifier_token)],
)
def submit_presentation(payload: VerificationSubmission) -> RiskInsightResponse:
    session = store.get_verification_session(payload.session_id)
    if not session or not session.is_active():
        raise HTTPException(status_code=404, detail="Verification session expired or not found")

    credential = store.get_credential(payload.credential_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")
    if credential.status is not CredentialStatus.ISSUED:
        raise HTTPException(status_code=400, detail="Credential is not in an issued state")
    if not credential.satisfies_ial(session.required_ial):
        raise HTTPException(status_code=400, detail="Credential does not satisfy verifier IAL requirement")
    if payload.scope != session.scope:
        raise HTTPException(status_code=400, detail="Presentation scope does not match session scope")
    if not payload.disclosed_fields:
        raise HTTPException(status_code=400, detail="At least one field must be disclosed")

    policy = next(
        (policy for policy in credential.disclosure_policies if policy.scope == session.scope),
        None,
    )
    if not policy:
        raise HTTPException(status_code=400, detail="Credential does not support the requested disclosure scope")

    allowed = set(session.allowed_fields)
    credential_allowed = set(policy.fields)
    if not allowed.issubset(credential_allowed):
        raise HTTPException(status_code=400, detail="Verifier requested fields beyond credential policy")

    submitted = set(payload.disclosed_fields.keys())
    if not submitted.issubset(allowed):
        raise HTTPException(status_code=400, detail="Disclosed fields exceed the allowed scope")
    if not credential.payload:
        raise HTTPException(status_code=400, detail="Credential payload is unavailable for verification")

    for field_name, field_value in payload.disclosed_fields.items():
        stored_value = _resolve_payload_value(credential.payload, field_name)
        if stored_value is not None and stored_value != field_value:
            raise HTTPException(
                status_code=400,
                detail=f"Field {field_name} does not match credential payload",
            )

    presentation = Presentation(
        presentation_id=f"vp-{uuid.uuid4().hex}",
        session_id=session.session_id,
        credential_id=credential.credential_id,
        holder_did=payload.holder_did,
        verifier_id=session.verifier_id,
        scope=session.scope,
        disclosed_fields=payload.disclosed_fields,
        issued_at=datetime.utcnow(),
    )
    store.persist_presentation(presentation)

    result = VerificationResult(
        session_id=session.session_id,
        verifier_id=session.verifier_id,
        verified=True,
        presentation=presentation,
    )
    store.persist_result(result)

    engine = get_risk_engine()
    insight = engine.evaluate(presentation)
    return RiskInsightResponse(result=result, insight=insight)


# Utility endpoints
@app.get("/api/wallet/{holder_did}/credentials", response_model=List[CredentialOffer])
def list_holder_credentials(holder_did: str) -> List[CredentialOffer]:
    return store.list_credentials_for_holder(holder_did)


@app.post(
    "/api/credentials/{credential_id}/revoke",
    response_model=CredentialOffer,
    dependencies=[Depends(require_issuer_token)],
)
def revoke_credential(credential_id: str) -> CredentialOffer:
    credential = store.get_credential(credential_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Unknown credential id")
    credential.status = CredentialStatus.REVOKED
    credential.last_action_at = datetime.utcnow()
    store.update_credential(credential)
    return credential


@app.delete(
    "/api/credentials/{credential_id}",
    dependencies=[Depends(require_issuer_token)],
)
def delete_credential(credential_id: str) -> Dict[str, str]:
    credential = store.get_credential(credential_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Unknown credential id")
    store.delete_credential(credential_id)
    return {"credential_id": credential_id, "status": "deleted"}


@app.delete("/api/wallet/{holder_did}/forget", response_model=ForgetSummary)
def forget_holder(holder_did: str) -> ForgetSummary:
    return store.forget_holder(holder_did)


@app.delete(
    "/api/did/vp/session/{session_id}",
    dependencies=[Depends(require_verifier_token)],
)
def purge_verification_session(session_id: str) -> Dict[str, str]:
    session = store.get_verification_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown session id")
    store.purge_session(session_id)
    return {"session_id": session_id, "status": "purged"}
