"""
Multi-tenant isolation tests.
These are the most critical correctness tests in Phase 1.
Every assertion verifies that zero cross-tenant data leakage occurs.
"""
import pytest
from httpx import AsyncClient
from tests.conftest import register_user, login_user


async def create_customer(client: AsyncClient, token: str, org_id: str, name: str) -> dict:
    resp = await client.post(
        "/api/v1/customers/",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def create_invoice(
    client: AsyncClient, token: str, org_id: str, customer_id: str, number: str
) -> dict:
    from datetime import date, timedelta
    resp = await client.post(
        "/api/v1/invoices/",
        json={
            "customer_id": customer_id,
            "invoice_number": number,
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "total_amount": "1000.00",
        },
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": org_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_user_b_cannot_see_user_a_invoices(client: AsyncClient):
    """User B's invoice list must NOT contain User A's invoices."""
    # Setup Org A
    a = await register_user(client, "tenant_a@test.com", "passA", "TenantA", "Org Alpha")
    token_a, org_a_id = a["access_token"], a["organization_id"]
    cust_a = await create_customer(client, token_a, org_a_id, "Customer Alpha")
    inv_a = await create_invoice(client, token_a, org_a_id, cust_a["id"], "INV-ALPHA-001")

    # Setup Org B
    b = await register_user(client, "tenant_b@test.com", "passB", "TenantB", "Org Beta")
    token_b, org_b_id = b["access_token"], b["organization_id"]

    # Org B lists invoices - must be empty (0 invoices from Org A)
    resp = await client.get(
        "/api/v1/invoices/",
        headers={"Authorization": f"Bearer {token_b}", "X-Organization-Id": org_b_id},
    )
    assert resp.status_code == 200
    invoice_ids = [inv["id"] for inv in resp.json()]
    assert inv_a["id"] not in invoice_ids, "ISOLATION BREACH: Org A invoice visible to Org B!"


@pytest.mark.asyncio
async def test_user_b_cannot_fetch_user_a_invoice_by_id(client: AsyncClient):
    """Direct GET of Org A's invoice ID by Org B returns 404."""
    # Org A
    a = await register_user(client, "tenant_c@test.com", "passC", "TenantC", "Org Gamma")
    token_a, org_a_id = a["access_token"], a["organization_id"]
    cust_a = await create_customer(client, token_a, org_a_id, "Gamma Customer")
    inv_a = await create_invoice(client, token_a, org_a_id, cust_a["id"], "INV-GAMMA-001")

    # Org B
    b = await register_user(client, "tenant_d@test.com", "passD", "TenantD", "Org Delta")
    token_b, org_b_id = b["access_token"], b["organization_id"]

    resp = await client.get(
        f"/api/v1/invoices/{inv_a['id']}",
        headers={"Authorization": f"Bearer {token_b}", "X-Organization-Id": org_b_id},
    )
    assert resp.status_code == 404, f"ISOLATION BREACH: Got {resp.status_code} instead of 404!"


@pytest.mark.asyncio
async def test_user_b_cannot_modify_user_a_invoice(client: AsyncClient):
    """PATCH of Org A's invoice ID by Org B returns 404."""
    # Org A
    a = await register_user(client, "tenant_e@test.com", "passE", "TenantE", "Org Epsilon")
    token_a, org_a_id = a["access_token"], a["organization_id"]
    cust_a = await create_customer(client, token_a, org_a_id, "Epsilon Customer")
    inv_a = await create_invoice(client, token_a, org_a_id, cust_a["id"], "INV-EPS-001")

    # Org B
    b = await register_user(client, "tenant_f@test.com", "passF", "TenantF", "Org Zeta")
    token_b, org_b_id = b["access_token"], b["organization_id"]

    resp = await client.patch(
        f"/api/v1/invoices/{inv_a['id']}",
        json={"notes": "tampered by Org B"},
        headers={"Authorization": f"Bearer {token_b}", "X-Organization-Id": org_b_id},
    )
    assert resp.status_code == 404, f"ISOLATION BREACH: Got {resp.status_code} instead of 404!"


@pytest.mark.asyncio
async def test_cross_org_header_access_denied(client: AsyncClient):
    """Org A's user passing Org B's ID in header returns 403."""
    a = await register_user(client, "tenant_g@test.com", "passG", "TenantG", "Org Eta")
    token_a, org_a_id = a["access_token"], a["organization_id"]

    b = await register_user(client, "tenant_h@test.com", "passH", "TenantH", "Org Theta")
    org_b_id = b["organization_id"]

    # User A tries to access Org B's context - should be 403
    resp = await client.get(
        "/api/v1/invoices/",
        headers={"Authorization": f"Bearer {token_a}", "X-Organization-Id": org_b_id},
    )
    assert resp.status_code == 403, f"ISOLATION BREACH: Got {resp.status_code} instead of 403!"


@pytest.mark.asyncio
async def test_user_b_cannot_see_user_a_customers(client: AsyncClient):
    """Customer list isolation between organizations."""
    a = await register_user(client, "tenant_i@test.com", "passI", "TenantI", "Org Iota")
    token_a, org_a_id = a["access_token"], a["organization_id"]
    cust_a = await create_customer(client, token_a, org_a_id, "Iota Secret Customer")

    b = await register_user(client, "tenant_j@test.com", "passJ", "TenantJ", "Org Kappa")
    token_b, org_b_id = b["access_token"], b["organization_id"]

    resp = await client.get(
        "/api/v1/customers/",
        headers={"Authorization": f"Bearer {token_b}", "X-Organization-Id": org_b_id},
    )
    assert resp.status_code == 200
    customer_ids = [c["id"] for c in resp.json()]
    assert cust_a["id"] not in customer_ids, "ISOLATION BREACH: Org A customer visible to Org B!"


@pytest.mark.asyncio
async def test_user_b_cannot_delete_user_a_customer(client: AsyncClient):
    """DELETE of Org A's customer by Org B returns 404."""
    a = await register_user(client, "tenant_k@test.com", "passK", "TenantK", "Org Lambda")
    token_a, org_a_id = a["access_token"], a["organization_id"]
    cust_a = await create_customer(client, token_a, org_a_id, "Lambda Customer")

    b = await register_user(client, "tenant_l@test.com", "passL", "TenantL", "Org Mu")
    token_b, org_b_id = b["access_token"], b["organization_id"]

    resp = await client.delete(
        f"/api/v1/customers/{cust_a['id']}",
        headers={"Authorization": f"Bearer {token_b}", "X-Organization-Id": org_b_id},
    )
    assert resp.status_code == 404, f"ISOLATION BREACH: Got {resp.status_code} instead of 404!"
