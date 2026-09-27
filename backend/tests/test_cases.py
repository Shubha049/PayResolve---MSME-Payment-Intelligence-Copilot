"""
Case CRUD and lifecycle tests.
"""
import uuid
import pytest
from datetime import date, timedelta
from httpx import AsyncClient
from tests.conftest import register_user


@pytest.fixture
async def case_context(client: AsyncClient):
    """Create user, org, customer, and invoice for case tests."""
    uid = uuid.uuid4().hex[:8]
    data = await register_user(client, f"case_user_{uid}@test.com", "casepass", "CaseUser", f"CaseOrg-{uid}")
    token = data["access_token"]
    org_id = data["organization_id"]
    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}

    cust_resp = await client.post("/api/v1/customers/", json={"name": "Case Buyer"}, headers=headers)
    customer_id = cust_resp.json()["id"]

    inv_resp = await client.post("/api/v1/invoices/", json={
        "customer_id": customer_id,
        "invoice_number": "CASE-INV-001",
        "issue_date": str(date.today()),
        "due_date": str(date.today() + timedelta(days=30)),
        "total_amount": "10000.00",
    }, headers=headers)
    invoice_id = inv_resp.json()["id"]

    return {
        "token": token, "org_id": org_id, "headers": headers,
        "customer_id": customer_id, "invoice_id": invoice_id,
    }


@pytest.mark.asyncio
async def test_create_case_success(client: AsyncClient, case_context):
    resp = await client.post("/api/v1/cases/", json={
        "customer_id": case_context["customer_id"],
        "invoice_id": case_context["invoice_id"],
        "case_number": "CASE-001",
        "title": "Recovery for CASE-INV-001",
        "priority": "HIGH",
    }, headers=case_context["headers"])
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["case_number"] == "CASE-001"
    assert data["status"] == "OPEN"
    assert data["priority"] == "HIGH"
    assert data["customer"]["name"] == "Case Buyer"
    assert data["invoice"]["invoice_number"] == "CASE-INV-001"


@pytest.mark.asyncio
async def test_create_case_duplicate_number_fails(client: AsyncClient, case_context):
    payload = {
        "customer_id": case_context["customer_id"],
        "case_number": "CASE-DUP",
        "title": "Duplicate Test",
    }
    r1 = await client.post("/api/v1/cases/", json=payload, headers=case_context["headers"])
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/cases/", json=payload, headers=case_context["headers"])
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_update_case_status_lifecycle(client: AsyncClient, case_context):
    """Walk a case through status transitions."""
    create_resp = await client.post("/api/v1/cases/", json={
        "customer_id": case_context["customer_id"],
        "case_number": "CASE-LIFECYCLE",
        "title": "Status Lifecycle Test",
    }, headers=case_context["headers"])
    case_id = create_resp.json()["id"]
    headers = case_context["headers"]

    for status in ["EVIDENCE_GATHERING", "REMINDER_SENT", "IN_DISPUTE", "ESCALATED", "RESOLVED"]:
        resp = await client.patch(
            f"/api/v1/cases/{case_id}",
            json={"status": status},
            headers=headers,
        )
        assert resp.status_code == 200, f"Failed at status: {status}"
        assert resp.json()["status"] == status


@pytest.mark.asyncio
async def test_list_cases_with_status_filter(client: AsyncClient, case_context):
    headers = case_context["headers"]
    customer_id = case_context["customer_id"]

    # Create open and resolved cases
    open_resp = await client.post("/api/v1/cases/", json={
        "customer_id": customer_id, "case_number": "CASE-OPEN-1",
        "title": "Open Case", "status": "OPEN",
    }, headers=headers)
    
    res_resp = await client.post("/api/v1/cases/", json={
        "customer_id": customer_id, "case_number": "CASE-RES-1",
        "title": "Resolved Case", "status": "RESOLVED",
    }, headers=headers)

    resp = await client.get("/api/v1/cases/?status=OPEN", headers=headers)
    assert resp.status_code == 200
    statuses = [c["status"] for c in resp.json()]
    assert all(s == "OPEN" for s in statuses)


@pytest.mark.asyncio
async def test_delete_case(client: AsyncClient, case_context):
    headers = case_context["headers"]
    create_resp = await client.post("/api/v1/cases/", json={
        "customer_id": case_context["customer_id"],
        "case_number": "CASE-DEL",
        "title": "To Be Deleted",
    }, headers=headers)
    case_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/cases/{case_id}", headers=headers)
    assert del_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/cases/{case_id}", headers=headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_dashboard_summary(client: AsyncClient, case_context):
    """Dashboard summary shows accurate metrics."""
    headers = case_context["headers"]
    resp = await client.get("/api/v1/dashboard/summary", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_invoiced" in data
    assert "total_outstanding" in data
    assert "active_cases_count" in data
    assert "customers_count" in data
    assert float(data["total_invoiced"]) >= 0
    assert float(data["customers_count"]) >= 1
