import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import register_user


@pytest.fixture
async def dashboard_context(client: AsyncClient):
    uid = uuid.uuid4().hex[:8]
    data = await register_user(
        client,
        f"dashboard_user_{uid}@test.com",
        "securepass123",
        "Dashboard User",
        f"DashboardOrg-{uid}",
    )
    headers = {
        "Authorization": f"Bearer {data['access_token']}",
        "X-Organization-Id": data["organization_id"],
    }

    customer = await client.post(
        "/api/v1/customers/",
        json={"name": "Dashboard Customer", "email": f"dashboard_{uid}@example.com"},
        headers=headers,
    )
    customer_id = customer.json()["id"]

    invoice = await client.post(
        "/api/v1/invoices/",
        json={
            "customer_id": customer_id,
            "invoice_number": f"DB-{uid}-001",
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "total_amount": "1000.00",
        },
        headers=headers,
    )
    invoice_id = invoice.json()["id"]

    case = await client.post(
        "/api/v1/cases/",
        json={
            "customer_id": customer_id,
            "invoice_id": invoice_id,
            "case_number": f"DB-{uid}",
            "title": "Dashboard case",
            "status": "OPEN",
            "priority": "HIGH",
        },
        headers=headers,
    )
    case_id = case.json()["id"]

    await client.post(
        "/api/v1/cases/{case_id}/actions".format(case_id=case_id),
        json={
            "action_type": "CUSTOMER_CONTACTED",
            "action_date": date.today().isoformat(),
            "notes": "Called customer",
        },
        headers=headers,
    )

    for amount in ["300.00", "250.00", "450.00"]:
        await client.post(
            "/api/v1/payments/",
            json={
                "invoice_id": invoice_id,
                "amount": amount,
                "payment_date": date.today().isoformat(),
                "reference": f"PAY-{amount}",
            },
            headers=headers,
        )

    await client.post(
        "/api/v1/cases/{case_id}/promises/".format(case_id=case_id),
        json={
            "promise_date": str(date.today() + timedelta(days=10)),
            "promised_amount": "250.00",
            "notes": "Pending promise",
        },
        headers=headers,
    )

    return {"headers": headers, "case_id": case_id, "org_id": data["organization_id"]}


@pytest.mark.asyncio
async def test_dashboard_summary_returns_expected_org_metrics(client: AsyncClient, dashboard_context):
    resp = await client.get("/api/v1/recovery/dashboard", headers=dashboard_context["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["cases"]["total"] >= 1
    assert body["cases"]["active"] >= 1
    assert body["financial"]["total_recovered"] == "1000.00"
    assert body["financial"]["total_outstanding"] == "0.00"
    assert body["promises"]["pending"] >= 1
    assert body["activity"]["actions_count"] >= 1


@pytest.mark.asyncio
async def test_dashboard_empty_org_returns_zero_metrics(client: AsyncClient):
    data = await register_user(
        client,
        f"empty_dashboard_{uuid.uuid4().hex[:8]}@test.com",
        "securepass123",
        "Empty Dashboard",
        f"EmptyOrg-{uuid.uuid4().hex[:8]}",
    )
    headers = {
        "Authorization": f"Bearer {data['access_token']}",
        "X-Organization-Id": data["organization_id"],
    }

    resp = await client.get("/api/v1/recovery/dashboard", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cases"]["total"] == 0
    assert body["financial"]["total_amount_in_recovery"] == "0.00"
    assert body["financial"]["total_recovered"] == "0.00"
    assert body["promises"]["pending"] == 0
    assert body["activity"]["actions_count"] == 0


@pytest.mark.asyncio
async def test_dashboard_is_tenant_scoped(client: AsyncClient):
    org_a = await register_user(
        client,
        f"tenantA_{uuid.uuid4().hex[:8]}@test.com",
        "securepass123",
        "Tenant A Org",
        f"TenantA-{uuid.uuid4().hex[:8]}",
    )
    headers_a = {
        "Authorization": f"Bearer {org_a['access_token']}",
        "X-Organization-Id": org_a["organization_id"],
    }
    customer_a = await client.post(
        "/api/v1/customers/",
        json={"name": "Customer A", "email": "customer-a@example.com"},
        headers=headers_a,
    )
    invoice_a = await client.post(
        "/api/v1/invoices/",
        json={
            "customer_id": customer_a.json()["id"],
            "invoice_number": f"A-{uuid.uuid4().hex[:6]}",
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=20)),
            "total_amount": "500.00",
        },
        headers=headers_a,
    )
    await client.post(
        "/api/v1/cases/",
        json={
            "customer_id": customer_a.json()["id"],
            "invoice_id": invoice_a.json()["id"],
            "case_number": f"A-{uuid.uuid4().hex[:6]}",
            "title": "Case A",
            "status": "OPEN",
        },
        headers=headers_a,
    )

    org_b = await register_user(
        client,
        f"tenantB_{uuid.uuid4().hex[:8]}@test.com",
        "securepass123",
        "Tenant B Org",
        f"TenantB-{uuid.uuid4().hex[:8]}",
    )
    headers_b = {
        "Authorization": f"Bearer {org_b['access_token']}",
        "X-Organization-Id": org_b["organization_id"],
    }
    customer_b = await client.post(
        "/api/v1/customers/",
        json={"name": "Customer B", "email": "customer-b@example.com"},
        headers=headers_b,
    )
    invoice_b = await client.post(
        "/api/v1/invoices/",
        json={
            "customer_id": customer_b.json()["id"],
            "invoice_number": f"B-{uuid.uuid4().hex[:6]}",
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=20)),
            "total_amount": "900.00",
        },
        headers=headers_b,
    )
    await client.post(
        "/api/v1/cases/",
        json={
            "customer_id": customer_b.json()["id"],
            "invoice_id": invoice_b.json()["id"],
            "case_number": f"B-{uuid.uuid4().hex[:6]}",
            "title": "Case B",
            "status": "OPEN",
        },
        headers=headers_b,
    )

    a_resp = await client.get("/api/v1/recovery/dashboard", headers=headers_a)
    b_resp = await client.get("/api/v1/recovery/dashboard", headers=headers_b)

    assert a_resp.status_code == 200
    assert b_resp.status_code == 200
    assert a_resp.json()["cases"]["total"] == 1
    assert b_resp.json()["cases"]["total"] == 1
    assert a_resp.json()["financial"]["total_recovered"] == "0.00"
    assert b_resp.json()["financial"]["total_recovered"] == "0.00"


@pytest.mark.asyncio
async def test_dashboard_activity_is_org_scoped(client: AsyncClient):
    data = await register_user(
        client,
        f"activity_dash_{uuid.uuid4().hex[:8]}@test.com",
        "securepass123",
        "Activity Dash",
        f"ActivityOrg-{uuid.uuid4().hex[:8]}",
    )
    headers = {
        "Authorization": f"Bearer {data['access_token']}",
        "X-Organization-Id": data["organization_id"],
    }
    customer = await client.post(
        "/api/v1/customers/",
        json={"name": "Activity Customer", "email": "activity@example.com"},
        headers=headers,
    )
    invoice = await client.post(
        "/api/v1/invoices/",
        json={
            "customer_id": customer.json()["id"],
            "invoice_number": f"ACT-{uuid.uuid4().hex[:6]}",
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=20)),
            "total_amount": "350.00",
        },
        headers=headers,
    )
    case = await client.post(
        "/api/v1/cases/",
        json={
            "customer_id": customer.json()["id"],
            "invoice_id": invoice.json()["id"],
            "case_number": f"ACT-{uuid.uuid4().hex[:6]}",
            "title": "Activity Case",
            "status": "OPEN",
        },
        headers=headers,
    )
    await client.post(
        f"/api/v1/cases/{case.json()['id']}/actions",
        json={
            "action_type": "EMAIL_SENT",
            "action_date": date.today().isoformat(),
            "notes": "Email sent",
        },
        headers=headers,
    )

    summary = await client.get("/api/v1/recovery/dashboard", headers=headers)
    activity = await client.get("/api/v1/recovery/dashboard/activity", headers=headers)
    assert summary.status_code == 200
    assert activity.status_code == 200
    assert summary.json()["activity"]["actions_count"] >= 1
    assert len(activity.json()) >= 1
    assert all(item["action"] for item in activity.json())
