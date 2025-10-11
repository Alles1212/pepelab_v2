from __future__ import annotations

from datetime import datetime
from typing import Dict

from .models import Presentation, RiskInsight


class GastritisRiskEngine:
    """A deterministic pseudo-analytics engine for gastritis trends."""

    def evaluate(self, presentation: Presentation) -> RiskInsight:
        visit_date = presentation.disclosed_fields.get("visit_date")
        diagnosis_code = presentation.disclosed_fields.get("diagnosis_code")
        physician_id = presentation.disclosed_fields.get("physician_id")

        baseline = 0.35
        modifiers: Dict[str, float] = {}

        if diagnosis_code and diagnosis_code.startswith("K29"):
            modifiers["icd_weight"] = 0.25
        elif diagnosis_code:
            modifiers["icd_weight"] = -0.1

        if visit_date:
            try:
                visit_dt = datetime.fromisoformat(visit_date)
            except ValueError:
                visit_dt = datetime.utcnow()
            days_since_visit = max((datetime.utcnow() - visit_dt).days, 0)
            window = max(30 - days_since_visit, 7)
        else:
            window = 14
        modifiers["recency_window"] = window / 100.0

        if physician_id:
            modifiers["physician_signal"] = (sum(ord(c) for c in physician_id) % 17) / 100

        score = baseline + sum(modifiers.values())
        score = max(0.0, min(score, 0.99))

        return RiskInsight(
            gastritis_risk_score=round(score, 3),
            trend_window_days=int(window),
            supporting_indicators=modifiers,
        )


def get_risk_engine() -> GastritisRiskEngine:
    return GastritisRiskEngine()
