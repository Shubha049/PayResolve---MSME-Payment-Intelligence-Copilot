from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from app.models.recovery_action import RecoveryActionType


class RecoveryActionBase(BaseModel):
    action_type: RecoveryActionType
    action_date: date
    notes: Optional[str] = None
    next_follow_up_date: Optional[date] = None


class RecoveryActionCreate(RecoveryActionBase):
    pass


class RecoveryActionRead(RecoveryActionBase):
    id: str
    case_id: str
    organization_id: str
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecoveryActionListResponse(BaseModel):
    actions: list[RecoveryActionRead]
    total: int


class AuditLogRead(BaseModel):
    id: str
    organization_id: str
    user_id: Optional[str] = None
    action: str
    entity_type: str
    entity_id: str
    details: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
