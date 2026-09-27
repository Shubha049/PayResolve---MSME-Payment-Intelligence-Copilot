"""
ML Risk Model Training Pipeline — PayResolve AI Phase 4.

Trains a LightGBM binary classifier on payment risk data with:
  - Class imbalance handling (class_weight)
  - Feature scaling (StandardScaler)
  - Stratified train/test split
  - PR-AUC, Precision, Recall, F1 evaluation
  - Model versioning and artifact persistence

Usage:
    python scripts/train_risk_model.py [--data PATH] [--version VERSION] [--test-size 0.2]

Outputs:
    models/artifacts/risk_model.pkl        - Trained LightGBM model
    models/artifacts/risk_scaler.pkl       - StandardScaler fitted on training data
    models/artifacts/risk_model_meta.json  - Metrics, version, feature names
"""

import argparse
import json
import pickle
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    precision_score,
    recall_score,
    f1_score,
    average_precision_score,
    classification_report,
    confusion_matrix,
)
from lightgbm import LGBMClassifier

# ── Paths ────────────────────────────────────────────────────────────────────
_ARTIFACTS_DIR = Path(__file__).parent.parent / "models" / "artifacts"
_DEFAULT_DATA = Path(__file__).parent / "training_data.csv"


def train_model(
    data_path: Path = _DEFAULT_DATA,
    model_version: str = "synthetic_v1",
    test_size: float = 0.2,
    random_state: int = 42,
) -> dict:
    """
    Train LightGBM risk classifier.

    Returns a dict with metrics and paths.
    """
    print(f"📂 Loading training data from {data_path}")
    df = pd.read_csv(data_path)

    # Verify expected columns
    feature_cols = [
        "prior_invoice_count",
        "late_payment_count",
        "avg_days_late",
        "outstanding_ratio",
        "overdue_invoice_count",
        "dispute_frequency",
        "invoice_age_days",
        "amount_vs_avg_ratio",
    ]
    label_col = "label"

    missing = set(feature_cols + [label_col]) - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in training data: {missing}")

    X = df[feature_cols].values
    y = df[label_col].values

    print(f"📊 Dataset: {len(df)} rows, {len(feature_cols)} features")
    print(f"   Label distribution: {np.bincount(y)} (0=low-risk, 1=high-risk)")

    # Stratified split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, stratify=y, random_state=random_state
    )

    # Scale features
    print("⚙️  Fitting StandardScaler...")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Train LightGBM with class balancing
    print("🚀 Training LightGBM classifier...")
    # Calculate class weights for imbalance handling
    n_samples = len(y_train)
    n_classes = 2
    class_counts = np.bincount(y_train)
    class_weight = {i: n_samples / (n_classes * class_counts[i]) for i in range(n_classes)}

    model = LGBMClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.05,
        class_weight=class_weight,
        random_state=random_state,
        verbose=-1,
    )
    model.fit(X_train_scaled, y_train)

    # Evaluate
    print("📈 Evaluating on test set...")
    y_pred = model.predict(X_test_scaled)
    y_proba = model.predict_proba(X_test_scaled)[:, 1]

    precision = precision_score(y_test, y_pred)
    recall = recall_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
    pr_auc = average_precision_score(y_test, y_proba)

    print("\n" + "="*60)
    print("EVALUATION RESULTS")
    print("="*60)
    print(f"Precision:  {precision:.3f}")
    print(f"Recall:     {recall:.3f}")
    print(f"F1 Score:   {f1:.3f}")
    print(f"PR-AUC:     {pr_auc:.3f}")
    print("\nConfusion Matrix:")
    print(confusion_matrix(y_test, y_pred))
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=["Low Risk", "High Risk"]))
    print("="*60 + "\n")

    # Persist artifacts
    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    model_path = _ARTIFACTS_DIR / "risk_model.pkl"
    scaler_path = _ARTIFACTS_DIR / "risk_scaler.pkl"
    meta_path = _ARTIFACTS_DIR / "risk_model_meta.json"

    print(f"💾 Saving model to {model_path}")
    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    print(f"💾 Saving scaler to {scaler_path}")
    with open(scaler_path, "wb") as f:
        pickle.dump(scaler, f)

    metadata = {
        "model_version": model_version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_data_path": str(data_path),
        "n_train": len(X_train),
        "n_test": len(X_test),
        "feature_names": feature_cols,
        "class_distribution_train": class_counts.tolist(),
        "class_weight": {str(k): float(v) for k, v in class_weight.items()},
        "metrics": {
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "pr_auc": float(pr_auc),
        },
        "hyperparameters": {
            "n_estimators": 100,
            "max_depth": 5,
            "learning_rate": 0.05,
        },
    }

    print(f"💾 Saving metadata to {meta_path}")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print("\n✅ Training complete!")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train payment risk scoring model")
    parser.add_argument(
        "--data",
        type=Path,
        default=_DEFAULT_DATA,
        help="Path to training CSV (default: scripts/training_data.csv)",
    )
    parser.add_argument(
        "--version",
        type=str,
        default="synthetic_v1",
        help="Model version tag (default: synthetic_v1)",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Test set proportion (default: 0.2)",
    )
    args = parser.parse_args()

    train_model(
        data_path=args.data,
        model_version=args.version,
        test_size=args.test_size,
    )
