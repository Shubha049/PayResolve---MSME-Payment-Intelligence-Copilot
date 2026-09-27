# Phase 4: ML-Based Payment Risk Scoring — Implementation Complete

## Overview

Complete ML risk scoring system with cold-start handling, SHAP explainability, automatic rescoring, and frontend UI integration.

## ✅ Completed Components

### 1. Data Model
- **RiskAssessment** (`app/models/stubs.py`)
  - Stores scoring history (never overwrites)
  - Fields: `risk_score` (0-1), `risk_category` (Low/Medium/High), `top_factors` (JSON), `scoring_method` (heuristic/ml), `model_version`
  - Links to invoice, customer, and optionally case
  - Tenant-scoped with organization_id

### 2. Feature Engineering
- **`app/services/risk_features.py`**
  - 8 features derived from payment/invoice/case history:
    1. `prior_invoice_count` — settled invoice history length
    2. `late_payment_count` — invoices paid after due date
    3. `avg_days_late` — average lateness in days
    4. `outstanding_ratio` — overdue amount / average invoice
    5. `overdue_invoice_count` — currently overdue invoices for customer
    6. `dispute_frequency` — % of invoices in dispute
    7. `invoice_age_days` — days since issue
    8. `amount_vs_avg_ratio` — current invoice / customer's average
  - `ML_HISTORY_THRESHOLD = 5` — minimum invoices before ML mode

### 3. Dual-Mode Scoring Engine
- **`app/services/risk_service.py`**
  
  **Heuristic Mode** (cold-start, <5 invoices):
  - Transparent weighted-sum of normalized features
  - Weights: outstanding_ratio (35%), invoice_age_days (25%), overdue_count (25%), dispute_freq (15%)
  - Used when: insufficient history OR no ML artifact
  - Clearly labeled as "provisional" in frontend
  
  **ML Mode** (≥5 invoices + trained model):
  - LightGBM binary classifier with class balancing
  - SHAP explanations for top 5 factors
  - StandardScaler normalization
  - Graceful fallback to heuristic on error

### 4. Training Pipeline
- **`scripts/train_risk_model.py`**
  - LightGBM with class weights (handles imbalance)
  - Stratified train/test split
  - Metrics: Precision, Recall, F1, PR-AUC (NOT accuracy as headline)
  - Persists: `models/artifacts/risk_model.pkl`, `risk_scaler.pkl`, `risk_model_meta.json`
  - Model versioning in metadata
  
- **`scripts/generate_synthetic_data.py`**
  - Generates 500 rows (70% low-risk, 30% high-risk) for bootstrap
  - Clearly marked with `source: synthetic_bootstrap`
  - Use for initial development; retrain with real data once available

### 5. Background Rescoring
- **`app/services/background_rescoring.py`**
  - `rescore_on_payment()` — triggered after Payment creation
  - `rescore_on_status_change()` — triggered on PENDING→OVERDUE, etc.
  - `rescore_customer_invoices()` — batch rescore all customer invoices
  - `rescore_overdue_invoices()` — scheduled job helper
  - Already integrated in `app/api/v1/invoices.py` via `_fire_rescore()`

### 6. REST API
- **`app/api/v1/risk.py`**
  - `GET /risk/invoice/{id}` — latest assessment (on-demand scoring if none)
  - `GET /risk/customer/{id}` — customer aggregate score
  - `POST /risk/invoice/{id}/rescore` — manual trigger
  - `GET /risk/invoice/{id}/history` — full timeline, newest first
  - All tenant-scoped, 404 on cross-org access

### 7. Frontend UI
- **`src/components/RiskBadge.tsx`**
  - Color-coded badge: Green (Low), Yellow (Medium), Red (High)
  - Provisional marker (†) for heuristic-mode scores
  - Expandable detail drawer with:
    - Score percentage and category
    - Scoring method badge (Heuristic/ML)
    - Plain-language contributing factors with trend icons
    - Rescore button
    - Model version and timestamp
  
- **Integration:**
  - `InvoicesPage.tsx` — Risk column in table
  - `CasesPage.tsx` — Risk column (shows badge if case has invoice_id)
  - `src/api/endpoints.ts` — riskAPI client methods

### 8. Comprehensive Tests
- **`tests/test_risk.py`** (15 test cases):
  1. Feature extraction correctness against fixture data
  2. Cold-start routing (heuristic when <5 invoices)
  3. ML mode with sufficient history
  4. Class imbalance handling (varied predictions, not majority-only)
  5. Tenant isolation on all endpoints
  6. SHAP factors present in ML mode
  7. Background rescoring on payment event
  8. Heuristic scorer unit test
  9. GET /risk/customer/{id} endpoint
  10. POST /risk/invoice/{id}/rescore endpoint
  11. GET /risk/invoice/{id}/history endpoint

## 🚀 Usage

### Initial Setup

1. **Install dependencies:**
   ```powershell
   cd backend
   pip install -r requirements.txt
   ```

2. **Generate synthetic training data:**
   ```powershell
   python scripts/generate_synthetic_data.py --rows 500 --seed 42
   ```
   Output: `scripts/training_data.csv`

3. **Train the model:**
   ```powershell
   python scripts/train_risk_model.py --version synthetic_v1
   ```
   Output: 
   - `models/artifacts/risk_model.pkl`
   - `models/artifacts/risk_scaler.pkl`
   - `models/artifacts/risk_model_meta.json`

4. **Run tests:**
   ```powershell
   pytest tests/test_risk.py -v
   ```

### Retraining with Real Data

Once you have production payment data:

1. Export features to CSV with same column order:
   ```
   prior_invoice_count,late_payment_count,avg_days_late,outstanding_ratio,
   overdue_invoice_count,dispute_frequency,invoice_age_days,amount_vs_avg_ratio,label
   ```
   - `label`: 1 = high risk (late/defaulted), 0 = low risk (on-time)

2. Train:
   ```powershell
   python scripts/train_risk_model.py --data path/to/real_data.csv --version real_v1
   ```

3. Verify metrics (check PR-AUC, not just accuracy)

4. Deploy — server auto-loads new artifact on restart

### API Usage Examples

**Get invoice risk:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/risk/invoice/{invoice_id}
```

**Manual rescore:**
```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/risk/invoice/{invoice_id}/rescore
```

**Get risk history:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/risk/invoice/{invoice_id}/history
```

## 🎯 Design Decisions

### Cold-Start Strategy
- **Below 5 invoices:** Heuristic mode with clear "provisional" labeling
- **Rationale:** Prevents ML from producing confident-looking but unreliable scores from sparse data
- **UX:** Frontend shows † symbol and blue badge for provisional scores
- **Transparency:** model_version field distinguishes "heuristic" vs "ml"

### Explainability
- **SHAP for ML mode:** Top 5 features with directional contributions
- **Heuristic factors:** Weighted components shown with same structure
- **Plain language:** Each factor gets human-readable label (e.g., "3 of last 5 invoices paid >15 days late")

### Class Imbalance Handling
- **Training:** LightGBM with class_weight (balanced by inverse frequency)
- **Metrics:** PR-AUC as primary (better for imbalanced than ROC-AUC or accuracy)
- **Testing:** Explicit test for varied predictions across contrasting profiles

### Automatic Rescoring
- **Event-driven:** Fires on payment record, status change (PENDING→OVERDUE)
- **Non-blocking:** Fire-and-forget async tasks, logs errors but doesn't fail requests
- **Rate limiting:** `should_rescore()` helper checks age of last assessment
- **Manual override:** Always available via POST /rescore endpoint

### History Preservation
- **Never overwrites:** Each scoring event creates a new RiskAssessment row
- **Timeline view:** /history endpoint returns full scoring evolution
- **Audit trail:** Can track how risk changed as payment behavior evolved

## 📊 Evaluation Metrics (from training)

Target metrics for production model:
- **PR-AUC:** >0.75 (primary metric)
- **Precision:** >0.70 (minimize false positives)
- **Recall:** >0.65 (catch high-risk cases)
- **F1:** >0.67 (balance)

Synthetic bootstrap model (synthetic_v1):
- Provides reasonable baseline for development
- Replace with real-data model before production use
- Metrics stored in `models/artifacts/risk_model_meta.json`

## 🔒 Security & Compliance

- **Tenant isolation:** All queries filter by organization_id
- **Audit logging:** Integrated with existing AuditLog via audit_service
- **No PII in features:** Risk score based on behavioral patterns, not personal attributes
- **Transparency:** Every score links to evidence (features + contribution values)
- **User control:** Frontend allows manual rescore and history review

## 🔄 Integration Points

### With Existing Systems
1. **Invoices API:** Auto-rescores on create/update via `_fire_rescore()`
2. **Dashboard:** Can surface high-risk invoice count (future enhancement)
3. **Cases:** Risk badge shows on CasesPage when case has invoice_id
4. **Documents:** Future: incorporate document evidence into features

### For Phase 5 (Recovery Workflow)
- Risk score/category available for prioritizing recovery actions
- Risk history timeline useful for dispute summaries
- Contributing factors can inform reminder tone/escalation level

## 📁 File Structure

```
backend/
├── app/
│   ├── models/
│   │   └── stubs.py                    # RiskAssessment model
│   ├── schemas/
│   │   └── risk.py                     # Pydantic schemas
│   ├── api/v1/
│   │   └── risk.py                     # REST endpoints
│   └── services/
│       ├── risk_features.py            # Feature engineering
│       ├── risk_service.py             # Scoring engine
│       └── background_rescoring.py     # Auto-rescore triggers
├── scripts/
│   ├── generate_synthetic_data.py      # Bootstrap data generator
│   └── train_risk_model.py             # Training pipeline
├── tests/
│   └── test_risk.py                    # 15 test cases
└── models/artifacts/                   # Model files (gitignored)
    ├── risk_model.pkl
    ├── risk_scaler.pkl
    └── risk_model_meta.json

frontend/
├── src/
│   ├── components/
│   │   └── RiskBadge.tsx               # Risk UI component
│   ├── pages/
│   │   ├── InvoicesPage.tsx            # + Risk column
│   │   └── CasesPage.tsx               # + Risk column
│   └── api/
│       └── endpoints.ts                # + riskAPI methods
```

## 🐛 Troubleshooting

**Model not loading (heuristic fallback always):**
- Check `models/artifacts/` exists and contains pkl files
- Verify lightgbm/shap installed: `pip install lightgbm shap`
- Review logs for import errors

**Risk badge shows "N/A":**
- Invoice might not exist or belong to different org (tenant isolation)
- Check browser console for 404/403 errors
- Verify invoice has customer_id (required for features)

**Tests fail with "No module named pytest":**
- Install test dependencies: `pip install pytest pytest-asyncio`
- Run from backend/ directory: `cd backend && pytest tests/test_risk.py`

**SHAP calculation slow:**
- Normal for first call (model compilation)
- Consider caching explainer object in production
- Async scoring prevents blocking API requests

## 📚 Next Steps (Phase 5)

Phase 4 provides the foundation for Phase 5 Recovery Workflow:
- **Risk score** determines reminder urgency/tone
- **Contributing factors** inform dispute summaries
- **Risk history** shows payment behavior evolution
- **Automatic rescoring** keeps recovery priority up-to-date

See Phase 5 prompt for recovery workflow implementation plan.
