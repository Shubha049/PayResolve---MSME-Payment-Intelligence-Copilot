from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.api.v1.router import api_router
import app.models  # Ensures all models are registered on Base.metadata


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables for development if needed (Alembic also handles this)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="PayResolve AI API",
    description=(
        "MSME Payment Intelligence Copilot API. "
        "NOTICE: PayResolve AI is an automated document-intelligence and workflow assistant, "
        "not a legal advisor. No communications or assessments generated constitute formal legal advice "
        "or guarantee debt recovery."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include v1 API
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "disclaimer": "PayResolve AI is a payment intelligence assistant, not legal counsel.",
    }


@app.get("/", tags=["System"])
async def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": "1.0.0",
        "docs": "/docs",
        "disclaimer": "Document intelligence and recovery workflow copilot for MSMEs.",
    }
