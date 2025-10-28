from __future__ import annotations

import base64
import io
import json
import os
import secrets
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import (
    APIRouter,
    Body,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

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


try:  # pragma: no cover - optional dependency for nicer QR codes
    import qrcode
except Exception:  # pragma: no cover - fallback to text payloads
    qrcode = None

app = FastAPI(title="MedSSI Sandbox APIs", version="0.6.0")
allowed_origins_env = os.getenv(
    "MEDSSI_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173",
)
ALLOWED_ORIGINS = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
api_v2 = APIRouter(prefix="/v2", tags=["MedSSI v2"])


ISSUER_ACCESS_TOKEN = os.getenv(
    "MEDSSI_ISSUER_TOKEN", "8BpMc9xm2l1HCJxx4Fm4m5D7KTEElRWP" # change to your own token
)
VERIFIER_ACCESS_TOKEN = os.getenv(
    "MEDSSI_VERIFIER_TOKEN", "J3LdHEiVxmHBYJ6iStnmATLblzRkz2AC" # change to your own token
)
WALLET_ACCESS_TOKEN = os.getenv("MEDSSI_WALLET_TOKEN", "wallet-sandbox-token")
DEFAULT_ISSUER_ID = os.getenv(
    "MEDSSI_DEFAULT_ISSUER_ID", "did:example:moda-issuer"
)


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
    issuer_id: str = Field(..., alias="issuerId")
    holder_did: Optional[str] = Field(None, alias="holderDid")
    holder_hint: Optional[str] = Field(
        None,
        alias="holderHint",
        description="Optional hint shown to wallets (e.g. patient name)",
    )
    ial: IdentityAssuranceLevel = Field(
        IdentityAssuranceLevel.NHI_CARD_PIN, alias="ial"
    )
    primary_scope: DisclosureScope = Field(
        DisclosureScope.MEDICAL_RECORD, alias="primaryScope"
    )
    payload: Optional[Union[CredentialPayload, Dict[str, Any]]] = Field(
        None, alias="payload"
    )
    disclosure_policies: Optional[List[DisclosurePolicy]] = Field(
        default=None,
        alias="disclosurePolicies",
        description="Selective disclosure policies grouped by scope.",
    )
    valid_for_minutes: int = Field(5, ge=1, le=5, alias="validMinutes")
    transaction_id: Optional[str] = Field(None, alias="transactionId")

    class Config:
        allow_population_by_field_name = True


class IssuanceWithoutDataRequest(BaseModel):
    issuer_id: str = Field(..., alias="issuerId")
    ial: IdentityAssuranceLevel = Field(
        IdentityAssuranceLevel.NHI_CARD_PIN, alias="ial"
    )
    primary_scope: DisclosureScope = Field(
        DisclosureScope.MEDICAL_RECORD, alias="primaryScope"
    )
    disclosure_policies: Optional[List[DisclosurePolicy]] = Field(
        default=None, alias="disclosurePolicies"
    )
    valid_for_minutes: int = Field(5, ge=1, le=5, alias="validMinutes")
    holder_hint: Optional[str] = Field(None, alias="holderHint")
    holder_did: Optional[str] = Field(None, alias="holderDid")
    transaction_id: Optional[str] = Field(None, alias="transactionId")
    payload_template: Optional[Union[CredentialPayload, Dict[str, Any]]] = Field(
        None,
        alias="payloadTemplate",
        description="Template describing the FHIR structure the holder must supply.",
    )

    class Config:
        allow_population_by_field_name = True


class VerificationSubmission(BaseModel):
    session_id: str
    credential_id: str
    holder_did: str
    disclosed_fields: Dict[str, str]


class ResetResponse(BaseModel):
    message: str
    timestamp: datetime


class MODAIssuanceField(BaseModel):
    ename: str
    content: Optional[str] = ""


class MODAIssuanceRequest(BaseModel):
    vc_uid: str = Field(..., alias="vcUid")
    issuance_date: Optional[date] = Field(None, alias="issuanceDate")
    expired_date: Optional[date] = Field(None, alias="expiredDate")
    fields: List[MODAIssuanceField] = Field(default_factory=list, alias="fields")
    holder_did: Optional[str] = Field(None, alias="holderDid")
    issuer_id: Optional[str] = Field(None, alias="issuerId")
    transaction_id: Optional[str] = Field(None, alias="transactionId")
    valid_minutes: Optional[int] = Field(None, alias="validMinutes")
    ial: Optional[IdentityAssuranceLevel] = Field(None, alias="ial")

    class Config:
        allow_population_by_field_name = True


class GovIssueResponse(BaseModel):
    transaction_id: str = Field(..., alias="transactionId")
    qr_code: str = Field(..., alias="qrCode")
    qr_payload: str = Field(..., alias="qrPayload")
    deep_link: str = Field(..., alias="deepLink")
    credential_id: str = Field(..., alias="credentialId")
    expires_at: datetime = Field(..., alias="expiresAt")
    ial: IdentityAssuranceLevel = Field(..., alias="ial")
    ial_description: str = Field(..., alias="ialDescription")
    scope: DisclosureScope = Field(..., alias="scope")

    class Config:
        allow_population_by_field_name = True


class GovCredentialNonceResponse(BaseModel):
    transaction_id: str = Field(..., alias="transactionId")
    credential_id: str = Field(..., alias="credentialId")
    credential_status: CredentialStatus = Field(..., alias="credentialStatus")
    nonce: str = Field(..., alias="nonce")
    ial: IdentityAssuranceLevel = Field(..., alias="ial")
    ial_description: str = Field(..., alias="ialDescription")
    mode: IssuanceMode = Field(..., alias="mode")
    expires_at: datetime = Field(..., alias="expiresAt")
    payload_available: bool = Field(..., alias="payloadAvailable")
    disclosure_policies: List[DisclosurePolicy] = Field(..., alias="disclosurePolicies")
    payload_template: Optional[CredentialPayload] = Field(None, alias="payloadTemplate")
    payload: Optional[CredentialPayload] = Field(None, alias="payload")
    credential: str = Field(..., alias="credential")

    class Config:
        allow_population_by_field_name = True


class OIDVPSessionRequest(BaseModel):
    verifier_id: str = Field(..., alias="verifierId")
    verifier_name: str = Field(..., alias="verifierName")
    purpose: Optional[str] = Field("憑證驗證", alias="purpose")
    scope: DisclosureScope = Field(DisclosureScope.MEDICAL_RECORD, alias="scope")
    ial: IdentityAssuranceLevel = Field(IdentityAssuranceLevel.NHI_CARD_PIN, alias="ial")
    fields: Optional[List[str]] = Field(None, alias="fields")
    valid_minutes: int = Field(5, ge=1, le=10, alias="validMinutes")
    transaction_id: Optional[str] = Field(None, alias="transactionId")
    ref: Optional[str] = Field(None, alias="ref")

    class Config:
        allow_population_by_field_name = True


class OIDVPQRCodeResponse(BaseModel):
    transaction_id: str = Field(..., alias="transactionId")
    qrcode_image: str = Field(..., alias="qrcodeImage")
    auth_uri: str = Field(..., alias="authUri")
    qr_payload: str = Field(..., alias="qrPayload")
    scope: DisclosureScope = Field(..., alias="scope")
    ial: IdentityAssuranceLevel = Field(..., alias="ial")
    expires_at: datetime = Field(..., alias="expiresAt")

    class Config:
        allow_population_by_field_name = True


class OIDVPResultRequest(BaseModel):
    transaction_id: str = Field(..., alias="transactionId")

    class Config:
        allow_population_by_field_name = True


class OIDVPResultResponse(BaseModel):
    verify_result: bool = Field(..., alias="verifyResult")
    result_description: str = Field(..., alias="resultDescription")
    transaction_id: str = Field(..., alias="transactionId")
    data: List[Dict[str, Any]] = Field(default_factory=list, alias="data")

    class Config:
        allow_population_by_field_name = True


def _build_qr_payload(token: str, kind: str) -> str:
    return f"medssi://{kind}?token={token}"


def _make_qr_data_uri(payload: str) -> str:
    if qrcode is not None:
        buffer = io.BytesIO()
        image = qrcode.make(payload)
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    return f"data:text/plain;base64,{encoded}"


def _build_deep_link(
    token: str, *, kind: str, transaction_id: Optional[str] = None
) -> str:
    base_scheme = "modadigitalwallet://"
    if kind == "credential":
        return f"{base_scheme}credential_offer?token={token}"
    params = [f"token={token}"]
    if transaction_id:
        params.append(f"transactionId={transaction_id}")
    return f"{base_scheme}authorize?{'&'.join(params)}"


def _normalize_vc_uid(vc_uid: str) -> str:
    slug = vc_uid.lower()
    if "_" in slug:
        slug = slug.split("_")[-1]
    return slug


MODA_VC_SCOPE_MAP = {
    "vc_cond": DisclosureScope.MEDICAL_RECORD,
    "vc_algy": DisclosureScope.MEDICAL_RECORD,
    "vc_pid": DisclosureScope.MEDICAL_RECORD,
    "vc_cons": DisclosureScope.RESEARCH_ANALYTICS,
    "vc_rx": DisclosureScope.MEDICATION_PICKUP,
}


MODA_SCOPE_DEFAULT_FIELDS = {
    DisclosureScope.MEDICAL_RECORD: ["cond_code", "cond_display", "cond_onset"],
    DisclosureScope.MEDICATION_PICKUP: [
        "med_code",
        "med_name",
        "qty_value",
        "qty_unit",
        "pickup_deadline",
    ],
    DisclosureScope.RESEARCH_ANALYTICS: [
        "cons_scope",
        "cons_purpose",
        "cons_path",
        "cons_issuer",
    ],
}


MODA_FIELD_TO_FHIR = {
    "cond_code": "condition.code.coding[0].code",
    "cond_display": "condition.code.coding[0].display",
    "cond_onset": "condition.recordedDate",
    "med_code": "medication_dispense[0].medicationCodeableConcept.coding[0].code",
    "med_name": "medication_dispense[0].medicationCodeableConcept.coding[0].display",
    "qty_value": "medication_dispense[0].days_supply",
    "pickup_deadline": "medication_dispense[0].pickup_window_end",
}


MODA_SCOPE_ALIAS = {
    "RESEARCH_INFO": DisclosureScope.RESEARCH_ANALYTICS.value,
    "RESEARCH": DisclosureScope.RESEARCH_ANALYTICS.value,
    "MEDICAL_INFO": DisclosureScope.MEDICAL_RECORD.value,
    "MEDICATION": DisclosureScope.MEDICATION_PICKUP.value,
}


def _mock_credential_jwt(offer: CredentialOffer) -> str:
    header = {"typ": "JWT", "alg": "ES256"}
    payload = {
        "jti": f"https://medssi.dev/api/credential/{offer.credential_id}",
        "sub": offer.holder_did or "did:example:patient-demo",
        "iss": offer.issuer_id,
        "iat": int(offer.created_at.timestamp()),
        "exp": int(offer.expires_at.timestamp()),
        "scope": offer.primary_scope.value,
        "nonce": offer.nonce,
        "ial": offer.ial.value,
    }
    encoded_header = base64.urlsafe_b64encode(json.dumps(header).encode("utf-8")).decode(
        "ascii"
    ).rstrip("=")
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode(
        "ascii"
    ).rstrip("=")
    signature = base64.urlsafe_b64encode(
        f"sig:{offer.credential_id}".encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"{encoded_header}.{encoded_payload}.{signature}"


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


def _resolve_policies(
    policies: Optional[List[DisclosurePolicy]],
) -> List[DisclosurePolicy]:
    if policies:
        _ensure_valid_policies(policies)
        return policies
    defaults = _default_disclosure_policies()
    _ensure_valid_policies(defaults)
    return defaults


def _sample_payload() -> CredentialPayload:
    today = date.today()
    sample_dict: Dict[str, Any] = {
        "fhir_profile": "https://profiles.iisigroup.com.tw/StructureDefinition/medssi-bundle",
        "condition": {
            "resourceType": "Condition",
            "id": "cond-sample",
            "code": {
                "coding": [
                    {
                        "system": "http://hl7.org/fhir/sid/icd-10",
                        "code": "K29.7",
                        "display": "Gastritis, unspecified",
                    }
                ],
                "text": "Gastritis, unspecified",
            },
            "recordedDate": today.isoformat(),
            "encounter": {"system": "urn:medssi:encounter-id", "value": "enc-sample"},
            "subject": {"system": "did:example", "value": "did:example:patient-demo"},
        },
        "encounter_summary_hash": "urn:sha256:demo-sample-hash",
        "managing_organization": {"system": "urn:medssi:org", "value": "org:demo-hospital"},
        "issued_on": today.isoformat(),
        "consent_expires_on": None,
        "medication_dispense": [],
    }
    return CredentialPayload.parse_obj(sample_dict)


def _deep_merge(target: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in updates.items():
        if value is None:
            continue
        if key not in target:
            target[key] = value
            continue
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key] = _deep_merge(dict(target[key]), value)
        else:
            target[key] = value
    return target


def _payload_overrides_from_alias(alias_map: Dict[str, str]) -> Optional[Dict[str, Any]]:
    overrides: Dict[str, Any] = {}

    def merge(update: Dict[str, Any]) -> None:
        nonlocal overrides
        overrides = _deep_merge(overrides, update)

    if alias_map.get("cond_code"):
        merge(
            {
                "condition": {
                    "code": {
                        "coding": [
                            {
                                "system": "http://hl7.org/fhir/sid/icd-10",
                                "code": alias_map["cond_code"],
                            }
                        ]
                    }
                }
            }
        )
    if alias_map.get("cond_display"):
        merge(
            {
                "condition": {
                    "code": {
                        "coding": [
                            {
                                "display": alias_map["cond_display"],
                            }
                        ],
                        "text": alias_map["cond_display"],
                    }
                }
            }
        )
    if alias_map.get("cond_onset"):
        merge({"condition": {"recordedDate": alias_map["cond_onset"]}})

    if alias_map.get("med_code"):
        merge(
            {
                "medication_dispense": [
                    {
                        "medicationCodeableConcept": {
                            "coding": [
                                {
                                    "system": "http://www.whocc.no/atc",
                                    "code": alias_map["med_code"],
                                }
                            ]
                        }
                    }
                ]
            }
        )
    if alias_map.get("med_name"):
        merge(
            {
                "medication_dispense": [
                    {
                        "medicationCodeableConcept": {
                            "coding": [
                                {
                                    "display": alias_map["med_name"],
                                }
                            ],
                            "text": alias_map["med_name"],
                        }
                    }
                ]
            }
        )

    qty_value = alias_map.get("qty_value")
    qty_unit = alias_map.get("qty_unit")
    quantity_text: Optional[str] = None
    if qty_value:
        try:
            days_supply = int(qty_value)
        except ValueError:
            days_supply = None
        merge(
            {
                "medication_dispense": [
                    {
                        "days_supply": days_supply if days_supply is not None else qty_value,
                    }
                ]
            }
        )
        quantity_text = qty_value
    if qty_unit:
        quantity_text = f"{qty_value or ''} {qty_unit}".strip()
    if quantity_text:
        merge(
            {
                "medication_dispense": [
                    {
                        "quantity_text": quantity_text,
                    }
                ]
            }
        )

    if alias_map.get("pickup_deadline"):
        merge(
            {
                "medication_dispense": [
                    {
                        "pickup_window_end": alias_map["pickup_deadline"],
                    }
                ]
            }
        )

    return overrides or None


def _expand_aliases(alias_map: Dict[str, str]) -> Dict[str, str]:
    expanded = dict(alias_map)

    def copy_if_missing(source: str, target: str) -> None:
        if source in alias_map and target not in expanded:
            expanded[target] = alias_map[source]

    copy_if_missing("med_code", "medication_list[0].medication_code")
    copy_if_missing("med_name", "medication_list[0].medication_name")
    copy_if_missing("qty_value", "medication_list[0].dosage")
    copy_if_missing("pickup_deadline", "pickup_info.pickup_deadline")
    copy_if_missing("cons_scope", "consent.scope")
    copy_if_missing("cons_purpose", "consent.purpose")
    copy_if_missing("cons_issuer", "consent.issuer")
    copy_if_missing("cons_path", "consent.path")
    copy_if_missing("pid_hash", "pid_info.pid_hash")
    copy_if_missing("pid_name", "pid_info.pid_name")
    copy_if_missing("pid_birth", "pid_info.pid_birth")

    return expanded


def _coerce_payload(
    payload: Optional[Union[CredentialPayload, Dict[str, Any]]]
) -> CredentialPayload:
    if isinstance(payload, CredentialPayload):
        return payload
    sample = _sample_payload()
    if payload is None:
        return sample
    if isinstance(payload, dict):
        base = sample.dict()
        merged = _deep_merge(base, payload)
        try:
            return CredentialPayload.parse_obj(merged)
        except ValidationError:
            return sample
    try:
        return CredentialPayload.parse_obj(payload)
    except ValidationError:
        return sample


def _issue_offer(
    *,
    issuer_id: str,
    primary_scope: DisclosureScope,
    ial: IdentityAssuranceLevel,
    mode: IssuanceMode,
    disclosure_policies: List[DisclosurePolicy],
    valid_for_minutes: int,
    holder_did: Optional[str],
    holder_hint: Optional[str],
    payload: Optional[CredentialPayload] = None,
    payload_template: Optional[CredentialPayload] = None,
    transaction_id: Optional[str] = None,
    selected_disclosures: Optional[Dict[str, str]] = None,
    external_fields: Optional[Dict[str, str]] = None,
) -> Tuple[CredentialOffer, str]:
    offer = _create_offer(
        issuer_id=issuer_id,
        primary_scope=primary_scope,
        ial=ial,
        mode=mode,
        disclosure_policies=disclosure_policies,
        valid_for_minutes=valid_for_minutes,
        holder_did=holder_did,
        holder_hint=holder_hint,
        payload=payload,
        payload_template=payload_template,
        transaction_id=transaction_id,
        selected_disclosures=selected_disclosures,
        external_fields=external_fields,
    )
    qr_payload = _build_qr_payload(offer.qr_token, "credential")
    return offer, qr_payload


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
    transaction_id: Optional[str] = None,
    selected_disclosures: Optional[Dict[str, str]] = None,
    external_fields: Optional[Dict[str, str]] = None,
) -> CredentialOffer:
    now = datetime.utcnow()
    credential_id = f"cred-{uuid.uuid4().hex}"
    transaction_id = transaction_id or str(uuid.uuid4())
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
        selected_disclosures=selected_disclosures or {},
        external_fields=external_fields or {},
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


def _resolve_field_value(credential: CredentialOffer, field: str) -> Optional[str]:
    if field in credential.external_fields:
        value = credential.external_fields[field]
        if value not in (None, ""):
            return str(value)
    fhir_path = MODA_FIELD_TO_FHIR.get(field)
    if fhir_path:
        resolved = _resolve_payload_value(credential.payload, fhir_path)
        if resolved is not None:
            return resolved
    return _resolve_payload_value(credential.payload, field)


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


def _issue_from_data_request(
    request: IssuanceWithDataRequest,
) -> Tuple[CredentialOffer, str]:
    policies = _resolve_policies(request.disclosure_policies)
    payload = _coerce_payload(request.payload)
    holder_did = request.holder_did or "did:example:patient-demo"
    return _issue_offer(
        issuer_id=request.issuer_id,
        primary_scope=request.primary_scope,
        ial=request.ial,
        mode=IssuanceMode.WITH_DATA,
        disclosure_policies=policies,
        valid_for_minutes=request.valid_for_minutes,
        holder_did=holder_did,
        holder_hint=request.holder_hint,
        payload=payload,
        transaction_id=request.transaction_id,
    )


def _issue_from_template_request(
    request: IssuanceWithoutDataRequest,
) -> Tuple[CredentialOffer, str]:
    policies = _resolve_policies(request.disclosure_policies)
    payload_template = (
        _coerce_payload(request.payload_template)
        if request.payload_template is not None
        else None
    )
    holder_did = request.holder_did or None
    return _issue_offer(
        issuer_id=request.issuer_id,
        primary_scope=request.primary_scope,
        ial=request.ial,
        mode=IssuanceMode.WITHOUT_DATA,
        disclosure_policies=policies,
        valid_for_minutes=request.valid_for_minutes,
        holder_did=holder_did,
        holder_hint=request.holder_hint,
        payload_template=payload_template,
        transaction_id=request.transaction_id,
    )


def _scope_for_moda_vc(vc_uid: str) -> DisclosureScope:
    slug = _normalize_vc_uid(vc_uid)
    return MODA_VC_SCOPE_MAP.get(slug, DisclosureScope.MEDICAL_RECORD)


def _issue_from_moda_request(request: MODAIssuanceRequest) -> Tuple[CredentialOffer, str]:
    scope = _scope_for_moda_vc(request.vc_uid)
    ial = request.ial or IdentityAssuranceLevel.NHI_CARD_PIN
    holder_did = request.holder_did or "did:example:patient-demo"
    issuer_id = request.issuer_id or DEFAULT_ISSUER_ID
    valid_minutes = request.valid_minutes or 5
    valid_minutes = max(1, min(10, valid_minutes))

    alias_map = _expand_aliases(
        {field.ename: field.content or "" for field in request.fields if field.ename}
    )
    policy_fields = list(dict.fromkeys(alias_map.keys()))
    if not policy_fields:
        policy_fields = MODA_SCOPE_DEFAULT_FIELDS.get(scope, ["cond_code"])

    payload_overrides = _payload_overrides_from_alias(alias_map)
    payload = _coerce_payload(payload_overrides)

    policies = [
        DisclosurePolicy(
            scope=scope,
            fields=policy_fields,
            description="MODA 沙盒欄位設定",
        )
    ]

    return _issue_offer(
        issuer_id=issuer_id,
        primary_scope=scope,
        ial=ial,
        mode=IssuanceMode.WITH_DATA,
        disclosure_policies=policies,
        valid_for_minutes=valid_minutes,
        holder_did=holder_did,
        holder_hint=None,
        payload=payload,
        transaction_id=request.transaction_id,
        selected_disclosures=alias_map,
        external_fields=alias_map,
    )


def _normalize_scope_entries(raw_policies: Any) -> Any:
    if not isinstance(raw_policies, list):
        return raw_policies
    for item in raw_policies:
        if not isinstance(item, dict):
            continue
        scope_value = item.get("scope")
        if isinstance(scope_value, str):
            normalized = MODA_SCOPE_ALIAS.get(scope_value.upper(), scope_value.upper())
            item["scope"] = normalized
    return raw_policies


def _issue_with_data_from_payload(payload: Dict[str, Any]) -> Tuple[CredentialOffer, str]:
    try:
        if "disclosurePolicies" in payload:
            payload["disclosurePolicies"] = _normalize_scope_entries(payload["disclosurePolicies"])
        if "vcUid" in payload:
            moda_request = MODAIssuanceRequest.parse_obj(payload)
            return _issue_from_moda_request(moda_request)
        request = IssuanceWithDataRequest.parse_obj(payload)
        return _issue_from_data_request(request)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=json.loads(exc.json())) from exc


def _issue_template_from_payload(payload: Dict[str, Any]) -> Tuple[CredentialOffer, str]:
    try:
        if "disclosurePolicies" in payload:
            payload["disclosurePolicies"] = _normalize_scope_entries(payload["disclosurePolicies"])
        if "vcUid" in payload:
            moda_request = MODAIssuanceRequest.parse_obj(payload)
            return _issue_from_moda_request(moda_request)
        request = IssuanceWithoutDataRequest.parse_obj(payload)
        return _issue_from_template_request(request)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=json.loads(exc.json())) from exc


def _build_issue_response(offer: CredentialOffer, qr_payload: str) -> GovIssueResponse:
    return GovIssueResponse(
        transaction_id=offer.transaction_id,
        qr_code=_make_qr_data_uri(qr_payload),
        qr_payload=qr_payload,
        deep_link=_build_deep_link(
            offer.qr_token,
            kind="credential",
            transaction_id=offer.transaction_id,
        ),
        credential_id=offer.credential_id,
        expires_at=offer.expires_at,
        ial=offer.ial,
        ial_description=offer.ial_description,
        scope=offer.primary_scope,
    )


def _build_nonce_response(offer: CredentialOffer) -> GovCredentialNonceResponse:
    return GovCredentialNonceResponse(
        transaction_id=offer.transaction_id,
        credential_id=offer.credential_id,
        credential_status=offer.status,
        nonce=offer.nonce,
        ial=offer.ial,
        ial_description=offer.ial_description,
        mode=offer.mode,
        expires_at=offer.expires_at,
        payload_available=offer.payload is not None,
        disclosure_policies=offer.disclosure_policies,
        payload_template=offer.payload_template,
        payload=offer.payload,
        credential=_mock_credential_jwt(offer),
    )


@api_v2.post(
    "/api/qrcode/data",
    response_model=QRCodeResponse,
    dependencies=[Depends(require_issuer_token)],
)
def create_qr_with_data(request: IssuanceWithDataRequest) -> QRCodeResponse:
    offer, qr_payload = _issue_from_data_request(request)
    return QRCodeResponse(credential=offer, qr_payload=qr_payload)


@api_v2.post(
    "/api/qrcode/nodata",
    response_model=QRCodeResponse,
    dependencies=[Depends(require_issuer_token)],
)
def create_qr_without_data(request: IssuanceWithoutDataRequest) -> QRCodeResponse:
    offer, qr_payload = _issue_from_template_request(request)
    return QRCodeResponse(credential=offer, qr_payload=qr_payload)


api_public = APIRouter(prefix="/api", tags=["MODA Sandbox compatibility"])


@api_public.post(
    "/qrcode/data",
    response_model=GovIssueResponse,
    status_code=201,
    dependencies=[Depends(require_issuer_token)],
)
def gov_issue_with_data(payload: Dict[str, Any] = Body(...)) -> GovIssueResponse:
    offer, qr_payload = _issue_with_data_from_payload(payload)
    return _build_issue_response(offer, qr_payload)


@api_public.post(
    "/medical/card/issue",
    response_model=GovIssueResponse,
    status_code=201,
    dependencies=[Depends(require_issuer_token)],
)
def gov_issue_medical_card(payload: Dict[str, Any] = Body(...)) -> GovIssueResponse:
    offer, qr_payload = _issue_with_data_from_payload(payload)
    return _build_issue_response(offer, qr_payload)


@api_public.post(
    "/qrcode/nodata",
    response_model=GovIssueResponse,
    status_code=201,
    dependencies=[Depends(require_issuer_token)],
)
def gov_issue_without_data(payload: Dict[str, Any] = Body(...)) -> GovIssueResponse:
    offer, qr_payload = _issue_template_from_payload(payload)
    return _build_issue_response(offer, qr_payload)


@api_public.get(
    "/credential/nonce/{transaction_id}",
    response_model=GovCredentialNonceResponse,
    dependencies=[Depends(require_wallet_token)],
)
def gov_get_nonce(transaction_id: str) -> GovCredentialNonceResponse:
    offer = store.get_credential_by_transaction(transaction_id)
    if not offer:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "61010",
                "message": "指定VC不存在，QR Code尚未被掃描",
            },
        )
    return _build_nonce_response(offer)


@api_public.get(
    "/credential/nonce",
    response_model=GovCredentialNonceResponse,
    dependencies=[Depends(require_wallet_token)],
)
def gov_get_nonce_query(transactionId: str = Query(..., alias="transactionId")) -> GovCredentialNonceResponse:
    return gov_get_nonce(transactionId)


@api_public.put(
    "/credential/{credential_id}/{action}",
    dependencies=[Depends(require_issuer_token)],
)
def gov_update_credential(credential_id: str, action: str) -> Dict[str, Any]:
    if action.lower() != "revocation":
        raise HTTPException(
            status_code=400,
            detail={"code": "61006", "message": "不合法的VC操作類型"},
        )
    try:
        store.revoke_credential(credential_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "61006", "message": "不合法的VC識別碼"},
        ) from None
    return {"credentialStatus": CredentialStatus.REVOKED.value, "credentialId": credential_id}


@api_public.post(
    "/oidvp/qrcode",
    response_model=OIDVPQRCodeResponse,
    status_code=201,
    dependencies=[Depends(require_verifier_token)],
)
def gov_create_oidvp_qrcode(payload: OIDVPSessionRequest) -> OIDVPQRCodeResponse:
    fields = payload.fields or []
    if len(fields) == 1 and "," in fields[0]:
        fields = [segment.strip() for segment in fields[0].split(",") if segment.strip()]
    if not fields:
        fallback_policy = next(
            (
                policy
                for policy in _default_disclosure_policies()
                if policy.scope == payload.scope
            ),
            None,
        )
        fields = list(fallback_policy.fields) if fallback_policy else ["condition.code.coding[0].code"]

    now = datetime.utcnow()
    transaction_id = payload.transaction_id or str(uuid.uuid4())
    session = VerificationSession(
        session_id=f"sess-{uuid.uuid4().hex}",
        transaction_id=transaction_id,
        verifier_id=payload.verifier_id,
        verifier_name=payload.verifier_name,
        purpose=payload.purpose or "憑證驗證",
        required_ial=payload.ial,
        scope=payload.scope,
        allowed_fields=list(dict.fromkeys(fields)),
        qr_token=secrets.token_urlsafe(24),
        created_at=now,
        expires_at=now + timedelta(minutes=payload.valid_minutes),
        last_polled_at=now,
        template_ref=payload.ref,
    )
    store.persist_verification_session(session)
    qr_payload = _build_qr_payload(session.qr_token, "vp-session")
    return OIDVPQRCodeResponse(
        transaction_id=transaction_id,
        qrcode_image=_make_qr_data_uri(qr_payload),
        auth_uri=_build_deep_link(
            session.qr_token,
            kind="oidvp",
            transaction_id=transaction_id,
        ),
        qr_payload=qr_payload,
        scope=session.scope,
        ial=session.required_ial,
        expires_at=session.expires_at,
    )


@api_public.post(
    "/oidvp/result",
    response_model=OIDVPResultResponse,
    dependencies=[Depends(require_verifier_token)],
)
def gov_fetch_oidvp_result(payload: OIDVPResultRequest) -> OIDVPResultResponse:
    session = store.get_verification_session_by_transaction(payload.transaction_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={"code": "404", "message": "查無交易紀錄"},
        )
    result = store.latest_result_for_session(session.session_id)
    if not result:
        raise HTTPException(
            status_code=400,
            detail={"code": "400", "message": "尚未接收到使用者上傳資料"},
        )
    session.last_polled_at = datetime.utcnow()
    store.persist_verification_session(session)
    claims = [
        {
            "credentialType": "MedSSI.VerifiableCredential",
            "claims": [
                {"ename": field, "cname": field, "value": value}
                for field, value in result.presentation.disclosed_fields.items()
            ],
        }
    ]
    description = "success" if result.verified else "failed"
    return OIDVPResultResponse(
        verify_result=result.verified,
        result_description=description,
        transaction_id=payload.transaction_id,
        data=claims,
    )

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
        actual_value = _resolve_field_value(credential, field)
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


app.include_router(api_public)
app.include_router(api_v2)


@app.get("/healthz")
def healthcheck():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
