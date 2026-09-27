"""Tests for Promise-to-Pay API endpoints."""
import uuid
import pytest
from httpx import AsyncClient
from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promise import PromiseToPay, PromiseStatus
from app.models.case import Case
from app.models.audit import AuditLog
from tests.conftest import register_user


@pytest.fixture
async def promise_context(client: AsyncClient):
    """Set up organization with user, customer, invoice, and case for promise tests."""
    uid = uuid.uuid4().hex[:8]
    data = await register_user(client, f"promise_user_{uid}@test.com", "promisepass", "PromiseUser", f"PromiseOrg-{uid}")
    token = data["access_token"]
    org_id = data["organization_id"]
    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}

    # Create customer
    cust_resp = await client.post("/api/v1/customers/", json={"name": "Promise Customer"}, headers=headers)
    customer_id = cust_resp.json()["id"]

    # Create invoice
    inv_resp = await client.post("/api/v1/invoices/", json={
        "customer_id": customer_id,
        "invoice_number": f"PROM-INV-{uid}",
        "issue_date": str(date.today()),
        "due_date": str(date.today() + timedelta(days=30)),
        "total_amount": "50000.00",
    }, headers=headers)
    invoice_id = inv_resp.json()["id"]

    # Create case
    case_resp = await client.post("/api/v1/cases/", json={
        "customer_id": customer_id,
        "invoice_id": invoice_id,
        "case_number": f"PROM-CASE-{uid}",
        "title": f"Recovery for {invoice_id}",
        "priority": "HIGH",
    }, headers=headers)
    case_id = case_resp.json()["id"]

    return {
        "token": token,
        "org_id": org_id,
        "headers": headers,
        "customer_id": customer_id,
        "invoice_id": invoice_id,
        "case_id": case_id,
    }


@pytest.fixture
async def promise_context2(client: AsyncClient):
    """Set up second organization for isolation tests."""
    uid = uuid.uuid4().hex[:8]
    data = await register_user(client, f"promise_user2_{uid}@test.com", "promisepass2", "PromiseUser2", f"PromiseOrg2-{uid}")
    token = data["access_token"]
    org_id = data["organization_id"]
    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}

    # Create customer
    cust_resp = await client.post("/api/v1/customers/", json={"name": "Promise Customer 2"}, headers=headers)
    customer_id = cust_resp.json()["id"]

    # Create invoice
    inv_resp = await client.post("/api/v1/invoices/", json={
        "customer_id": customer_id,
        "invoice_number": f"PROM2-INV-{uid}",
        "issue_date": str(date.today()),
        "due_date": str(date.today() + timedelta(days=30)),
        "total_amount": "30000.00",
    }, headers=headers)
    invoice_id = inv_resp.json()["id"]

    # Create case
    case_resp = await client.post("/api/v1/cases/", json={
        "customer_id": customer_id,
        "invoice_id": invoice_id,
        "case_number": f"PROM2-CASE-{uid}",
        "title": f"Recovery 2 for {invoice_id}",
        "priority": "MEDIUM",
    }, headers=headers)
    case_id = case_resp.json()["id"]

    return {
        "token": token,
        "org_id": org_id,
        "headers": headers,
        "customer_id": customer_id,
        "invoice_id": invoice_id,
        "case_id": case_id,
    }


@pytest.mark.asyncio
async def test_create_promise_success(client: AsyncClient, promise_context, db_session: AsyncSession):
    """Creating a promise updates case expected_payment_date and creates audit logs."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    org_id = promise_context["org_id"]
    
    # Create promise
    promise_date = date.today() + timedelta(days=15)
    promise_data = {
        "promise_date": str(promise_date),
        "promised_amount": 25000.00,
        "notes": "Customer promises to pay half amount"
    }
    
    resp = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise_data,
        headers=headers
    )
    assert resp.status_code == 201
    data = resp.json()
    
    assert data["case_id"] == case_id
    assert Decimal(data["promised_amount"]) == Decimal("25000.00")
    assert data["promise_date"] == str(promise_date)
    assert data["status"] == "PENDING"
    assert data["notes"] == "Customer promises to pay half amount"
    assert data["organization_id"] == org_id
    assert "id" in data
    
    # Verify case expected_payment_date updated
    case_resp = await client.get(
        f"/api/v1/cases/{case_id}",
        headers=headers
    )
    assert case_resp.status_code == 200
    case_data = case_resp.json()
    assert case_data["expected_payment_date"] == str(promise_date)
    
    # Verify audit logs created
    stmt = select(AuditLog).where(
        AuditLog.organization_id == org_id,
        AuditLog.action.in_(["PROMISE_CREATED", "CASE_UPDATED"])
    ).order_by(AuditLog.created_at)
    result = await db_session.execute(stmt)
    logs = result.scalars().all()
    
    assert len(logs) >= 2
    promise_log = next((log for log in logs if log.action == "PROMISE_CREATED"), None)
    assert promise_log is not None
    assert promise_log.entity_type == "PromiseToPay"
    
    case_log = next((log for log in logs if log.action == "CASE_UPDATED" and log.details.get("reason") == "promise_created"), None)
    assert case_log is not None
    assert case_log.entity_id == case_id


@pytest.mark.asyncio
async def test_create_promise_past_date_rejected(client: AsyncClient, promise_context):
    """Promise with past date is rejected."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    # Try to create promise with past date
    past_date = date.today() - timedelta(days=5)
    promise_data = {
        "promise_date": str(past_date),
        "promised_amount": 10000.00,
    }
    
    resp = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise_data,
        headers=headers
    )
    assert resp.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_create_promise_zero_amount_rejected(client: AsyncClient, promise_context):
    """Promise with zero amount is rejected."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    promise_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 0.00,
    }
    
    resp = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise_data,
        headers=headers
    )
    assert resp.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_create_promise_negative_amount_rejected(client: AsyncClient, promise_context):
    """Promise with negative amount is rejected."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    promise_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": -5000.00,
    }
    
    resp = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise_data,
        headers=headers
    )
    assert resp.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_create_promise_nonexistent_case(client: AsyncClient, promise_context):
    """Creating promise for nonexistent case returns 404."""
    headers = promise_context["headers"]
    
    promise_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 10000.00,
    }
    
    resp = await client.post(
        "/api/v1/cases/nonexistent-uuid-12345/promises/",
        json=promise_data,
        headers=headers
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_promise_cross_tenant_case_rejected(client: AsyncClient, promise_context, promise_context2):
    """Creating promise for another org's case returns 404 (tenant isolation)."""
    case_id_org1 = promise_context["case_id"]
    headers_org2 = promise_context2["headers"]
    
    promise_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 10000.00,
    }
    
    resp = await client.post(
        f"/api/v1/cases/{case_id_org1}/promises/",
        json=promise_data,
        headers=headers_org2
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower() or "does not belong" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_case_promises(client: AsyncClient, promise_context):
    """List all promises for a case in chronological order."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    # Create multiple promises
    promise1_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 15000.00,
        "notes": "First promise"
    }
    resp1 = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise1_data,
        headers=headers
    )
    assert resp1.status_code == 201
    
    promise2_data = {
        "promise_date": str(date.today() + timedelta(days=20)),
        "promised_amount": 20000.00,
        "notes": "Second promise"
    }
    resp2 = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise2_data,
        headers=headers
    )
    assert resp2.status_code == 201
    
    # List promises
    list_resp = await client.get(
        f"/api/v1/cases/{case_id}/promises/",
        headers=headers
    )
    assert list_resp.status_code == 200
    data = list_resp.json()
    
    assert data["total"] == 2
    assert len(data["promises"]) == 2
    
    # Verify chronological order (earliest first)
    assert data["promises"][0]["promised_amount"] == "15000.00"
    assert data["promises"][1]["promised_amount"] == "20000.00"


@pytest.mark.asyncio
async def test_list_promises_empty(client: AsyncClient, promise_context):
    """Listing promises for case with no promises returns empty list."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    resp = await client.get(
        f"/api/v1/cases/{case_id}/promises/",
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["promises"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_promises_cross_tenant_rejected(client: AsyncClient, promise_context, promise_context2):
    """Listing promises for another org's case returns 404."""
    case_id_org1 = promise_context["case_id"]
    headers_org2 = promise_context2["headers"]
    
    resp = await client.get(
        f"/api/v1/cases/{case_id_org1}/promises/",
        headers=headers_org2
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_promise_by_id(client: AsyncClient, promise_context):
    """Retrieve a single promise by ID."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    # Create promise
    promise_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 12000.00,
        "notes": "Test promise"
    }
    create_resp = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise_data,
        headers=headers
    )
    promise_id = create_resp.json()["id"]
    
    # Get promise by ID
    resp = await client.get(
        f"/api/v1/promises/{promise_id}/",
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    
    assert data["id"] == promise_id
    assert Decimal(data["promised_amount"]) == Decimal("12000.00")
    assert data["notes"] == "Test promise"


@pytest.mark.asyncio
async def test_get_promise_nonexistent(client: AsyncClient, promise_context):
    """Getting nonexistent promise returns 404."""
    headers = promise_context["headers"]
    
    resp = await client.get(
        "/api/v1/promises/nonexistent-uuid-12345/",
        headers=headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_promise_cross_tenant_rejected(client: AsyncClient, promise_context, promise_context2):
    """Getting promise from another org returns 404."""
    case_id_org1 = promise_context["case_id"]
    headers_org1 = promise_context["headers"]
    headers_org2 = promise_context2["headers"]
    
    # Org1 creates promise
    promise_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 8000.00,
    }
    create_resp = await client.post(
        f"/api/v1/cases/{case_id_org1}/promises/",
        json=promise_data,
        headers=headers_org1
    )
    promise_id = create_resp.json()["id"]
    
    # Org2 attempts to get Org1's promise
    resp = await client.get(
        f"/api/v1/promises/{promise_id}/",
        headers=headers_org2
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_promise_date(client: AsyncClient, promise_context):
    """Update promise date (customer requests extension)."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    # Create promise
    original_date = date.today() + timedelta(days=10)
    promise_data = {
        "promise_date": str(original_date),
        "promised_amount": 10000.00,
    }
    create_resp = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise_data,
        headers=headers
    )
    promise_id = create_resp.json()["id"]
    
    # Update promise date
    new_date = date.today() + timedelta(days=25)
    update_data = {
        "promise_date": str(new_date)
    }
    update_resp = await client.patch(
        f"/api/v1/promises/{promise_id}/",
        json=update_data,
        headers=headers
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    
    assert data["promise_date"] == str(new_date)
    assert Decimal(data["promised_amount"]) == Decimal("10000.00")  # Unchanged


@pytest.mark.asyncio
async def test_update_promise_amount(client: AsyncClient, promise_context):
    """Update promised amount."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    # Create promise
    promise_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 10000.00,
    }
    create_resp = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise_data,
        headers=headers
    )
    promise_id = create_resp.json()["id"]
    
    # Update amount
    update_data = {
        "promised_amount": 15000.00
    }
    update_resp = await client.patch(
        f"/api/v1/promises/{promise_id}/",
        json=update_data,
        headers=headers
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    
    assert Decimal(data["promised_amount"]) == Decimal("15000.00")


@pytest.mark.asyncio
async def test_update_promise_notes(client: AsyncClient, promise_context):
    """Update promise notes."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    # Create promise
    promise_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 10000.00,
        "notes": "Original note"
    }
    create_resp = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise_data,
        headers=headers
    )
    promise_id = create_resp.json()["id"]
    
    # Update notes
    update_data = {
        "notes": "Updated note - customer called for extension"
    }
    update_resp = await client.patch(
        f"/api/v1/promises/{promise_id}/",
        json=update_data,
        headers=headers
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    
    assert data["notes"] == "Updated note - customer called for extension"


@pytest.mark.asyncio
async def test_cancel_promise(client: AsyncClient, promise_context):
    """Cancel a pending promise (valid status transition)."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    # Create promise
    promise_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 10000.00,
    }
    create_resp = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise_data,
        headers=headers
    )
    promise_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "PENDING"
    
    # Cancel promise
    update_data = {
        "status": "CANCELLED"
    }
    update_resp = await client.patch(
        f"/api/v1/promises/{promise_id}/",
        json=update_data,
        headers=headers
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_invalid_status_transition_rejected(client: AsyncClient, promise_context):
    """Invalid status transition is rejected (e.g., FULFILLED → PENDING)."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    # Create promise and mark as FULFILLED
    promise_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 10000.00,
    }
    create_resp = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise_data,
        headers=headers
    )
    promise_id = create_resp.json()["id"]
    
    # Manually mark as FULFILLED
    fulfill_resp = await client.patch(
        f"/api/v1/promises/{promise_id}/",
        json={"status": "FULFILLED"},
        headers=headers
    )
    assert fulfill_resp.status_code == 200
    
    # Try to change FULFILLED → PENDING (invalid)
    invalid_update = {
        "status": "PENDING"
    }
    resp = await client.patch(
        f"/api/v1/promises/{promise_id}/",
        json=invalid_update,
        headers=headers
    )
    assert resp.status_code == 400
    assert "Invalid status transition" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_promise_cross_tenant_rejected(client: AsyncClient, promise_context, promise_context2):
    """Updating promise from another org returns 404."""
    case_id_org1 = promise_context["case_id"]
    headers_org1 = promise_context["headers"]
    headers_org2 = promise_context2["headers"]
    
    # Org1 creates promise
    promise_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 10000.00,
    }
    create_resp = await client.post(
        f"/api/v1/cases/{case_id_org1}/promises/",
        json=promise_data,
        headers=headers_org1
    )
    promise_id = create_resp.json()["id"]
    
    # Org2 attempts to update Org1's promise
    update_data = {
        "notes": "Trying to update another org's promise"
    }
    resp = await client.patch(
        f"/api/v1/promises/{promise_id}/",
        json=update_data,
        headers=headers_org2
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_multiple_promises_per_case(client: AsyncClient, promise_context):
    """Multiple promises can exist for one case (installment plan)."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    # Create first promise
    promise1_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 20000.00,
        "notes": "First installment"
    }
    resp1 = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise1_data,
        headers=headers
    )
    assert resp1.status_code == 201
    promise1_id = resp1.json()["id"]
    
    # Create second promise
    promise2_data = {
        "promise_date": str(date.today() + timedelta(days=30)),
        "promised_amount": 30000.00,
        "notes": "Second installment"
    }
    resp2 = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise2_data,
        headers=headers
    )
    assert resp2.status_code == 201
    promise2_id = resp2.json()["id"]
    
    # Verify both exist
    list_resp = await client.get(
        f"/api/v1/cases/{case_id}/promises/",
        headers=headers
    )
    data = list_resp.json()
    assert data["total"] == 2
    
    # Verify oldest promise is unchanged
    get_resp1 = await client.get(
        f"/api/v1/promises/{promise1_id}/",
        headers=headers
    )
    assert get_resp1.status_code == 200
    assert Decimal(get_resp1.json()["promised_amount"]) == Decimal("20000.00")
    assert get_resp1.json()["status"] == "PENDING"


@pytest.mark.asyncio
async def test_case_expected_payment_date_tracks_earliest_promise(client: AsyncClient, promise_context):
    """Case.expected_payment_date reflects earliest pending promise."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    
    # Create promise for day 20
    promise1_data = {
        "promise_date": str(date.today() + timedelta(days=20)),
        "promised_amount": 15000.00,
    }
    await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise1_data,
        headers=headers
    )
    
    # Check case expected_payment_date
    case_resp = await client.get(f"/api/v1/cases/{case_id}", headers=headers)
    assert case_resp.json()["expected_payment_date"] == str(date.today() + timedelta(days=20))
    
    # Create earlier promise for day 10
    promise2_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 10000.00,
    }
    await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise2_data,
        headers=headers
    )
    
    # Check case expected_payment_date updated to earliest
    case_resp2 = await client.get(f"/api/v1/cases/{case_id}", headers=headers)
    assert case_resp2.json()["expected_payment_date"] == str(date.today() + timedelta(days=10))


@pytest.mark.asyncio
async def test_promise_status_change_creates_audit_log(client: AsyncClient, promise_context, db_session: AsyncSession):
    """Status change creates PROMISE_STATUS_CHANGED audit event."""
    case_id = promise_context["case_id"]
    headers = promise_context["headers"]
    org_id = promise_context["org_id"]
    
    # Create promise
    promise_data = {
        "promise_date": str(date.today() + timedelta(days=10)),
        "promised_amount": 10000.00,
    }
    create_resp = await client.post(
        f"/api/v1/cases/{case_id}/promises/",
        json=promise_data,
        headers=headers
    )
    promise_id = create_resp.json()["id"]
    
    # Cancel promise
    update_resp = await client.patch(
        f"/api/v1/promises/{promise_id}/",
        json={"status": "CANCELLED"},
        headers=headers
    )
    assert update_resp.status_code == 200
    
    # Verify PROMISE_STATUS_CHANGED audit log
    stmt = select(AuditLog).where(
        AuditLog.organization_id == org_id,
        AuditLog.action == "PROMISE_STATUS_CHANGED",
        AuditLog.entity_id == promise_id
    )
    result = await db_session.execute(stmt)
    log = result.scalar_one_or_none()
    
    assert log is not None
    assert log.details["old_status"] == "PENDING"
    assert log.details["new_status"] == "CANCELLED"
