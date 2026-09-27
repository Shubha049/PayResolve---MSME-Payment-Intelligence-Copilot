"""Promise-to-Pay API endpoints for recovery workflow."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.api.deps import get_db, get_current_tenant, TenantContext
from app.models.case import Case
from app.models.promise import PromiseToPay, PromiseStatus
from app.schemas.promise import PromiseCreate, PromiseUpdate, PromiseRead, PromiseListResponse
from app.services.audit_service import log_audit_event

router = APIRouter()


@router.post("/cases/{case_id}/promises/", response_model=PromiseRead, status_code=status.HTTP_201_CREATED)
async def create_promise(
    case_id: str,
    promise_in: PromiseCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new payment promise for a recovery case.
    
    Validates:
    - Case exists and belongs to the authenticated organization
    - Promise amount is positive (enforced by schema)
    - Promise date is not in the past
    
    Updates:
    - Case.expected_payment_date (if this is the earliest pending promise)
    
    Creates audit log entry.
    """
    # Validate case exists and belongs to organization
    stmt = select(Case).where(
        Case.id == case_id,
        Case.organization_id == tenant.organization_id
    )
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case {case_id} not found or does not belong to your organization"
        )
    
    # Create promise
    promise = PromiseToPay(
        organization_id=tenant.organization_id,
        case_id=case_id,
        promise_date=promise_in.promise_date,
        promised_amount=promise_in.promised_amount,
        notes=promise_in.notes,
        status=PromiseStatus.PENDING,
    )
    db.add(promise)
    await db.flush()  # Get promise.id
    
    # Update case expected_payment_date to earliest pending promise
    # Get all pending promises for this case (including the new one)
    pending_stmt = select(func.min(PromiseToPay.promise_date)).where(
        PromiseToPay.case_id == case_id,
        PromiseToPay.status == PromiseStatus.PENDING
    )
    earliest_date = await db.scalar(pending_stmt)
    case.expected_payment_date = earliest_date
    
    # Audit log for promise creation
    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="PROMISE_CREATED",
        entity_type="PromiseToPay",
        entity_id=promise.id,
        details={
            "case_id": case_id,
            "promise_date": promise_in.promise_date.isoformat(),
            "promised_amount": str(promise_in.promised_amount),
            "notes": promise_in.notes,
        }
    )
    
    # Audit log for case update (expected_payment_date changed)
    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="CASE_UPDATED",
        entity_type="Case",
        entity_id=case_id,
        details={
            "expected_payment_date": earliest_date.isoformat() if earliest_date else None,
            "reason": "promise_created"
        }
    )
    
    await db.commit()
    await db.refresh(promise)
    
    return promise


@router.get("/cases/{case_id}/promises/", response_model=PromiseListResponse)
async def list_case_promises(
    case_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    List all promises for a specific case.
    
    Returns promises in chronological order (oldest first).
    Enforces tenant isolation.
    """
    # Validate case exists and belongs to organization
    stmt = select(Case).where(
        Case.id == case_id,
        Case.organization_id == tenant.organization_id
    )
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case {case_id} not found or does not belong to your organization"
        )
    
    # Get all promises for this case
    promises_stmt = select(PromiseToPay).where(
        PromiseToPay.case_id == case_id
    ).order_by(PromiseToPay.promise_date.asc(), PromiseToPay.created_at.asc())
    
    result = await db.execute(promises_stmt)
    promises = result.scalars().all()
    
    return PromiseListResponse(promises=list(promises), total=len(promises))


@router.get("/promises/{promise_id}/", response_model=PromiseRead)
async def get_promise(
    promise_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve a single promise by ID.
    
    Enforces tenant isolation through Case relationship.
    """
    # Join through Case to enforce tenant isolation
    stmt = select(PromiseToPay).join(Case).where(
        PromiseToPay.id == promise_id,
        Case.organization_id == tenant.organization_id
    )
    result = await db.execute(stmt)
    promise = result.scalar_one_or_none()
    
    if not promise:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Promise {promise_id} not found or does not belong to your organization"
        )
    
    return promise


@router.patch("/promises/{promise_id}/", response_model=PromiseRead)
async def update_promise(
    promise_id: str,
    promise_update: PromiseUpdate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a promise.
    
    Allowed updates:
    - promise_date (must not be in the past)
    - promised_amount (must be positive)
    - notes
    - status (with validation)
    
    Status transitions:
    - PENDING → FULFILLED (when payment received)
    - PENDING → BROKEN (when promise date passed without payment)
    - PENDING → CANCELLED (when promise voided/renegotiated)
    - FULFILLED → cannot change (final state)
    - BROKEN → CANCELLED (can cancel a broken promise)
    - CANCELLED → cannot change (final state)
    
    Enforces tenant isolation.
    """
    # Join through Case to enforce tenant isolation
    stmt = select(PromiseToPay).join(Case).where(
        PromiseToPay.id == promise_id,
        Case.organization_id == tenant.organization_id
    )
    result = await db.execute(stmt)
    promise = result.scalar_one_or_none()
    
    if not promise:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Promise {promise_id} not found or does not belong to your organization"
        )
    
    # Validate status transitions
    if promise_update.status is not None and promise_update.status != promise.status:
        old_status = promise.status
        new_status = promise_update.status
        
        # Define valid transitions
        valid_transitions = {
            PromiseStatus.PENDING: {PromiseStatus.FULFILLED, PromiseStatus.BROKEN, PromiseStatus.CANCELLED},
            PromiseStatus.BROKEN: {PromiseStatus.CANCELLED},
            PromiseStatus.FULFILLED: set(),  # Final state
            PromiseStatus.CANCELLED: set(),  # Final state
        }
        
        if new_status not in valid_transitions.get(old_status, set()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status transition: {old_status} → {new_status}"
            )
    
    # Track what changed for audit
    changes = {}
    
    # Apply updates
    if promise_update.promise_date is not None:
        promise.promise_date = promise_update.promise_date
        changes["promise_date"] = promise_update.promise_date.isoformat()
    
    if promise_update.promised_amount is not None:
        promise.promised_amount = promise_update.promised_amount
        changes["promised_amount"] = str(promise_update.promised_amount)
    
    if promise_update.notes is not None:
        promise.notes = promise_update.notes
        changes["notes"] = promise_update.notes
    
    if promise_update.status is not None and promise_update.status != promise.status:
        old_status = promise.status
        promise.status = promise_update.status
        changes["status"] = f"{old_status} → {promise_update.status}"
        
        # Log status change as separate audit event
        await log_audit_event(
            db,
            organization_id=tenant.organization_id,
            user_id=tenant.user.id,
            action="PROMISE_STATUS_CHANGED",
            entity_type="PromiseToPay",
            entity_id=promise.id,
            details={
                "old_status": old_status.value,
                "new_status": promise_update.status.value,
                "case_id": promise.case_id,
            }
        )
    
    # If promise_date or status changed, update case.expected_payment_date
    if "promise_date" in changes or "status" in changes:
        # Recalculate earliest pending promise date for this case
        pending_stmt = select(func.min(PromiseToPay.promise_date)).where(
            PromiseToPay.case_id == promise.case_id,
            PromiseToPay.status == PromiseStatus.PENDING
        )
        earliest_date = await db.scalar(pending_stmt)
        
        # Get case
        case_stmt = select(Case).where(Case.id == promise.case_id)
        case_result = await db.execute(case_stmt)
        case = case_result.scalar_one()
        case.expected_payment_date = earliest_date
    
    # Audit log for promise update
    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="PROMISE_UPDATED",
        entity_type="PromiseToPay",
        entity_id=promise.id,
        details=changes
    )
    
    await db.commit()
    await db.refresh(promise)
    
    return promise
