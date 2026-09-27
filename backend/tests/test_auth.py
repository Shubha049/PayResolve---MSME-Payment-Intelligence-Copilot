import pytest
from httpx import AsyncClient
from tests.conftest import register_user, login_user


@pytest.mark.asyncio
async def test_register_creates_user_org_and_membership(client: AsyncClient):
    """Registration creates a user, an org, and OWNER membership."""
    data = await register_user(
        client, "alice@example.com", "SecurePass1!", "Alice", "Alice Corp"
    )
    assert data["email"] == "alice@example.com"
    assert data["full_name"] == "Alice"
    assert "access_token" in data
    assert "organization_id" in data
    assert data["organization_id"] != ""


@pytest.mark.asyncio
async def test_register_duplicate_email_fails(client: AsyncClient):
    """Registering the same email twice returns 400."""
    await register_user(client, "bob@example.com", "pass123", "Bob", "Bob Ltd")
    resp = await client.post("/api/v1/auth/register", json={
        "email": "bob@example.com",
        "password": "different",
        "full_name": "Bob2",
        "organization_name": "Bob Ltd 2",
    })
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_with_valid_credentials(client: AsyncClient):
    """Login with correct credentials returns a valid JWT."""
    await register_user(client, "carol@example.com", "password!", "Carol", "Carol Inc")
    resp = await client.post("/api/v1/auth/login", json={
        "email": "carol@example.com",
        "password": "password!",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["email"] == "carol@example.com"


@pytest.mark.asyncio
async def test_login_with_invalid_password_returns_401(client: AsyncClient):
    """Login with wrong password returns 401."""
    await register_user(client, "dave@example.com", "correct_pass", "Dave", "Dave Co")
    resp = await client.post("/api/v1/auth/login", json={
        "email": "dave@example.com",
        "password": "wrong_pass",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_with_nonexistent_email_returns_401(client: AsyncClient):
    """Login with unknown email returns 401."""
    resp = await client.post("/api/v1/auth/login", json={
        "email": "nobody@example.com",
        "password": "whatever",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me_with_valid_token(client: AsyncClient):
    """GET /me returns the authenticated user profile."""
    await register_user(client, "eve@example.com", "pass456", "Eve", "Eve Org")
    token = await login_user(client, "eve@example.com", "pass456")
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "eve@example.com"


@pytest.mark.asyncio
async def test_get_me_without_token_returns_401(client: AsyncClient):
    """GET /me without auth header returns 401."""
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me_with_malformed_token_returns_401(client: AsyncClient):
    """GET /me with a fake token returns 401."""
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer this.is.not.valid"},
    )
    assert resp.status_code == 401
