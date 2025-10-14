from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from .models import (
    CredentialOffer,
    CredentialStatus,
    ForgetSummary,
    Presentation,
    VerificationResult,
    VerificationSession,
    ConsentRecord,
    Credential,
    VerificationRequest,
)


class ConsentRecord(BaseModel):
    consent_id: str
    holder_did: str
    verifier_id: str
    consent_given_at: datetime
    
class InMemoryStore:
    """A tiny in-memory store for demo purposes."""

    def __init__(self) -> None:
        self._credential_offers: Dict[str, CredentialOffer] = {}
        self._credentials: Dict[str, Credential] = {}
        self._transaction_index: Dict[str, str] = {}
        self._verification_sessions: Dict[str, VerificationSession] = {}
        self._verification_requests: Dict[str, VerificationRequest] = {}
        self._consents: Dict[str, ConsentRecord] = {}
        self._presentations: Dict[str, Presentation] = {}
        self._results: Dict[str, VerificationResult] = {}

    # Credential lifecycle -------------------------------------------------
    def persist_credential_offer(self, credential: CredentialOffer) -> None:
        self._credential_offers[credential.credential_id] = credential
        self._transaction_index[credential.transaction_id] = credential.credential_id

    def get_credential_offer(self, credential_id: str) -> Optional[CredentialOffer]:
        return self._credential_offers.get(credential_id)

    def get_credential_offer_by_transaction(self, transaction_id: str) -> Optional[CredentialOffer]:
        credential_id = self._transaction_index.get(transaction_id)
        if not credential_id:
            return None
        return self._credential_offers.get(credential_id)

    def update_credential_offer(self, credential: CredentialOffer) -> None:
        self._credential_offers[credential.credential_id] = credential
        self._transaction_index[credential.transaction_id] = credential.credential_id

    def list_credential_offers_for_holder(self, holder_did: str) -> List[CredentialOffer]:
        return [c for c in self._credential_offers.values() if c.holder_did == holder_did]

    def revoke_credential_offer(self, credential_id: str) -> None:
        credential = self._credential_offers.get(credential_id)
        if not credential:
            raise KeyError(f"Unknown credential {credential_id}")
        credential.status = CredentialStatus.REVOKED
        credential.last_action_at = datetime.utcnow()
        self.update_credential_offer(credential)

    def delete_credential_offer(self, credential_id: str) -> None:
        credential = self._credential_offers.pop(credential_id, None)
        if credential:
            self._transaction_index.pop(credential.transaction_id, None)

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

    # Verification session lifecycle --------------------------------------
    def persist_verification_session(self, session: VerificationSession) -> None:
        self._verification_sessions[session.session_id] = session

    def get_verification_session(self, session_id: str) -> Optional[VerificationSession]:
        return self._verification_sessions.get(session_id)

    def list_active_sessions(self, verifier_id: Optional[str] = None) -> List[VerificationSession]:
        now = datetime.utcnow()
        return [
            s for s in self._verification_sessions.values()
            if s.is_active(now) and (verifier_id is None or s.verifier_id == verifier_id)
        ]

    # Verification request lifecycle --------------------------------------
    def persist_request(self, verification_request: VerificationRequest) -> None:
        self._verification_requests[verification_request.request_id] = verification_request

    def get_request(self, request_id: str) -> Optional[VerificationRequest]:
        return self._verification_requests.get(request_id)

    def list_active_requests(self, verifier_id: Optional[str] = None) -> List[VerificationRequest]:
        now = datetime.utcnow()
        return [
            r for r in self._verification_requests.values()
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

    def get_presentation(self, presentation_id: str) -> Optional[Presentation]:
        return self._presentations.get(presentation_id)

    def list_presentations_for_session(self, session_id: str) -> List[Presentation]:
        return [p for p in self._presentations.values() if getattr(p, "session_id", None) == session_id]

    def list_presentations_for_request(self, request_id: str) -> List[Presentation]:
        return [p for p in self._presentations.values() if getattr(p, "consent_id", None) == request_id]

    def list_presentations_for_verifier(self, verifier_id: str) -> List[Presentation]:
        return [p for p in self._presentations.values() if p.verifier_id == verifier_id]

    def delete_presentation(self, presentation_id: str) -> None:
        presentation = self._presentations.pop(presentation_id, None)
        if presentation:
            keys_to_remove = [key for key in self._results if key.endswith(f":{presentation.presentation_id}")]
            for key in keys_to_remove:
                self._results.pop(key, None)

    def delete_presentations_for_holder(self, holder_did: str) -> int:
        to_remove = [
            pid for pid, pres in self._presentations.items()
            if self._consents.get(pres.consent_id) and self._consents[pres.consent_id].holder_did == holder_did
        ]
        for pid in to_remove:
            del self._presentations[pid]
        return len(to_remove)

    # Verification result cache -------------------------------------------
    def persist_result(self, result: VerificationResult) -> None:
        key = f"{getattr(result, 'session_id', 'session')}:{result.presentation.presentation_id}"
        self._results[key] = result

    def get_result(self, session_id: str, presentation_id: str) -> Optional[VerificationResult]:
        key = f"{session_id}:{presentation_id}"
        return self._results.get(key)

    # Forget / right-to-be-forgotten --------------------------------------
    def forget_holder(self, holder_did: str) -> ForgetSummary:
        credential_ids = [
            credential_id for credential_id, credential in self._credential_offers.items()
            if credential.holder_did == holder_did
        ]
        for credential_id in credential_ids:
            credential = self._credential_offers.pop(credential_id, None)
            if credential:
                self._transaction_index.pop(credential.transaction_id, None)

        presentations_to_remove = [
            pid for pid, presentation in self._presentations.items()
            if presentation.holder_did == holder_did
        ]
        for pid in presentations_to_remove:
            self.delete_presentation(pid)

        results_to_remove = [
            key for key, result in self._results.items()
            if result.presentation.holder_did == holder_did
        ]
        for key in results_to_remove:
            self._results.pop(key, None)

        return ForgetSummary(
            holder_did=holder_did,
            credentials_removed=len(credential_ids),
            presentations_removed=len(presentations_to_remove),
            verification_results_removed=len(results_to_remove),
        )

    def purge_session(self, session_id: str) -> None:
        self._verification_sessions.pop(session_id, None)
        presentations_to_remove = [
            pid for pid, presentation in self._presentations.items()
            if getattr(presentation, "session_id", None) == session_id
        ]
        for pid in presentations_to_remove:
            self.delete_presentation(pid)
        keys_to_remove = [key for key in self._results if key.startswith(f"{session_id}:")]
        for key in keys_to_remove:
            self._results.pop(key, None)


store = InMemoryStore()
