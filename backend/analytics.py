from __future__ import annotations

from datetime import datetime
from typing import Dict

from .models import DisclosureScope, Presentation, RiskInsight


class InsightEngine:
    """Deterministic analytics engine supporting both medical record and medication pickup scopes."""

    def evaluate(self, presentation: Presentation) -> RiskInsight:
        if presentation.scope == DisclosureScope.MEDICAL_RECORD:
            return self._medical_record_insight(presentation)
        return self._medication_pickup_insight(presentation)

    def _medical_record_insight(self, presentation: Presentation) -> RiskInsight:
        condition_code = presentation.disclosed_fields.get("condition.code.coding[0].code")
        recorded_date = presentation.disclosed_fields.get("condition.recordedDate")
        managing_org = presentation.disclosed_fields.get("managing_organization.value")

        baseline = 0.32
        modifiers: Dict[str, float] = {}

        if condition_code and condition_code.startswith("K29"):
            modifiers["icd_flag"] = 0.28
        elif condition_code:
            modifiers["icd_flag"] = -0.12

        if recorded_date:
            try:
                visit_dt = datetime.fromisoformat(recorded_date)
            except ValueError:
                visit_dt = datetime.utcnow()
            days_since_visit = max((datetime.utcnow() - visit_dt).days, 0)
            window = max(45 - days_since_visit, 7)
        else:
            window = 21
        modifiers["recency_window"] = window / 90.0

        if managing_org:
            modifiers["org_signal"] = (sum(ord(c) for c in managing_org) % 13) / 100

        score = baseline + sum(modifiers.values())
        score = max(0.0, min(score, 0.99))

        return RiskInsight(
            scope=DisclosureScope.MEDICAL_RECORD,
            gastritis_risk_score=round(score, 3),
            trend_window_days=int(window),
            supporting_indicators=modifiers,
        )

    def _medication_pickup_insight(self, presentation: Presentation) -> RiskInsight:
        medication_code = presentation.disclosed_fields.get(
            "medication_dispense[0].medicationCodeableConcept.coding[0].code"
        )
        days_supply_raw = presentation.disclosed_fields.get(
            "medication_dispense[0].days_supply"
        )
        pickup_deadline = presentation.disclosed_fields.get(
            "medication_dispense[0].pickup_window_end"
        )

        modifiers: Dict[str, float] = {}
        baseline = 0.5

        if medication_code:
            modifiers["med_code_hash"] = (sum(ord(c) for c in medication_code) % 11) / 100

        days_supply = 0
        if days_supply_raw:
            try:
                days_supply = int(days_supply_raw)
            except ValueError:
                days_supply = 0
        if days_supply:
            modifiers["days_supply"] = min(days_supply / 60.0, 1.0)

        if pickup_deadline:
            try:
                deadline_dt = datetime.fromisoformat(pickup_deadline)
            except ValueError:
                deadline_dt = datetime.utcnow()
            days_left = (deadline_dt - datetime.utcnow()).days
            modifiers["pickup_urgency"] = max(0, min(1, (14 - days_left) / 14.0))

        score = baseline + sum(modifiers.values()) - 0.2
        score = max(0.0, min(score, 0.99))

        return RiskInsight(
            scope=DisclosureScope.MEDICATION_PICKUP,
            gastritis_risk_score=round(score, 3),
            trend_window_days=14,
            supporting_indicators=modifiers,
        )


def get_risk_engine() -> InsightEngine:
    return InsightEngine()
