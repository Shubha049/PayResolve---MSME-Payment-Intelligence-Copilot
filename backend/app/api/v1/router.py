from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.organizations import router as org_router
from app.api.v1.customers import router as customer_router
from app.api.v1.invoices import router as invoice_router
from app.api.v1.cases import router as case_router
from app.api.v1.dashboard import recovery_router as recovery_dashboard_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.documents import router as document_router
from app.api.v1.copilot import router as copilot_router
from app.api.v1.risk import router as risk_router
from app.api.v1.payments import router as payment_router
from app.api.v1.promises import router as promise_router
from app.api.v1.recovery_actions import router as recovery_action_router
from app.api.v1.recovery_automation import router as recovery_automation_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(org_router)
api_router.include_router(customer_router)
api_router.include_router(invoice_router)
api_router.include_router(case_router)
api_router.include_router(dashboard_router)
api_router.include_router(recovery_dashboard_router)
api_router.include_router(document_router)
api_router.include_router(copilot_router)
api_router.include_router(risk_router)
api_router.include_router(payment_router, prefix="/payments", tags=["payments"])
api_router.include_router(promise_router, prefix="", tags=["promises"])
api_router.include_router(recovery_action_router, prefix="", tags=["recovery-actions"])
api_router.include_router(recovery_automation_router)
