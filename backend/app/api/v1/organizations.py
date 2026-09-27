import re
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User
from app.models.organization import Organization, OrganizationMember, MemberRole
from app.schemas.organization import (
    OrganizationRead,
    OrganizationCreate,
    MemberRead,
    MemberInvite,
)
from app.api.deps import get_current_user, get_current_tenant, TenantContext
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/organizations", tags=["Organizations"])


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[-\s]+", "-", slug)


@router.get("/", response_model=List[OrganizationRead])
async def list_user_organizations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user.id)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base_slug = payload.slug or slugify(payload.name)
    slug = base_slug
    counter = 1
    while True:
        existing = await db.execute(select(Organization).where(Organization.slug == slug))
        if not existing.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    org = Organization(name=payload.name, slug=slug)
    db.add(org)
    await db.flush()

    membership = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=MemberRole.OWNER,
    )
    db.add(membership)

    await log_audit_event(
        db,
        organization_id=org.id,
        user_id=user.id,
        action="ORGANIZATION_CREATED",
        entity_type="Organization",
        entity_id=org.id,
        details={"name": org.name, "slug": org.slug},
    )

    await db.commit()
    await db.refresh(org)
    return org


@router.get("/members", response_model=List[MemberRead])
async def list_members(
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(OrganizationMember)
        .where(OrganizationMember.organization_id == tenant.organization_id)
        .options(selectinload(OrganizationMember.user))
    )
    result = await db.execute(stmt)
    members = result.scalars().all()
    return [
        MemberRead(
            id=m.id,
            user_id=m.user_id,
            email=m.user.email,
            full_name=m.user.full_name,
            role=m.role,
            created_at=m.created_at,
        )
        for m in members
    ]


@router.post("/members", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def add_member(
    payload: MemberInvite,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Only OWNER or ADMIN can add members
    if tenant.membership.role not in [MemberRole.OWNER, MemberRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization owners and admins can invite members",
        )

    # Check if target user exists
    user_res = await db.execute(select(User).where(User.email == payload.email.lower()))
    target_user = user_res.scalar_one_or_none()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target user not found with specified email",
        )

    # Check if already member
    existing_mem = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == tenant.organization_id,
            OrganizationMember.user_id == target_user.id,
        )
    )
    if existing_mem.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this organization",
        )

    new_mem = OrganizationMember(
        organization_id=tenant.organization_id,
        user_id=target_user.id,
        role=payload.role,
    )
    db.add(new_mem)

    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="MEMBER_ADDED",
        entity_type="OrganizationMember",
        entity_id=target_user.id,
        details={"role": payload.role, "email": target_user.email},
    )

    await db.commit()
    await db.refresh(new_mem)

    return MemberRead(
        id=new_mem.id,
        user_id=target_user.id,
        email=target_user.email,
        full_name=target_user.full_name,
        role=new_mem.role,
        created_at=new_mem.created_at,
    )
