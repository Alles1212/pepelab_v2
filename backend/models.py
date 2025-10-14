from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from typing import Literal

from pydantic import BaseModel, Field, root_validator


class IdentityAssuranceLevel(str, Enum):
    """IAL definitions aligned with Taiwan MyData / NHI assurance levels."""

    MYDATA_LIGHT = "MYDATA_LIGHT"
    """Login with MyData soft token (基本憑證)."""

    NHI_CARD_PIN = "NHI_CARD_PIN"
    """NHI smart card + PIN verification."""

    MOICA_CERT = "MOICA_CERT"
    """MOICA citizen digital certificate with card reader."""


IAL_ORDER = {
    IdentityAssuranceLevel.MYDATA_LIGHT: 1,
    IdentityAssuranceLevel.NHI_CARD_PIN: 2,
    IdentityAssuranceLevel.MOICA_CERT: 3,
}


IAL_DESCRIPTIONS = {
    IdentityAssuranceLevel.MYDATA_LIGHT: "MyData 行動化驗證（手機門號＋健保卡號）對應 IAL2 遠端實名驗證。",
    IdentityAssuranceLevel.NHI_CARD_PIN: "健保卡 + PIN 裝置綁定（健保快易通 APP）屬於 IAL2 強度。",
    IdentityAssuranceLevel.MOICA_CERT: "自然人憑證或醫事人員卡臨櫃核發，相當於 IAL3 高度保證。",
}


def describe_ial(ial: IdentityAssuranceLevel) -> str:
    return IAL_DESCRIPTIONS[ial]


class FHIRCoding(BaseModel):
    system: str = Field(..., description="FHIR coding system URI")
    code: str = Field(..., description="Code value (e.g. ICD-10, ATC)")
    display: Optional[str] = Field(None, description="Human friendly label")


class FHIRCodeableConcept(BaseModel):
    coding: List[FHIRCoding]
    text: Optional[str] = None


class FHIRIdentifier(BaseModel):
    system: str
    value: str
    assigner: Optional[str] = None


class FHIRConditionSummary(BaseModel):
    resourceType: Literal["Condition"] = "Condition"
    id: str
    code: FHIRCodeableConcept
    recordedDate: date
    encounter: FHIRIdentifier
    subject: FHIRIdentifier


class FHIRMedicationDispenseSummary(BaseModel):
    resourceType: Literal["MedicationDispense"] = "MedicationDispense"
    id: str
    medicationCodeableConcept: FHIRCodeableConcept
    quantity_text: str = Field(..., description="Formatted quantity string, e.g. '30 tablets'")
    days_supply: int = Field(..., ge=1, description="Days of therapy covered by this dispense")
    performer: Optional[FHIRIdentifier] = Field(
        None, description="Pharmacist or institution identifier"
    )
    pickup_window_end: Optional[date] = Field(
        None, description="Last day the medication can be picked up"
    )


class CredentialPayload(BaseModel):
    """FHIR-aligned payload embedded inside the verifiable credential."""

    fhir_profile: str = Field(
        "https://profiles.iisigroup.com.tw/StructureDefinition/medssi-bundle",
        description="FHIR profile URI used for this credential payload",
    )
    condition: FHIRConditionSummary
    encounter_summary_hash: str = Field(
        ..., description="Hash of the supporting DiagnosticReport / bundle stored off-chain"
    )
    managing_organization: FHIRIdentifier
    issued_on: date
    consent_expires_on: Optional[date] = Field(
        None, description="Holder defined expiry for consented sharing"
    )
    medication_dispense: Optional[List[FHIRMedicationDispenseSummary]] = Field(
        default_factory=list,
        description="Optional medication dispense summaries linked to the visit",
    )


class IssuanceMode(str, Enum):
    WITH_DATA = "WITH_DATA"
    WITHOUT_DATA = "WITHOUT_DATA"


class DisclosureScope(str, Enum):
    MEDICAL_RECORD = "MEDICAL_RECORD"
    MEDICATION_PICKUP = "MEDICATION_PICKUP"


class DisclosurePolicy(BaseModel):
    scope: DisclosureScope
    fields: List[str] = Field(
        ..., description="List of FHIR path strings available for selective disclosure"
    )
    description: Optional[str] = Field(None, description="Human friendly explanation")


class CredentialStatus(str, Enum):
    OFFERED = "OFFERED"
    ISSUED = "ISSUED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"


class CredentialOffer(BaseModel):
    credential_id: str
    transaction_id: str
    issuer_id: str
    ial: IdentityAssuranceLevel
    ial_description: str
    mode: IssuanceMode
    qr_token: str
    nonce: str
    status: CredentialStatus
    created_at: datetime
    expires_at: datetime
    last_action_at: datetime
    disclosure_policies: List[DisclosurePolicy]
    holder_did: Optional[str] = None
    holder_hint: Optional[str] = None
    payload: Optional[CredentialPayload] = None

    @root_validator(pre=True)
    def _ensure_ial_description(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        ial_value = values.get("ial")
        if ial_value is not None and "ial_description" not in values:
            if not isinstance(ial_value, IdentityAssuranceLevel):
                ial_value = IdentityAssuranceLevel(ial_value)
            values["ial_description"] = describe_ial(ial_value)
        return values

    def is_active(self, as_of: Optional[datetime] = None) -> bool:
        now = as_of or datetime.utcnow()
        return self.status not in {CredentialStatus.REVOKED, CredentialStatus.DECLINED} and now <= self.expires_at

    def satisfies_ial(self, required: IdentityAssuranceLevel) -> bool:
        return IAL_ORDER[self.ial] >= IAL_ORDER[required]


class QRCodeResponse(BaseModel):
    credential: CredentialOffer
    qr_payload: str


class NonceResponse(BaseModel):
    transaction_id: str
    credential_id: str
    nonce: str
    ial: IdentityAssuranceLevel
    ial_description: str
    status: CredentialStatus
    expires_at: datetime
    mode: IssuanceMode
    disclosure_policies: List[DisclosurePolicy]
    payload_available: bool

    @root_validator(pre=True)
    def _ensure_nonce_ial(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        ial_value = values.get("ial")
        if ial_value is not None and "ial_description" not in values:
            if not isinstance(ial_value, IdentityAssuranceLevel):
                ial_value = IdentityAssuranceLevel(ial_value)
            values["ial_description"] = describe_ial(ial_value)
        return values


class CredentialAction(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    REVOKE = "REVOKE"
    UPDATE = "UPDATE"


class CredentialActionRequest(BaseModel):
    action: CredentialAction
    holder_did: Optional[str] = None
    payload: Optional[CredentialPayload] = None
    disclosures: Optional[Dict[str, str]] = None


class VerificationSession(BaseModel):
    session_id: str
    verifier_id: str
    verifier_name: str
    purpose: str
    required_ial: IdentityAssuranceLevel
    ial_description: str
    scope: DisclosureScope
    allowed_fields: List[str]
    qr_token: str
    created_at: datetime
    expires_at: datetime
    last_polled_at: datetime

    @root_validator(pre=True)
    def _ensure_session_ial(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        ial_value = values.get("required_ial")
        if ial_value is not None and "ial_description" not in values:
            if not isinstance(ial_value, IdentityAssuranceLevel):
                ial_value = IdentityAssuranceLevel(ial_value)
            values["ial_description"] = describe_ial(ial_value)
        return values

    def is_active(self, as_of: Optional[datetime] = None) -> bool:
        now = as_of or datetime.utcnow()
        return now <= self.expires_at


class VerificationCodeResponse(BaseModel):
    session: VerificationSession
    qr_payload: str


class Presentation(BaseModel):
    presentation_id: str
    session_id: str
    credential_id: str
    holder_did: str
    verifier_id: str
    scope: DisclosureScope
    disclosed_fields: Dict[str, str]
    issued_at: datetime


class VerificationResult(BaseModel):
    session_id: str
    verifier_id: str
    verified: bool
    presentation: Presentation


class RiskInsight(BaseModel):
    scope: DisclosureScope
    gastritis_risk_score: float
    trend_window_days: int
    supporting_indicators: Dict[str, float]


class RiskInsightResponse(BaseModel):
    result: VerificationResult
    insight: RiskInsight


class ForgetSummary(BaseModel):
    holder_did: str
    credentials_removed: int
    presentations_removed: int
    verification_results_removed: int
