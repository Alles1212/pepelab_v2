from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from .models import (
    ConsentRecord,
    Credential,
    Presentation,
    VerificationRequest,
)


class InMemoryStore:
    """A tiny in-memory event store to keep the prototype stateless and auditable."""

    def __init__(self) -> None:
        self._credentials: Dict[str, Credential] = {}
        self._verification_requests: Dict[str, VerificationRequest] = {}
        self._consents: Dict[str, ConsentRecord] = {}
        self._presentations: Dict[str, Presentation] = {}

    # Credential lifecycle -------------------------------------------------
    def persist_credential(self, credential: Credential) -> None:
        self._credentials[credential.credential_id] = credential

    def get_credential(self, credential_id: str) -> Optional[Credential]:
        return self._credentials.get(credential_id)

    def list_holder_credentials(self, holder_did: str) -> List[Credential]:
        return [c for c in self._credentials.values() if c.holder_did == holder_did]

    def revoke_credential(self, credential_id: str, revoked_at: Optional[datetime] = None) -> None:
        cred = self._credentials.get(credential_id)
        if not cred:
            raise KeyError(f"Unknown credential {credential_id}")
        cred.revoked_at = revoked_at or datetime.utcnow()
        self._credentials[credential_id] = cred

    def delete_holder_credentials(self, holder_did: str) -> int:
        removed = [cid for cid, cred in self._credentials.items() if cred.holder_did == holder_did]
        for cid in removed:
            del self._credentials[cid]
        return len(removed)

    # Verification request lifecycle --------------------------------------
    def persist_request(self, verification_request: VerificationRequest) -> None:
        self._verification_requests[verification_request.request_id] = verification_request

    def get_request(self, request_id: str) -> Optional[VerificationRequest]:
        return self._verification_requests.get(request_id)

    def list_active_requests(self, verifier_id: Optional[str] = None) -> List[VerificationRequest]:
        now = datetime.utcnow()
        return [
            r
            for r in self._verification_requests.values()
            if r.is_active(now) and (verifier_id is None or r.verifier_id == verifier_id)
        ]

    # Consent lifecycle ----------------------------------------------------
    def persist_consent(self, consent: ConsentRecord) -> None:
        self._consents[consent.consent_id] = consent

    def get_consent(self, consent_id: str) -> Optional[ConsentRecord]:
        return self._consents.get(consent_id)

    def list_holder_consents(self, holder_did: str) -> List[ConsentRecord]:
        return [c for c in self._consents.values() if c.holder_did == holder_did]

    # Presentation lifecycle ----------------------------------------------
    def persist_presentation(self, presentation: Presentation) -> None:
        self._presentations[presentation.presentation_id] = presentation

    def list_presentations_for_request(self, request_id: str) -> List[Presentation]:
        return [p for p in self._presentations.values() if p.consent_id == request_id]

    def list_presentations_for_verifier(self, verifier_id: str) -> List[Presentation]:
        return [p for p in self._presentations.values() if p.verifier_id == verifier_id]

    def delete_presentations_for_holder(self, holder_did: str) -> int:
        to_remove = [
            pid
            for pid, pres in self._presentations.items()
            if self._consents.get(pres.consent_id) and self._consents[pres.consent_id].holder_did == holder_did
        ]
        for pid in to_remove:
            del self._presentations[pid]
        return len(to_remove)


store = InMemoryStore()
