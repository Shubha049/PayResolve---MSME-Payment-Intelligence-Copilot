from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.case import Case, CaseStatus, CasePriority
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.schemas.case import CaseCreate, CaseUpdate, CaseRead
from app.api.deps import get_current_tenant, TenantContext
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/cases", tags=["Cases"])


@router.get("/", response_model=List[CaseRead])
async def list_cases(
    status_filter: Optional[CaseStatus] = Query(None, alias="status"),
    priority_filter: Optional[CasePriority] = Query(None, alias="priority"),
    customer_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Case)
        .where(Case.organization_id == tenant.organization_id)
        .options(
            selectinload(Case.customer),
            selectinload(Case.invoice),
            selectinload(Case.assigned_to),
        )
        .order_by(Case.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    if status_filter:
        stmt = stmt.where(Case.status == status_filter)
    if priority_filter:
        stmt = stmt.where(Case.priority == priority_filter)
    if customer_id:
        stmt = stmt.where(Case.customer_id == customer_id)

    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=CaseRead, status_code=status.HTTP_201_CREATED)
async def create_case(
    payload: CaseCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Verify customer in this org
    cust_stmt = select(Customer).where(
        Customer.id == payload.customer_id,
        Customer.organization_id == tenant.organization_id,
    )
    cust = (await db.execute(cust_stmt)).scalar_one_or_none()
    if not cust:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found in this organization",
        )

    # If invoice specified, verify it belongs to this org
    if payload.invoice_id:
        inv_stmt = select(Invoice).where(
            Invoice.id == payload.invoice_id,
            Invoice.organization_id == tenant.organization_id,
        )
        inv = (await db.execute(inv_stmt)).scalar_one_or_none()
        if not inv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invoice not found in this organization",
            )

    # Check duplicate case_number in org
    dup_stmt = select(Case).where(
        Case.organization_id == tenant.organization_id,
        Case.case_number == payload.case_number,
    )
    if (await db.execute(dup_stmt)).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Case with this number already exists",
        )

    case = Case(
        organization_id=tenant.organization_id,
        customer_id=payload.customer_id,
        invoice_id=payload.invoice_id,
        case_number=payload.case_number,
        title=payload.title,
        status=payload.status,
        priority=payload.priority,
        assigned_to_user_id=payload.assigned_to_user_id or tenant.user.id,
        summary=payload.summary,
    )
    db.add(case)
    await db.flush()

    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="CASE_CREATED",
        entity_type="Case",
        entity_id=case.id,
        details={"case_number": case.case_number, "title": case.title},
    )

    await db.commit()

    # Re-fetch with relationships
    stmt = (
        select(Case)
        .where(Case.id == case.id)
        .options(
            selectinload(Case.customer),
            selectinload(Case.invoice),
            selectinload(Case.assigned_to),
        )
    )
    return (await db.execute(stmt)).scalar_one()


@router.get("/{case_id}", response_model=CaseRead)
async def get_case(
    case_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Case)
        .where(
            Case.id == case_id,
            Case.organization_id == tenant.organization_id,
        )
        .options(
            selectinload(Case.customer),
            selectinload(Case.invoice),
            selectinload(Case.assigned_to),
        )
    )
    case = (await db.execute(stmt)).scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return case


@router.patch("/{case_id}", response_model=CaseRead)
async def update_case(
    case_id: str,
    payload: CaseUpdate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Case)
        .where(
            Case.id == case_id,
            Case.organization_id == tenant.organization_id,
        )
        .options(
            selectinload(Case.customer),
            selectinload(Case.invoice),
            selectinload(Case.assigned_to),
        )
    )
    case = (await db.execute(stmt)).scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(case, field, val)

    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="CASE_UPDATED",
        entity_type="Case",
        entity_id=case.id,
        details={k: str(v) for k, v in update_data.items()},
    )

    await db.commit()
    await db.refresh(case)
    return case


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(
    case_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Case).where(
        Case.id == case_id,
        Case.organization_id == tenant.organization_id,
    )
    case = (await db.execute(stmt)).scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="CASE_DELETED",
        entity_type="Case",
        entity_id=case.id,
        details={"case_number": case.case_number},
    )

    await db.delete(case)
    await db.commit()
    return None
