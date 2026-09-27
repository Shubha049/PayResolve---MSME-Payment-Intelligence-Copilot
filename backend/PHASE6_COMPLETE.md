# Phase 6 Complete: Recovery Automation

## Implemented features

- Added an authenticated manual trigger at `POST /api/v1/recovery/automation/run`.
- Detects `PENDING` promises with `promise_date < today` and creates `PROMISE_OVERDUE` actions. Promise status is left unchanged.
- Detects active cases with `next_follow_up_date <= today` and creates `FOLLOW_UP_DUE` actions.
- Detects `BROKEN` promises and creates `BROKEN_PROMISE_ATTENTION` actions.
- Creates an `AuditLog` event for each generated RecoveryAction. Events use action `RECOVERY_AUTOMATION_ACTION_CREATED` and entity type `RecoveryAction`.
- Every query and generated record is scoped to the authenticated organization.
- No scheduler was present in the backend, so this phase provides an explicit manual run endpoint and does not add a scheduler or external job dependency.

## Files changed

- `app/models/recovery_action.py`
- `app/services/recovery_automation.py`
- `app/schemas/recovery_automation.py`
- `app/api/v1/recovery_automation.py`
- `app/api/v1/router.py`
- `alembic/versions/003_recovery_action_idempotency.py`
- `tests/test_recovery_automation.py`
- `PHASE6_COMPLETE.md`

The existing Phase 5 recovery dashboard router was also mounted in `app/api/v1/router.py` to preserve its routes in the current codebase.

## Idempotency strategy

Automated actions store a stable `idempotency_key` on `RecoveryAction`:

- Overdue promise: `promise-overdue:<promise_id>`
- Broken promise attention: `broken-promise-attention:<promise_id>`
- Due follow-up: `follow-up-due:<case_id>:<follow_up_date>`

Repeated runs use these source keys to skip existing actions. A filtered unique index on non-null idempotency keys protects against overlapping runs at the database boundary. Each insert and its audit record run inside a savepoint, so a uniqueness conflict skips only that duplicate.

## Safety boundaries

- Does not change PromiseToPay status.
- Does not change invoice or payment records, amounts, or statuses.
- Does not change case status, `amount_in_recovery`, or risk/ML behavior.
- Does not create a timeline or audit table.
- Automated actions use the authenticated user as `created_by_user_id` because no system-user convention exists in this repository.

## Tests and results

- Phase 6 focused: `pytest tests/test_recovery_automation.py -q` — 2 passed.
- Phase 5 + Phase 6 focused: `pytest tests/test_recovery_dashboard.py tests/test_recovery_automation.py -q` — 6 passed.
- Phase 1–6 recovery regression: `pytest tests/test_recovery_automation.py tests/test_recovery_models.py tests/test_payments.py tests/test_promises.py tests/test_recovery_actions.py tests/test_timeline.py tests/test_recovery_dashboard.py -q` — 64 passed.
- Full backend suite: `pytest -q` — 114 passed, 4 warnings in 315.46 seconds. Warnings are from SHAP/LightGBM TreeExplainer output behavior in risk tests.

## Limitations

- Automation runs only when an authenticated member explicitly calls the trigger; no background scheduler was installed or added.
- Broken promises are attention-detected regardless of their promise date because the `BROKEN` status itself is the signal.
- Due follow-up idempotency is keyed by case and follow-up date. If the case receives a new follow-up date, that later due date can produce another action, as intended.