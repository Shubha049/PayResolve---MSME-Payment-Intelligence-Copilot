import secrets
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "PayResolve AI"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./payresolve.db"
    # In PostgreSQL docker/prod: postgresql+asyncpg://postgres:postgres@localhost:5432/payresolve

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

    # Vector Database (Qdrant)
    QDRANT_URL: str | None = None  # If None, runs in-memory / local disk embedded mode
    QDRANT_COLLECTION: str = "payresolve_document_chunks"
    QDRANT_PATH: str = "./qdrant_storage"

    # AI & Embeddings
    EMBEDDING_PROVIDER: str = "fast"  # "fast" | "openai" | "gemini"
    EMBEDDING_DIMENSION: int = 384
    LLM_PROVIDER: str = "grounded"    # "grounded" | "openai" | "gemini"
    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    def model_post_init(self, __context: object) -> None:
        if self.ENVIRONMENT.lower() in {"production", "prod"} and len(self.SECRET_KEY) < 32:
            raise ValueError("SECRET_KEY must be configured with at least 32 characters in production")


settings = Settings()
