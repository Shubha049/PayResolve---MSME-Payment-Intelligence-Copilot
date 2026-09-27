from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


class RiskFactor(BaseModel):
    """One contributing factor from either heuristic or ML scoring."""
    name: str
    contribution: float    # positive = increases risk, negative = decreases risk
    label: str             # Plain-English explanation, e.g. "↑ increasing risk — 3 invoices paid late"


class RiskAssessmentRead(BaseModel):
    """
    Read schema for a persisted RiskAssessment row.
    scoring_method: "heuristic" | "ml"
    model_version:  "heuristic" | "heuristic_no_artifact" | "synthetic_v1" | "real_vN"
    """
    id: str
    organization_id: str
    invoice_id: Optional[str] = None
    customer_id: Optional[str] = None
    case_id: Optional[str] = None
    risk_score: float
    risk_category: str
    top_factors: list[RiskFactor]
    model_version: str
    scoring_method: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
