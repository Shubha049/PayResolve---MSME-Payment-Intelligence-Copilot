import pytest
from httpx import AsyncClient

from app.config import Settings
from app.services.document_service import DocumentValidationError, validate_upload
from app.services.rate_limit import FixedWindowRateLimiter


def test_production_requires_configured_secret():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(ENVIRONMENT="production", SECRET_KEY="too-short")


def test_upload_rejects_mismatched_content_type():
    with pytest.raises(DocumentValidationError, match="content type"):
        validate_upload("invoice.pdf", "text/plain", b"not-a-real-pdf")


def test_rate_limiter_returns_retryable_http_error():
    limiter = FixedWindowRateLimiter(limit=1)
    limiter.check("test-client")
    with pytest.raises(Exception) as error:
        limiter.check("test-client")
    assert getattr(error.value, "status_code", None) == 429


@pytest.mark.asyncio
async def test_health_is_public_and_protected_api_rejects_anonymous(client: AsyncClient):
    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"

    response = await client.get("/api/v1/customers/")
    assert response.status_code == 401
    assert "traceback" not in response.text.lower()