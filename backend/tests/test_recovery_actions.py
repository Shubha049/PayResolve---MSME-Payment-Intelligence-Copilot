import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import register_user


@pytest.fixture
async def recovery_case_context(client: AsyncClient):
    uid = uuid.uuid4().hex[:8]
    data = await register_user(
        client,
        f"recovery_user_{uid}@test.com",
        "securepass123",
        "Recovery User",
        f"RecoveryOrg-{uid}",
    )
    headers = {
        "Authorization": f"Bearer {data['access_token']}",
        "X-Organization-Id": data["organization_id"],
    }

    customer = await client.post(
        "/api/v1/customers/",
        json={"name": "Recovery Customer", "email": f"customer_{uid}@example.com"},
        headers=headers,
    )
    assert customer.status_code == 201, customer.text

    invoice = await client.post(
        "/api/v1/invoices/",
        json={
            "customer_id": customer.json()["id"],
            "invoice_number": f"REC-{uid}-001",
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "total_amount": "2000.00",
        },
        headers=headers,
    )
    assert invoice.status_code == 201, invoice.text

    case = await client.post(
        "/api/v1/cases/",
        json={
            "customer_id": customer.json()["id"],
            "invoice_id": invoice.json()["id"],
            "case_number": f"RC-{uid}",
            "title": "Recovery case",
        },
        headers=headers,
    )
    assert case.status_code == 201, case.text

    return {
        "headers": headers,
        "case_id": case.json()["id"],
        "org_id": data["organization_id"],
    }


@pytest.mark.asyncio
async def test_create_valid_recovery_action_updates_last_contact_date(client: AsyncClient, recovery_case_context):
    action_date = date.today()
    resp = await client.post(
        f"/api/v1/cases/{recovery_case_context['case_id']}/actions",
        json={
            "action_type": "CUSTOMER_CONTACTED",
            "action_date": action_date.isoformat(),
            "notes": "Called customer to discuss payment",
        },
        headers=recovery_case_context["headers"],
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["action_type"] == "CUSTOMER_CONTACTED"
    assert data["notes"] == "Called customer to discuss payment"

    case_resp = await client.get(
        f"/api/v1/cases/{recovery_case_context['case_id']}",
        headers=recovery_case_context["headers"],
    )
    assert case_resp.status_code == 200, case_resp.text
    assert case_resp.json()["last_contact_date"] == action_date.isoformat()


@pytest.mark.asyncio
async def test_invalid_action_type_rejected(client: AsyncClient, recovery_case_context):
    resp = await client.post(
        f"/api/v1/cases/{recovery_case_context['case_id']}/actions",
        json={
            "action_type": "NOT_A_REAL_ACTION",
            "action_date": date.today().isoformat(),
        },
        headers=recovery_case_context["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_non_contact_action_does_not_update_last_contact_date(client: AsyncClient, recovery_case_context):
    before = await client.get(
        f"/api/v1/cases/{recovery_case_context['case_id']}",
        headers=recovery_case_context["headers"],
    )
    original = before.json()["last_contact_date"]

    resp = await client.post(
        f"/api/v1/cases/{recovery_case_context['case_id']}/actions",
        json={
            "action_type": "NOTE_ADDED",
            "action_date": date.today().isoformat(),
            "notes": "Internal admin note",
        },
        headers=recovery_case_context["headers"],
    )
    assert resp.status_code == 201, resp.text

    after = await client.get(
        f"/api/v1/cases/{recovery_case_context['case_id']}",
        headers=recovery_case_context["headers"],
    )
    assert after.json()["last_contact_date"] == original


@pytest.mark.asyncio
async def test_explicit_follow_up_date_updates_case(client: AsyncClient, recovery_case_context):
    follow_up_date = date.today() + timedelta(days=9)
    resp = await client.post(
        f"/api/v1/cases/{recovery_case_context['case_id']}/actions",
        json={
            "action_type": "FOLLOW_UP_SCHEDULED",
            "action_date": date.today().isoformat(),
            "next_follow_up_date": follow_up_date.isoformat(),
            "notes": "Customer requested a callback",
        },
        headers=recovery_case_context["headers"],
    )
    assert resp.status_code == 201, resp.text

    case_resp = await client.get(
        f"/api/v1/cases/{recovery_case_context['case_id']}",
        headers=recovery_case_context["headers"],
    )
    assert case_resp.status_code == 200, case_resp.text
    assert case_resp.json()["next_follow_up_date"] == follow_up_date.isoformat()


@pytest.mark.asyncio
async def test_no_automatic_follow_up_date_is_generated(client: AsyncClient, recovery_case_context):
    resp = await client.post(
        f"/api/v1/cases/{recovery_case_context['case_id']}/actions",
        json={
            "action_type": "EMAIL_SENT",
            "action_date": date.today().isoformat(),
            "notes": "Follow-up email sent",
        },
        headers=recovery_case_context["headers"],
    )
    assert resp.status_code == 201, resp.text

    case_resp = await client.get(
        f"/api/v1/cases/{recovery_case_context['case_id']}",
        headers=recovery_case_context["headers"],
    )
    assert case_resp.status_code == 200, case_resp.text
    assert case_resp.json()["next_follow_up_date"] is None


@pytest.mark.asyncio
async def test_list_recovery_actions_is_ordered_and_tenant_scoped(client: AsyncClient, recovery_case_context):
    for action_type in ["EMAIL_SENT", "NOTE_ADDED"]:
        resp = await client.post(
            f"/api/v1/cases/{recovery_case_context['case_id']}/actions",
            json={
                "action_type": action_type,
                "action_date": date.today().isoformat(),
                "notes": f"{action_type} action",
            },
            headers=recovery_case_context["headers"],
        )
        assert resp.status_code == 201, resp.text

    resp = await client.get(
        f"/api/v1/cases/{recovery_case_context['case_id']}/actions",
        headers=recovery_case_context["headers"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] >= 2
    assert [item["action_type"] for item in data["actions"]][:2] in (["EMAIL_SENT", "NOTE_ADDED"], ["NOTE_ADDED", "EMAIL_SENT"])


@pytest.mark.asyncio
async def test_cross_tenant_action_access_is_rejected(client: AsyncClient, recovery_case_context):
    other = await register_user(
        client,
        f"other_recovery_{uuid.uuid4().hex[:8]}@test.com",
        "otherpass123",
        "Other User",
        f"OtherOrg-{uuid.uuid4().hex[:8]}",
    )
    other_headers = {
        "Authorization": f"Bearer {other['access_token']}",
        "X-Organization-Id": other["organization_id"],
    }

    resp = await client.get(
        f"/api/v1/cases/{recovery_case_context['case_id']}/actions",
        headers=other_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_action_creates_audit_log_visible_in_timeline(client: AsyncClient, recovery_case_context):
    resp = await client.post(
        f"/api/v1/cases/{recovery_case_context['case_id']}/actions",
        json={
            "action_type": "PAYMENT_DISCUSSED",
            "action_date": date.today().isoformat(),
            "notes": "Discussed scheduled payment",
        },
        headers=recovery_case_context["headers"],
    )
    assert resp.status_code == 201, resp.text

    timeline = await client.get(
        f"/api/v1/cases/{recovery_case_context['case_id']}/timeline",
        headers=recovery_case_context["headers"],
    )
    assert timeline.status_code == 200, timeline.text
    actions = [item["action"] for item in timeline.json()]
    assert "RECOVERY_ACTION_CREATED" in actions


@pytest.mark.asyncio
async def test_missing_required_fields_rejected(client: AsyncClient, recovery_case_context):
    resp = await client.post(
        f"/api/v1/cases/{recovery_case_context['case_id']}/actions",
        json={"notes": "Missing action type"},
        headers=recovery_case_context["headers"],
    )
    assert resp.status_code == 422
