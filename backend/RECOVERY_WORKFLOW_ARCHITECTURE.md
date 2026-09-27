# PayResolve Recovery Workflow - Architecture Analysis & Design

**Status:** Planning Phase — Implementation NOT started  
**Test Baseline:** 50 passed, 0 failed, 0 errors (153.30s)  
**Date:** 2026-09-24

---

## Executive Summary

This document analyzes PayResolve's existing architecture and proposes the minimal clean extensions needed to support a full Recovery Workflow. The design **reuses existing structures** (Case model, AuditLog, Payment table) rather than creating duplicate systems.

**Key Decision:** Recovery is a **workflow variant of Cases**, not a separate entity. Extend Case model with 4 new fields. Use AuditLog conventions for recovery action timeline. No new tables needed.

---

## Phase 1: Existing Architecture Review

### 1. Existing Case System

**Model:** `app/models/case.py`

| Field | Type | Purpose |
|-------|------|---------|
| `customer_id` | FK → customers (NOT NULL) | Who this case is about |
| `invoice_id` | FK → invoices (nullable) | Optional invoice linkage |
| `case_number` | String(50), unique per org | Human-readable ID |
| `title` | String(255) | Short description |
| `status` | Enum | OPEN/EVIDENCE_GATHERING/REMINDER_SENT/IN_DISPUTE/ESCALATED/RESOLVED/CLOSED |
| `priority` | Enum | LOW/MEDIUM/HIGH/CRITICAL |
| `assigned_to_user_id` | FK → users (nullable) | Case owner |
| `summary` | Text | Long-form notes |

**Current API:**
- `GET /api/v1/cases/` — List with filters
- `POST /api/v1/cases/` — Create
- `GET /api/v1/cases/{id}` — Detail
- `PATCH /api/v1/cases/{id}` — Update
- `DELETE /api/v1/cases/{id}` — Delete

**Lifecycle behavior:**
- All operations audited (CASE_CREATED, CASE_UPDATED, CASE_DELETED)
- Tenant isolation enforced via organization_id
- Status transitions unrestricted (no state machine validation)

**Missing for recovery:**
- No amount tracking
- No promise-to-pay support
- No structured action timeline
- No automatic case creation from risk

---

### 2. Existing Audit System

**Model:** `app/models/audit.py`

```python
class AuditLog:
    organization_id: str         # Tenant isolation
    user_id: Optional[str]       # Who (nullable for system)
    action: str                  # What happened
    entity_type: str             # What was affected
    entity_id: str               # Which specific entity
    details: dict                # JSON metadata
    ip_address: Optional[str]    # Where from
    created_at: datetime         # When
```

**Can it support recovery timeline?** ✅ **YES**

The AuditLog provides:
- Chronological ordering
- User attribution
- Flexible metadata (details JSON)
- Tenant isolation
- Queryable by entity

**Strategy:** Use action naming conventions:
- `RECOVERY_CASE_CREATED`
- `RECOVERY_REMINDER_SENT`
- `RECOVERY_CUSTOMER_CONTACTED`
- `RECOVERY_PROMISE_RECORDED`
- `RECOVERY_PAYMENT_RECEIVED`
- `RECOVERY_ESCALATED`
- `RECOVERY_RESOLVED`

**Verdict:** DO NOT create separate RecoveryAction table. Use AuditLog.

---

### 3. Existing Payment System

**Model:** `app/models/stubs.py`

```python
class Payment:
    organization_id: str        # Tenant isolation
    invoice_id: str             # FK → invoices (NOT NULL)
    amount: Decimal             # Payment amount
    payment_date: Date          # When received
    reference: Optional[str]    # Transaction ID
```

**Characteristics:**
- Multiple payments per invoice supported (no unique constraint)
- Partial payments possible
- No direct Case relationship (traverse via invoice)
- **No API endpoints exist** (only used in tests/risk scoring)

**Background rescoring exists** but not integrated:
- `rescore_on_payment()` function defined
- Not called from any API endpoint

**Missing:**
- Payment creation API
- Automatic case status update on payment
- Integration with recovery workflow

---

### 4. Existing Risk System

**Model:** `app/models/stubs.py`

```python
class RiskAssessment:
    invoice_id: Optional[str]      # Scored entity
    customer_id: str               # Risk subject
    case_id: Optional[str]         # Link to case (UNUSED currently)
    risk_score: float              # 0-100
    risk_category: str             # LOW/MEDIUM/HIGH/CRITICAL
    top_factors: dict              # SHAP/feature explanations
    model_version: str             # ML_v1 or HEURISTIC_v1
    scoring_method: str            # "ml" or "heuristic"
```

**API:**
- `GET /risk/invoice/{id}` — Latest score (creates if missing)
- `GET /risk/customer/{id}` — Customer aggregate
- `POST /risk/invoice/{id}/rescore` — Manual rescore
- `GET /risk/invoice/{id}/history` — Score timeline

**Missing for recovery:**
- No automatic case creation from high risk
- case_id field exists but unused
- No API to create case from risk assessment

---

### 5. Existing Document/Evidence System

**Model:** `app/models/document.py`

```python
class Document:
    invoice_id: Optional[str]          # Optional linkage
    case_id: Optional[str]             # Optional linkage (functional)
    doc_type: DocType                  # INVOICE/CONTRACT/RECEIPT/CORRESPONDENCE
    extracted_fields: dict             # Evidence with page citations
    status: DocStatus                  # PENDING/PROCESSING/DONE/FAILED
```

**API:**
- `POST /documents/upload` — Upload with optional case_id/invoice_id
- `GET /documents/` — List with filters
- `GET /documents/{id}` — Detail
- `DELETE /documents/{id}` — Delete

**What works:**
- ✅ Documents can link to cases
- ✅ Evidence provenance tracked (page, confidence)
- ✅ Tenant isolation enforced

**Missing:**
- No GET /cases/{id}/documents endpoint
- No workflow for uploading evidence to existing case

---

### 6. Existing API Structure

| Module | Prefix | Key Endpoints |
|--------|--------|---------------|
| auth | / | POST /register, /login, /refresh, GET /me |
| organizations | /organizations | CRUD operations |
| customers | /customers | CRUD + list |
| invoices | /invoices | CRUD + GET /{id}/pdf |
| **cases** | **/cases** | **CRUD (no timeline endpoint)** |
| dashboard | /dashboard | summary, aging-buckets, top-delinquents |
| documents | /documents | upload, list, detail, chunks |
| copilot | /copilot | POST /query |
| risk | /risk | invoice/customer scoring, rescore, history |

**Missing:**
- ❌ No `/payments` endpoints
- ❌ No `/cases/{id}/timeline`
- ❌ No `/cases/{id}/documents`
- ❌ No recovery action recording endpoints

---

## Phase 2: Recovery Workflow Design

### A. What should a Recovery Case represent?

A **Recovery Case** = active debt collection effort for overdue invoice(s).

**Workflow:**
```
High-risk invoice detected
    ↓
Recovery Case created (OPEN)
    ↓
Actions: reminders, calls, negotiations
    ↓
Customer responds: promise/dispute/payment
    ↓
Outcome: RESOLVED (paid) or ESCALATED (legal)
```

**Design decision:** Recovery is a **type of Case**, not separate entity.

---

### B. Which existing Case fields can be reused?

✅ **ALL existing fields work for recovery:**

| Field | Recovery Usage |
|-------|----------------|
| customer_id | Who owes the debt |
| invoice_id | Primary invoice (nullable for multi-invoice cases) |
| case_number | Human reference (e.g., "REC-2024-001") |
| title | "Recovery: Invoice INV-123 - $5,000 overdue" |
| status | OPEN → REMINDER_SENT → RESOLVED/ESCALATED |
| priority | Set by risk score + amount |
| assigned_to_user_id | Collections agent |
| summary | Recovery strategy notes |

**Existing status enum maps perfectly:**
- OPEN = Recovery initiated
- EVIDENCE_GATHERING = Collecting docs
- REMINDER_SENT = Payment reminder(s) sent
- IN_DISPUTE = Customer disputes debt
- ESCALATED = Legal/external collections
- RESOLVED = Payment received
- CLOSED = Written off

---

### C. What genuinely needs to be added?

**4 new fields in Case model:**

```python
amount_in_recovery: Optional[Decimal]     # Total being collected
expected_payment_date: Optional[Date]     # Promise-to-pay date
last_contact_date: Optional[Date]         # When we last reached customer
next_follow_up_date: Optional[Date]       # When to contact again
```

**Why these:**
1. `amount_in_recovery` — Cases may involve partial amounts/multiple invoices
2. `expected_payment_date` — Track customer commitments
3. `last_contact_date` — Enforce cadences (avoid harassment)
4. `next_follow_up_date` — Agent task queue

**Migration:**
```sql
ALTER TABLE cases ADD COLUMN amount_in_recovery NUMERIC(15,2);
ALTER TABLE cases ADD COLUMN expected_payment_date DATE;
ALTER TABLE cases ADD COLUMN last_contact_date DATE;
ALTER TABLE cases ADD COLUMN next_follow_up_date DATE;

CREATE INDEX idx_cases_expected_payment
  ON cases(organization_id, expected_payment_date)
  WHERE expected_payment_date IS NOT NULL;

CREATE INDEX idx_cases_next_followup
  ON cases(organization_id, next_follow_up_date)
  WHERE next_follow_up_date IS NOT NULL;
```

---

### D. Do we need a separate RecoveryAction table?

**NO — Use AuditLog with conventions.**

**Rationale:**
- ✅ AuditLog has: ordering, user attribution, tenant isolation, flexible metadata
- ✅ Query timeline: `SELECT * FROM audit_log WHERE entity_type='Case' AND entity_id=? ORDER BY created_at`
- ✅ Flexible: Add new action types without migrations

**Action convention:**

```python
RECOVERY_REMINDER_SENT
  details: {
    "channel": "email",
    "recipient": "customer@example.com",
    "template": "payment_reminder_1"
  }

RECOVERY_CUSTOMER_CONTACTED
  details: {
    "channel": "phone",
    "outcome": "promised_payment",
    "promise_date": "2024-10-15",
    "notes": "Agreed to partial payment"
  }

RECOVERY_PROMISE_RECORDED
  details: {
    "promise_date": "2024-10-15",
    "promise_amount": 2500.00,
    "payment_plan": "single"
  }

RECOVERY_PAYMENT_RECEIVED
  details: {
    "payment_id": "uuid",
    "amount": 2500.00,
    "promise_kept": true
  }
```

**API:**
```python
GET /api/v1/cases/{case_id}/timeline
  → Query AuditLog WHERE entity_type='Case' AND entity_id=case_id
  → ORDER BY created_at DESC
```

---

### E. How should Promise-to-Pay work?

**NO separate table — Use AuditLog + Case fields.**

**When customer promises:**
1. Log audit event:
   ```python
   action="RECOVERY_PROMISE_RECORDED"
   details={"promise_date": "2024-10-15", "promise_amount": 2500.00}
   ```

2. Update Case:
   ```python
   case.expected_payment_date = promise_date
   case.next_follow_up_date = promise_date + timedelta(days=1)
   ```

**Track broken promises:**
```sql
SELECT * FROM cases
WHERE expected_payment_date < CURRENT_DATE
  AND status NOT IN ('RESOLVED', 'CLOSED')
```

**Promise ≠ Payment:**
- Promise = commitment (Case field + audit log)
- Payment = actual money (Payment table record)

**When payment received:**
```python
# 1. Create Payment record
payment = Payment(invoice_id=..., amount=..., payment_date=...)

# 2. Log RECOVERY_PAYMENT_RECEIVED
details={
    "payment_id": payment.id,
    "promise_kept": payment_date <= case.expected_payment_date
}

# 3. Update Case
case.amount_in_recovery -= payment.amount
if case.amount_in_recovery <= 0:
    case.status = RESOLVED
```

---

### F. How should actual payment affect recovery?

**Integrated workflow:**

```
1. Customer promises
   ↓
   RECOVERY_PROMISE_RECORDED logged
   case.expected_payment_date = promise_date

2. Payment received
   ↓
   POST /api/v1/payments {invoice_id, amount, date}

3. Payment creation triggers:
   a) Update Invoice (paid_amount, status)
   b) Log RECOVERY_PAYMENT_RECEIVED
   c) Update Case (amount_in_recovery, status)
   d) Background risk rescoring

4. Dashboard updates → Next case in queue
```

**Implementation:**

```python
# New endpoint: POST /api/v1/payments
@router.post("/")
async def create_payment(
    payload: PaymentCreate,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # 1. Create payment
    payment = Payment(
        organization_id=tenant.organization_id,
        invoice_id=payload.invoice_id,
        amount=payload.amount,
        payment_date=payload.payment_date,
    )
    db.add(payment)
    
    # 2. Update invoice
    invoice = await _get_invoice_or_404(db, payload.invoice_id, tenant.organization_id)
    invoice.paid_amount += payment.amount
    if invoice.paid_amount >= invoice.total_amount:
        invoice.status = InvoiceStatus.PAID
    
    # 3. Update related case (if exists)
    if invoice.case:
        case = invoice.case
        promise_kept = (
            case.expected_payment_date
            and payment.payment_date <= case.expected_payment_date
        )
        
        await log_audit_event(
            db, tenant.organization_id, tenant.user.id,
            "RECOVERY_PAYMENT_RECEIVED", "Case", case.id,
            details={"payment_id": str(payment.id), "amount": float(payment.amount), "promise_kept": promise_kept}
        )
        
        case.amount_in_recovery -= payment.amount
        if case.amount_in_recovery <= 0:
            case.status = CaseStatus.RESOLVED
    
    await db.commit()
    
    # 4. Background rescoring
    background_tasks.add_task(rescore_on_payment, tenant.organization_id, invoice.id)
    
    return payment
```

**Fits existing architecture:** ✅
- Uses BackgroundTasks (same as documents)
- Reuses rescore_on_payment() from background_rescoring.py
- Follows audit logging patterns

---

### G. Tenant Isolation

**Enforcement for all new components:**

| Component | Isolation Mechanism |
|-----------|---------------------|
| Case (extended) | ✅ Already: organization_id FK, all queries filter by org |
| Payment API | Verify invoice.organization_id == tenant.organization_id |
| AuditLog (recovery) | ✅ Already: organization_id required in all queries |
| Timeline API | Filter: `AuditLog.organization_id == tenant AND entity_id == case.id` |
| Promise tracking | Stored in Case (isolated) + AuditLog (isolated) |

**Pattern (used everywhere):**
```python
async def _get_case_or_404(db, case_id, org_id) -> Case:
    stmt = select(Case).where(
        Case.id == case_id,
        Case.organization_id == org_id,  # ← Tenant boundary
    )
    case = (await db.execute(stmt)).scalar_one_or_none()
    if not case:
        raise HTTPException(404)
    return case
```

**New indexes:**
```sql
CREATE INDEX idx_cases_expected_payment
  ON cases(organization_id, expected_payment_date)
  WHERE expected_payment_date IS NOT NULL;
```

---

### H. API Proposal

**New endpoints (implementation deferred):**

#### Payment Management
```
POST   /api/v1/payments                    Create payment
GET    /api/v1/payments                    List payments
GET    /api/v1/payments/{id}               Payment detail
```

#### Case Timeline
```
GET    /api/v1/cases/{id}/timeline         Recovery action history
POST   /api/v1/cases/{id}/actions          Record custom action
```

#### Recovery Actions
```
POST   /api/v1/cases/{id}/remind           Send reminder
POST   /api/v1/cases/{id}/contact          Log customer contact
POST   /api/v1/cases/{id}/promise          Record promise-to-pay
POST   /api/v1/cases/{id}/escalate         Escalate case
POST   /api/v1/cases/{id}/resolve          Close case
```

#### Document Integration
```
GET    /api/v1/cases/{id}/documents        List evidence docs
```

#### Dashboard
```
GET    /api/v1/dashboard/recovery-queue    Cases needing attention
GET    /api/v1/dashboard/broken-promises   Overdue promises
GET    /api/v1/dashboard/collection-metrics Recovery KPIs
```

#### Automatic Case Creation
```
POST   /api/v1/risk/invoice/{id}/create-case   Create case from high risk
```

**New schemas:**

```python
# app/schemas/payment.py (NEW)
class PaymentCreate(BaseModel):
    invoice_id: str
    amount: Decimal = Field(gt=0)
    payment_date: date
    reference: Optional[str] = None

class PaymentRead(BaseModel):
    id: str
    organization_id: str
    invoice_id: str
    amount: Decimal
    payment_date: date
    created_at: datetime

# app/schemas/case.py (UPDATED)
class CaseTimelineItem(BaseModel):
    id: str
    timestamp: datetime
    action: str
    user: Optional[UserRead]
    details: dict

class PromiseToPayCreate(BaseModel):
    promise_date: date
    promise_amount: Decimal = Field(gt=0)
    payment_plan: str = Field(pattern="^(single|installments)$")
    notes: Optional[str] = None
```

---

### I. Database Migration Proposal

**Migration 001: Add recovery fields to cases**

```sql
-- Add columns
ALTER TABLE cases ADD COLUMN amount_in_recovery NUMERIC(15,2);
ALTER TABLE cases ADD COLUMN expected_payment_date DATE;
ALTER TABLE cases ADD COLUMN last_contact_date DATE;
ALTER TABLE cases ADD COLUMN next_follow_up_date DATE;

-- Add indexes
CREATE INDEX idx_cases_expected_payment
  ON cases(organization_id, expected_payment_date)
  WHERE expected_payment_date IS NOT NULL;

CREATE INDEX idx_cases_next_followup
  ON cases(organization_id, next_follow_up_date)
  WHERE next_follow_up_date IS NOT NULL
    AND status NOT IN ('RESOLVED', 'CLOSED');

CREATE INDEX idx_cases_recovery_status
  ON cases(organization_id, status)
  WHERE status IN ('OPEN', 'EVIDENCE_GATHERING', 'REMINDER_SENT', 'IN_DISPUTE', 'ESCALATED');

-- Add constraint
ALTER TABLE cases ADD CONSTRAINT chk_recovery_amount_positive
  CHECK (amount_in_recovery IS NULL OR amount_in_recovery > 0);
```

**NO changes needed for:**
- ✅ AuditLog (already supports all recovery actions)
- ✅ Payment (exists, needs API only)
- ✅ RiskAssessment (case_id field exists)
- ✅ Document (case_id field exists)

**Model updates:**

```python
# app/models/case.py (UPDATED)
class Case(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    # ... existing fields ...
    
    # NEW: Recovery fields
    amount_in_recovery: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    expected_payment_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True
    )
    last_contact_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    next_follow_up_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True
    )
```

**Schema updates:**

```python
# app/schemas/case.py (UPDATED)
class CaseBase(BaseModel):
    # ... existing fields ...
    amount_in_recovery: Optional[Decimal] = None
    expected_payment_date: Optional[date] = None
    last_contact_date: Optional[date] = None
    next_follow_up_date: Optional[date] = None

class CaseCreate(CaseBase):
    @field_validator('amount_in_recovery')
    def validate_recovery_amount(cls, v):
        if v is not None and v <= 0:
            raise ValueError('amount_in_recovery must be positive')
        return v
```

---

### J. Test Plan

**1. Case Lifecycle Tests**
```python
test_create_recovery_case()
  - Create case with amount_in_recovery
  - Verify case_number unique per org
  - Check tenant isolation

test_case_status_transitions()
  - OPEN → REMINDER_SENT → RESOLVED
  - OPEN → IN_DISPUTE → ESCALATED
  - Verify audit log entries created

test_case_with_multiple_invoices()
  - Case linked to primary invoice
  - amount_in_recovery > single invoice total
  - Payments reduce amount_in_recovery
```

**2. Recovery Action Tests**
```python
test_record_reminder_sent()
  - Log RECOVERY_REMINDER_SENT action
  - Verify details JSON structure
  - Check timeline retrieval

test_record_customer_contact()
  - Log phone/email contact
  - Update last_contact_date
  - Verify user attribution

test_cannot_record_action_for_other_org_case()
  - Attempt cross-tenant action
  - Expect 404 (not 403, no entity leak)
```

**3. Promise-to-Pay Tests**
```python
test_record_promise_updates_case()
  - Record promise via API
  - Verify expected_payment_date set
  - Verify next_follow_up_date set
  - Check RECOVERY_PROMISE_RECORDED in audit

test_list_broken_promises()
  - Create case with expected_payment_date in past
  - Query /dashboard/broken-promises
  - Verify only overdue promises returned
  - Verify tenant isolation

test_multiple_promises_tracked_in_timeline()
  - Record initial promise
  - Customer breaks promise
  - Record new promise
  - Verify both in timeline, most recent in case.expected_payment_date
```

**4. Payment Interaction Tests**
```python
test_payment_resolves_case()
  - Create case with amount_in_recovery=5000
  - Record payment of 5000
  - Verify case.status = RESOLVED
  - Verify case.amount_in_recovery = 0
  - Check RECOVERY_PAYMENT_RECEIVED logged

test_partial_payment_updates_amount()
  - Case with amount=5000
  - Payment of 2000
  - Verify amount_in_recovery=3000
  - Verify status unchanged (still OPEN)

test_payment_honors_promise()
  - Case with expected_payment_date = "2024-10-15"
  - Payment on "2024-10-15"
  - Verify promise_kept=True in audit details
  
test_payment_breaks_promise()
  - Expected "2024-10-15", paid "2024-10-20"
  - Verify promise_kept=False

test_payment_triggers_risk_rescore()
  - Mock background_tasks
  - Create payment
  - Verify rescore_on_payment queued
```

**5. Invalid Transition Tests**
```python
test_cannot_set_negative_amount()
  - Attempt amount_in_recovery = -100
  - Expect validation error

test_cannot_link_case_to_other_org_invoice()
  - User in org A
  - Attempt case with invoice from org B
  - Expect 404

test_cannot_set_past_expected_payment_date()
  - Attempt expected_payment_date = yesterday
  - Expect validation error (or allow with warning)
```

**6. Tenant Isolation Tests**
```python
test_cannot_view_other_org_case_timeline()
  - Org A case
  - Org B user requests timeline
  - Expect 404

test_cannot_create_payment_for_other_org_invoice()
  - User in org A
  - Invoice in org B
  - POST /payments with invoice_id
  - Expect 404

test_recovery_queue_filtered_by_org()
  - Create cases in org A and org B
  - User A requests /dashboard/recovery-queue
  - Verify only org A cases returned
```

**7. Authorization Tests**
```python
test_non_assigned_user_cannot_edit_case()
  - Case assigned to user A
  - User B (same org) attempts PATCH
  - Expect 403 (or allow based on role)

test_system_can_auto_create_case_from_risk()
  - High-risk invoice detected
  - POST /risk/invoice/{id}/create-case
  - Verify case created with user_id=None or system user
  - Check audit log for system attribution
```

**8. Audit Timeline Tests**
```python
test_timeline_shows_all_recovery_actions()
  - Create case
  - Record 3 different actions
  - GET /cases/{id}/timeline
  - Verify 4 entries (creation + 3 actions)
  - Verify chronological order

test_timeline_includes_user_info()
  - Action by user A
  - Timeline returns user.email, user.name
  - Verify user details populated

test_timeline_handles_system_actions()
  - Automatic case creation (user_id=NULL)
  - Timeline shows user=None
  - Action still visible
```

**9. Document/Evidence Tests**
```python
test_upload_document_to_case()
  - POST /documents/upload?case_id=xxx
  - Verify doc.case_id set
  - Check DOCUMENT_UPLOAD audit entry

test_list_case_documents()
  - Case with 3 linked docs
  - GET /cases/{id}/documents
  - Verify all 3 returned
  - Verify tenant isolation

test_cannot_link_document_to_other_org_case()
  - User in org A
  - Attempt upload with org B case_id
  - Expect 404
```

**10. Risk Integration Tests**
```python
test_auto_create_case_from_high_risk()
  - Invoice with risk_score > 80
  - POST /risk/invoice/{id}/create-case
  - Verify case created
  - Verify case.invoice_id = invoice.id
  - Verify case.amount_in_recovery = invoice.outstanding_amount
  - Check RiskAssessment.case_id linked

test_risk_rescore_after_payment()
  - Invoice with risk_score=85
  - Record payment
  - Wait for background task
  - Verify new RiskAssessment created
  - Verify risk_score decreased

test_cannot_create_duplicate_recovery_case()
  - Invoice already has case
  - Attempt POST /risk/invoice/{id}/create-case
  - Expect 409 Conflict
```

---

## Phase 3: Final Recommendation

### 1. Current State

PayResolve has:
- ✅ Solid Case model with tenant isolation
- ✅ Flexible AuditLog for timeline tracking
- ✅ Payment model (no API yet)
- ✅ Risk scoring with ML/heuristic fallback
- ✅ Document management with case linkage
- ✅ Background rescoring infrastructure
- ✅ 50/50 passing test suite

**Architecture is recovery-ready** — needs extensions, not replacements.

---

### 2. What Is Missing for Recovery Workflow

**Minimal gaps:**

1. **Case model:** Missing 4 recovery-specific fields
2. **Payment API:** Model exists, endpoints missing
3. **Timeline API:** AuditLog exists, GET endpoint missing
4. **Recovery actions:** Audit conventions undefined, convenience endpoints missing
5. **Automatic triggers:** High-risk → case creation not wired
6. **Dashboard queries:** Recovery-specific views missing

**NOT missing:**
- ❌ NO new tables needed
- ❌ NO duplicate recovery entity
- ❌ NO separate action tracking system

---

### 3. Recommended Design

**End-to-end flow:**

```
┌─────────────────────────────────────────────────────────┐
│ 1. Invoice becomes overdue                              │
│    Risk service scores → risk_score = 85 (HIGH)         │
└─────────────────────────────┬───────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│ 2. Automatic case creation (optional)                   │
│    POST /risk/invoice/{id}/create-case                  │
│    Creates: Case(                                       │
│      customer_id = invoice.customer_id,                 │
│      invoice_id = invoice.id,                           │
│      amount_in_recovery = invoice.outstanding_amount,   │
│      status = OPEN,                                     │
│      priority = based on risk + amount                  │
│    )                                                    │
│    Audit: RECOVERY_CASE_CREATED                         │
└─────────────────────────────┬───────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│ 3. Collections agent takes action                       │
│    POST /cases/{id}/remind → sends email                │
│    Audit: RECOVERY_REMINDER_SENT                        │
│    Update: case.last_contact_date = today               │
└─────────────────────────────┬───────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│ 4. Agent calls customer                                 │
│    POST /cases/{id}/contact                             │
│    Audit: RECOVERY_CUSTOMER_CONTACTED                   │
│      details: {channel: "phone", outcome: "promised"}   │
└─────────────────────────────┬───────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│ 5. Customer promises payment                            │
│    POST /cases/{id}/promise {date: "2024-10-15"}        │
│    Update: case.expected_payment_date = "2024-10-15"    │
│    Update: case.next_follow_up_date = "2024-10-16"      │
│    Audit: RECOVERY_PROMISE_RECORDED                     │
└─────────────────────────────┬───────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│ 6. Payment received                                     │
│    POST /payments {invoice_id, amount, date}            │
│    Creates: Payment record                              │
│    Updates: invoice.paid_amount += amount               │
│    Updates: case.amount_in_recovery -= amount           │
│    If amount_in_recovery <= 0:                          │
│      case.status = RESOLVED                             │
│    Audit: RECOVERY_PAYMENT_RECEIVED                     │
│      details: {promise_kept: true}                      │
│    Background: rescore_on_payment() queued              │
└─────────────────────────────┬───────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│ 7. Risk rescored                                        │
│    Background task creates new RiskAssessment           │
│    risk_score drops to 35 (LOW)                         │
│    Dashboard metrics updated                            │
└─────────────────────────────────────────────────────────┘

Alternative path: Customer disputes
┌─────────────────────────────────────────────────────────┐
│ 4b. Customer disputes debt                              │
│     PATCH /cases/{id} {status: "IN_DISPUTE"}            │
│     Audit: CASE_UPDATED + RECOVERY_DISPUTED             │
│     Agent uploads evidence documents                    │
│     POST /documents/upload?case_id={id}                 │
└─────────────────────────────┬───────────────────────────┘
                              ↓
                         Resolution or Escalation
```

---

### 4. Files Likely to Change

**Models (4 files):**
- `app/models/case.py` — Add 4 recovery fields
- `app/models/stubs.py` — NO changes (Payment already exists)
- `app/schemas/case.py` — Add recovery field schemas, validators
- `app/schemas/payment.py` — **NEW FILE** (PaymentCreate, PaymentRead)

**API (3 new files, 2 updated):**
- `app/api/v1/payments.py` — **NEW** (POST, GET endpoints)
- `app/api/v1/case_timeline.py` — **NEW** (GET /cases/{id}/timeline)
- `app/api/v1/recovery_actions.py` — **NEW** (POST /cases/{id}/remind, /contact, /promise, /escalate)
- `app/api/v1/router.py` — UPDATED (include new routers)
- `app/api/v1/dashboard.py` — UPDATED (add recovery-queue, broken-promises endpoints)

**Services (2 updated):**
- `app/services/background_rescoring.py` — UPDATED (wire rescore_on_payment into payment API)
- `app/services/audit_service.py` — NO changes (already sufficient)

**Database:**
- `alembic/versions/XXX_add_recovery_fields.py` — **NEW** migration

**Tests (5 new files):**
- `tests/test_payments.py` — **NEW** (payment CRUD, tenant isolation)
- `tests/test_recovery_actions.py` — **NEW** (remind, contact, promise, escalate)
- `tests/test_promise_to_pay.py` — **NEW** (promise tracking, broken promises)
- `tests/test_case_timeline.py` — **NEW** (audit log queries, timeline API)
- `tests/test_recovery_integration.py` — **NEW** (end-to-end: case → payment → rescore)

**Updated tests (3 files):**
- `tests/test_cases.py` — UPDATED (test new recovery fields, validation)
- `tests/test_risk.py` — UPDATED (test case_id linkage, auto-case-creation)
- `tests/test_dashboard.py` — UPDATED (recovery-queue, broken-promises endpoints)

---

### 5. Implementation Phases

**Phase 1: Models & Migration** (Est: 0.5 days)
- Add 4 fields to Case model
- Add validation to CaseCreate/CaseUpdate schemas
- Create alembic migration
- Run migration on test DB
- Verify existing tests still pass (50/50)

**Phase 2: Payment API** (Est: 1 day)
- Create `app/schemas/payment.py`
- Create `app/api/v1/payments.py`
- Implement POST /payments with payment → invoice → case integration
- Implement GET /payments (list, detail)
- Wire rescore_on_payment into BackgroundTasks
- Write tests: test_payments.py (CRUD, tenant isolation, rescoring trigger)
- Target: All existing + new payment tests pass

**Phase 3: Case Timeline** (Est: 0.5 days)
- Create `app/api/v1/case_timeline.py`
- Implement GET /cases/{id}/timeline (query AuditLog)
- Enrich with user information
- Write tests: test_case_timeline.py
- Target: Timeline queries work, tenant-isolated

**Phase 4: Recovery Actions** (Est: 1.5 days)
- Create `app/api/v1/recovery_actions.py`
- Implement POST /cases/{id}/remind (send email/SMS, log action)
- Implement POST /cases/{id}/contact (log contact, update last_contact_date)
- Implement POST /cases/{id}/promise (update case fields, log promise)
- Implement POST /cases/{id}/escalate (update status, log escalation)
- Implement POST /cases/{id}/resolve (close case, log resolution)
- Write tests: test_recovery_actions.py, test_promise_to_pay.py
- Target: All action endpoints functional, properly audited

**Phase 5: Dashboard & Queries** (Est: 1 day)
- Implement GET /dashboard/recovery-queue (cases needing attention)
- Implement GET /dashboard/broken-promises (overdue promise dates)
- Implement GET /dashboard/collection-metrics (KPIs)
- Update test_dashboard.py
- Target: Dashboard queries performant, tenant-isolated

**Phase 6: Risk Integration** (Est: 1 day)
- Implement POST /risk/invoice/{id}/create-case (auto-case-creation)
- Wire RiskAssessment.case_id linkage
- Add duplicate case prevention
- Update test_risk.py with integration tests
- Write test_recovery_integration.py (end-to-end flow)
- Target: Full workflow functional, risk → case → payment → rescore

**Phase 7: Documentation & Polish** (Est: 0.5 days)
- Update API documentation (OpenAPI/Swagger)
- Add docstrings to new endpoints
- Create user guide for recovery workflow
- Run full test suite: Target 70+ tests passing

**Total estimated time: 6 days development**

---

### 6. Risk Assessment

**Potential breaking changes / risks:**

| Risk | Mitigation |
|------|------------|
| **Tenant isolation breach** | Follow existing `_get_or_404(db, id, org_id)` pattern in ALL new endpoints. Add tenant-crossing tests. |
| **Case model migration fails** | Test migration on copy of prod DB first. Fields are all nullable, no data loss risk. |
| **Payment API allows double-payment** | Add idempotency key or unique constraint on (invoice_id, reference). Prevent same payment recorded twice. |
| **Background rescoring overloads queue** | Already has `should_rescore()` debouncing (24h threshold). Keep it. |
| **Audit log grows unbounded** | Already a concern (not recovery-specific). Consider partition strategy or archival policy (separate task). |
| **Promise-to-pay no validation** | Add business rule: expected_payment_date must be >= today. Prevent backdated promises. |
| **Broken promise queries slow** | Indexes added: `idx_cases_expected_payment`, `idx_cases_next_followup`. Should be fast. Monitor in prod. |
| **Payment → case update race condition** | Use DB transaction. Payment creation, invoice update, case update in single `await db.commit()`. |
| **Risk score doesn't trigger case** | Auto-creation is OPTIONAL endpoint. Collections team decides when to call it. No automatic trigger initially. |
| **Existing case tests break** | Run test suite after Phase 1. If failures, case model changes too aggressive—rollback and simplify. |
| **RAG/Copilot affected** | NO: Document model unchanged. Vector store unchanged. Copilot service unchanged. |
| **Auth/permissions unclear** | Define role-based access: "collections_agent" role can POST /cases/{id}/*, "admin" can DELETE. (Separate RBAC task.) |

**Specific concerns:**

1. **Existing Case functionality:**
   - Risk: Adding fields breaks existing case creation
   - Mitigation: All new fields nullable, have defaults. Existing API calls work unchanged.

2. **Payments:**
   - Risk: Creating Payment API enables fraud (fake payments)
   - Mitigation: Require elevated permissions. Log all payment creation. Add audit alerts for large payments.

3. **Risk scoring:**
   - Risk: Background rescoring fails due to session handling
   - Mitigation: Already fixed in Phase 4 (async_session_factory pattern). Keep that fix.

4. **Documents:**
   - Risk: Case deletion orphans documents
   - Mitigation: Document.case_id has `ondelete="SET NULL"` (already). Documents survive case deletion.

5. **Tenancy:**
   - Risk: Cross-org data leak via timeline/payment endpoints
   - Mitigation: Test suite MUST include cross-org attempts for every new endpoint. Expect 404, not 403.

**Critical: Preserve test baseline**
- After Phase 1 (models): Run full suite. Expect 50 passed (or more if new tests added).
- Do NOT proceed to Phase 2 if any existing tests regress.

---

## Appendices

### A. Action Naming Convention Reference

```python
# Case lifecycle
RECOVERY_CASE_CREATED         # Automatic or manual case creation
RECOVERY_CASE_UPDATED         # Generic update (use specific actions when possible)
RECOVERY_RESOLVED             # Case closed successfully
RECOVERY_CLOSED               # Case closed without resolution

# Customer communication
RECOVERY_REMINDER_SENT        # Email/SMS payment reminder
RECOVERY_CUSTOMER_CONTACTED   # Phone call, meeting, in-person visit
RECOVERY_DISPUTE_RECEIVED     # Customer disputes the debt
RECOVERY_ESCALATED            # Sent to legal/collections agency

# Promises & payments
RECOVERY_PROMISE_RECORDED     # Customer commits to payment date
RECOVERY_PAYMENT_RECEIVED     # Actual payment recorded
RECOVERY_PAYMENT_PLAN_CREATED # Installment plan agreed

# Evidence & documentation
RECOVERY_EVIDENCE_UPLOADED    # Document added as evidence
RECOVERY_EVIDENCE_REVIEWED    # Agent reviewed evidence
```

### B. Query Patterns

**Get case timeline:**
```python
stmt = (
    select(AuditLog, User)
    .outerjoin(User, AuditLog.user_id == User.id)
    .where(
        AuditLog.organization_id == tenant.organization_id,
        AuditLog.entity_type == "Case",
        AuditLog.entity_id == case_id,
    )
    .order_by(AuditLog.created_at.desc())
)
```

**Get broken promises:**
```python
stmt = (
    select(Case)
    .where(
        Case.organization_id == org_id,
        Case.expected_payment_date < date.today(),
        Case.status.in_([CaseStatus.OPEN, CaseStatus.REMINDER_SENT, CaseStatus.EVIDENCE_GATHERING]),
    )
    .order_by(Case.expected_payment_date.asc())
)
```

**Get recovery queue (next cases to work):**
```python
stmt = (
    select(Case)
    .where(
        Case.organization_id == org_id,
        Case.status.in_([CaseStatus.OPEN, CaseStatus.REMINDER_SENT]),
        or_(
            Case.next_follow_up_date <= date.today(),
            Case.next_follow_up_date.is_(None),
        )
    )
    .order_by(Case.priority.desc(), Case.created_at.asc())
    .limit(50)
)
```

---

## Conclusion

PayResolve's architecture is **fundamentally sound** for recovery workflows. The design extends existing structures rather than duplicating them:

- **Case model:** Add 4 fields (no new table)
- **Action timeline:** Use AuditLog conventions (no new table)
- **Promises:** Case fields + audit log (no new table)
- **Payments:** API for existing model (no schema changes)

**Total new tables: 0**  
**Total model changes: 1 (Case)**  
**Total new endpoints: ~15**

The 50/50 test baseline remains intact. Implementation can proceed incrementally, phase by phase, with continuous validation.

**Recommendation: APPROVED for implementation.**

---

*End of architecture document.*
