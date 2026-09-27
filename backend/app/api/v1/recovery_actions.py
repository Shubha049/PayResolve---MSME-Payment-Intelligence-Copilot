from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant, TenantContext
from app.database import get_db
from app.models.audit import AuditLog
from app.models.case import Case
from app.models.recovery_action import RecoveryAction, RecoveryActionType
from app.schemas.recovery_action import RecoveryActionCreate, RecoveryActionListResponse, RecoveryActionRead
from app.services.audit_service import log_audit_event

router = APIRouter()

CONTACT_ACTION_TYPES = {
    RecoveryActionType.CUSTOMER_CONTACTED,
    RecoveryActionType.EMAIL_SENT,
    RecoveryActionType.REMINDER_SENT,
    RecoveryActionType.PAYMENT_DISCUSSED,
}


async def _get_case_for_tenant(case_id: str, tenant: TenantContext, db: AsyncSession) -> Case:
    stmt = select(Case).where(
        Case.id == case_id,
        Case.organization_id == tenant.organization_id,
    )
    case = (await db.execute(stmt)).scalar_one_or_none()
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found or does not belong to your organization",
        )
    return case


@router.post(
    "/cases/{case_id}/actions",
    response_model=RecoveryActionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_recovery_action(
    case_id: str,
    payload: RecoveryActionCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    case = await _get_case_for_tenant(case_id, tenant, db)

    action_type = payload.action_type
    if action_type not in RecoveryActionType:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid action type")

    action = RecoveryAction(
        organization_id=tenant.organization_id,
        case_id=case.id,
        created_by_user_id=tenant.user.id,
        action_type=action_type,
        action_date=payload.action_date,
        notes=payload.notes,
        next_follow_up_date=payload.next_follow_up_date,
    )
    db.add(action)
    await db.flush()

    if action_type in CONTACT_ACTION_TYPES:
        case.last_contact_date = payload.action_date

    if payload.next_follow_up_date is not None:
        case.next_follow_up_date = payload.next_follow_up_date

    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="RECOVERY_ACTION_CREATED",
        entity_type="RecoveryAction",
        entity_id=action.id,
        details={
            "case_id": case.id,
            "action_id": action.id,
            "action_type": action_type.value,
            "action_date": payload.action_date.isoformat(),
            "notes": payload.notes,
            "next_follow_up_date": payload.next_follow_up_date.isoformat() if payload.next_follow_up_date else None,
        },
    )

    await db.commit()
    await db.refresh(action)
    return action


@router.get("/cases/{case_id}/actions", response_model=RecoveryActionListResponse)
async def list_recovery_actions(
    case_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    await _get_case_for_tenant(case_id, tenant, db)

    stmt = (
        select(RecoveryAction)
        .where(
            RecoveryAction.case_id == case_id,
            RecoveryAction.organization_id == tenant.organization_id,
        )
        .order_by(RecoveryAction.action_date.desc(), RecoveryAction.created_at.desc(), RecoveryAction.id.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    actions = list(result.scalars().all())
    total_stmt = select(RecoveryAction).where(
        RecoveryAction.case_id == case_id,
        RecoveryAction.organization_id == tenant.organization_id,
    )
    total = len((await db.execute(total_stmt)).scalars().all())
    return RecoveryActionListResponse(actions=actions, total=total)


@router.get("/cases/{case_id}/timeline")
async def get_case_timeline(
    case_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    case = await _get_case_for_tenant(case_id, tenant, db)

    buffered: list[AuditLog] = []

    case_logs = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.organization_id == tenant.organization_id,
                AuditLog.entity_type == "Case",
                AuditLog.entity_id == case_id,
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        )
    ).scalars().all()
    buffered.extend(case_logs)

    for audit_kind in ["RecoveryAction", "PromiseToPay", "Payment", "Invoice"]:
        logs = (
            await db.execute(
                select(AuditLog)
                .where(
                    AuditLog.organization_id == tenant.organization_id,
                    AuditLog.entity_type == audit_kind,
                )
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            )
        ).scalars().all()
        for log in logs:
            details = log.details or {}
            if audit_kind == "RecoveryAction" and details.get("case_id") == case_id:
                buffered.append(log)
            elif audit_kind == "PromiseToPay" and details.get("case_id") == case_id:
                buffered.append(log)
            elif audit_kind == "Payment" and details.get("invoice_id") == case.invoice_id:
                buffered.append(log)
            elif audit_kind == "Invoice" and log.entity_id == case.invoice_id:
                buffered.append(log)

    unique: list[AuditLog] = []
    seen: set[str] = set()
    for log in buffered:
        if log.id not in seen:
            unique.append(log)
            seen.add(log.id)

    unique.sort(key=lambda item: (item.created_at, item.id), reverse=True)
    return [
        {
            "id": entry.id,
            "action": entry.action,
            "timestamp": entry.created_at.isoformat(),
            "user_id": entry.user_id,
            "entity_type": entry.entity_type,
            "entity_id": entry.entity_id,
            "details": entry.details,
            "created_at": entry.created_at.isoformat(),
        }
        for entry in unique
    ]
