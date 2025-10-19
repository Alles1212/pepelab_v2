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
)


class InMemoryStore:
    """A tiny in-memory store for demo purposes."""

    def __init__(self) -> None:
        self._credential_offers: Dict[str, CredentialOffer] = {}
        self._transaction_index: Dict[str, str] = {}
        self._verification_sessions: Dict[str, VerificationSession] = {}
        self._presentations: Dict[str, Presentation] = {}
        self._results: Dict[str, VerificationResult] = {}
        self._consents: Dict[str, ConsentRecord] = {}

    # -------------------------------
    # Credential lifecycle
    # -------------------------------
    def persist_credential_offer(self, credential: CredentialOffer) -> None:
        self._credential_offers[credential.credential_id] = credential
        self._transaction_index[credential.transaction_id] = credential.credential_id

    def get_credential_offer(self, credential_id: str) -> Optional[CredentialOffer]:
        return self._credential_offers.get(credential_id)

    def get_credential_offer_by_transaction(self, transaction_id: str) -> Optional[CredentialOffer]:
        credential_id = self._transaction_index.get(transaction_id)
        return self._credential_offers.get(credential_id) if credential_id else None

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

    # -------------------------------
    # Verification session lifecycle
    # -------------------------------
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

    # -------------------------------
    # Consent lifecycle
    # -------------------------------
    def persist_consent(self, consent: ConsentRecord) -> None:
        self._consents[consent.consent_id] = consent

    def get_consent(self, consent_id: str) -> Optional[ConsentRecord]:
        return self._consents.get(consent_id)

    def list_holder_consents(self, holder_did: str) -> List[ConsentRecord]:
        return [c for c in self._consents.values() if c.holder_did == holder_did]

    # -------------------------------
    # Presentation lifecycle
    # -------------------------------
    def persist_presentation(self, presentation: Presentation) -> None:
        self._presentations[presentation.presentation_id] = presentation

    def get_presentation(self, presentation_id: str) -> Optional[Presentation]:
        return self._presentations.get(presentation_id)

    def list_presentations_for_session(self, session_id: str) -> List[Presentation]:
        return [p for p in self._presentations.values() if getattr(p, "session_id", None) == session_id]

    def list_presentations_for_verifier(self, verifier_id: str) -> List[Presentation]:
        return [p for p in self._presentations.values() if p.verifier_id == verifier_id]

    def delete_presentation(self, presentation_id: str) -> None:
        presentation = self._presentations.pop(presentation_id, None)
        if presentation:
            keys_to_remove = [key for key in self._results if key.endswith(f":{presentation.presentation_id}")]
            for key in keys_to_remove:
                self._results.pop(key, None)

    # -------------------------------
    # Result cache
    # -------------------------------
    def persist_result(self, result: VerificationResult) -> None:
        key = f"{result.session_id}:{result.presentation.presentation_id}"
        self._results[key] = result

    def get_result(self, session_id: str, presentation_id: str) -> Optional[VerificationResult]:
        return self._results.get(f"{session_id}:{presentation_id}")

    # -------------------------------
    # Forget / 清除使用者資料
    # -------------------------------
    def forget_holder(self, holder_did: str) -> ForgetSummary:
        credential_ids = [
            cid for cid, c in self._credential_offers.items() if c.holder_did == holder_did
        ]
        for cid in credential_ids:
            cred = self._credential_offers.pop(cid, None)
            if cred:
                self._transaction_index.pop(cred.transaction_id, None)

        presentations_to_remove = [
            pid for pid, p in self._presentations.items() if p.holder_did == holder_did
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

    # -------------------------------
    # Session 清除
    # -------------------------------
    def purge_session(self, session_id: str) -> None:
        self._verification_sessions.pop(session_id, None)
        to_remove = [
            pid for pid, p in self._presentations.items()
            if getattr(p, "session_id", None) == session_id
        ]
        for pid in to_remove:
            self.delete_presentation(pid)

        result_keys = [key for key in self._results if key.startswith(f"{session_id}:")]
        for key in result_keys:
            self._results.pop(key, None)


store = InMemoryStore()
