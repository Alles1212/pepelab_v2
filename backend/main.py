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

# ---------------------------------------------------------------------------
# Access Token Validation
# ---------------------------------------------------------------------------
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
    holder_hint: Optional[str] = Field(None, description="Optional hint shown to the wallet (e.g. patient name)")


class IssuanceWithoutDataRequest(BaseModel):
    issuer_id: str
    ial: IdentityAssuranceLevel
    disclosure_policies: List[DisclosurePolicy]
    valid_for_minutes: int = Field(5, ge=1, le=5)
    holder_hint: Optional[str] = None
    holder_did: Optional[str] = None
    payload_template: Optional[CredentialPayload] = Field(
        None, description="Optional template so the wallet knows what data will be requested",
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
            raise HTTPException(status_code=400, detail=f"Duplicate disclosure policy for scope {policy.scope}")
        seen_scopes.add(policy.scope)
        if not policy.fields:
            raise HTTPException(status_code=400, detail=f"Disclosure fields for scope {policy.scope} cannot be empty")


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
