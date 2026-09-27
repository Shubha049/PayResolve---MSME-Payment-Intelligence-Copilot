import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import register_user


@pytest.fixture
async def timeline_case_context(client: AsyncClient):
    uid = uuid.uuid4().hex[:8]
    data = await register_user(
        client,
        f"timeline_user_{uid}@test.com",
        "securepass123",
        "Timeline User",
        f"TimelineOrg-{uid}",
    )
    headers = {
        "Authorization": f"Bearer {data['access_token']}",
        "X-Organization-Id": data["organization_id"],
    }

    customer = await client.post(
        "/api/v1/customers/",
        json={"name": "Timeline Customer", "email": f"timeline_{uid}@example.com"},
        headers=headers,
    )
    invoice = await client.post(
        "/api/v1/invoices/",
        json={
            "customer_id": customer.json()["id"],
            "invoice_number": f"TL-{uid}-001",
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=45)),
            "total_amount": "5000.00",
        },
        headers=headers,
    )
    case = await client.post(
        "/api/v1/cases/",
        json={
            "customer_id": customer.json()["id"],
            "invoice_id": invoice.json()["id"],
            "case_number": f"TL-{uid}",
            "title": "Timeline case",
        },
        headers=headers,
    )
    return {
        "headers": headers,
        "case_id": case.json()["id"],
        "org_id": data["organization_id"],
    }


@pytest.mark.asyncio
async def test_case_timeline_returns_chronological_audit_events(client: AsyncClient, timeline_case_context):
    case_id = timeline_case_context["case_id"]
    headers = timeline_case_context["headers"]

    resp = await client.get(f"/api/v1/cases/{case_id}/timeline", headers=headers)
    assert resp.status_code == 200, resp.text
    events = resp.json()
    assert len(events) >= 1
    assert events[0]["action"] == "CASE_CREATED"

    await client.post(
        f"/api/v1/cases/{case_id}/actions",
        json={
            "action_type": "EMAIL_SENT",
            "action_date": date.today().isoformat(),
            "notes": "Reminder email sent",
        },
        headers=headers,
    )

    timeline = await client.get(f"/api/v1/cases/{case_id}/timeline", headers=headers)
    assert timeline.status_code == 200, timeline.text
    actions = [event["action"] for event in timeline.json()]
    assert "CASE_CREATED" in actions
    assert "RECOVERY_ACTION_CREATED" in actions
    assert timeline.json()[0]["created_at"] >= timeline.json()[-1]["created_at"]


@pytest.mark.asyncio
async def test_timeline_for_new_case_contains_only_case_created_event(client: AsyncClient, timeline_case_context):
    new_customer = await client.post(
        "/api/v1/customers/",
        json={"name": "Other customer", "email": "othercase@example.com"},
        headers=timeline_case_context["headers"],
    )
    new_case = await client.post(
        "/api/v1/cases/",
        json={
            "customer_id": new_customer.json()["id"],
            "case_number": f"EMPTY-{uuid.uuid4().hex[:6]}",
            "title": "Case with only creation event",
        },
        headers=timeline_case_context["headers"],
    )
    resp = await client.get(f"/api/v1/cases/{new_case.json()['id']}/timeline", headers=timeline_case_context["headers"])
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 1
    assert [event["action"] for event in events][0] == "CASE_CREATED"
    assert all(event["action"] == "CASE_CREATED" for event in events)


@pytest.mark.asyncio
async def test_cross_tenant_timeline_access_is_rejected(client: AsyncClient, timeline_case_context):
    other = await register_user(
        client,
        f"timeline_other_{uuid.uuid4().hex[:8]}@test.com",
        "otherpass123",
        "Other Timeline User",
        f"OtherTimelineOrg-{uuid.uuid4().hex[:8]}",
    )
    headers = {
        "Authorization": f"Bearer {other['access_token']}",
        "X-Organization-Id": other["organization_id"],
    }

    resp = await client.get(f"/api/v1/cases/{timeline_case_context['case_id']}/timeline", headers=headers)
    assert resp.status_code == 404
