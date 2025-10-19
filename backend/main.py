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


def _validate_token(authorization: Optional[str], expected: str, audience: str) -> None:
    if not authorization:
        raise HTTPException(status_code=401, detail=f"Missing {audience} access token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Access token must use Bearer scheme")
    if token != expected:
        raise HTTPException(status_code=403, detail=f"{audience.capitalize()} access token rejected")


def require_issuer_token(authorization: Optional[str] = Header(None)) -> None:
    _validate_token(authorization, ISSUER_ACCESS_TOKEN, "issuer")


def require_verifier_token(authorization: Optional[str] = Header(None)) -> None:
    _validate_token(authorization, VERIFIER_ACCESS_TOKEN, "verifier")


# ---------------------------------------------------------------------------
# Issuance APIs
# ---------------------------------------------------------------------------
class IssuanceWithDataRequest(BaseModel):
    issuer_id: str
    holder_did: str
    ial: IdentityAssuranceLevel
    payload: CredentialPayload
    disclosure_policies: List[DisclosurePolicy] = Field(
        default_factory=lambda: _default_disclosure_policies(),
        description="Selective disclosure rules grouped by scope",
    )
    valid_for_minutes: int = Field(5, ge=1, le=5)
    holder_hint: Optional[str] = Field(
        None, description="Optional hint shown to the wallet (e.g. patient name)"
    )


class IssuanceWithoutDataRequest(BaseModel):
    issuer_id: str
    ial: IdentityAssuranceLevel
    disclosure_policies: List[DisclosurePolicy]
    valid_for_minutes: int = Field(5, ge=1, le=5)
    holder_hint: Optional[str] = None
    holder_did: Optional[str] = None
    payload_template: Optional[CredentialPayload] = Field(
        None,
        description="Optional template so the wallet knows what data will be requested",
    )


def _build_qr_payload(token: str, kind: str) -> str:
    return f"medssi://{kind}?token={token}"


def _default_disclosure_policies() -> List[DisclosurePolicy]:
    return [
        DisclosurePolicy(
            scope=DisclosureScope.MEDICAL_RECORD,
            fields=[
                "condition.code.coding[0].code",
                "condition.recordedDate",
                "managing_organization.value",
            ],
            description="跨院病歷摘要：診斷碼、紀錄日期、發卡院所",
        ),
        DisclosurePolicy(
            scope=DisclosureScope.MEDICATION_PICKUP,
            fields=[
                "medication_dispense[0].medicationCodeableConcept.coding[0].code",
                "medication_dispense[0].days_supply",
                "medication_dispense[0].pickup_window_end",
            ],
            description="領藥資訊：藥品代碼、給藥天數、取藥期限",
        ),
    ]


def _ensure_valid_policies(policies: List[DisclosurePolicy]) -> None:
    if not policies:
        raise HTTPException(status_code=400, detail="Disclosure policies cannot be empty")

    seen_scopes = set()
    for policy in policies:
        if policy.scope in seen_scopes:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate disclosure policy for scope {policy.scope}",
            )
        seen_scopes.add(policy.scope)
        if not policy.fields:
            raise HTTPException(
                status_code=400,
                detail=f"Disclosure fields for scope {policy.scope} cannot be empty",
            )


def _create_offer(
    *,
    issuer_id: str,
    ial: IdentityAssuranceLevel,
    mode: IssuanceMode,
    disclosure_policies: List[DisclosurePolicy],
    valid_for_minutes: int,
    holder_did: Optional[str] = None,
    holder_hint: Optional[str] = None,
    payload: Optional[CredentialPayload] = None,
) -> CredentialOffer:
    now = datetime.utcnow()
    credential_id = f"cred-{uuid.uuid4().hex}"
    transaction_id = str(uuid.uuid4())
    nonce = secrets.token_urlsafe(16)
    qr_token = secrets.token_urlsafe(24)

    offer = CredentialOffer(
        credential_id=credential_id,
        transaction_id=transaction_id,
        issuer_id=issuer_id,
        ial=ial,
        mode=mode,
        qr_token=qr_token,
        nonce=nonce,
        status=CredentialStatus.OFFERED,
        created_at=now,
        expires_at=now + timedelta(minutes=valid_for_minutes),
        last_action_at=now,
        disclosure_policies=disclosure_policies,
        holder_did=holder_did,
        holder_hint=holder_hint,
        payload=payload,
    )
    store.persist_credential(offer)
    return offer


def _get_child(current: Any, name: str) -> Any:
    if current is None:
        return None
    if isinstance(current, BaseModel):
        return getattr(current, name, None)
    if isinstance(current, dict):
        return current.get(name)
    return getattr(current, name, None)


def _resolve_payload_value(payload: Optional[CredentialPayload], path: str) -> Optional[str]:
    if payload is None:
        return None

    current: Any = payload
    for segment in path.split('.'):
        if not segment:
            continue
        while '[' in segment:
            attr, rest = segment.split('[', 1)
            if attr:
                current = _get_child(current, attr)
            else:
                attr = ''
            if current is None:
                return None
            index_str, remainder = rest.split(']', 1)
            try:
                index = int(index_str)
            except ValueError:
                return None
            if not isinstance(current, (list, tuple)):
                return None
            if index >= len(current):
                return None
            current = current[index]
            segment = remainder
            if segment.startswith('.'):  # Should not happen due to split, but be safe
                segment = segment[1:]
        if segment:
            current = _get_child(current, segment)
        if current is None:
            return None

    if isinstance(current, (date, datetime)):
        return current.isoformat()
    if isinstance(current, (str, int, float)):
        return str(current)
    if isinstance(current, BaseModel):
        return current.json()
    if isinstance(current, dict):
        return str(current)
    return None


@app.post(
    "/api/qrcode/data",
    response_model=QRCodeResponse,
    dependencies=[Depends(require_issuer_token)],
)
def create_qr_with_data(request: IssuanceWithDataRequest) -> QRCodeResponse:
    _ensure_valid_policies(request.disclosure_policies)

    offer = _create_offer(
        issuer_id=request.issuer_id,
        ial=request.ial,
        mode=IssuanceMode.WITH_DATA,
        disclosure_policies=request.disclosure_policies,
        valid_for_minutes=request.valid_for_minutes,
        holder_did=request.holder_did,
        holder_hint=request.holder_hint,
        payload=request.payload,
    )

    qr_payload = _build_qr_payload(offer.qr_token, "credential")
    return QRCodeResponse(credential=offer, qr_payload=qr_payload)


@app.post(
    "/api/qrcode/nodata",
    response_model=QRCodeResponse,
    dependencies=[Depends(require_issuer_token)],
)
def create_qr_without_data(request: IssuanceWithoutDataRequest) -> QRCodeResponse:
    _ensure_valid_policies(request.disclosure_policies)

    offer = _create_offer(
        issuer_id=request.issuer_id,
        ial=request.ial,
        mode=IssuanceMode.WITHOUT_DATA,
        disclosure_policies=request.disclosure_policies,
        valid_for_minutes=request.valid_for_minutes,
        holder_did=request.holder_did,
        holder_hint=request.holder_hint,
        payload=request.payload_template,
    )

    qr_payload = _build_qr_payload(offer.qr_token, "credential")
    return QRCodeResponse(credential=offer, qr_payload=qr_payload)


@app.get("/api/credential/nonce", response_model=NonceResponse)
def get_nonce(transactionId: str = Query(..., alias="transactionId")) -> NonceResponse:  # noqa: N802
    try:
        uuid.UUID(transactionId)
    except ValueError as exc:  # pragma: no cover - defensive parsing
        raise HTTPException(status_code=400, detail="transactionId must be a UUID") from exc

    offer = store.get_credential_by_transaction(transactionId)
    if not offer:
        raise HTTPException(status_code=404, detail="Unknown transaction id")
    if not offer.is_active():
        raise HTTPException(status_code=410, detail="Credential offer expired or revoked")

    return NonceResponse(
        transaction_id=offer.transaction_id,
        credential_id=offer.credential_id,
        nonce=offer.nonce,
        ial=offer.ial,
        status=offer.status,
        expires_at=offer.expires_at,
        mode=offer.mode,
        disclosure_policies=offer.disclosure_policies,
        payload_available=offer.payload is not None,
    )


@app.put("/api/credential/{credential_id}/action", response_model=CredentialOffer)
def handle_credential_action(credential_id: str, payload: CredentialActionRequest) -> CredentialOffer:
    credential = store.get_credential(credential_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Unknown credential id")

    now = datetime.utcnow()

    if payload.action == CredentialAction.ACCEPT:
        if credential.status is CredentialStatus.REVOKED:
            raise HTTPException(status_code=400, detail="Credential already revoked")
        if credential.mode is IssuanceMode.WITHOUT_DATA and not (credential.payload or payload.payload):
            raise HTTPException(status_code=400, detail="Payload required before accepting credential")
        if payload.payload:
            credential.payload = payload.payload
        if payload.holder_did:
            credential.holder_did = payload.holder_did
        if not credential.holder_did:
            raise HTTPException(status_code=400, detail="Holder DID must be provided when accepting")
        credential.status = CredentialStatus.ISSUED
    elif payload.action == CredentialAction.DECLINE:
        credential.status = CredentialStatus.DECLINED
    elif payload.action == CredentialAction.REVOKE:
        credential.status = CredentialStatus.REVOKED
    elif payload.action == CredentialAction.UPDATE:
        if payload.payload:
            credential.payload = payload.payload
    else:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail="Unsupported action")

    credential.last_action_at = now
    store.update_credential(credential)
    return credential


# ---------------------------------------------------------------------------
# Verification APIs
# ---------------------------------------------------------------------------
class VerificationSubmission(BaseModel):
    session_id: str
    credential_id: str
    holder_did: str
    scope: DisclosureScope
    disclosed_fields: Dict[str, str]


@app.get(
    "/api/did/vp/code",
    response_model=VerificationCodeResponse,
    dependencies=[Depends(require_verifier_token)],
)
def get_verification_code(
    verifier_id: str = Query(..., description="Verifier identifier registered in the trust registry"),
    verifier_name: str = Query(..., description="Display name for the verifier"),
    purpose: str = Query("Clinical research", description="Why the verifier needs the data"),
    ial: IdentityAssuranceLevel = Query(IdentityAssuranceLevel.NHI_CARD_PIN, alias="ial"),
    scope: DisclosureScope = Query(DisclosureScope.MEDICAL_RECORD, description="MEDICAL_RECORD or MEDICATION_PICKUP"),
    fields: Optional[str] = Query(
        None,
        description="Comma separated list of selective disclosure fields; defaults depend on scope",
    ),
    valid_for_minutes: int = Query(5, ge=1, le=5, alias="validMinutes"),
) -> VerificationCodeResponse:
    if fields:
        allowed_fields = [f.strip() for f in fields.split(",") if f.strip()]
    else:
        policy = next(
            (policy for policy in _default_disclosure_policies() if policy.scope == scope),
            None,
        )
        allowed_fields = policy.fields if policy else []

    if not allowed_fields:
        raise HTTPException(status_code=400, detail="At least one disclosure field is required")

    now = datetime.utcnow()
    active_sessions = [
        s
        for s in store.list_active_sessions(verifier_id)
        if s.purpose == purpose
        and set(s.allowed_fields) == set(allowed_fields)
        and s.required_ial == ial
        and s.scope == scope
    ]

    if active_sessions:
        session = sorted(active_sessions, key=lambda s: s.created_at)[-1]
        session.last_polled_at = now
    else:
        session = VerificationSession(
            session_id=f"sess-{uuid.uuid4().hex}",
            verifier_id=verifier_id,
            verifier_name=verifier_name,
            purpose=purpose,
            required_ial=ial,
            scope=scope,
            allowed_fields=allowed_fields,
            qr_token=secrets.token_urlsafe(24),
            created_at=now,
            expires_at=now + timedelta(minutes=valid_for_minutes),
            last_polled_at=now,
        )
    store.persist_verification_session(session)
    qr_payload = _build_qr_payload(session.qr_token, "verification")
    return VerificationCodeResponse(session=session, qr_payload=qr_payload)


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


# ---------------------------------------------------------------------------
# Utility endpoints for demos
# ---------------------------------------------------------------------------
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
