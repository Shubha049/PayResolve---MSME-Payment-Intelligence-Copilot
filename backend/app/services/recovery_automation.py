from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case, CaseStatus
from app.models.promise import PromiseStatus, PromiseToPay
from app.models.recovery_action import RecoveryAction, RecoveryActionType
from app.services.audit_service import log_audit_event


class RecoveryAutomationService:
    @staticmethod
    async def run_for_organization(
        db: AsyncSession,
        organization_id: str,
        user_id: str,
        today: date | None = None,
    ) -> dict[str, int]:
        run_date = today or date.today()
        candidates: list[tuple[str, str, RecoveryActionType, str]] = []

        overdue_promises = (
            await db.execute(
                select(PromiseToPay)
                .join(Case, Case.id == PromiseToPay.case_id)
                .where(
                    PromiseToPay.organization_id == organization_id,
                    Case.organization_id == organization_id,
                    PromiseToPay.status == PromiseStatus.PENDING,
                    PromiseToPay.promise_date < run_date,
                )
            )
        ).scalars().all()
        for promise in overdue_promises:
            candidates.append((
                promise.case_id,
                f"promise-overdue:{promise.id}",
                RecoveryActionType.PROMISE_OVERDUE,
                f"Pending promise {promise.id} was overdue as of {run_date.isoformat()}.",
            ))

        due_cases = (
            await db.execute(
                select(Case).where(
                    Case.organization_id == organization_id,
                    Case.status.notin_([CaseStatus.RESOLVED, CaseStatus.CLOSED]),
                    Case.next_follow_up_date <= run_date,
                )
            )
        ).scalars().all()
        for case in due_cases:
            candidates.append((
                case.id,
                f"follow-up-due:{case.id}:{case.next_follow_up_date.isoformat()}",
                RecoveryActionType.FOLLOW_UP_DUE,
                f"Follow-up due date {case.next_follow_up_date.isoformat()} has arrived.",
            ))

        broken_promises = (
            await db.execute(
                select(PromiseToPay)
                .join(Case, Case.id == PromiseToPay.case_id)
                .where(
                    PromiseToPay.organization_id == organization_id,
                    Case.organization_id == organization_id,
                    PromiseToPay.status == PromiseStatus.BROKEN,
                )
            )
        ).scalars().all()
        for promise in broken_promises:
            candidates.append((
                promise.case_id,
                f"broken-promise-attention:{promise.id}",
                RecoveryActionType.BROKEN_PROMISE_ATTENTION,
                f"Broken promise {promise.id} requires recovery attention.",
            ))

        if not candidates:
            return {
                "created_count": 0,
                "promise_overdue": 0,
                "follow_up_due": 0,
                "broken_promise_attention": 0,
            }

        keys = [candidate[1] for candidate in candidates]
        existing_keys = set(
            (
                await db.execute(
                    select(RecoveryAction.idempotency_key).where(
                        RecoveryAction.organization_id == organization_id,
                        RecoveryAction.idempotency_key.in_(keys),
                    )
                )
            ).scalars().all()
        )

        created = {
            RecoveryActionType.PROMISE_OVERDUE: 0,
            RecoveryActionType.FOLLOW_UP_DUE: 0,
            RecoveryActionType.BROKEN_PROMISE_ATTENTION: 0,
        }
        for case_id, key, action_type, notes in candidates:
            if key in existing_keys:
                continue

            try:
                async with db.begin_nested():
                    action = RecoveryAction(
                        organization_id=organization_id,
                        case_id=case_id,
                        created_by_user_id=user_id,
                        action_type=action_type,
                        action_date=run_date,
                        notes=notes,
                        idempotency_key=key,
                    )
                    db.add(action)
                    await db.flush()
                    await log_audit_event(
                        db,
                        organization_id=organization_id,
                        user_id=user_id,
                        action="RECOVERY_AUTOMATION_ACTION_CREATED",
                        entity_type="RecoveryAction",
                        entity_id=action.id,
                        details={
                            "action_type": action_type.value,
                            "idempotency_key": key,
                            "trigger": "manual_automation_run",
                        },
                    )
                    await db.flush()
            except IntegrityError:
                # The unique idempotency index handles overlapping manual runs.
                existing_keys.add(key)
                continue

            existing_keys.add(key)
            created[action_type] += 1

        await db.commit()
        return {
            "created_count": sum(created.values()),
            "promise_overdue": created[RecoveryActionType.PROMISE_OVERDUE],
            "follow_up_due": created[RecoveryActionType.FOLLOW_UP_DUE],
            "broken_promise_attention": created[RecoveryActionType.BROKEN_PROMISE_ATTENTION],
        }
