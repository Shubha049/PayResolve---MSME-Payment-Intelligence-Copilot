import asyncio
import os
import tempfile
from pathlib import Path
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.database import Base, get_db

# Keep the transient SQLite database outside synced workspace folders on Windows.
TEST_DATABASE_PATH = Path(tempfile.gettempdir()) / f"payresolve-tests-{os.getpid()}.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DATABASE_PATH.as_posix()}"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)

import app.database as db_module
db_module.async_session_factory = TestSessionLocal


@pytest_asyncio.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_database():
    """Create all tables before each test, drop them after - ensures test isolation."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture()
async def db_session():
    """Provide a DB session for tests."""
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture()
async def client(db_session):
    """Provide an HTTPX AsyncClient with the test DB wired in."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# --- Shared helper to register + login a user ---
async def register_user(client: AsyncClient, email: str, password: str, name: str, org: str) -> dict:
    resp = await client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": name,
        "organization_name": org,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


async def login_user(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# --- Risk test fixtures ---
from app.models.organization import Organization
from app.models.user import User
from app.models.customer import Customer
from app.services.auth_service import get_password_hash


@pytest_asyncio.fixture()
async def org(db_session):
    """Create a test organization with unique slug."""
    import uuid
    slug = f"test-org-risk-{uuid.uuid4().hex[:8]}"
    org = Organization(name="Test Org Risk", slug=slug)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture()
async def org2(db_session):
    """Create a second test organization for isolation tests."""
    import uuid
    slug = f"test-org-risk-2-{uuid.uuid4().hex[:8]}"
    org = Organization(name="Test Org Risk 2", slug=slug)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture()
async def user(db_session, org):
    """Create a test user linked to org via OrganizationMember."""
    from app.models.organization import OrganizationMember
    user = User(
        email="riskuser@test.com",
        full_name="Risk User",
        hashed_password=get_password_hash("testpass123"),
    )
    db_session.add(user)
    await db_session.flush()
    
    # Create membership
    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role="ADMIN",
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture()
async def user2(db_session, org2):
    """Create a test user for second org."""
    from app.models.organization import OrganizationMember
    user = User(
        email="riskuser2@test.com",
        full_name="Risk User 2",
        hashed_password=get_password_hash("testpass123"),
    )
    db_session.add(user)
    await db_session.flush()
    
    # Create membership
    member = OrganizationMember(
        organization_id=org2.id,
        user_id=user.id,
        role="ADMIN",
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture()
async def customer(db_session, org):
    """Create a test customer."""
    customer = Customer(
        organization_id=org.id,
        name="Test Customer Risk",
        email="customer@test.com",
    )
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)
    return customer


@pytest_asyncio.fixture()
async def auth_headers(user, org):
    """Generate auth headers for user."""
    from app.services.auth_service import create_access_token
    token = create_access_token(subject=user.id, organization_id=org.id)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture()
async def auth_headers2(user2, org2):
    """Generate auth headers for user2."""
    from app.services.auth_service import create_access_token
    token = create_access_token(subject=user2.id, organization_id=org2.id)
    return {"Authorization": f"Bearer {token}"}
