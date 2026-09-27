import re
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User
from app.models.organization import Organization, OrganizationMember, MemberRole
from app.schemas.auth import UserRegister, UserLogin, Token
from app.schemas.user import UserRead
from app.services.auth_service import verify_password, get_password_hash, create_access_token
from app.api.deps import get_current_user
from app.services.rate_limit import check_auth_rate_limit

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[-\s]+", "-", slug)


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(check_auth_rate_limit)])
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    # Check if user email already exists
    existing = await db.execute(select(User).where(User.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        )

    # Create User
    new_user = User(
        email=payload.email.lower(),
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()

    # Generate slug for organization
    base_slug = slugify(payload.organization_name)
    slug = base_slug
    counter = 1
    while True:
        existing_org = await db.execute(select(Organization).where(Organization.slug == slug))
        if not existing_org.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    # Create Organization
    org = Organization(
        name=payload.organization_name,
        slug=slug,
    )
    db.add(org)
    await db.flush()

    # Create Membership as OWNER
    membership = OrganizationMember(
        organization_id=org.id,
        user_id=new_user.id,
        role=MemberRole.OWNER,
    )
    db.add(membership)
    await db.commit()

    # Generate token
    token = create_access_token(subject=new_user.id, organization_id=org.id)

    return Token(
        access_token=token,
        token_type="bearer",
        user_id=new_user.id,
        organization_id=org.id,
        email=new_user.email,
        full_name=new_user.full_name,
    )


@router.post("/login", response_model=Token, dependencies=[Depends(check_auth_rate_limit)])
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    # Authenticate user
    stmt = (
        select(User)
        .where(User.email == payload.email.lower())
        .options(selectinload(User.memberships))
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        logger.warning("Authentication failed for supplied email")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user account",
        )

    if not user.memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have an active organization membership",
        )

    # Default to first organization
    default_org_id = user.memberships[0].organization_id
    token = create_access_token(subject=user.id, organization_id=default_org_id)

    return Token(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        organization_id=default_org_id,
        email=user.email,
        full_name=user.full_name,
    )


@router.get("/me", response_model=UserRead)
async def get_me(user: User = Depends(get_current_user)):
    return user
