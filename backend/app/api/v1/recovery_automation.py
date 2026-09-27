from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TenantContext, get_current_tenant
from app.database import get_db
from app.schemas.recovery_automation import RecoveryAutomationRunResult
from app.services.recovery_automation import RecoveryAutomationService


router = APIRouter(prefix="/recovery/automation", tags=["Recovery Automation"])


@router.post("/run", response_model=RecoveryAutomationRunResult)
async def run_recovery_automation(
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    return await RecoveryAutomationService.run_for_organization(
        db=db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
    )
