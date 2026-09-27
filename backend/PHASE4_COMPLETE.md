# Phase 4 Complete: Timeline + Recovery Actions

## Files created
- app/api/v1/recovery_actions.py
- app/models/recovery_action.py
- app/schemas/recovery_action.py
- tests/test_recovery_actions.py
- tests/test_timeline.py
- alembic/versions/002_add_recovery_actions.py
- PHASE4_COMPLETE.md

## Files modified
- app/models/case.py
- app/models/__init__.py
- app/api/v1/router.py

## New endpoints
- GET /api/v1/cases/{case_id}/timeline
- POST /api/v1/cases/{case_id}/actions
- GET /api/v1/cases/{case_id}/actions

## Database / migration changes
- Added recovery_actions table via Alembic migration 002_recovery_actions.
- This is a small operational model for case recovery activities.
- No separate timeline table was created.

## Timeline architecture
- The system uses AuditLog as the timeline source of truth.
- Timeline reads case-specific and relevant org-scoped audit records, including case, payment, invoice, promise, and recovery-action events.
- Ordering is deterministic and newest-first by created_at and then id.

## Recovery Action architecture
- RecoveryAction stores a case-linked operational activity.
- Action types follow the existing enum design pattern used by the project.
- Each action includes: id, case_id, organization_id, created_by_user_id, action_type, action_date, notes, next_follow_up_date, created_at, updated_at.
- Actions are operational records only; they do not modify financial totals.

## Tenant isolation
- All timeline and action endpoints validate the target Case belongs to the authenticated organization.
- Cross-tenant access returns 404 for both case lookups and timeline retrieval.
- Audit entries are filtered by organization_id before being surfaced in the timeline.

## Audit behavior
- Recovery actions create an AuditLog entry with action = RECOVERY_ACTION_CREATED.
- The details payload includes case_id, action_id, action_type, action_date, notes, and next_follow_up_date (when supplied).
- The same audit event becomes visible in the case timeline.

## Case date-field behavior
- last_contact_date is updated only for genuine contact-type actions.
- Unrelated internal actions such as NOTE_ADDED do not update last_contact_date.
- next_follow_up_date is updated only when the action explicitly provides a future follow-up date.
- No automatic +3 day / +7 day / +14 day scheduling logic was added.
- amount_in_recovery behavior was left unchanged.

## Financial safety
- Recovery actions do not modify Payment, Invoice, or amount_in_recovery logic.
- No financial totals or payment behavior were changed.

## Promise safety
- Promise lifecycle behavior remains unchanged.
- No automatic promise fulfillment, breaking, cancellation, or payment-to-promise matching was introduced.

## Exact verification results
### Phase 4 tests
- Command: python -m pytest tests/test_recovery_actions.py tests/test_timeline.py -q --tb=line
- Result: 12 passed in 26.43s

### Phase 1-4 regression
- Command: python -m pytest tests/test_recovery_models.py tests/test_payments.py tests/test_promises.py tests/test_timeline.py tests/test_recovery_actions.py -q --tb=line
- Result: 58 passed in 163.93s

### Full suite
- Command: python -m pytest -q --tb=line
- Result: TIMEOUT after 180000 ms.
- The suite was still progressing when the timeout occurred; no final completion status was recorded.

## Known limitations
- Full suite completion was not confirmed because the overall backend suite timed out before final exit reporting.
- The implementation intentionally stays within Phase 4 scope and does not include dashboard or automation features.

## Features intentionally deferred
- Recovery dashboard / analytics
- ML / risk automation
- automatic case resolution
- automatic promise lifecycle changes
- scheduled reminders / background jobs
- email/SMS automation
- frontend UI work
- Phase 5+ functionality
