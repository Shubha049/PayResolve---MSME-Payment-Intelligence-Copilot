"""
Synthetic Bootstrap Data Generator — PayResolve AI Phase 4.

Generates a plausible training dataset (training_data.csv) for the risk scoring
model.  All data is SYNTHETIC and clearly labelled as such (source column).

UPDATED: Uses probabilistic labeling with class overlap to avoid perfect separation.

Usage:
    python scripts/generate_synthetic_data.py [--rows N] [--seed S] [--out PATH]

Label distribution:
    ~30% late/high-risk (realistic B2B imbalance)
    ~70% on-time/low-risk
"""

import argparse
import csv
import random
import math
from pathlib import Path

DEFAULT_OUT = Path(__file__).parent / "training_data.csv"
FEATURE_NAMES = [
    "prior_invoice_count",
    "late_payment_count",
    "avg_days_late",
    "outstanding_ratio",
    "overdue_invoice_count",
    "dispute_frequency",
    "invoice_age_days",
    "amount_vs_avg_ratio",
]
LABEL_COL = "label"          # 1 = high risk (late/overdue), 0 = low risk (on-time)
SOURCE_COL = "source"


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _sigmoid(x: float) -> float:
    """Logistic function for probability conversion."""
    return 1 / (1 + math.exp(-x))


def _generate_row(rng: random.Random, target_high_risk: bool) -> dict:
    """
    Generate a single row with probabilistic labeling.
    
    Creates features with overlap between classes, then computes risk probability
    and samples the label rather than using a hard threshold.
    """
    # Generate features with class-dependent distributions but overlapping ranges
    if target_high_risk:
        # High-risk profile (but noisy)
        prior = rng.randint(0, 15)
        late = max(0, min(prior, int(rng.gauss(prior * 0.6, prior * 0.2))))
        avg_late = rng.gauss(20, 15) if late > 0 else 0.0
        outstanding = rng.gauss(1.2, 0.6)
        overdue_count = max(0, int(rng.gauss(2.5, 1.5)))
        dispute = rng.gauss(0.25, 0.15)
        age = rng.gauss(60, 30)
        amt_ratio = rng.gauss(1.5, 0.5)
    else:
        # Low-risk profile (but noisy)
        prior = rng.randint(3, 30)
        late = max(0, min(prior, int(rng.gauss(prior * 0.15, prior * 0.1))))
        avg_late = rng.gauss(3, 5) if late > 0 else 0.0
        outstanding = rng.gauss(0.3, 0.3)
        overdue_count = max(0, int(rng.gauss(0.3, 0.6)))
        dispute = rng.gauss(0.05, 0.08)
        age = rng.gauss(25, 20)
        amt_ratio = rng.gauss(1.0, 0.3)
    
    # Clamp to valid ranges
    avg_late = _clamp(avg_late, 0, 90)
    outstanding = _clamp(outstanding, 0, 3.0)
    overdue_count = int(_clamp(overdue_count, 0, 5))
    dispute = _clamp(dispute, 0, 1.0)
    age = _clamp(age, 0, 180)
    amt_ratio = _clamp(amt_ratio, 0.2, 5.0)
    
    # Compute risk probability as weighted function of features
    # These weights roughly match the heuristic scorer for consistency
    risk_logit = (
        -2.0  # baseline (favors low-risk)
        + (late / max(1, prior)) * 3.0  # late payment ratio
        + (avg_late / 30.0) * 2.0  # average lateness
        + (outstanding - 0.5) * 1.5  # outstanding ratio
        + overdue_count * 0.8
        + dispute * 2.0
        + (age / 60.0) * 1.0
        + (amt_ratio - 1.0) * 0.5
        + rng.gauss(0, 0.8)  # noise term for overlap
    )
    
    risk_prob = _sigmoid(risk_logit)
    
    # Sample label from Bernoulli(risk_prob)
    label = 1 if rng.random() < risk_prob else 0
    
    return {
        "prior_invoice_count": prior,
        "late_payment_count": late,
        "avg_days_late": round(avg_late, 2),
        "outstanding_ratio": round(outstanding, 3),
        "overdue_invoice_count": overdue_count,
        "dispute_frequency": round(dispute, 3),
        "invoice_age_days": int(age),
        "amount_vs_avg_ratio": round(amt_ratio, 3),
        LABEL_COL: label,
        SOURCE_COL: "synthetic_bootstrap",
    }


def generate(rows: int = 500, seed: int = 42, out: Path = DEFAULT_OUT) -> Path:
    rng = random.Random(seed)
    
    # Target 30% high-risk
    n_high_target = int(rows * 0.30)
    n_low_target = rows - n_high_target
    
    records = []
    
    # Generate with target distributions (but actual labels will vary due to sampling)
    for _ in range(n_low_target):
        records.append(_generate_row(rng, target_high_risk=False))
    for _ in range(n_high_target):
        records.append(_generate_row(rng, target_high_risk=True))
    
    rng.shuffle(records)
    
    # Count actual label distribution
    n_actual_high = sum(1 for r in records if r[LABEL_COL] == 1)
    n_actual_low = rows - n_actual_high
    
    fieldnames = FEATURE_NAMES + [LABEL_COL, SOURCE_COL]
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    
    print(f"✅ Generated {rows} rows ({n_actual_low} low-risk, {n_actual_high} high-risk) → {out}")
    print(f"   (Target was {n_low_target} low-risk, {n_high_target} high-risk)")
    
    # Sanity check: print feature overlap stats
    low_risk = [r for r in records if r[LABEL_COL] == 0]
    high_risk = [r for r in records if r[LABEL_COL] == 1]
    
    print("\n📊 Feature overlap check (mean ± std):")
    for feat in ["late_payment_count", "avg_days_late", "outstanding_ratio", "overdue_invoice_count"]:
        low_vals = [r[feat] for r in low_risk]
        high_vals = [r[feat] for r in high_risk]
        low_mean = sum(low_vals) / len(low_vals) if low_vals else 0
        high_mean = sum(high_vals) / len(high_vals) if high_vals else 0
        print(f"   {feat}: Low={low_mean:.2f}, High={high_mean:.2f}")
    
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic risk training data")
    parser.add_argument("--rows", type=int, default=500, help="Number of rows to generate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output CSV path")
    args = parser.parse_args()
    generate(rows=args.rows, seed=args.seed, out=args.out)
