# PayResolve

PayResolve is an MSME payment-intelligence and recovery workflow platform. It combines invoice and payment tracking, recovery cases, promises-to-pay, document evidence, risk assessment, and an organization-scoped Copilot.

> PayResolve AI is a document-intelligence and workflow assistant, not legal counsel. Generated assessments and responses do not constitute legal advice or guarantee debt recovery.

## Product Areas

- Dashboard recovery metrics and activity
- Multi-tenant organizations with authenticated access
- Customers, invoices, payments, and overdue tracking
- Recovery cases, timelines, actions, and promises-to-pay
- Document upload, extraction, evidence, and chunking
- Organization-scoped Qdrant retrieval and Copilot responses
- Heuristic and ML-assisted invoice risk assessment

## Stack

### Backend

- FastAPI and Uvicorn
- SQLAlchemy async sessions
- SQLite for local development, PostgreSQL-compatible configuration for production
- Alembic migrations
- JWT authentication
- Qdrant vector storage
- PyMuPDF, python-docx, Pillow/Tesseract, and OpenPyXL for document processing
- Pytest and pytest-asyncio

### Frontend

- React 19 and TypeScript
- Vite
- React Router
- Axios
- Tailwind CSS
- Lucide icons
- Oxlint

## Repository Layout

```text
backend/    FastAPI application, models, schemas, services, migrations, and tests
frontend/   React/Vite SaaS application
```

## Local Setup

### Prerequisites

- Python 3.12+
- Node.js and npm
- Optional: Tesseract OCR for image document extraction
- Optional: external Qdrant and PostgreSQL for production-style deployment

### Backend

From the repository root on Windows PowerShell:

```powershell
Set-Location .\backend
..\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
..\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The backend is available at:

- API: `http://127.0.0.1:8000`
- Swagger UI: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

For production, set a random `SECRET_KEY` of at least 32 characters and configure the database, CORS origins, Qdrant, and optional LLM provider keys through environment variables. Never commit `.env` or real credentials.

### Frontend

In a second terminal:

```powershell
Set-Location .\frontend
npm install
npm run dev -- --host=127.0.0.1
```

The frontend is available at `http://localhost:5173`.

To point the frontend at another backend, create `frontend/.env.local`:

```text
VITE_API_URL=http://127.0.0.1:8000
```

## Testing and Validation

### Backend

Run the complete backend suite with the project interpreter:

```powershell
Set-Location .\backend
..\venv\Scripts\python.exe -m pytest tests -v --tb=line
```

Current verified baseline: 123 collected, 121 passed, 2 skipped, 0 failed, and 0 errors. The skipped tests are capability-dependent ML/SHAP tests.

### Frontend

```powershell
Set-Location .\frontend
npm run lint
npm run build
```

The production build runs TypeScript checking followed by the Vite build.

## Security Model

- Protected API routes require a valid JWT.
- Organization membership is checked by the backend for the active tenant.
- Resource queries and Qdrant retrievals are organization-scoped server-side.
- The frontend does not treat organization IDs as authorization; the backend remains authoritative.
- Frontend sessions use `sessionStorage` rather than persistent `localStorage`.
- Uploads enforce allowed filenames, extensions, MIME types, size limits, and organization-specific storage paths.
- Authentication, upload, and Copilot endpoints have process-local rate limiting.
- Production secrets are supplied through environment configuration.

## Database and Migrations

Do not reset or recreate production databases. Use Alembic for schema changes:

```powershell
Set-Location .\backend
..\venv\Scripts\python.exe -m alembic upgrade head
```

Local development startup can create missing tables for convenience; production deployments should use the migration workflow.

## API Documentation

The FastAPI application exposes interactive documentation at `/docs` and OpenAPI JSON at `/openapi.json` while running.

## Phase Reports

- [Project status](PROJECT_STATUS.md)
- [Phase 8 production hardening](backend/PHASE8_COMPLETE.md)
- [Phase 9 frontend integration](PHASE9_COMPLETE.md)
- [Phase 9 UI redesign](PHASE9_UI_REDESIGN_COMPLETE.md)

## Operational Notes

- The current rate limiter is process-local and is not shared across multiple workers or hosts.
- Upload size limits should also be enforced at the reverse proxy in production.
- External LLM providers are optional; the grounded/local configuration remains the default.
- Do not commit generated databases, uploads, Qdrant storage, virtual environments, frontend dependencies, or environment files.
