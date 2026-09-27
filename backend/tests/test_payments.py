"""Tests for Payment API endpoints."""
import uuid
import pytest
from httpx import AsyncClient
from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.stubs import Payment
from app.models.audit import AuditLog
from tests.conftest import register_user, login_user


@pytest.fixture
async def org_context(client: AsyncClient):
    """Set up org 1 with user and customer for payment tests."""
    uid = uuid.uuid4().hex[:8]
    data = await register_user(client, f"pay_user_{uid}@test.com", "paypass", "PayUser", f"PayOrg-{uid}")
    token = data["access_token"]
    org_id = data["organization_id"]
    
    # Create customer
    resp = await client.post(
        "/api/v1/customers/",
        json={"name": "Payment Test Customer"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id},
    )
    customer = resp.json()
    return {"token": token, "org_id": org_id, "customer_id": customer["id"]}


@pytest.fixture
async def org2_context(client: AsyncClient):
    """Set up org 2 with user and customer for isolation tests."""
    uid = uuid.uuid4().hex[:8]
    data = await register_user(client, f"pay_user2_{uid}@test.com", "paypass2", "PayUser2", f"PayOrg2-{uid}")
    token = data["access_token"]
    org_id = data["organization_id"]
    
    # Create customer
    resp = await client.post(
        "/api/v1/customers/",
        json={"name": "Payment Test Customer 2"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id},
    )
    customer = resp.json()
    return {"token": token, "org_id": org_id, "customer_id": customer["id"]}


@pytest.mark.asyncio
async def test_create_payment_success(client: AsyncClient, org_context, db_session: AsyncSession):
    """Creating a payment updates invoice.paid_amount and creates audit log."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    
    # Create invoice
    invoice_data = {
        "customer_id": customer_id,
        "invoice_number": "INV-PAY-001",
        "issue_date": str(date.today()),
        "due_date": str(date.today() + timedelta(days=30)),
        "total_amount": 1000.00,
        "status": "ISSUED"
    }
    inv_resp = await client.post(
        "/api/v1/invoices/",
        json=invoice_data,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert inv_resp.status_code == 201
    invoice_id = inv_resp.json()["id"]
    
    # Create payment
    payment_data = {
        "invoice_id": invoice_id,
        "amount": 300.00,
        "payment_date": "2024-01-15",
        "reference": "CHK-12345"
    }
    resp = await client.post(
        "/api/v1/payments/",
        json=payment_data,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp.status_code == 201
    data = resp.json()
    
    assert data["invoice_id"] == invoice_id
    assert Decimal(data["amount"]) == Decimal("300.00")
    assert data["payment_date"] == "2024-01-15"
    assert data["reference"] == "CHK-12345"
    assert data["organization_id"] == org_id
    assert "id" in data
    
    # Verify invoice paid_amount updated
    inv_resp = await client.get(
        f"/api/v1/invoices/{invoice_id}",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert inv_resp.status_code == 200
    invoice = inv_resp.json()
    assert Decimal(invoice["paid_amount"]) == Decimal("300.00")
    assert Decimal(invoice["outstanding_amount"]) == Decimal("700.00")
    # Status remains as originally set (ISSUED), not fully paid yet
    
    # Verify audit logs created
    stmt = select(AuditLog).where(
        AuditLog.organization_id == org_id,
        AuditLog.action.in_(["PAYMENT_CREATED", "INVOICE_UPDATED"])
    ).order_by(AuditLog.created_at)
    result = await db_session.execute(stmt)
    logs = result.scalars().all()
    
    assert len(logs) >= 2
    payment_log = next((log for log in logs if log.action == "PAYMENT_CREATED"), None)
    assert payment_log is not None
    assert payment_log.entity_type == "Payment"
    
    invoice_log = next((log for log in logs if log.action == "INVOICE_UPDATED" and log.details.get("reason") == "payment_recorded"), None)
    assert invoice_log is not None
    assert invoice_log.entity_id == invoice_id


@pytest.mark.asyncio
async def test_create_payment_auto_sets_paid_status(client: AsyncClient, org_context):
    """Payment that brings paid_amount >= total_amount auto-sets status to PAID."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    
    # Create invoice
    invoice_data = {
        "customer_id": customer_id,
        "invoice_number": "INV-PAY-002",
        "issue_date": "2024-01-01",
        "due_date": "2024-02-01",
        "total_amount": 500.00,
        "status": "ISSUED"
    }
    inv_resp = await client.post(
        "/api/v1/invoices/",
        json=invoice_data,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert inv_resp.status_code == 201
    invoice_id = inv_resp.json()["id"]
    
    # Make full payment
    payment_data = {
        "invoice_id": invoice_id,
        "amount": 500.00,
        "payment_date": "2024-01-15"
    }
    resp = await client.post(
        "/api/v1/payments/",
        json=payment_data,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp.status_code == 201
    
    # Verify status auto-set to PAID
    inv_resp = await client.get(
        f"/api/v1/invoices/{invoice_id}",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    invoice = inv_resp.json()
    assert Decimal(invoice["paid_amount"]) == Decimal("500.00")
    assert Decimal(invoice["outstanding_amount"]) == Decimal("0.00")
    assert invoice["status"] == "PAID"


@pytest.mark.asyncio
async def test_create_payment_multiple_payments_cumulative(client: AsyncClient, org_context):
    """Multiple payments update paid_amount cumulatively."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    
    # Create invoice
    invoice_data = {
        "customer_id": customer_id,
        "invoice_number": "INV-PAY-003",
        "issue_date": "2024-01-01",
        "due_date": "2024-02-01",
        "total_amount": 1000.00,
        "status": "ISSUED"
    }
    inv_resp = await client.post(
        "/api/v1/invoices/",
        json=invoice_data,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    invoice_id = inv_resp.json()["id"]
    
    # First payment
    resp1 = await client.post(
        "/api/v1/payments/",
        json={"invoice_id": invoice_id, "amount": 300.00, "payment_date": "2024-01-10"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp1.status_code == 201
    
    # Second payment
    resp2 = await client.post(
        "/api/v1/payments/",
        json={"invoice_id": invoice_id, "amount": 250.00, "payment_date": "2024-01-20"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp2.status_code == 201
    
    # Third payment (completes)
    resp3 = await client.post(
        "/api/v1/payments/",
        json={"invoice_id": invoice_id, "amount": 450.00, "payment_date": "2024-01-25"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp3.status_code == 201
    
    # Verify cumulative paid_amount
    inv_resp = await client.get(
        f"/api/v1/invoices/{invoice_id}",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    invoice = inv_resp.json()
    assert Decimal(invoice["paid_amount"]) == Decimal("1000.00")
    assert Decimal(invoice["outstanding_amount"]) == Decimal("0.00")
    assert invoice["status"] == "PAID"


@pytest.mark.asyncio
async def test_create_payment_overpayment_allowed(client: AsyncClient, org_context):
    """Overpayment is allowed (existing behavior); outstanding_amount becomes 0."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    
    # Create invoice
    invoice_data = {
        "customer_id": customer_id,
        "invoice_number": "INV-PAY-004",
        "issue_date": "2024-01-01",
        "due_date": "2024-02-01",
        "total_amount": 500.00,
        "status": "ISSUED"
    }
    inv_resp = await client.post(
        "/api/v1/invoices/",
        json=invoice_data,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    invoice_id = inv_resp.json()["id"]
    
    # Overpayment
    payment_data = {
        "invoice_id": invoice_id,
        "amount": 600.00,
        "payment_date": "2024-01-15"
    }
    resp = await client.post(
        "/api/v1/payments/",
        json=payment_data,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp.status_code == 201
    
    # Verify overpayment recorded, outstanding = 0 (existing behavior: max(0, total - paid))
    inv_resp = await client.get(
        f"/api/v1/invoices/{invoice_id}",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    invoice = inv_resp.json()
    assert Decimal(invoice["paid_amount"]) == Decimal("600.00")
    assert Decimal(invoice["outstanding_amount"]) == Decimal("0.00")  # max(0, 500 - 600)
    assert invoice["status"] == "PAID"


@pytest.mark.asyncio
async def test_create_payment_negative_amount_rejected(client: AsyncClient, org_context):
    """Payment with negative amount is rejected."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    
    # Create invoice
    invoice_data = {
        "customer_id": customer_id,
        "invoice_number": "INV-PAY-005",
        "issue_date": "2024-01-01",
        "due_date": "2024-02-01",
        "total_amount": 500.00,
        "status": "ISSUED"
    }
    inv_resp = await client.post(
        "/api/v1/invoices/",
        json=invoice_data,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    invoice_id = inv_resp.json()["id"]
    
    # Negative payment
    payment_data = {
        "invoice_id": invoice_id,
        "amount": -100.00,
        "payment_date": "2024-01-15"
    }
    resp = await client.post(
        "/api/v1/payments/",
        json=payment_data,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_create_payment_zero_amount_rejected(client: AsyncClient, org_context):
    """Payment with zero amount is rejected."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    
    # Create invoice
    invoice_data = {
        "customer_id": customer_id,
        "invoice_number": "INV-PAY-006",
        "issue_date": "2024-01-01",
        "due_date": "2024-02-01",
        "total_amount": 500.00,
        "status": "ISSUED"
    }
    inv_resp = await client.post(
        "/api/v1/invoices/",
        json=invoice_data,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    invoice_id = inv_resp.json()["id"]
    
    # Zero payment
    payment_data = {
        "invoice_id": invoice_id,
        "amount": 0.00,
        "payment_date": "2024-01-15"
    }
    resp = await client.post(
        "/api/v1/payments/",
        json=payment_data,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_create_payment_nonexistent_invoice(client: AsyncClient, org_context):
    """Payment for nonexistent invoice returns 404."""
    token, org_id = org_context["token"], org_context["org_id"]
    
    payment_data = {
        "invoice_id": "nonexistent-uuid-12345",
        "amount": 100.00,
        "payment_date": "2024-01-15"
    }
    resp = await client.post(
        "/api/v1/payments/",
        json=payment_data,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_payment_invoice_from_other_org_rejected(client: AsyncClient, org_context, org2_context):
    """Payment for invoice belonging to another organization returns 404 (tenant isolation)."""
    token1, org_id1, customer_id1 = org_context["token"], org_context["org_id"], org_context["customer_id"]
    token2, org_id2 = org2_context["token"], org2_context["org_id"]
    
    # Org1 creates invoice
    invoice_data = {
        "customer_id": customer_id1,
        "invoice_number": "INV-ORG1-001",
        "issue_date": "2024-01-01",
        "due_date": "2024-02-01",
        "total_amount": 500.00,
        "status": "ISSUED"
    }
    inv_resp = await client.post(
        "/api/v1/invoices/",
        json=invoice_data,
        headers={"Authorization": f"Bearer {token1}", "X-Organization-Id": org_id1}
    )
    assert inv_resp.status_code == 201
    invoice_id = inv_resp.json()["id"]
    
    # Org2 attempts to create payment for Org1's invoice
    payment_data = {
        "invoice_id": invoice_id,
        "amount": 100.00,
        "payment_date": "2024-01-15"
    }
    resp = await client.post(
        "/api/v1/payments/",
        json=payment_data,
        headers={"Authorization": f"Bearer {token2}", "X-Organization-Id": org_id2}
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower() or "does not belong" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_payments_empty(client: AsyncClient, org_context):
    """Listing payments returns empty list when none exist."""
    token, org_id = org_context["token"], org_context["org_id"]
    
    resp = await client.get(
        "/api/v1/payments/",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["payments"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_payments_tenant_isolation(client: AsyncClient, org_context, org2_context):
    """Payments are isolated by organization."""
    token1, org_id1, customer_id1 = org_context["token"], org_context["org_id"], org_context["customer_id"]
    token2, org_id2, customer_id2 = org2_context["token"], org2_context["org_id"], org2_context["customer_id"]
    
    # Org1 creates invoice and payment
    inv_data1 = {
        "customer_id": customer_id1,
        "invoice_number": "INV-ORG1-P001",
        "issue_date": "2024-01-01",
        "due_date": "2024-02-01",
        "total_amount": 500.00,
        "status": "ISSUED"
    }
    inv1 = await client.post("/api/v1/invoices/", json=inv_data1, headers={"Authorization": f"Bearer {token1}", "X-Organization-Id": org_id1})
    invoice_id1 = inv1.json()["id"]
    
    pay_data1 = {"invoice_id": invoice_id1, "amount": 200.00, "payment_date": "2024-01-10"}
    await client.post("/api/v1/payments/", json=pay_data1, headers={"Authorization": f"Bearer {token1}", "X-Organization-Id": org_id1})
    
    # Org2 creates invoice and payment
    inv_data2 = {
        "customer_id": customer_id2,
        "invoice_number": "INV-ORG2-P001",
        "issue_date": "2024-01-01",
        "due_date": "2024-02-01",
        "total_amount": 300.00,
        "status": "ISSUED"
    }
    inv2 = await client.post("/api/v1/invoices/", json=inv_data2, headers={"Authorization": f"Bearer {token2}", "X-Organization-Id": org_id2})
    invoice_id2 = inv2.json()["id"]
    
    pay_data2 = {"invoice_id": invoice_id2, "amount": 150.00, "payment_date": "2024-01-15"}
    await client.post("/api/v1/payments/", json=pay_data2, headers={"Authorization": f"Bearer {token2}", "X-Organization-Id": org_id2})
    
    # Org1 sees only their payment
    resp1 = await client.get("/api/v1/payments/", headers={"Authorization": f"Bearer {token1}", "X-Organization-Id": org_id1})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["total"] == 1
    assert Decimal(data1["payments"][0]["amount"]) == Decimal("200.00")
    
    # Org2 sees only their payment
    resp2 = await client.get("/api/v1/payments/", headers={"Authorization": f"Bearer {token2}", "X-Organization-Id": org_id2})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["total"] == 1
    assert Decimal(data2["payments"][0]["amount"]) == Decimal("150.00")


@pytest.mark.asyncio
async def test_list_payments_filter_by_invoice(client: AsyncClient, org_context):
    """List payments can filter by invoice_id."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    
    # Create two invoices
    inv1 = await client.post(
        "/api/v1/invoices/",
        json={"customer_id": customer_id, "invoice_number": "INV-F1", "issue_date": "2024-01-01", "due_date": "2024-02-01", "total_amount": 500.00, "status": "ISSUED"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    invoice_id1 = inv1.json()["id"]
    
    inv2 = await client.post(
        "/api/v1/invoices/",
        json={"customer_id": customer_id, "invoice_number": "INV-F2", "issue_date": "2024-01-01", "due_date": "2024-02-01", "total_amount": 300.00, "status": "ISSUED"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    invoice_id2 = inv2.json()["id"]
    
    # Create payments for both invoices
    await client.post("/api/v1/payments/", json={"invoice_id": invoice_id1, "amount": 100.00, "payment_date": "2024-01-10"}, headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id})
    await client.post("/api/v1/payments/", json={"invoice_id": invoice_id1, "amount": 150.00, "payment_date": "2024-01-15"}, headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id})
    await client.post("/api/v1/payments/", json={"invoice_id": invoice_id2, "amount": 200.00, "payment_date": "2024-01-20"}, headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id})
    
    # Filter by invoice_id1
    resp = await client.get(
        f"/api/v1/payments/?invoice_id={invoice_id1}",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    for payment in data["payments"]:
        assert payment["invoice_id"] == invoice_id1


@pytest.mark.asyncio
async def test_list_payments_filter_by_date_range(client: AsyncClient, org_context):
    """List payments can filter by date range."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    
    # Create invoice
    inv = await client.post(
        "/api/v1/invoices/",
        json={"customer_id": customer_id, "invoice_number": "INV-DATE", "issue_date": "2024-01-01", "due_date": "2024-02-01", "total_amount": 1000.00, "status": "ISSUED"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    invoice_id = inv.json()["id"]
    
    # Create payments on different dates
    await client.post("/api/v1/payments/", json={"invoice_id": invoice_id, "amount": 100.00, "payment_date": "2024-01-05"}, headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id})
    await client.post("/api/v1/payments/", json={"invoice_id": invoice_id, "amount": 200.00, "payment_date": "2024-01-15"}, headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id})
    await client.post("/api/v1/payments/", json={"invoice_id": invoice_id, "amount": 300.00, "payment_date": "2024-01-25"}, headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id})
    
    # Filter by date range (2024-01-10 to 2024-01-20)
    resp = await client.get(
        "/api/v1/payments/?from_date=2024-01-10&to_date=2024-01-20",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert Decimal(data["payments"][0]["amount"]) == Decimal("200.00")


@pytest.mark.asyncio
async def test_list_payments_pagination(client: AsyncClient, org_context):
    """List payments supports pagination."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    
    # Create invoice
    inv = await client.post(
        "/api/v1/invoices/",
        json={"customer_id": customer_id, "invoice_number": "INV-PAGE", "issue_date": "2024-01-01", "due_date": "2024-02-01", "total_amount": 1000.00, "status": "ISSUED"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    invoice_id = inv.json()["id"]
    
    # Create 5 payments
    for i in range(1, 6):
        await client.post(
            "/api/v1/payments/",
            json={"invoice_id": invoice_id, "amount": 50.00, "payment_date": f"2024-01-{i:02d}"},
            headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
        )
    
    # Get first page (limit=2)
    resp = await client.get(
        "/api/v1/payments/?limit=2",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["payments"]) == 2
    assert data["total"] == 5
    
    # Get second page (skip=2, limit=2)
    resp2 = await client.get(
        "/api/v1/payments/?skip=2&limit=2",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["payments"]) == 2
    assert data2["total"] == 5


@pytest.mark.asyncio
async def test_get_payment_by_id(client: AsyncClient, org_context):
    """Retrieve a single payment by ID."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    
    # Create invoice and payment
    inv = await client.post(
        "/api/v1/invoices/",
        json={"customer_id": customer_id, "invoice_number": "INV-GET", "issue_date": "2024-01-01", "due_date": "2024-02-01", "total_amount": 500.00, "status": "ISSUED"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    invoice_id = inv.json()["id"]
    
    pay = await client.post(
        "/api/v1/payments/",
        json={"invoice_id": invoice_id, "amount": 250.00, "payment_date": "2024-01-10", "reference": "REF-001"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    payment_id = pay.json()["id"]
    
    # Get payment by ID
    resp = await client.get(
        f"/api/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == payment_id
    assert Decimal(data["amount"]) == Decimal("250.00")
    assert data["reference"] == "REF-001"


@pytest.mark.asyncio
async def test_get_payment_nonexistent(client: AsyncClient, org_context):
    """Getting nonexistent payment returns 404."""
    token, org_id = org_context["token"], org_context["org_id"]
    
    resp = await client.get(
        "/api/v1/payments/999999",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_payment_from_other_org_rejected(client: AsyncClient, org_context, org2_context):
    """Getting payment from another organization returns 404 (tenant isolation)."""
    token1, org_id1, customer_id1 = org_context["token"], org_context["org_id"], org_context["customer_id"]
    token2, org_id2 = org2_context["token"], org2_context["org_id"]
    
    # Org1 creates invoice and payment
    inv = await client.post(
        "/api/v1/invoices/",
        json={"customer_id": customer_id1, "invoice_number": "INV-ISO", "issue_date": "2024-01-01", "due_date": "2024-02-01", "total_amount": 500.00, "status": "ISSUED"},
        headers={"Authorization": f"Bearer {token1}", "X-Organization-Id": org_id1}
    )
    invoice_id = inv.json()["id"]
    
    pay = await client.post(
        "/api/v1/payments/",
        json={"invoice_id": invoice_id, "amount": 250.00, "payment_date": "2024-01-10"},
        headers={"Authorization": f"Bearer {token1}", "X-Organization-Id": org_id1}
    )
    payment_id = pay.json()["id"]
    
    # Org2 attempts to get Org1's payment
    resp = await client.get(
        f"/api/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {token2}", "X-Organization-Id": org_id2}
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower() or "does not belong" in resp.json()["detail"].lower()
