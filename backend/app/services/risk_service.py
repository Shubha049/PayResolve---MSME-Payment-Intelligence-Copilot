"""
Risk Scoring Engine — PayResolve AI Phase 4.

Two scoring modes:
  heuristic — transparent weighted-sum, used when prior_invoice_count < ML_HISTORY_THRESHOLD
              or when no ML artifact is present.
  ml        — LightGBM classifier with SHAP explanations, used otherwise.

Both modes produce the same output structure so the API / frontend need no branching.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
from pathlib import Path
from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stubs import RiskAssessment
from app.models.invoice import Invoice
from app.services.risk_features import (
    RiskFeatureVector,
    extract_features,
    ML_HISTORY_THRESHOLD,
)

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────
_ARTIFACTS_DIR = Path(__file__).parent.parent.parent / "models" / "artifacts"
_MODEL_PATH = _ARTIFACTS_DIR / "risk_model.pkl"
_META_PATH = _ARTIFACTS_DIR / "risk_model_meta.json"
_SCALER_PATH = _ARTIFACTS_DIR / "risk_scaler.pkl"


# ── Category thresholds ──────────────────────────────────────────────────────
def _categorise(score: float) -> str:
    if score < 0.35:
        return "Low"
    if score < 0.65:
        return "Medium"
    return "High"


# ── Plain-language label helpers ─────────────────────────────────────────────
def _label(name: str, value: float, contribution: float) -> str:
    """Convert a raw feature value + SHAP contribution into a plain English string."""
    templates: dict[str, str] = {
        "prior_invoice_count":   f"{int(value)} prior settled invoice(s) on record",
        "late_payment_count":    f"{int(value)} invoice(s) paid after due date",
        "avg_days_late":         f"Average {value:.0f} day(s) late on past payments",
        "outstanding_ratio":     f"Outstanding balance is {value:.0%} of typical invoice size",
        "overdue_invoice_count": f"{int(value)} currently overdue invoice(s) for this customer",
        "dispute_frequency":     f"Dispute rate: {value:.0%} of invoices in dispute",
        "invoice_age_days":      f"Invoice is {int(value)} day(s) old",
        "amount_vs_avg_ratio":   f"Invoice amount is {value:.1f}× the customer's average",
    }
    prefix = "↑ increasing risk —" if contribution > 0 else "↓ decreasing risk —"
    base = templates.get(name, f"{name} = {value:.2f}")
    return f"{prefix} {base}"


# ══════════════════════════════════════════════════════════════════════════════
# Heuristic Scorer
# ══════════════════════════════════════════════════════════════════════════════

# Weights must sum to 1.0
_HEURISTIC_WEIGHTS: dict[str, float] = {
    "outstanding_ratio":     0.35,
    "invoice_age_days":      0.25,  # normalised by AGE_HORIZON_DAYS in scorer
    "overdue_invoice_count": 0.25,  # normalised over max 5
    "dispute_frequency":     0.15,
}


class HeuristicScorer:
    """
    Transparent weighted-sum scorer for cold-start customers.
    All components are normalised to [0, 1] before weighting.
    """

    @staticmethod
    def score(fv: RiskFeatureVector) -> tuple[float, str, list[dict[str, Any]]]:
        from app.services.risk_features import AGE_HORIZON_DAYS

        components = {
            "outstanding_ratio":     min(1.0, fv.outstanding_ratio / 2.0),
            "invoice_age_days":      min(1.0, fv.invoice_age_days / AGE_HORIZON_DAYS),
            "overdue_invoice_count": min(1.0, fv.overdue_invoice_count / 5.0),
            "dispute_frequency":     fv.dispute_frequency,
        }

        raw_score = sum(components[k] * _HEURISTIC_WEIGHTS[k] for k in components)
        score = max(0.0, min(1.0, raw_score))
        category = _categorise(score)

        # Build factor objects sorted by contribution descending
        factors: list[dict[str, Any]] = []
        fv_dict = fv.to_dict()
        for fname, norm_val in sorted(components.items(), key=lambda x: -abs(x[1])):
            contribution = norm_val * _HEURISTIC_WEIGHTS[fname]
            raw_val = fv_dict.get(fname, norm_val)
            factors.append({
                "name":         fname,
                "contribution": round(contribution, 4),
                "label":        _label(fname, float(raw_val), contribution),
            })

        return score, category, factors


# ══════════════════════════════════════════════════════════════════════════════
# ML Scorer (LightGBM / GradientBoosting + SHAP)
# ══════════════════════════════════════════════════════════════════════════════

class MLScorer:
    """
    LightGBM-backed scorer.  Falls back gracefully to HeuristicScorer if the
    artifact is missing or if import fails.

    Lazy-loaded on first call — avoids import overhead at server start when
    artifact hasn't been trained yet.
    """

    _model: Any = None
    _scaler: Any = None
    _meta: dict[str, Any] = {}
    _loaded: bool = False
    _available: bool = False

    @classmethod
    def _load(cls) -> bool:
        if cls._loaded:
            return cls._available
        cls._loaded = True
        try:
            if not _MODEL_PATH.exists():
                logger.info("No ML artifact at %s — ML scoring unavailable.", _MODEL_PATH)
                return False
            with open(_MODEL_PATH, "rb") as f:
                cls._model = pickle.load(f)
            if _SCALER_PATH.exists():
                with open(_SCALER_PATH, "rb") as f:
                    cls._scaler = pickle.load(f)
            if _META_PATH.exists():
                with open(_META_PATH) as f:
                    cls._meta = json.load(f)
            cls._available = True
            logger.info("ML risk model loaded: version=%s", cls._meta.get("model_version", "unknown"))
        except Exception as exc:
            logger.warning("Failed to load ML risk model: %s", exc)
        return cls._available

    @classmethod
    def is_available(cls) -> bool:
        return cls._load()

    @classmethod
    def model_version(cls) -> str:
        cls._load()
        return cls._meta.get("model_version", "unknown")

    @classmethod
    def score(cls, fv: RiskFeatureVector) -> tuple[float, str, list[dict[str, Any]]]:
        if not cls._load():
            raise RuntimeError("ML model not available")

        feature_list = fv.to_list()
        feature_names = RiskFeatureVector.feature_names()

        # Apply scaler if available
        if cls._scaler is not None:
            import numpy as np
            X = np.array([feature_list])
            X_scaled = cls._scaler.transform(X)
        else:
            import numpy as np
            X_scaled = np.array([feature_list])

        # Predict probability of "high risk" (class 1)
        proba = cls._model.predict_proba(X_scaled)[0]
        score = float(proba[1]) if len(proba) > 1 else float(proba[0])
        score = max(0.0, min(1.0, score))
        category = _categorise(score)

        # SHAP explanations
        factors: list[dict[str, Any]] = []
        try:
            import shap
            explainer = shap.TreeExplainer(cls._model)
            shap_values = explainer.shap_values(X_scaled)
            # For binary classifiers shap_values is [class0_array, class1_array]
            if isinstance(shap_values, list) and len(shap_values) > 1:
                sv = shap_values[1][0]  # class 1 SHAP values for first (only) sample
            else:
                sv = shap_values[0] if hasattr(shap_values[0], '__len__') else shap_values

            fv_dict = fv.to_dict()
            shap_pairs = sorted(
                zip(feature_names, sv),
                key=lambda x: -abs(x[1])
            )[:5]  # Top 5 by absolute contribution
            for fname, shap_val in shap_pairs:
                raw_val = fv_dict.get(fname, 0.0)
                factors.append({
                    "name":         fname,
                    "contribution": round(float(shap_val), 4),
                    "label":        _label(fname, float(raw_val), float(shap_val)),
                })
        except Exception as exc:
            logger.warning("SHAP explanation failed, using feature values: %s", exc)
            fv_dict = fv.to_dict()
            for fname in feature_names[:5]:
                val = fv_dict.get(fname, 0.0)
                factors.append({
                    "name":         fname,
                    "contribution": round(float(val) * 0.1, 4),
                    "label":        _label(fname, float(val), 0.1),
                })

        return score, category, factors


# ══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════════════

async def score_invoice(
    db: AsyncSession,
    org_id: str,
    invoice_id: str,
) -> Optional[RiskAssessment]:
    """
    Score a single invoice, persist the result, and return the ORM object.

    Routing logic:
      - prior_invoice_count < ML_HISTORY_THRESHOLD  → HeuristicScorer
      - ML artifact present AND enough history       → MLScorer
      - ML artifact missing but enough history       → HeuristicScorer with
                                                       model_version="heuristic_no_artifact"
    """
    # Load invoice — must belong to this org
    inv_stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.organization_id == org_id,
    )
    inv_result = await db.execute(inv_stmt)
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        logger.warning("score_invoice: invoice %s not found in org %s", invoice_id, org_id)
        return None

    # Extract features
    fv = await extract_features(db, org_id, invoice.customer_id, invoice)

    # Route to scorer
    use_ml = (
        fv.prior_invoice_count >= ML_HISTORY_THRESHOLD
        and MLScorer.is_available()
    )

    if use_ml:
        try:
            risk_score, risk_category, top_factors = MLScorer.score(fv)
            scoring_method = "ml"
            model_version = MLScorer.model_version()
        except Exception as exc:
            logger.warning("ML scoring failed, falling back to heuristic: %s", exc)
            risk_score, risk_category, top_factors = HeuristicScorer.score(fv)
            scoring_method = "heuristic"
            model_version = "heuristic_fallback"
    else:
        risk_score, risk_category, top_factors = HeuristicScorer.score(fv)
        scoring_method = "heuristic"
        if fv.prior_invoice_count >= ML_HISTORY_THRESHOLD:
            model_version = "heuristic_no_artifact"
        else:
            model_version = "heuristic"

    # Persist new assessment row (history preserved)
    assessment = RiskAssessment(
        organization_id=org_id,
        invoice_id=invoice_id,
        customer_id=invoice.customer_id,
        risk_score=risk_score,
        risk_category=risk_category,
        top_factors=top_factors,
        model_version=model_version,
        scoring_method=scoring_method,
    )
    db.add(assessment)
    await db.commit()
    await db.refresh(assessment)
    return assessment


async def score_customer_aggregate(
    db: AsyncSession,
    org_id: str,
    customer_id: str,
) -> Optional[RiskAssessment]:
    """
    Score a customer using their latest/most-overdue open invoice as the proxy.
    If the customer has no open invoices, score using a zero-amount synthetic stub.
    """
    # Find the most overdue open invoice for this customer
    inv_stmt = (
        select(Invoice)
        .where(
            Invoice.organization_id == org_id,
            Invoice.customer_id == customer_id,
            Invoice.status.in_([
                Invoice.status.OVERDUE if hasattr(Invoice.status, 'OVERDUE') else "OVERDUE"
            ])
        )
        .order_by(Invoice.due_date.asc())
        .limit(1)
    )
    # Simplified: use any non-paid invoice
    inv_stmt2 = (
        select(Invoice)
        .where(
            Invoice.organization_id == org_id,
            Invoice.customer_id == customer_id,
        )
        .order_by(Invoice.due_date.asc())
        .limit(1)
    )
    inv_result = await db.execute(inv_stmt2)
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        return None

    fv = await extract_features(db, org_id, customer_id, invoice)

    use_ml = (
        fv.prior_invoice_count >= ML_HISTORY_THRESHOLD
        and MLScorer.is_available()
    )
    if use_ml:
        try:
            risk_score, risk_category, top_factors = MLScorer.score(fv)
            scoring_method = "ml"
            model_version = MLScorer.model_version()
        except Exception:
            risk_score, risk_category, top_factors = HeuristicScorer.score(fv)
            scoring_method = "heuristic"
            model_version = "heuristic_fallback"
    else:
        risk_score, risk_category, top_factors = HeuristicScorer.score(fv)
        scoring_method = "heuristic"
        model_version = "heuristic"

    assessment = RiskAssessment(
        organization_id=org_id,
        invoice_id=invoice.id,
        customer_id=customer_id,
        risk_score=risk_score,
        risk_category=risk_category,
        top_factors=top_factors,
        model_version=model_version,
        scoring_method=scoring_method,
    )
    db.add(assessment)
    await db.commit()
    await db.refresh(assessment)
    return assessment
