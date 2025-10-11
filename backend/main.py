from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .analytics import get_risk_engine
from .models import (
    ConsentDecision,
    ConsentRecord,
    Credential,
    CredentialPayload,
    IdentityAssuranceLevel,
    Presentation,
    RiskInsightResponse,
    VerificationRequest,
    VerificationScope,
)
from .store import store

app = FastAPI(title="MedSSI v2 Prototype", version="0.2.0")


# Issuer endpoints ---------------------------------------------------------
@app.post("/api/issuers/{issuer_id}/issue", response_model=Credential)
def issue_credential(
    issuer_id: str,
    payload: CredentialPayload,
    holder_did: str,
    ial: IdentityAssuranceLevel,
) -> Credential:
    credential_id = f"cred-{uuid.uuid4().hex}"
    credential = Credential(
        credential_id=credential_id,
        holder_did=holder_did,
        issuer_id=issuer_id,
        ial=ial,
        payload=payload,
        created_at=datetime.utcnow(),
    )
    store.persist_credential(credential)
    return credential


@app.post("/api/credentials/{credential_id}/revoke")
def revoke_credential(credential_id: str) -> Dict[str, str]:
    try:
        store.revoke_credential(credential_id)
    except KeyError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "revoked", "credential_id": credential_id}


@app.get("/api/wallet/{holder_did}/credentials", response_model=list[Credential])
def list_holder_credentials(holder_did: str) -> list[Credential]:
    return store.list_holder_credentials(holder_did)


@app.post("/api/wallet/{holder_did}/forget")
def forget_holder_records(holder_did: str) -> Dict[str, int]:
    """Simulate the right to be forgotten by deleting cached proofs."""

    removed_credentials = store.delete_holder_credentials(holder_did)
    removed_presentations = store.delete_presentations_for_holder(holder_did)

    return {
        "removed_credentials": removed_credentials,
        "removed_presentations": removed_presentations,
    }


# Verifier endpoints -------------------------------------------------------
class VerificationRequestCreate(BaseModel):
    verifier_id: str
    verifier_name: str
    purpose: str
    required_ial: IdentityAssuranceLevel
    allowed_scopes: list[VerificationScope]
    expires_in_minutes: int = 30


@app.post("/api/verifiers/requests", response_model=VerificationRequest)
def create_verification_request(payload: VerificationRequestCreate) -> VerificationRequest:
    if not payload.allowed_scopes:
        raise HTTPException(status_code=400, detail="At least one selective disclosure scope required")

    request_obj = VerificationRequest(
        request_id=f"req-{uuid.uuid4().hex}",
        verifier_id=payload.verifier_id,
        verifier_name=payload.verifier_name,
        purpose=payload.purpose,
        required_ial=payload.required_ial,
        allowed_scopes=payload.allowed_scopes,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=payload.expires_in_minutes),
    )
    store.persist_request(request_obj)
    return request_obj


@app.get("/api/verifiers/{verifier_id}/requests", response_model=list[VerificationRequest])
def list_verifier_requests(verifier_id: str) -> list[VerificationRequest]:
    return store.list_active_requests(verifier_id)


# Consent and presentation -------------------------------------------------
class ConsentInput(BaseModel):
    request_id: str
    holder_did: str
    decision: ConsentDecision
    selected_scope_label: Optional[str] = None


class PresentationResponse(BaseModel):
    presentation: Presentation
    consent: ConsentRecord


@app.post("/api/wallet/consents", response_model=PresentationResponse)
def record_consent(payload: ConsentInput) -> PresentationResponse:
    request_obj = store.get_request(payload.request_id)
    if not request_obj or not request_obj.is_active():
        raise HTTPException(status_code=404, detail="Verification request not found or expired")

    consent_id = f"consent-{uuid.uuid4().hex}"
    consent = ConsentRecord(
        consent_id=consent_id,
        request_id=payload.request_id,
        holder_did=payload.holder_did,
        decision=payload.decision,
        selected_scope_label=payload.selected_scope_label,
        audited_at=datetime.utcnow(),
    )
    store.persist_consent(consent)

    if payload.decision is ConsentDecision.DENIED:
        raise HTTPException(status_code=202, detail="Consent denied; no presentation generated")

    scope = _resolve_scope(request_obj, payload.selected_scope_label)

    credential = _select_credential(payload.holder_did, request_obj.required_ial)
    disclosed_fields = _build_disclosure(credential, scope)

    presentation = Presentation(
        presentation_id=f"vp-{uuid.uuid4().hex}",
        consent_id=consent_id,
        credential_id=credential.credential_id,
        verifier_id=request_obj.verifier_id,
        disclosed_fields=disclosed_fields,
        issued_at=datetime.utcnow(),
    )
    store.persist_presentation(presentation)

    return PresentationResponse(presentation=presentation, consent=consent)


@app.post("/api/verifiers/verify", response_model=RiskInsightResponse)
def verify_presentation(presentation: Presentation) -> RiskInsightResponse:
    credential = store.get_credential(presentation.credential_id)
    if not credential or not credential.is_active():
        raise HTTPException(status_code=400, detail="Credential revoked or expired")

    consent = store.get_consent(presentation.consent_id)
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")

    request_obj = store.get_request(consent.request_id)
    if request_obj and not credential.satisfies_ial(request_obj.required_ial):
        raise HTTPException(status_code=400, detail="Insufficient identity assurance level")

    engine = get_risk_engine()
    insight = engine.evaluate(presentation)
    return RiskInsightResponse(presentation=presentation, insight=insight)


# Helper functions ---------------------------------------------------------
def _resolve_scope(request_obj: VerificationRequest, selected_scope_label: Optional[str]) -> VerificationScope:
    if selected_scope_label:
        for scope in request_obj.allowed_scopes:
            if scope.label == selected_scope_label:
                return scope
        raise HTTPException(status_code=400, detail="Selected scope not recognised")
    return min(request_obj.allowed_scopes, key=lambda s: len(s.fields))


def _select_credential(holder_did: str, required_ial: IdentityAssuranceLevel) -> Credential:
    credentials = store.list_holder_credentials(holder_did)
    if not credentials:
        raise HTTPException(status_code=404, detail="Holder has no credentials")

    eligible = [c for c in credentials if c.satisfies_ial(required_ial) and c.is_active()]
    if not eligible:
        raise HTTPException(status_code=400, detail="No credential satisfies the IAL requirement")

    return sorted(eligible, key=lambda c: c.created_at, reverse=True)[0]


def _build_disclosure(credential: Credential, scope: VerificationScope) -> Dict[str, str]:
    disclosure: Dict[str, str] = {}
    for field in scope.fields:
        value = getattr(credential.payload, field, None)
        if value is None:
            continue
        disclosure[field] = value.isoformat() if hasattr(value, "isoformat") else str(value)
    disclosure["issuer_id"] = credential.issuer_id
    disclosure["ial"] = credential.ial.value
    return disclosure
