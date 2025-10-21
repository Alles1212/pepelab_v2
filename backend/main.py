from __future__ import annotations

import os
import secrets
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
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
    ProblemDetail,
    QRCodeResponse,
    RiskInsightResponse,
    VerificationCodeResponse,
    VerificationResult,
    VerificationSession,
)
from .store import store


app = FastAPI(title="MedSSI Sandbox APIs", version="0.6.0")
api_v2 = APIRouter(prefix="/v2", tags=["MedSSI v2"])


ISSUER_ACCESS_TOKEN = os.getenv("MEDSSI_ISSUER_TOKEN", "issuer-sandbox-token")
VERIFIER_ACCESS_TOKEN = os.getenv("MEDSSI_VERIFIER_TOKEN", "verifier-sandbox-token")
WALLET_ACCESS_TOKEN = os.getenv("MEDSSI_WALLET_TOKEN", "wallet-sandbox-token")


def _raise_problem(*, status: int, type_: str, title: str, detail: str) -> None:
    raise HTTPException(
        status_code=status,
        detail=ProblemDetail(type=type_, title=title, status=status, detail=detail).dict(),
    )


def _validate_token(authorization: Optional[str], expected: str, audience: str) -> None:
    if not authorization:
        _raise_problem(
            status=401,
            type_="https://medssi.dev/errors/missing-token",
            title=f"{audience.capitalize()} token required",
            detail=f"Provide Bearer token for {audience} access.",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        _raise_problem(
            status=401,
            type_="https://medssi.dev/errors/invalid-token-format",
            title="Bearer token format required",
            detail="Authorization header must be formatted as 'Bearer <token>'.",
        )
    if token != expected:
        _raise_problem(
            status=403,
            type_="https://medssi.dev/errors/token-rejected",
            title="Access token rejected",
            detail=f"The supplied token is not valid for {audience} operations.",
        )


def require_issuer_token(authorization: Optional[str] = Header(None)) -> None:
    _validate_token(authorization, ISSUER_ACCESS_TOKEN, "issuer")


def require_verifier_token(authorization: Optional[str] = Header(None)) -> None:
    _validate_token(authorization, VERIFIER_ACCESS_TOKEN, "verifier")


def require_wallet_token(authorization: Optional[str] = Header(None)) -> None:
    _validate_token(authorization, WALLET_ACCESS_TOKEN, "wallet")


def require_any_sandbox_token(authorization: Optional[str] = Header(None)) -> None:
    if authorization is None:
        _raise_problem(
            status=401,
            type_="https://medssi.dev/errors/missing-token",
            title="Sandbox token required",
            detail="Provide issuer, wallet, or verifier token.",
        )
    try:
        _validate_token(authorization, ISSUER_ACCESS_TOKEN, "issuer")
        return
    except HTTPException:
        pass
    try:
        _validate_token(authorization, VERIFIER_ACCESS_TOKEN, "verifier")
        return
    except HTTPException:
        pass
    _validate_token(authorization, WALLET_ACCESS_TOKEN, "wallet")


@app.middleware("http")
async def cleanup_expired_middleware(request, call_next):
    store.cleanup_expired()
    response = await call_next(request)
    return response


class IssuanceWithDataRequest(BaseModel):
    issuer_id: str
    holder_did: str
    holder_hint: Optional[str] = Field(
        None, description="Optional hint shown to wallets (e.g. patient name)",
    )
    ial: IdentityAssuranceLevel
    primary_scope: DisclosureScope
    payload: CredentialPayload
    disclosure_policies: List[DisclosurePolicy] = Field(
        default_factory=lambda: _default_disclosure_policies(),
        description="Selective disclosure policies grouped by scope.",
    )
    valid_for_minutes: int = Field(5, ge=1, le=5)


class IssuanceWithoutDataRequest(BaseModel):
    issuer_id: str
    ial: IdentityAssuranceLevel
    primary_scope: DisclosureScope
    disclosure_policies: List[DisclosurePolicy]
    valid_for_minutes: int = Field(5, ge=1, le=5)
    holder_hint: Optional[str] = None
    holder_did: Optional[str] = None
    payload_template: Optional[CredentialPayload] = Field(
        None,
        description="Template describing the FHIR structure the holder must supply.",
    )


class VerificationSubmission(BaseModel):
    session_id: str
    credential_id: str
    holder_did: str
    disclosed_fields: Dict[str, str]


class ResetResponse(BaseModel):
    message: str
    timestamp: datetime


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
        DisclosurePolicy(
            scope=DisclosureScope.RESEARCH_ANALYTICS,
            fields=[
                "condition.code.coding[0].code",
                "encounter_summary_hash",
            ],
            description="匿名化研究卡：以摘要雜湊與診斷碼提供研究合作",
        ),
    ]


def _ensure_valid_policies(policies: List[DisclosurePolicy]) -> None:
    if not policies:
        _raise_problem(
            status=400,
            type_="https://medssi.dev/errors/policy-empty",
            title="Disclosure policies required",
            detail="Select at least one disclosure policy scope.",
        )

    seen_scopes = set()
    for policy in policies:
        if policy.scope in seen_scopes:
            _raise_problem(
                status=400,
                type_="https://medssi.dev/errors/policy-duplicate",
                title="Duplicate disclosure scope",
                detail=f"Scope {policy.scope} defined more than once.",
            )
        seen_scopes.add(policy.scope)
        if not policy.fields:
            _raise_problem(
                status=400,
                type_="https://medssi.dev/errors/policy-fields-empty",
                title="Disclosure fields required",
                detail=f"Scope {policy.scope} must list at least one field.",
            )


def _create_offer(
    *,
    issuer_id: str,
    primary_scope: DisclosureScope,
    ial: IdentityAssuranceLevel,
    mode: IssuanceMode,
    disclosure_policies: List[DisclosurePolicy],
    valid_for_minutes: int,
    holder_did: Optional[str] = None,
    holder_hint: Optional[str] = None,
    payload: Optional[CredentialPayload] = None,
    payload_template: Optional[CredentialPayload] = None,
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
        primary_scope=primary_scope,
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
        payload_template=payload_template,
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
            if segment.startswith('.'):
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


def _select_allowed_fields(offer: CredentialOffer, disclosures: Dict[str, str]) -> Dict[str, str]:
    allowed = {
        field
        for policy in offer.disclosure_policies
        for field in policy.fields
    }
    invalid = [field for field in disclosures if field not in allowed]
    if invalid:
        _raise_problem(
            status=400,
            type_="https://medssi.dev/errors/disclosure-invalid",
            title="Field outside of disclosure policy",
            detail=f"Fields {', '.join(invalid)} not allowed for this credential.",
        )
    return disclosures


def _retention_days(scope: DisclosureScope) -> int:
    if scope == DisclosureScope.MEDICATION_PICKUP:
        return 3
    if scope == DisclosureScope.MEDICAL_RECORD:
        return 7
    return 30


def _touch_retention(offer: CredentialOffer) -> None:
    issued_at = datetime.utcnow()
    offer.issued_at = issued_at
    offer.retention_expires_at = issued_at + timedelta(days=_retention_days(offer.primary_scope))
    offer.last_action_at = issued_at


@api_v2.post(
    "/api/qrcode/data",
    response_model=QRCodeResponse,
    dependencies=[Depends(require_issuer_token)],
)
def create_qr_with_data(request: IssuanceWithDataRequest) -> QRCodeResponse:
    _ensure_valid_policies(request.disclosure_policies)

    offer = _create_offer(
        issuer_id=request.issuer_id,
        primary_scope=request.primary_scope,
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


@api_v2.post(
    "/api/qrcode/nodata",
    response_model=QRCodeResponse,
    dependencies=[Depends(require_issuer_token)],
)
def create_qr_without_data(request: IssuanceWithoutDataRequest) -> QRCodeResponse:
    _ensure_valid_policies(request.disclosure_policies)

    offer = _create_offer(
        issuer_id=request.issuer_id,
        primary_scope=request.primary_scope,
        ial=request.ial,
        mode=IssuanceMode.WITHOUT_DATA,
        disclosure_policies=request.disclosure_policies,
        valid_for_minutes=request.valid_for_minutes,
        holder_did=request.holder_did,
        holder_hint=request.holder_hint,
        payload_template=request.payload_template,
    )

    qr_payload = _build_qr_payload(offer.qr_token, "credential")
    return QRCodeResponse(credential=offer, qr_payload=qr_payload)


@api_v2.post(
    "/api/credentials/{credential_id}/revoke",
    response_model=CredentialOffer,
    dependencies=[Depends(require_issuer_token)],
)
def revoke_credential(credential_id: str) -> CredentialOffer:
    credential = store.get_credential(credential_id)
    if not credential:
        _raise_problem(
            status=404,
            type_="https://medssi.dev/errors/credential-not-found",
            title="Credential not found",
            detail=f"Credential {credential_id} does not exist.",
        )

    credential.status = CredentialStatus.REVOKED
    credential.last_action_at = datetime.utcnow()
    credential.retention_expires_at = credential.last_action_at
    store.update_credential(credential)
    return credential


@api_v2.delete(
    "/api/credentials/{credential_id}",
    dependencies=[Depends(require_issuer_token)],
)
def delete_credential(credential_id: str):
    if not store.get_credential(credential_id):
        _raise_problem(
            status=404,
            type_="https://medssi.dev/errors/credential-not-found",
            title="Credential not found",
            detail=f"Credential {credential_id} does not exist.",
        )
    store.delete_credential(credential_id)
    return {"credential_id": credential_id, "status": "DELETED"}


@api_v2.get(
    "/api/credential/nonce",
    response_model=NonceResponse,
    dependencies=[Depends(require_wallet_token)],
)
def get_nonce(transactionId: str = Query(..., alias="transactionId")) -> NonceResponse:  # noqa: N802
    try:
        uuid.UUID(transactionId)
    except ValueError:
        _raise_problem(
            status=400,
            type_="https://medssi.dev/errors/transaction-id",
            title="transactionId invalid",
            detail="transactionId must be a UUIDv4 string.",
        )

    offer = store.get_credential_by_transaction(transactionId)
    if not offer:
        _raise_problem(
            status=404,
            type_="https://medssi.dev/errors/transaction-not-found",
            title="Transaction not found",
            detail="No credential offer found for this transactionId.",
        )
    if not offer.is_active():
        _raise_problem(
            status=410,
            type_="https://medssi.dev/errors/offer-expired",
            title="Credential offer expired",
            detail="The QR Code has expired or the credential was revoked.",
        )

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
        payload_template=offer.payload_template,
    )


@api_v2.put(
    "/api/credential/{credential_id}/action",
    response_model=CredentialOffer,
    dependencies=[Depends(require_wallet_token)],
)
def handle_credential_action(credential_id: str, payload: CredentialActionRequest) -> CredentialOffer:
    credential = store.get_credential(credential_id)
    if not credential:
        _raise_problem(
            status=404,
            type_="https://medssi.dev/errors/credential-not-found",
            title="Credential not found",
            detail=f"Credential {credential_id} does not exist.",
        )

    now = datetime.utcnow()

    if payload.action == CredentialAction.ACCEPT:
        if credential.status == CredentialStatus.REVOKED:
            _raise_problem(
                status=400,
                type_="https://medssi.dev/errors/credential-revoked",
                title="Credential revoked",
                detail="Revoked credentials cannot be accepted.",
            )
        if not payload.holder_did and not credential.holder_did:
            _raise_problem(
                status=400,
                type_="https://medssi.dev/errors/missing-holder",
                title="Holder DID required",
                detail="Provide holder_did when accepting the credential.",
            )
        if credential.mode is IssuanceMode.WITHOUT_DATA:
            if payload.payload is None:
                _raise_problem(
                    status=400,
                    type_="https://medssi.dev/errors/missing-payload",
                    title="Payload required",
                    detail="Submit the FHIR payload when accepting a placeholder credential.",
                )
            credential.payload = payload.payload
        elif payload.payload is not None:
            credential.payload = payload.payload

        disclosures = payload.disclosures or {}
        credential.selected_disclosures = _select_allowed_fields(credential, disclosures)
        if payload.holder_did:
            credential.holder_did = payload.holder_did
        credential.status = CredentialStatus.ISSUED
        _touch_retention(credential)
    elif payload.action == CredentialAction.UPDATE:
        if credential.status != CredentialStatus.ISSUED:
            _raise_problem(
                status=400,
                type_="https://medssi.dev/errors/credential-not-issued",
                title="Credential not issued",
                detail="Only issued credentials can be updated.",
            )
        if payload.payload:
            credential.payload = payload.payload
        if payload.disclosures:
            credential.selected_disclosures = _select_allowed_fields(credential, payload.disclosures)
        credential.last_action_at = now
    elif payload.action == CredentialAction.DECLINE:
        credential.status = CredentialStatus.DECLINED
        credential.last_action_at = now
    elif payload.action == CredentialAction.REVOKE:
        credential.status = CredentialStatus.REVOKED
        credential.retention_expires_at = now
        credential.last_action_at = now
    else:
        _raise_problem(
            status=400,
            type_="https://medssi.dev/errors/unsupported-action",
            title="Unsupported action",
            detail=f"Action {payload.action} is not supported.",
        )

    store.update_credential(credential)
    return credential


@api_v2.get(
    "/api/wallet/{holder_did}/credentials",
    response_model=List[CredentialOffer],
    dependencies=[Depends(require_wallet_token)],
)
def list_holder_credentials(holder_did: str) -> List[CredentialOffer]:
    return store.list_credentials_for_holder(holder_did)


@api_v2.delete(
    "/api/wallet/{holder_did}/forget",
    response_model=ForgetSummary,
    dependencies=[Depends(require_wallet_token)],
)
def forget_holder(holder_did: str) -> ForgetSummary:
    return store.forget_holder(holder_did)


@api_v2.get(
    "/api/did/vp/code",
    response_model=VerificationCodeResponse,
    dependencies=[Depends(require_verifier_token)],
)
def get_verification_code(
    verifierId: str = Query(..., alias="verifierId"),
    verifierName: str = Query(..., alias="verifierName"),
    purpose: str = Query("Clinical research"),
    ial_min: IdentityAssuranceLevel = Query(
        IdentityAssuranceLevel.NHI_CARD_PIN, alias="ial_min"
    ),
    scope: DisclosureScope = Query(DisclosureScope.MEDICAL_RECORD),
    fields: List[str] = Query(
        ..., description="List of fields requested for selective disclosure"
    ),
    validMinutes: int = Query(5, ge=1, le=5, alias="validMinutes"),
) -> VerificationCodeResponse:
    if len(fields) == 1 and "," in fields[0]:
        fields = [segment.strip() for segment in fields[0].split(",") if segment.strip()]

    if not fields:
        _raise_problem(
            status=400,
            type_="https://medssi.dev/errors/fields-required",
            title="At least one field required",
            detail="Provide at least one selective disclosure field.",
        )

    now = datetime.utcnow()
    session = VerificationSession(
        session_id=f"sess-{uuid.uuid4().hex}",
        verifier_id=verifierId,
        verifier_name=verifierName,
        purpose=purpose,
        required_ial=ial_min,
        scope=scope,
        allowed_fields=list(dict.fromkeys(fields)),
        qr_token=secrets.token_urlsafe(24),
        created_at=now,
        expires_at=now + timedelta(minutes=validMinutes),
        last_polled_at=now,
    )
    store.persist_verification_session(session)
    qr_payload = _build_qr_payload(session.qr_token, "vp-session")
    return VerificationCodeResponse(session=session, qr_payload=qr_payload)


@api_v2.post(
    "/api/did/vp/result",
    response_model=RiskInsightResponse,
    dependencies=[Depends(require_verifier_token)],
)
def submit_presentation(payload: VerificationSubmission) -> RiskInsightResponse:
    session = store.get_verification_session(payload.session_id)
    if not session or not session.is_active():
        _raise_problem(
            status=410,
            type_="https://medssi.dev/errors/session-expired",
            title="Verification session expired",
            detail="Create a new QR code to verify credentials.",
        )

    credential = store.get_credential(payload.credential_id)
    if not credential:
        _raise_problem(
            status=404,
            type_="https://medssi.dev/errors/credential-not-found",
            title="Credential not found",
            detail="Holder credential not located.",
        )
    if credential.status != CredentialStatus.ISSUED:
        _raise_problem(
            status=400,
            type_="https://medssi.dev/errors/credential-not-issued",
            title="Credential not issued",
            detail="Only issued credentials may be presented.",
        )
    if not credential.satisfies_ial(session.required_ial):
        _raise_problem(
            status=403,
            type_="https://medssi.dev/errors/ial-mismatch",
            title="Identity assurance insufficient",
            detail="Credential assurance level below verifier minimum.",
        )
    if credential.holder_did != payload.holder_did:
        _raise_problem(
            status=403,
            type_="https://medssi.dev/errors/holder-mismatch",
            title="Holder DID mismatch",
            detail="Presentation holder does not match credential owner.",
        )

    session_fields = set(session.allowed_fields)
    requested_fields = set(payload.disclosed_fields.keys())
    if not requested_fields.issubset(session_fields):
        _raise_problem(
            status=400,
            type_="https://medssi.dev/errors/fields-not-authorized",
            title="Unauthorized disclosure field",
            detail="Presentation includes fields outside session scope.",
        )

    selected_fields = set(credential.selected_disclosures.keys()) or session_fields
    if not requested_fields.issubset(selected_fields):
        _raise_problem(
            status=400,
            type_="https://medssi.dev/errors/fields-not-consented",
            title="Holder did not consent to field",
            detail="Presentation attempts to disclose fields outside holder consent.",
        )

    resolved_fields: Dict[str, str] = {}
    for field in session.allowed_fields:
        presented_value = payload.disclosed_fields.get(field)
        if presented_value is None:
            continue
        actual_value = _resolve_payload_value(credential.payload, field)
        if actual_value is not None and str(presented_value) != str(actual_value):
            _raise_problem(
                status=400,
                type_="https://medssi.dev/errors/value-mismatch",
                title="Disclosed value mismatch",
                detail=f"Field {field} does not match credential contents.",
            )
        resolved_fields[field] = str(presented_value)

    presentation = Presentation(
        presentation_id=f"vp-{uuid.uuid4().hex}",
        session_id=session.session_id,
        credential_id=credential.credential_id,
        holder_did=payload.holder_did,
        verifier_id=session.verifier_id,
        scope=session.scope,
        disclosed_fields=resolved_fields,
        issued_at=datetime.utcnow(),
        nonce=credential.nonce,
    )
    result = VerificationResult(
        session_id=session.session_id,
        verifier_id=session.verifier_id,
        verified=True,
        presentation=presentation,
    )
    store.persist_presentation(presentation)
    store.persist_result(result)

    insight = get_risk_engine().evaluate(presentation)
    return RiskInsightResponse(result=result, insight=insight)


@api_v2.delete(
    "/api/did/vp/session/{session_id}",
    dependencies=[Depends(require_verifier_token)],
)
def purge_session(session_id: str):
    store.purge_session(session_id)
    return {"session_id": session_id, "status": "PURGED"}


@api_v2.post(
    "/api/system/reset",
    response_model=ResetResponse,
    dependencies=[Depends(require_any_sandbox_token)],
)
def reset_sandbox_state() -> ResetResponse:
    store.reset()
    return ResetResponse(message="MedSSI in-memory store reset", timestamp=datetime.utcnow())


app.include_router(api_v2)


@app.get("/healthz")
def healthcheck():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
