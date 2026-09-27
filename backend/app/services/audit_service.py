from typing import Optional, Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditLog


async def log_audit_event(
    db: AsyncSession,
    organization_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> AuditLog:
    audit_entry = AuditLog(
        organization_id=organization_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
        ip_address=ip_address,
    )
    db.add(audit_entry)
    # The caller will commit with their transaction
    return audit_entry
