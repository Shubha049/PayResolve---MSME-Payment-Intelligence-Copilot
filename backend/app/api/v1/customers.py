from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.database import get_db
from app.models.customer import Customer
from app.schemas.customer import CustomerCreate, CustomerUpdate, CustomerRead
from app.api.deps import get_current_tenant, TenantContext
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("/", response_model=List[CustomerRead])
async def list_customers(
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Customer)
        .where(Customer.organization_id == tenant.organization_id)
        .order_by(Customer.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                Customer.name.ilike(pattern),
                Customer.tax_id.ilike(pattern),
                Customer.email.ilike(pattern),
            )
        )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Check duplicate customer name within this organization
    dup = await db.execute(
        select(Customer).where(
            Customer.organization_id == tenant.organization_id,
            Customer.name == payload.name,
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A customer with this name already exists in your organization",
        )

    customer = Customer(
        organization_id=tenant.organization_id,
        name=payload.name,
        tax_id=payload.tax_id,
        email=payload.email,
        phone=payload.phone,
        address=payload.address,
    )
    db.add(customer)
    await db.flush()

    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="CUSTOMER_CREATED",
        entity_type="Customer",
        entity_id=customer.id,
        details={"name": customer.name, "tax_id": customer.tax_id},
    )

    await db.commit()
    await db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=CustomerRead)
async def get_customer(
    customer_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Customer).where(
        Customer.id == customer_id,
        Customer.organization_id == tenant.organization_id,
    )
    result = await db.execute(stmt)
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.patch("/{customer_id}", response_model=CustomerRead)
async def update_customer(
    customer_id: str,
    payload: CustomerUpdate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Customer).where(
        Customer.id == customer_id,
        Customer.organization_id == tenant.organization_id,
    )
    result = await db.execute(stmt)
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(customer, field, val)

    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="CUSTOMER_UPDATED",
        entity_type="Customer",
        entity_id=customer.id,
        details=update_data,
    )

    await db.commit()
    await db.refresh(customer)
    return customer


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Customer).where(
        Customer.id == customer_id,
        Customer.organization_id == tenant.organization_id,
    )
    result = await db.execute(stmt)
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="CUSTOMER_DELETED",
        entity_type="Customer",
        entity_id=customer.id,
        details={"name": customer.name},
    )

    await db.delete(customer)
    await db.commit()
    return None
