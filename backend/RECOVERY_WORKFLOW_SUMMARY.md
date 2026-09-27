# Recovery Workflow Architecture - Executive Summary

**Status:** Planning complete ✅ | Implementation NOT started  
**Test Baseline:** 50 passed, 0 failed, 0 errors (153.30s) — PRESERVED

---

## Key Findings

### What Exists (Strong Foundation)
- ✅ Case model with status workflow
- ✅ AuditLog for event tracking
- ✅ Payment model (needs API)
- ✅ Risk scoring with ML
- ✅ Document management with case linkage
- ✅ Tenant isolation throughout

### What's Needed (Minimal Extensions)
1. **Add 4 fields to Case:** amount_in_recovery, expected_payment_date, last_contact_date, next_follow_up_date
2. **Create Payment API:** POST/GET endpoints for existing Payment model
3. **Add Timeline API:** GET /cases/{id}/timeline (query AuditLog)
4. **Define audit conventions:** RECOVERY_* action names
5. **Wire auto-triggers:** High risk → case creation

### What's NOT Needed
- ❌ No separate RecoveryCase table
- ❌ No separate RecoveryAction table  
- ❌ No new database tables at all

---

## Core Design Decision

**Recovery is a workflow variant of Cases, not a separate entity.**

Use existing infrastructure:
- Case model → Add recovery fields
- AuditLog → Define action conventions
- Payment model → Add API endpoints

Total new tables: **0**

---

## Proposed Workflow

```
High-risk invoice
    ↓
Auto-create Case (OPEN)
    ↓
Send reminder → Log: RECOVERY_REMINDER_SENT
    ↓
Customer contacted → Log: RECOVERY_CUSTOMER_CONTACTED
    ↓
Promise recorded → Update: case.expected_payment_date
                → Log: RECOVERY_PROMISE_RECORDED
    ↓
Payment received → Create Payment record
                → Update invoice, case
                → Log: RECOVERY_PAYMENT_RECEIVED
                → Background: risk rescore
    ↓
Case RESOLVED
```

---

## Implementation Phases

| Phase | Work | Est. Time |
|-------|------|-----------|
| 1. Models & Migration | Add 4 Case fields, create migration | 0.5 days |
| 2. Payment API | POST/GET /payments with case integration | 1 day |
| 3. Case Timeline | GET /cases/{id}/timeline from AuditLog | 0.5 days |
| 4. Recovery Actions | POST /cases/{id}/remind, /contact, /promise | 1.5 days |
| 5. Dashboard | recovery-queue, broken-promises queries | 1 day |
| 6. Risk Integration | Auto case creation, risk rescoring | 1 day |
| 7. Polish | Docs, tests, validation | 0.5 days |
| **TOTAL** | | **6 days** |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Breaking existing tests | All new fields nullable; run suite after Phase 1 |
| Tenant isolation breach | Use `org_id` filter pattern in ALL endpoints |
| Payment double-recording | Add idempotency / unique constraints |
| Audit log growth | Existing concern; plan archival separately |
| Case deletion orphans docs | Already handled: Document.case_id SET NULL |

---

## Next Steps

1. **Review this document** with stakeholders
2. **Approve design** or request changes
3. **Begin Phase 1** (models & migration)
4. **Run test suite** after each phase
5. **Stop immediately** if tests regress

**Critical:** Do NOT proceed to implementation until design is approved.

---

## Files to Create/Modify

**New Files (7):**
- `app/schemas/payment.py`
- `app/api/v1/payments.py`
- `app/api/v1/case_timeline.py`
- `app/api/v1/recovery_actions.py`
- `alembic/versions/XXX_add_recovery_fields.py`
- `tests/test_payments.py`
- `tests/test_recovery_*.py` (3-4 test files)

**Modified Files (5):**
- `app/models/case.py` — Add 4 fields
- `app/schemas/case.py` — Add field schemas
- `app/api/v1/router.py` — Include new routers
- `app/api/v1/dashboard.py` — Add recovery endpoints
- `tests/test_cases.py` — Test new fields

**Unchanged (Safe):**
- ✅ All risk scoring logic
- ✅ All document/RAG functionality
- ✅ All authentication/authorization
- ✅ All customer/invoice APIs
- ✅ Database session handling (already fixed)

---

## Success Criteria

**After implementation:**
- [ ] All existing 50 tests still pass
- [ ] 20+ new recovery tests pass
- [ ] Payment API functional with tenant isolation
- [ ] Case timeline shows recovery actions
- [ ] Promise-to-pay tracking works
- [ ] Payment → case update → risk rescore chain works
- [ ] Dashboard shows recovery queue
- [ ] Full end-to-end workflow tested

**Target:** 70+ tests passing, 0 regressions

---

*See RECOVERY_WORKFLOW_ARCHITECTURE.md for detailed design.*
