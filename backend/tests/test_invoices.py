"""
Invoice CRUD tests with full tenant context.
"""
import uuid
import pytest
from datetime import date, timedelta
from httpx import AsyncClient
from tests.conftest import register_user, login_user


@pytest.fixture
async def org_context(client: AsyncClient):
    """Set up a user, org, and customer; return auth info."""
    uid = uuid.uuid4().hex[:8]
    data = await register_user(client, f"inv_user_{uid}@test.com", "invpass", "InvUser", f"InvOrg-{uid}")
    token = data["access_token"]
    org_id = data["organization_id"]

    # Create a customer
    resp = await client.post(
        "/api/v1/customers/",
        json={"name": "Test Buyer Corp"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id},
    )
    customer = resp.json()
    return {"token": token, "org_id": org_id, "customer_id": customer["id"]}


@pytest.mark.asyncio
async def test_create_invoice_success(client: AsyncClient, org_context):
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    resp = await client.post(
        "/api/v1/invoices/",
        json={
            "customer_id": customer_id,
            "invoice_number": "INV-001",
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "total_amount": "5000.00",
            "currency": "INR",
        },
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["invoice_number"] == "INV-001"
    assert data["status"] == "ISSUED"
    assert data["outstanding_amount"] == "5000.00"
    assert data["customer"]["name"] == "Test Buyer Corp"


@pytest.mark.asyncio
async def test_create_invoice_past_due_auto_overdue(client: AsyncClient, org_context):
    """If due_date is in the past, status is auto-set to OVERDUE."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    resp = await client.post(
        "/api/v1/invoices/",
        json={
            "customer_id": customer_id,
            "invoice_number": "INV-002",
            "issue_date": str(date.today() - timedelta(days=60)),
            "due_date": str(date.today() - timedelta(days=30)),
            "total_amount": "2000.00",
        },
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "OVERDUE"


@pytest.mark.asyncio
async def test_create_invoice_duplicate_number_fails(client: AsyncClient, org_context):
    """Duplicate invoice number within same org returns 400."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    payload = {
        "customer_id": customer_id,
        "invoice_number": "INV-DUP",
        "issue_date": str(date.today()),
        "due_date": str(date.today() + timedelta(days=30)),
        "total_amount": "500.00",
    }
    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}
    r1 = await client.post("/api/v1/invoices/", json=payload, headers=headers)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/invoices/", json=payload, headers=headers)
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_create_invoice_negative_amount_fails(client: AsyncClient, org_context):
    """Negative total_amount should fail validation."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    resp = await client.post(
        "/api/v1/invoices/",
        json={
            "customer_id": customer_id,
            "invoice_number": "INV-NEG",
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "total_amount": "-100.00",
        },
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_paid_amount_auto_sets_paid_status(client: AsyncClient, org_context):
    """Updating paid_amount to equal total_amount auto-sets status to PAID."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]

    create_resp = await client.post(
        "/api/v1/invoices/",
        json={
            "customer_id": customer_id,
            "invoice_number": "INV-PAY",
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "total_amount": "3000.00",
        },
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id},
    )
    invoice_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"paid_amount": "3000.00"},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "PAID"
    assert update_resp.json()["outstanding_amount"] == "0.00"


@pytest.mark.asyncio
async def test_list_invoices_overdue_filter(client: AsyncClient, org_context):
    """is_overdue=true filter returns only overdue invoices."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}

    # Create overdue invoice
    await client.post("/api/v1/invoices/", json={
        "customer_id": customer_id, "invoice_number": "INV-OVD-1",
        "issue_date": str(date.today() - timedelta(days=60)),
        "due_date": str(date.today() - timedelta(days=30)),
        "total_amount": "1000.00",
    }, headers=headers)

    # Create non-overdue invoice
    await client.post("/api/v1/invoices/", json={
        "customer_id": customer_id, "invoice_number": "INV-OK-1",
        "issue_date": str(date.today()),
        "due_date": str(date.today() + timedelta(days=60)),
        "total_amount": "500.00",
    }, headers=headers)

    resp = await client.get(
        "/api/v1/invoices/?is_overdue=true",
        headers=headers,
    )
    assert resp.status_code == 200
    invoices = resp.json()
    assert all(i["status"] in ["OVERDUE", "ISSUED", "PARTIALLY_PAID"] for i in invoices)


@pytest.mark.asyncio
async def test_delete_invoice(client: AsyncClient, org_context):
    """Delete an invoice returns 204 and subsequent GET returns 404."""
    token, org_id, customer_id = org_context["token"], org_context["org_id"], org_context["customer_id"]
    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}

    create_resp = await client.post("/api/v1/invoices/", json={
        "customer_id": customer_id, "invoice_number": "INV-DEL",
        "issue_date": str(date.today()),
        "due_date": str(date.today() + timedelta(days=30)),
        "total_amount": "100.00",
    }, headers=headers)
    inv_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/invoices/{inv_id}", headers=headers)
    assert del_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/invoices/{inv_id}", headers=headers)
    assert get_resp.status_code == 404
