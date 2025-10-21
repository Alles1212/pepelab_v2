from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from .models import (
    CredentialOffer,
    CredentialStatus,
    DisclosureScope,
    ForgetSummary,
    Presentation,
    VerificationResult,
    VerificationSession,
)


class InMemoryStore:
    """A tiny in-memory store for demo purposes."""

    def __init__(self) -> None:
        self._credentials: Dict[str, CredentialOffer] = {}
        self._transaction_index: Dict[str, str] = {}
        self._verification_sessions: Dict[str, VerificationSession] = {}
        self._presentations: Dict[str, Presentation] = {}
        self._results: Dict[str, VerificationResult] = {}

    # Credential lifecycle -------------------------------------------------
    def persist_credential(self, credential: CredentialOffer) -> None:
        self._credentials[credential.credential_id] = credential
        self._transaction_index[credential.transaction_id] = credential.credential_id

    def get_credential(self, credential_id: str) -> Optional[CredentialOffer]:
        return self._credentials.get(credential_id)

    def get_credential_by_transaction(self, transaction_id: str) -> Optional[CredentialOffer]:
        credential_id = self._transaction_index.get(transaction_id)
        if not credential_id:
            return None
        return self._credentials.get(credential_id)

    def update_credential(self, credential: CredentialOffer) -> None:
        self._credentials[credential.credential_id] = credential
        self._transaction_index[credential.transaction_id] = credential.credential_id

    def list_credentials_for_holder(self, holder_did: str) -> List[CredentialOffer]:
        return [c for c in self._credentials.values() if c.holder_did == holder_did]

    def revoke_credential(self, credential_id: str) -> None:
        credential = self._credentials.get(credential_id)
        if not credential:
            raise KeyError(f"Unknown credential {credential_id}")
        credential.status = CredentialStatus.REVOKED
        credential.last_action_at = datetime.utcnow()
        credential.retention_expires_at = credential.last_action_at
        self.update_credential(credential)

    def delete_credential(self, credential_id: str) -> None:
        credential = self._credentials.pop(credential_id, None)
        if credential:
            self._transaction_index.pop(credential.transaction_id, None)

    # Verification session lifecycle --------------------------------------
    def persist_verification_session(self, session: VerificationSession) -> None:
        self._verification_sessions[session.session_id] = session

    def get_verification_session(self, session_id: str) -> Optional[VerificationSession]:
        return self._verification_sessions.get(session_id)

    def list_active_sessions(self, verifier_id: Optional[str] = None) -> List[VerificationSession]:
        now = datetime.utcnow()
        return [
            s
            for s in self._verification_sessions.values()
            if s.is_active(now) and (verifier_id is None or s.verifier_id == verifier_id)
        ]

    # Presentation lifecycle ----------------------------------------------
    def persist_presentation(self, presentation: Presentation) -> None:
        self._presentations[presentation.presentation_id] = presentation

    def get_presentation(self, presentation_id: str) -> Optional[Presentation]:
        return self._presentations.get(presentation_id)

    def list_presentations_for_session(self, session_id: str) -> List[Presentation]:
        return [p for p in self._presentations.values() if p.session_id == session_id]

    def delete_presentation(self, presentation_id: str) -> None:
        presentation = self._presentations.pop(presentation_id, None)
        if presentation:
            keys_to_remove = [
                key for key in self._results if key.endswith(f":{presentation.presentation_id}")
            ]
            for key in keys_to_remove:
                self._results.pop(key, None)

    # Verification result cache -------------------------------------------
    def persist_result(self, result: VerificationResult) -> None:
        key = f"{result.session_id}:{result.presentation.presentation_id}"
        self._results[key] = result

    def get_result(self, session_id: str, presentation_id: str) -> Optional[VerificationResult]:
        key = f"{session_id}:{presentation_id}"
        return self._results.get(key)

    # Forget / right-to-be-forgotten --------------------------------------
    def forget_holder(self, holder_did: str) -> ForgetSummary:
        credential_ids = [
            credential_id
            for credential_id, credential in self._credentials.items()
            if credential.holder_did == holder_did
        ]
        for credential_id in credential_ids:
            credential = self._credentials.pop(credential_id, None)
            if credential:
                self._transaction_index.pop(credential.transaction_id, None)

        presentations_to_remove = [
            pid
            for pid, presentation in self._presentations.items()
            if presentation.holder_did == holder_did
        ]
        for pid in presentations_to_remove:
            self.delete_presentation(pid)

        results_to_remove = [
            key
            for key, result in self._results.items()
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
            pid
            for pid, presentation in self._presentations.items()
            if presentation.session_id == session_id
        ]
        for pid in presentations_to_remove:
            self.delete_presentation(pid)
        keys_to_remove = [key for key in self._results if key.startswith(f"{session_id}:")]
        for key in keys_to_remove:
            self._results.pop(key, None)

    # Housekeeping ---------------------------------------------------------
    def cleanup_expired(self, now: Optional[datetime] = None) -> None:
        reference = now or datetime.utcnow()

        # Expire credential offers that were never accepted
        expired_offers = [
            credential_id
            for credential_id, credential in self._credentials.items()
            if credential.status == CredentialStatus.OFFERED
            and reference > credential.expires_at
        ]
        for credential_id in expired_offers:
            self.delete_credential(credential_id)

        # Seal or remove issued credentials whose retention elapsed
        for credential in list(self._credentials.values()):
            if credential.status != CredentialStatus.ISSUED:
                continue
            if credential.retention_expires_at and reference > credential.retention_expires_at:
                if credential.primary_scope == DisclosureScope.MEDICATION_PICKUP:
                    self.delete_credential(credential.credential_id)
                    continue
                if credential.payload is not None:
                    credential.payload = None
                    credential.selected_disclosures.clear()
                    credential.sealed_at = reference
                    credential.last_action_at = reference
                    self.update_credential(credential)

        # Remove expired verification sessions
        expired_sessions = [
            session_id
            for session_id, session in self._verification_sessions.items()
            if not session.is_active(reference)
        ]
        for session_id in expired_sessions:
            self.purge_session(session_id)

    def reset(self) -> None:
        self.__init__()


store = InMemoryStore()
