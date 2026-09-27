"""
Risk Scoring System Tests — PayResolve AI Phase 4.

Test coverage:
  1. Feature extraction correctness
  2. Cold-start threshold routing (heuristic vs ML)
  3. Class imbalance handling (verify model doesn't predict only majority class)
  4. Tenant isolation on risk endpoints
  5. SHAP factors presence for ML-mode scores
  6. Background rescoring triggers (simulated)
"""

import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Organization,
    User,
    Customer,
    Invoice,
    InvoiceStatus,
    Case,
    CaseStatus,
    CasePriority,
    RiskAssessment,
    Payment,
)
from app.services.risk_features import extract_features, ML_HISTORY_THRESHOLD
from app.services.risk_service import (
    score_invoice,
    HeuristicScorer,
    MLScorer,
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Feature Extraction Tests
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_feature_extraction_correctness(db_session: AsyncSession, org: Organization, customer: Customer):
    """Verify feature engineering produces correct values from known fixture data."""
    db = db_session
    today = date.today()

    # Create historical invoices: 5 total, 2 paid late, 1 currently overdue
    inv1 = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="INV-001",
        issue_date=today - timedelta(days=90),
        due_date=today - timedelta(days=60),
        total_amount=Decimal("1000.0"),
        status=InvoiceStatus.PAID,
    )
    inv2 = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="INV-002",
        issue_date=today - timedelta(days=70),
        due_date=today - timedelta(days=40),
        total_amount=Decimal("1500.0"),
        status=InvoiceStatus.PAID,
    )
    inv3 = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="INV-003",
        issue_date=today - timedelta(days=50),
        due_date=today - timedelta(days=20),
        total_amount=Decimal("1200.0"),
        status=InvoiceStatus.PAID,
    )
    inv4 = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="INV-004",
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=10),
        total_amount=Decimal("1100.0"),
        status=InvoiceStatus.OVERDUE,
    )
    # Current invoice being scored
    inv5 = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="INV-005",
        issue_date=today - timedelta(days=15),
        due_date=today + timedelta(days=15),
        total_amount=Decimal("2000.0"),
        status=InvoiceStatus.ISSUED,
    )
    db.add_all([inv1, inv2, inv3, inv4, inv5])
    await db.commit()

    # Add payments for first 3 invoices (2 late)
    # inv1: paid 10 days late
    pay1 = Payment(
        organization_id=org.id,
        invoice_id=inv1.id,
        amount=Decimal("1000.0"),
        payment_date=inv1.due_date + timedelta(days=10),
    )
    # inv2: paid 5 days late
    pay2 = Payment(
        organization_id=org.id,
        invoice_id=inv2.id,
        amount=Decimal("1500.0"),
        payment_date=inv2.due_date + timedelta(days=5),
    )
    # inv3: paid on time
    pay3 = Payment(
        organization_id=org.id,
        invoice_id=inv3.id,
        amount=Decimal("1200.0"),
        payment_date=inv3.due_date,
    )
    db.add_all([pay1, pay2, pay3])
    await db.commit()

    # Add a dispute case
    case1 = Case(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_id=inv4.id,
        case_number="CASE-001",
        title="Dispute on INV-004",
        summary="Amount incorrect",
        status=CaseStatus.OPEN,
        priority=CasePriority.HIGH,
    )
    db.add(case1)
    await db.commit()

    # Extract features for inv5
    fv = await extract_features(db, org.id, customer.id, inv5)

    # Verify correctness
    assert fv.prior_invoice_count == 3, "Should count 3 prior settled (PAID) invoices"
    assert fv.late_payment_count == 2, "2 invoices paid late"
    assert fv.avg_days_late == 7.5, "Average of 10 and 5 days late = 7.5"
    assert fv.overdue_invoice_count == 1, "1 currently overdue invoice (INV-004)"
    assert fv.dispute_frequency == 0.2, "1 dispute out of 5 total invoices (excl current) = 20%"
    assert fv.invoice_age_days == 15, "Invoice issued 15 days ago"

    # Amount vs average: settled amounts [1000, 1500, 1200], avg=1233.33, current=2000
    expected_ratio = 2000.0 / 1233.33
    assert abs(fv.amount_vs_avg_ratio - expected_ratio) < 0.01

    # Outstanding ratio: uses invoice.outstanding_amount = total_amount - paid_amount
    # inv5: 2000 - 0 = 2000; ratio = 2000 / 1233.33
    expected_outstanding = 2000.0 / 1233.33
    assert abs(fv.outstanding_ratio - expected_outstanding) < 0.01


# ══════════════════════════════════════════════════════════════════════════════
# 2. Cold-Start Routing Tests
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cold_start_uses_heuristic(db_session: AsyncSession, org: Organization, customer: Customer):
    """
    A customer with < ML_HISTORY_THRESHOLD invoices should get scoring_method='heuristic'.
    """
    db = db_session
    today = date.today()
    # Create only 2 invoices (below threshold of 5)
    inv1 = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="INV-COLD-1",
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=10),
        total_amount=Decimal("1000.0"),
        status=InvoiceStatus.ISSUED,
    )
    inv2 = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="INV-COLD-2",
        issue_date=today - timedelta(days=15),
        due_date=today + timedelta(days=15),
        total_amount=Decimal("1200.0"),
        status=InvoiceStatus.ISSUED,
    )
    db.add_all([inv1, inv2])
    await db.commit()

    assessment = await score_invoice(db, org.id, inv2.id)
    assert assessment is not None
    assert assessment.scoring_method == "heuristic"
    assert assessment.model_version == "heuristic"
    assert 0.0 <= assessment.risk_score <= 1.0
    assert assessment.risk_category in ["Low", "Medium", "High"]
    assert len(assessment.top_factors) > 0


@pytest.mark.asyncio
async def test_ml_mode_with_sufficient_history(db_session: AsyncSession, org: Organization, customer: Customer):
    """
    A customer with >= ML_HISTORY_THRESHOLD invoices should attempt ML scoring if artifact exists.
    If no artifact, falls back to heuristic with model_version='heuristic_no_artifact'.
    """
    db = db_session
    today = date.today()
    # Create 6 invoices (above threshold)
    invoices = []
    for i in range(6):
        inv = Invoice(
            organization_id=org.id,
            customer_id=customer.id,
            invoice_number=f"INV-ML-{i+1}",
            issue_date=today - timedelta(days=60 - i*5),
            due_date=today - timedelta(days=30 - i*5),
            total_amount=Decimal(str(1000.0 + i*100)),
            status=InvoiceStatus.PAID if i < 5 else InvoiceStatus.ISSUED,
        )
        invoices.append(inv)
    db.add_all(invoices)
    await db.commit()

    # Add payments for first 5
    for inv in invoices[:5]:
        pay = Payment(
            organization_id=org.id,
            invoice_id=inv.id,
            amount=inv.total_amount,
            payment_date=inv.due_date,
        )
        db.add(pay)
    await db.commit()

    assessment = await score_invoice(db, org.id, invoices[-1].id)
    assert assessment is not None

    # If ML artifact exists, should use "ml"; otherwise "heuristic_no_artifact" or "heuristic_fallback"
    # Since tests likely don't have trained model, expect heuristic fallback
    if MLScorer.is_available():
        assert assessment.scoring_method == "ml"
        assert "synthetic_v" in assessment.model_version or assessment.model_version == "unknown"
    else:
        assert assessment.scoring_method == "heuristic"
        assert assessment.model_version in ["heuristic_no_artifact", "heuristic_fallback"]


# ══════════════════════════════════════════════════════════════════════════════
# 3. Class Imbalance Handling Test
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ml_does_not_predict_only_majority_class(db_session: AsyncSession, org: Organization):
    """
    Verify that the ML model (if available) produces varied predictions, not just majority class.
    This is a smoke test — proper validation is in training pipeline metrics.
    """
    db = db_session
    if not MLScorer.is_available():
        pytest.skip("ML model not available for this test")

    # Create two customers with contrasting risk profiles
    customer_low = Customer(
        organization_id=org.id,
        name="Low Risk Corp",
        email="low@example.com",
    )
    customer_high = Customer(
        organization_id=org.id,
        name="High Risk Inc",
        email="high@example.com",
    )
    db.add_all([customer_low, customer_high])
    await db.commit()

    today = date.today()

    # Low-risk customer: many on-time invoices
    low_invoices = []
    for i in range(10):
        inv = Invoice(
            organization_id=org.id,
            customer_id=customer_low.id,
            invoice_number=f"LOW-{i+1}",
            issue_date=today - timedelta(days=90 - i*5),
            due_date=today - timedelta(days=60 - i*5),
            total_amount=Decimal("1000.0"),
            status=InvoiceStatus.PAID,
        )
        db.add(inv)
        low_invoices.append(inv)
    await db.flush()  # Get IDs for invoices
    
    for inv in low_invoices:
        pay = Payment(
            organization_id=org.id,
            invoice_id=inv.id,
            amount=Decimal("1000.0"),
            payment_date=inv.due_date,  # on time
        )
        db.add(pay)

    # High-risk customer: many late payments, disputes
    high_invoices = []
    for i in range(10):
        inv = Invoice(
            organization_id=org.id,
            customer_id=customer_high.id,
            invoice_number=f"HIGH-{i+1}",
            issue_date=today - timedelta(days=90 - i*5),
            due_date=today - timedelta(days=60 - i*5),
            total_amount=Decimal("1000.0"),
            status=InvoiceStatus.OVERDUE if i < 3 else InvoiceStatus.PAID,
        )
        db.add(inv)
        high_invoices.append(inv)
    await db.flush()  # Get IDs for invoices
    
    for i, inv in enumerate(high_invoices):
        if i >= 3:  # Only paid invoices get payment records
            pay = Payment(
                organization_id=org.id,
                invoice_id=inv.id,
                amount=Decimal("1000.0"),
                payment_date=inv.due_date + timedelta(days=30),  # very late
            )
            db.add(pay)

    await db.commit()

    # Score current invoices for both customers
    inv_low = Invoice(
        organization_id=org.id,
        customer_id=customer_low.id,
        invoice_number="LOW-CURRENT",
        issue_date=today,
        due_date=today + timedelta(days=30),
        total_amount=Decimal("1000.0"),
        status=InvoiceStatus.ISSUED,
    )
    inv_high = Invoice(
        organization_id=org.id,
        customer_id=customer_high.id,
        invoice_number="HIGH-CURRENT",
        issue_date=today,
        due_date=today + timedelta(days=30),
        total_amount=Decimal("1000.0"),
        status=InvoiceStatus.ISSUED,
    )
    db.add_all([inv_low, inv_high])
    await db.commit()

    assess_low = await score_invoice(db, org.id, inv_low.id)
    assess_high = await score_invoice(db, org.id, inv_high.id)

    assert assess_low is not None
    assert assess_high is not None

    # Expect low-risk customer to have lower score than high-risk customer
    assert assess_low.risk_score < assess_high.risk_score, (
        "Model should differentiate between low and high-risk profiles"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4. Tenant Isolation Tests
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_risk_endpoint_tenant_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    org: Organization,
    org2: Organization,
    user: User,
    user2: User,
    customer: Customer,
    auth_headers: dict,
    auth_headers2: dict,
):
    """
    Verify that risk endpoints enforce tenant isolation:
      - Org1 user cannot access Org2's risk assessments
      - Org2 user cannot access Org1's risk assessments
    """
    db = db_session
    today = date.today()

    # Org1 invoice
    inv1 = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="ORG1-INV",
        issue_date=today,
        due_date=today + timedelta(days=30),
        total_amount=Decimal("1000.0"),
        status=InvoiceStatus.ISSUED,
    )
    db.add(inv1)

    # Org2 customer and invoice
    customer2 = Customer(
        organization_id=org2.id,
        name="Org2 Customer",
        email="org2customer@example.com",
    )
    db.add(customer2)
    await db.commit()

    inv2 = Invoice(
        organization_id=org2.id,
        customer_id=customer2.id,
        invoice_number="ORG2-INV",
        issue_date=today,
        due_date=today + timedelta(days=30),
        total_amount=Decimal("2000.0"),
        status=InvoiceStatus.ISSUED,
    )
    db.add(inv2)
    await db.commit()

    # Org1 user tries to access Org1 invoice risk — should succeed
    resp = await client.get(f"/api/v1/risk/invoice/{inv1.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["invoice_id"] == inv1.id

    # Org1 user tries to access Org2 invoice risk — should fail with 404
    resp = await client.get(f"/api/v1/risk/invoice/{inv2.id}", headers=auth_headers)
    assert resp.status_code == 404

    # Org2 user tries to access Org2 invoice risk — should succeed
    resp = await client.get(f"/api/v1/risk/invoice/{inv2.id}", headers=auth_headers2)
    assert resp.status_code == 200
    data = resp.json()
    assert data["invoice_id"] == inv2.id

    # Org2 user tries to access Org1 invoice risk — should fail with 404
    resp = await client.get(f"/api/v1/risk/invoice/{inv1.id}", headers=auth_headers2)
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 5. SHAP Factors Presence Test
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_shap_factors_present_in_ml_mode(db_session: AsyncSession, org: Organization, customer: Customer):
    """
    When scoring in ML mode, top_factors should be non-empty and contain contribution values.
    """
    db = db_session
    if not MLScorer.is_available():
        pytest.skip("ML model not available for SHAP test")

    today = date.today()
    # Create sufficient history
    invoices = []
    for i in range(10):
        inv = Invoice(
            organization_id=org.id,
            customer_id=customer.id,
            invoice_number=f"SHAP-{i+1}",
            issue_date=today - timedelta(days=90 - i*5),
            due_date=today - timedelta(days=60 - i*5),
            total_amount=Decimal("1000.0"),
            status=InvoiceStatus.PAID,
        )
        db.add(inv)
        invoices.append(inv)
    await db.flush()  # Get IDs for invoices
    
    for inv in invoices:
        pay = Payment(
            organization_id=org.id,
            invoice_id=inv.id,
            amount=Decimal("1000.0"),
            payment_date=inv.due_date,
        )
        db.add(pay)
    await db.commit()

    # Current invoice
    inv_current = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="SHAP-CURRENT",
        issue_date=today,
        due_date=today + timedelta(days=30),
        total_amount=Decimal("1000.0"),
        status=InvoiceStatus.ISSUED,
    )
    db.add(inv_current)
    await db.commit()

    assessment = await score_invoice(db, org.id, inv_current.id)
    assert assessment is not None

    if assessment.scoring_method == "ml":
        assert assessment.top_factors is not None
        assert len(assessment.top_factors) > 0, "ML mode should produce SHAP factors"
        for factor in assessment.top_factors:
            assert "name" in factor
            assert "contribution" in factor
            assert "label" in factor
            assert isinstance(factor["contribution"], (int, float))


# ══════════════════════════════════════════════════════════════════════════════
# 6. Background Rescoring Trigger Test
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_background_rescoring_on_payment_event(db_session: AsyncSession, org: Organization, customer: Customer):
    """
    Simulate a payment event and verify that rescoring is triggered.
    In production, this would be handled by a background job or webhook.
    For testing, we manually trigger rescoring after payment and verify a new assessment is created.
    """
    db = db_session
    today = date.today()

    # Create an invoice with initial assessment
    inv = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="RESCORE-INV",
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=15),
        total_amount=Decimal("1000.0"),
        status=InvoiceStatus.OVERDUE,
    )
    db.add(inv)
    await db.commit()

    # Initial score
    initial_assessment = await score_invoice(db, org.id, inv.id)
    assert initial_assessment is not None
    initial_score = initial_assessment.risk_score

    # Simulate payment event (mark invoice as paid)
    pay = Payment(
        organization_id=org.id,
        invoice_id=inv.id,
        amount=Decimal("1000.0"),
        payment_date=today,  # paid late
    )
    db.add(pay)
    inv.status = InvoiceStatus.PAID
    await db.commit()

    # Trigger rescoring (in production, this would be automated)
    new_assessment = await score_invoice(db, org.id, inv.id)
    assert new_assessment is not None
    assert new_assessment.id != initial_assessment.id, "Should create a new assessment row"

    # Verify history is preserved
    stmt = select(RiskAssessment).where(
        RiskAssessment.invoice_id == inv.id,
        RiskAssessment.organization_id == org.id,
    ).order_by(RiskAssessment.created_at.desc())
    assessments = (await db.execute(stmt)).scalars().all()
    assert len(assessments) == 2, "Should have 2 assessment rows (history preserved)"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Heuristic Scorer Correctness
# ══════════════════════════════════════════════════════════════════════════════

def test_heuristic_scorer_produces_valid_output():
    """
    Unit test for HeuristicScorer to ensure it produces valid score and factors.
    """
    from app.services.risk_features import RiskFeatureVector

    # Create a high-risk feature vector
    fv = RiskFeatureVector(
        prior_invoice_count=3,
        late_payment_count=2,
        avg_days_late=20.0,
        outstanding_ratio=1.5,
        overdue_invoice_count=3,
        dispute_frequency=0.3,
        invoice_age_days=90,
        amount_vs_avg_ratio=2.0,
    )

    score, category, factors = HeuristicScorer.score(fv)

    assert 0.0 <= score <= 1.0
    assert category in ["Low", "Medium", "High"]
    assert len(factors) == 4, "Heuristic uses 4 weighted components"
    assert all("name" in f and "contribution" in f and "label" in f for f in factors)


# ══════════════════════════════════════════════════════════════════════════════
# 8. API Endpoint Tests
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_customer_risk_endpoint(
    client: AsyncClient,
    db_session: AsyncSession,
    org: Organization,
    customer: Customer,
    auth_headers: dict,
):
    """Test GET /risk/customer/{customer_id} endpoint."""
    db = db_session
    today = date.today()

    # Create invoices for customer
    for i in range(3):
        inv = Invoice(
            organization_id=org.id,
            customer_id=customer.id,
            invoice_number=f"CUST-RISK-{i+1}",
            issue_date=today - timedelta(days=30 - i*5),
            due_date=today - timedelta(days=10 - i*5),
            total_amount=Decimal("1000.0"),
            status=InvoiceStatus.ISSUED,
        )
        db.add(inv)
    await db.commit()

    resp = await client.get(f"/api/v1/risk/customer/{customer.id}", headers=auth_headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["customer_id"] == customer.id
    assert data["organization_id"] == org.id
    assert "risk_score" in data
    assert "risk_category" in data
    assert "top_factors" in data
    assert "scoring_method" in data


@pytest.mark.asyncio
async def test_rescore_invoice_endpoint(
    client: AsyncClient,
    db_session: AsyncSession,
    org: Organization,
    customer: Customer,
    auth_headers: dict,
):
    """Test POST /risk/invoice/{invoice_id}/rescore endpoint."""
    db = db_session
    today = date.today()

    inv = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="RESCORE-API",
        issue_date=today,
        due_date=today + timedelta(days=30),
        total_amount=Decimal("1000.0"),
        status=InvoiceStatus.ISSUED,
    )
    db.add(inv)
    await db.commit()

    resp = await client.post(f"/api/v1/risk/invoice/{inv.id}/rescore", headers=auth_headers)
    assert resp.status_code == 201

    data = resp.json()
    assert data["invoice_id"] == inv.id
    assert "risk_score" in data


@pytest.mark.asyncio
async def test_get_invoice_risk_history_endpoint(
    client: AsyncClient,
    db_session: AsyncSession,
    org: Organization,
    customer: Customer,
    auth_headers: dict,
):
    """Test GET /risk/invoice/{invoice_id}/history endpoint."""
    db = db_session
    today = date.today()

    inv = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="HISTORY-INV",
        issue_date=today,
        due_date=today + timedelta(days=30),
        total_amount=Decimal("1000.0"),
        status=InvoiceStatus.ISSUED,
    )
    db.add(inv)
    await db.commit()

    # Create multiple assessments (simulating rescoring over time)
    await score_invoice(db, org.id, inv.id)
    await score_invoice(db, org.id, inv.id)
    await score_invoice(db, org.id, inv.id)

    resp = await client.get(f"/api/v1/risk/invoice/{inv.id}/history", headers=auth_headers)
    assert resp.status_code == 200

    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 3, "Should return 3 historical assessments"
    # Verify newest first
    assert data[0]["created_at"] >= data[1]["created_at"] >= data[2]["created_at"]
