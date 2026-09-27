from typing import Optional
from dataclasses import dataclass
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User
from app.models.organization import Organization, OrganizationMember
from app.services.auth_service import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


@dataclass
class TenantContext:
    user: User
    organization: Organization
    membership: OrganizationMember

    @property
    def organization_id(self) -> str:
        return self.organization.id


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    payload = decode_token(token)
    if payload is None:
        raise credentials_exception

    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    stmt = select(User).where(User.id == user_id, User.is_active == True)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    return user


async def get_current_tenant(
    user: User = Depends(get_current_user),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id"),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    # If no explicit organization passed in header, find the user's first org membership
    if not x_organization_id:
        stmt = (
            select(OrganizationMember)
            .where(OrganizationMember.user_id == user.id)
            .options(selectinload(OrganizationMember.organization))
            .limit(1)
        )
        res = await db.execute(stmt)
        member = res.scalar_one_or_none()
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not belong to any organization",
            )
        return TenantContext(
            user=user,
            organization=member.organization,
            membership=member,
        )

    # If organization ID specified, strictly enforce membership
    stmt = (
        select(OrganizationMember)
        .where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == x_organization_id,
        )
        .options(selectinload(OrganizationMember.organization))
    )
    res = await db.execute(stmt)
    member = res.scalar_one_or_none()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to requested organization",
        )

    return TenantContext(
        user=user,
        organization=member.organization,
        membership=member,
    )


async def get_current_org_id(
    tenant: TenantContext = Depends(get_current_tenant),
) -> str:
    """Convenience dependency: returns the active organization ID string."""
    return tenant.organization_id
