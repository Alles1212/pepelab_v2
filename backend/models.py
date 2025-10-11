from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class IdentityAssuranceLevel(str, Enum):
    IAL1 = "IAL1"
    IAL2 = "IAL2"
    IAL3 = "IAL3"


class CredentialPayload(BaseModel):
    diagnosis_code: str = Field(..., description="ICD-10-CM or SNOMED diagnosis code")
    visit_date: date
    physician_id: str
    facility_id: str
    encounter_notes_hash: str = Field(..., description="Hash pointer to the clinical note or bundle")
    lab_bundle_hash: Optional[str] = Field(
        None, description="Optional hash pointer to lab bundle stored off-chain"
    )
    expiry: Optional[date] = Field(
        None, description="Optional date after which the credential should be refreshed"
    )


class Credential(BaseModel):
    credential_id: str
    holder_did: str
    issuer_id: str
    ial: IdentityAssuranceLevel
    payload: CredentialPayload
    created_at: datetime
    revoked_at: Optional[datetime] = None

    def is_active(self, as_of: Optional[datetime] = None) -> bool:
        now = as_of or datetime.utcnow()
        if self.revoked_at and self.revoked_at <= now:
            return False
        if self.payload.expiry and self.payload.expiry < now.date():
            return False
        return True

    def satisfies_ial(self, required: IdentityAssuranceLevel) -> bool:
        return IAL_ORDER[self.ial] >= IAL_ORDER[required]


class VerificationScope(BaseModel):
    label: str
    fields: List[str]


class VerificationRequest(BaseModel):
    request_id: str
    verifier_id: str
    verifier_name: str
    purpose: str
    required_ial: IdentityAssuranceLevel
    allowed_scopes: List[VerificationScope]
    expires_at: datetime
    created_at: datetime

    def is_active(self, as_of: Optional[datetime] = None) -> bool:
        now = as_of or datetime.utcnow()
        return now <= self.expires_at


class ConsentDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ConsentRecord(BaseModel):
    consent_id: str
    request_id: str
    holder_did: str
    decision: ConsentDecision
    selected_scope_label: Optional[str] = None
    audited_at: datetime


class Presentation(BaseModel):
    presentation_id: str
    consent_id: str
    credential_id: str
    verifier_id: str
    disclosed_fields: Dict[str, str]
    issued_at: datetime


class RiskInsight(BaseModel):
    gastritis_risk_score: float
    trend_window_days: int
    supporting_indicators: Dict[str, float]


class RiskInsightResponse(BaseModel):
    presentation: Presentation
    insight: RiskInsight


IAL_ORDER = {
    IdentityAssuranceLevel.IAL1: 1,
    IdentityAssuranceLevel.IAL2: 2,
    IdentityAssuranceLevel.IAL3: 3,
}
