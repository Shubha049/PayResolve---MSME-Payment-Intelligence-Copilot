# PayResolve Recovery Workflow - FINAL DESIGN

**Status:** Design Refinement Complete  
**Test Baseline:** 50 passed, 0 failed, 0 errors (153.30s) — PRESERVED  
**Date:** 2026-09-24

---

## 1. Core Architectural Decision

### Recovery = Extended Case System ✅

**Rationale:**

The existing Case model is **designed for recovery workflows**:

1. **Customer-centric:** Cases track customer issues (✓)
2. **Invoice-linkable:** Optional invoice_id field (✓)
3. **Status workflow:** OPEN → REMINDER_SENT → IN_DISPUTE → ESCALATED → RESOLVED (✓)
4. **Priority levels:** LOW/MEDIUM/HIGH/CRITICAL match risk-based prioritization (✓)
5. **Assignable:** assigned_to_user_id for collections agents (✓)
6. **Tenant-isolated:** organization_id FK with CASCADE (✓)
7. **Unique identifiers:** case_number unique per org (✓)

**Existing status enum perfectly matches recovery stages:**

| CaseStatus | Recovery Meaning |
|------------|------------------|
| OPEN | Recovery initiated |
| EVIDENCE_GATHERING | Collecting proof (invoices, contracts, delivery confirmation) |
| REMINDER_SENT | Payment reminder(s) sent |
| IN_DISPUTE | Customer disputes the debt |
| ESCALATED | Legal/external collections |
| RESOLVED | Payment received, case closed |
| CLOSED | Written off or closed without payment |

**Conclusion:** Extend Case, do NOT create RecoveryCase table.

---

## 2. Promise-to-Pay Design Analysis

### Option A: Case Fields + AuditLog

**Structure:**
```python
# Case model
expected_payment_date: Optional[Date]  # Latest promise

# AuditLog entries
action="promise.recorded"
details={"promise_date": "2024-10-15", "promise_amount": 2500.00}
```

**Pros:**
- Simple: no new table
- Works for single active promise
- Timeline via AuditLog query

**Cons:**
- ❌ Cannot track multiple concurrent promises
- ❌ No structured promise state (pending/fulfilled/broken)
- ❌ Complex queries for promise metrics
- ❌ Cannot link promise to specific payment
- ❌ Cannot track partial promise fulfillment

### Option B: Dedicated PromiseToPay Table

**Structure:**
```python
class PromiseToPay(Base):
    case_id: str                      # FK → cases
    promise_date: Date                # When customer promises to pay
    promised_amount: Decimal          # How much promised
    status: PromiseStatus             # PENDING/FULFILLED/BROKEN/CANCELLED
    fulfilled_by_payment_id: Optional[str]  # FK → payments (nullable)
    notes: Optional[str]
```

**Pros:**
- ✅ First-class promise tracking
- ✅ Multiple promises per case
- ✅ Clear promise state machine
- ✅ Links promise → actual payment
- ✅ Easy queries: "broken promises", "fulfillment rate"
- ✅ Supports promise amendments/cancellations

**Cons:**
- Adds one table
- Slightly more complex (managed separately from Case)

### Decision: **Option B — Create PromiseToPay Table**

**Reasoning:**

Recovery workflows require **structured promise tracking**:

1. **Customer negotiation:** "I'll pay ₹2,500 on Oct 15, then ₹2,500 on Nov 15"
2. **Promise amendments:** Customer calls to extend promise date
3. **Fulfillment tracking:** Did payment match promise?
4. **Broken promise detection:** Automated follow-up when promise_date passes
5. **Reporting:** Promise fulfillment rate, average days to broken promise

**Promise-to-Pay is NOT just audit metadata** — it's a **commitment with state and consequences**.

The Case field `expected_payment_date` can store the **next upcoming promise date** for quick filtering, but full promise history needs dedicated storage.

---

## 3. Payment → Invoice → Case Behavior

### Business Rules

#### Rule 1: Full Payment

```
Invoice: total_amount = ₹100,000, paid_amount = ₹0
Payment: amount = ₹100,000

Actions:
1. Create Payment record
2. invoice.paid_amount = ₹100,000
3. invoice.status = PAID
4. invoice.outstanding_amount = ₹0 (computed property)
5. IF invoice.case EXISTS:
     case.status = RESOLVED
     log("payment.received.full", case_id)
6. Background: rescore_on_payment(invoice_id)
```

#### Rule 2: Partial Payment

```
Invoice: total_amount = ₹100,000, paid_amount = ₹0
Payment: amount = ₹30,000

Actions:
1. Create Payment record
2. invoice.paid_amount = ₹30,000
3. invoice.status = PARTIALLY_PAID
4. invoice.outstanding_amount = ₹70,000
5. IF invoice.case EXISTS:
     case REMAINS ACTIVE (status unchanged)
     log("payment.received.partial", case_id, details={amount: 30000, remaining: 70000})
6. Background: rescore_on_payment(invoice_id)
```

#### Rule 3: Multiple Payments

```
Invoice: total_amount = ₹100,000
Payments: ₹30,000 + ₹20,000 + ₹50,000 = ₹100,000

Actions:
- Each payment follows Rule 2
- Final payment (cumulative = total) triggers Rule 1 logic
- Case resolved when invoice.paid_amount >= invoice.total_amount
```

#### Rule 4: Promise Fulfillment Check

```
Case has promise: expected_payment_date = "2024-10-15", promised_amount = ₹50,000
Payment received: payment_date = "2024-10-15", amount = ₹50,000

Actions:
1. Find active PromiseToPay WHERE case_id = X AND status = PENDING
2. IF payment_date <= promise_date AND amount >= promised_amount:
     promise.status = FULFILLED
     promise.fulfilled_by_payment_id = payment.id
   ELSE:
     promise.status = BROKEN (or remains PENDING if future)
3. Log: "promise.fulfilled" or "promise.partially_fulfilled"
```

#### Rule 5: Over-Payment

```
Invoice: total_amount = ₹100,000
Payment: amount = ₹110,000

Actions:
1. Create Payment record
2. invoice.paid_amount = ₹110,000
3. invoice.status = PAID
4. outstanding_amount = ₹0 (not negative)
5. Log warning: "payment.overpayment" details={excess: 10000}
```

### Outstanding Amount Calculation

**Currently implemented as Invoice property:**

```python
# app/models/invoice.py
@property
def outstanding_amount(self) -> Decimal:
    return max(Decimal("0.00"), self.total_amount - self.paid_amount)
```

**This is correct.** Do NOT store as database column — always computed.

---

## 4. Risk → Recovery Relationship

### Separation of Concerns

**Risk System Responsibility:**
- Score invoices/customers: 0-100
- Categorize: LOW/MEDIUM/HIGH/CRITICAL
- Explain: top factors (SHAP or heuristic)
- Track history: multiple assessments per invoice

**Recovery System Responsibility:**
- Manage collection workflow
- Track actions/contacts
- Record promises
- Link to payments
- Close cases

### Integration Points

#### Risk Influences Recovery (One Direction)

1. **Case Priority:**
   ```python
   # When creating recovery case
   if risk_score >= 80:
       case.priority = CRITICAL
   elif risk_score >= 60:
       case.priority = HIGH
   elif risk_score >= 40:
       case.priority = MEDIUM
   else:
       case.priority = LOW
   ```

2. **Dashboard Filtering:**
   ```
   GET /dashboard/recovery-queue?min_risk=60
   → Cases with latest risk_score >= 60
   ```

3. **Follow-up Timing:**
   ```python
   # Suggest next action based on risk
   if risk_score >= 80:
       case.next_follow_up_date = today + timedelta(days=1)  # Daily
   elif risk_score >= 60:
       case.next_follow_up_date = today + timedelta(days=3)  # Every 3 days
   ```

#### Recovery Does NOT Modify Risk

- ❌ Case status changes do NOT trigger automatic rescoring
- ❌ Case actions do NOT update risk_score
- ✅ Only **actual payments** trigger risk rescoring (via rescore_on_payment)

#### RiskAssessment.case_id Usage

**Current:** Field exists but unused.

**Proposed:**
```python
# When creating recovery case from high-risk invoice
assessment = await get_latest_risk(invoice_id)
case = Case(...)
db.add(case)
await db.flush()

# Link assessment to case
assessment.case_id = case.id  # Or create new assessment with case_id
```

**Purpose:** Trace which risk assessment triggered case creation.

**Query:** "Show all cases created from risk scores >= 80"
```python
stmt = select(Case).join(RiskAssessment).where(
    RiskAssessment.risk_score >= 80,
    RiskAssessment.case_id == Case.id
)
```

---

## 5. API Endpoint Refinement

### Existing Audit Action Naming Convention

**Pattern observed:**
- `ENTITY_ACTION` format (e.g., `CASE_CREATED`, `INVOICE_UPDATED`)
- lowercase.dot format for internal actions (e.g., `copilot.query`, `document.upload`)

**For recovery, use:**
- Public API actions: `CASE_CREATED`, `PAYMENT_RECORDED`, `PROMISE_RECORDED`
- Internal/background: `payment.received.full`, `promise.fulfilled`

### MVP Endpoints (Required for Working Workflow)

#### Group 1: Payment Management (NEW)
```
POST   /api/v1/payments
  Request: PaymentCreate {invoice_id, amount, payment_date, reference?}
  Response: PaymentRead
  Action: Create payment, update invoice, resolve case if fully paid, trigger rescore
  Auth: Requires "collections" or "admin" role
  Tenant: Verify invoice.organization_id == tenant.organization_id

GET    /api/v1/payments
  Query: ?invoice_id, ?customer_id, ?date_from, ?date_to, limit, offset
  Response: List[PaymentRead]
  Tenant: Filter by organization_id

GET    /api/v1/payments/{payment_id}
  Response: PaymentRead
  Tenant: Verify payment.organization_id == tenant.organization_id
```

#### Group 2: Promise-to-Pay (NEW)
```
POST   /api/v1/cases/{case_id}/promises
  Request: PromiseCreate {promise_date, promised_amount, notes?}
  Response: PromiseRead
  Action: Create promise (status=PENDING), update case.expected_payment_date, log audit
  Tenant: Verify case.organization_id == tenant.organization_id

GET    /api/v1/cases/{case_id}/promises
  Response: List[PromiseRead] (chronological, all promises)
  Tenant: Verify case.organization_id == tenant.organization_id

PATCH  /api/v1/promises/{promise_id}
  Request: PromiseUpdate {promise_date?, promised_amount?, status?, notes?}
  Response: PromiseRead
  Action: Amend promise (customer requests extension), log audit
  Tenant: Verify promise.case.organization_id == tenant.organization_id
```

#### Group 3: Case Timeline (NEW)
```
GET    /api/v1/cases/{case_id}/timeline
  Response: List[TimelineItem] {timestamp, action, user?, details}
  Query: AuditLog WHERE entity_type='Case' AND entity_id=case_id
  Enrich: Join User for user attribution
  Tenant: Verify case.organization_id == tenant.organization_id
```

#### Group 4: Recovery Actions (NEW)
```
POST   /api/v1/cases/{case_id}/actions
  Request: RecoveryActionCreate {action_type, channel?, outcome?, notes?}
  Response: Success + audit_id
  Action: Log structured audit event, update case.last_contact_date
  Examples:
    - action_type="reminder_sent", channel="email"
    - action_type="customer_contacted", channel="phone", outcome="promised_payment"
    - action_type="evidence_collected", details={document_ids: []}
  Tenant: Verify case.organization_id == tenant.organization_id
```

**Total MVP endpoints: 8**

### Later Endpoints (Deferred, Not Required for MVP)

```
GET    /api/v1/cases/{case_id}/documents  (can use GET /documents?case_id={id} instead)
POST   /api/v1/risk/invoice/{id}/create-case  (manual for now, automate later)
GET    /api/v1/dashboard/recovery-queue  (can use GET /cases?status=OPEN&next_follow_up_date<=today)
GET    /api/v1/dashboard/broken-promises  (defer to Phase 2)
GET    /api/v1/dashboard/collection-metrics  (defer to Phase 2)
```

---

## 6. Case Fields Re-evaluation

### Proposed Fields from Initial Design

1. `amount_in_recovery: Decimal`
2. `expected_payment_date: Date`
3. `last_contact_date: Date`
4. `next_follow_up_date: Date`

### Analysis

#### Field 1: amount_in_recovery

**Is it necessary?**
- Purpose: Track how much needs to be collected
- Derivable from: `invoice.outstanding_amount` (total_amount - paid_amount)

**Problem:** Cases can be about multiple invoices, or non-invoice issues.

**Decision: KEEP** with clarification:
- For single-invoice cases: `amount_in_recovery = invoice.outstanding_amount`
- For multi-invoice cases: `amount_in_recovery = SUM(invoices.outstanding_amount)`
- For non-invoice cases: `amount_in_recovery = NULL` or manually set

**Nullable:** YES  
**Indexed:** NO (not queried directly)

#### Field 2: expected_payment_date

**Is it necessary?**
- Purpose: Quick "broken promises" query
- Derivable from: `SELECT MIN(promise_date) FROM promises WHERE status=PENDING`

**Decision: KEEP**
- Denormalized for performance
- Updated automatically when promise created/fulfilled
- Enables fast query: `WHERE expected_payment_date < CURRENT_DATE AND status NOT IN ('RESOLVED', 'CLOSED')`

**Nullable:** YES  
**Indexed:** YES `(organization_id, expected_payment_date)`

#### Field 3: last_contact_date

**Is it necessary?**
- Purpose: Enforce contact cadences, avoid harassment
- Derivable from: `SELECT MAX(created_at) FROM audit_logs WHERE action LIKE 'contact.%'`

**Decision: KEEP**
- Critical for compliance (avoid over-contacting customers)
- Fast query: "Cases with no contact in 7+ days"
- Updated when action_type="customer_contacted"

**Nullable:** YES  
**Indexed:** NO (not primary query field)

#### Field 4: next_follow_up_date

**Is it necessary?**
- Purpose: Task queue for collections agents
- Derivable from: Not easily — requires business logic (escalation rules, promise dates, etc.)

**Decision: KEEP**
- Core workflow driver: `GET /cases?next_follow_up_date<=TODAY`
- Set by:
  - Promise recorded → next_follow_up = promise_date + 1 day
  - Action taken → next_follow_up = today + cadence
  - Risk-based → High risk = shorter cadence

**Nullable:** YES  
**Indexed:** YES `(organization_id, next_follow_up_date, status)`

### Final Case Fields

```python
class Case(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    # ... existing fields ...
    
    # Recovery extensions
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

**Naming:** Consistent with existing project style (snake_case, descriptive).

---

## 7. Audit Action Design

### Existing Convention Analysis

**Patterns:**
1. **Entity lifecycle:** `CASE_CREATED`, `INVOICE_UPDATED`, `CUSTOMER_DELETED`
2. **Internal operations:** `copilot.query`, `document.upload`, `document.delete`

**Format:** 
- Public/user-triggered: `ENTITY_ACTION` (uppercase, underscores)
- System/background: `namespace.action` (lowercase, dots)

### Recovery Audit Actions

**Case Lifecycle:**
```
CASE_CREATED          # Existing (reuse)
CASE_UPDATED          # Existing (reuse)
CASE_DELETED          # Existing (reuse)
```

**Recovery Actions (New):**
```
PAYMENT_RECORDED
  entity_type="Payment", entity_id=payment.id
  details={invoice_id, amount, payment_date, case_id?}

PROMISE_RECORDED
  entity_type="PromiseToPay", entity_id=promise.id
  details={case_id, promise_date, promised_amount}

PROMISE_FULFILLED
  entity_type="PromiseToPay", entity_id=promise.id
  details={payment_id, fulfilled_date, amount}

PROMISE_BROKEN
  entity_type="PromiseToPay", entity_id=promise.id
  details={promise_date, days_overdue}

CONTACT_RECORDED
  entity_type="Case", entity_id=case.id
  details={channel: "phone"|"email"|"in_person", outcome, notes}

REMINDER_SENT
  entity_type="Case", entity_id=case.id
  details={channel: "email"|"sms", recipient, template_id?}

EVIDENCE_ATTACHED
  entity_type="Case", entity_id=case.id
  details={document_ids: [...]}
```

**Background Events (lowercase):**
```
payment.received.full
payment.received.partial
payment.overpayment
promise.auto_expired
case.auto_escalated
```

### Timeline Sufficiency

**Can AuditLog serve as case timeline?** ✅ **YES**

**Query:**
```python
stmt = (
    select(AuditLog, User)
    .outerjoin(User, AuditLog.user_id == User.id)
    .where(
        AuditLog.organization_id == org_id,
        AuditLog.entity_type == "Case",
        AuditLog.entity_id == case_id
    )
    .order_by(AuditLog.created_at.desc())
)
```

**Also include related events:**
```python
# Get payment events for case's invoice
stmt_payment = select(AuditLog).where(
    AuditLog.entity_type == "Payment",
    AuditLog.details['invoice_id'] == case.invoice_id
)

# Get promise events
stmt_promise = select(AuditLog).where(
    AuditLog.entity_type == "PromiseToPay",
    AuditLog.details['case_id'] == case_id
)

# Union and sort chronologically
```

**Conclusion:** AuditLog is sufficient. No separate timeline table needed.

---

## 8. Tenant Isolation

### Enforcement Pattern (Existing)

```python
# Universal pattern used throughout PayResolve APIs
stmt = select(Entity).where(
    Entity.id == entity_id,
    Entity.organization_id == tenant.organization_id  # ← Always present
)
```

### New Recovery Endpoints - Isolation Rules

| Endpoint | Isolation Mechanism |
|----------|---------------------|
| **POST /payments** | Verify `invoice.organization_id == tenant.organization_id` before creating payment |
| **GET /payments** | Filter `Payment.organization_id == tenant.organization_id` |
| **GET /payments/{id}** | WHERE `Payment.id == id AND Payment.organization_id == tenant.organization_id` |
| **POST /cases/{id}/promises** | Verify `case.organization_id == tenant.organization_id` before creating promise |
| **GET /cases/{id}/promises** | Get case first (tenant-checked), then `promise.case_id == case.id` |
| **PATCH /promises/{id}** | JOIN promises → cases WHERE `cases.organization_id == tenant.organization_id` |
| **GET /cases/{id}/timeline** | Filter `AuditLog.organization_id == tenant.organization_id AND entity_id == case.id` |
| **POST /cases/{id}/actions** | Verify `case.organization_id == tenant.organization_id` before logging action |

### Database-Level Guarantees

**FK constraints (existing):**
```sql
ALTER TABLE cases
  ADD CONSTRAINT fk_case_org
  FOREIGN KEY (organization_id) REFERENCES organizations(id)
  ON DELETE CASCADE;

ALTER TABLE payments
  ADD CONSTRAINT fk_payment_org
  FOREIGN KEY (organization_id) REFERENCES organizations(id)
  ON DELETE CASCADE;
```

**New FK for PromiseToPay:**
```sql
CREATE TABLE promises_to_pay (
  id UUID PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  ...
);

CREATE INDEX idx_promises_org_status ON promises_to_pay(organization_id, status);
```

### Cross-Tenant Attack Vectors

**Prevented:**
1. ✅ User A cannot view User B's cases (filtered by organization_id)
2. ✅ User A cannot create payment for User B's invoice (invoice lookup fails)
3. ✅ User A cannot view User B's case timeline (AuditLog filtered by org_id)
4. ✅ User A cannot create promise on User B's case (case lookup fails, returns 404)

**Return 404, not 403:** Prevents entity existence leakage across tenants.

---

## 9. Database Schema - FINAL

### Existing Tables (Reused, No Changes)

**Organizations, Users, Customers, Invoices, Documents, AuditLog, RiskAssessment**

### Modified Table: Case

```sql
ALTER TABLE cases ADD COLUMN amount_in_recovery NUMERIC(15,2);
ALTER TABLE cases ADD COLUMN expected_payment_date DATE;
ALTER TABLE cases ADD COLUMN last_contact_date DATE;
ALTER TABLE cases ADD COLUMN next_follow_up_date DATE;

CREATE INDEX idx_cases_expected_payment
  ON cases(organization_id, expected_payment_date)
  WHERE expected_payment_date IS NOT NULL;

CREATE INDEX idx_cases_next_followup
  ON cases(organization_id, next_follow_up_date, status)
  WHERE next_follow_up_date IS NOT NULL;
```

### New Table: PromiseToPay

```sql
CREATE TABLE promises_to_pay (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  
  promise_date DATE NOT NULL,
  promised_amount NUMERIC(15,2) NOT NULL CHECK (promised_amount > 0),
  status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'FULFILLED', 'BROKEN', 'CANCELLED')),
  
  fulfilled_by_payment_id UUID REFERENCES payments(id) ON DELETE SET NULL,
  notes TEXT,
  
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  
  CONSTRAINT fk_promise_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
  CONSTRAINT fk_promise_case FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
);

CREATE INDEX idx_promises_case ON promises_to_pay(case_id);
CREATE INDEX idx_promises_org_status ON promises_to_pay(organization_id, status);
CREATE INDEX idx_promises_date_status ON promises_to_pay(promise_date, status)
  WHERE status = 'PENDING';
```

### Existing Table: Payment (No Changes, API Only)

```sql
-- Already exists, no schema changes
CREATE TABLE payments (
  id UUID PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  amount NUMERIC(15,2) NOT NULL,
  payment_date DATE NOT NULL,
  reference VARCHAR(100),
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
```

### Entity Relationships

```
Organization
 ├─ User
 ├─ Customer
 ├─ Invoice
 │   ├─ Payment (many)
 │   ├─ Case (one, optional)
 │   └─ RiskAssessment (many, history)
 ├─ Case
 │   ├─ PromiseToPay (many)
 │   └─ Document (many, evidence)
 ├─ AuditLog (all entity events)
 └─ Document (uploaded evidence)
```

**Total new tables: 1** (PromiseToPay)

---

## 10. Test Strategy

### Test Coverage Matrix

#### Unit/Integration Tests (Per Module)

**test_payments.py** (NEW)
```python
test_create_payment_success()
test_create_payment_updates_invoice()
test_full_payment_marks_invoice_paid()
test_partial_payment_sets_partially_paid()
test_multiple_payments_cumulative()
test_payment_resolves_case_when_invoice_paid()
test_payment_triggers_risk_rescore()
test_create_payment_for_other_org_invoice_fails()  # Tenant isolation
test_create_payment_negative_amount_fails()
test_overpayment_handled_correctly()
```

**test_promises.py** (NEW)
```python
test_create_promise_success()
test_create_promise_updates_case_expected_date()
test_list_case_promises()
test_amend_promise_date()
test_cancel_promise()
test_promise_fulfilled_by_payment()
test_promise_broken_detection()
test_multiple_promises_per_case()
test_create_promise_for_other_org_case_fails()  # Tenant isolation
test_past_promise_date_fails_validation()
```

**test_case_timeline.py** (NEW)
```python
test_get_case_timeline()
test_timeline_includes_case_events()
test_timeline_includes_payment_events()
test_timeline_includes_promise_events()
test_timeline_chronological_order()
test_timeline_user_attribution()
test_timeline_other_org_case_fails()  # Tenant isolation
```

**test_recovery_actions.py** (NEW)
```python
test_record_customer_contact()
test_record_reminder_sent()
test_record_evidence_attached()
test_action_updates_last_contact_date()
test_action_creates_audit_entry()
test_record_action_other_org_case_fails()  # Tenant isolation
```

**test_cases.py** (UPDATED)
```python
# Existing tests remain
test_create_case_with_recovery_fields()  # NEW
test_case_amount_in_recovery_validation()  # NEW
test_case_next_followup_query()  # NEW
```

**test_recovery_integration.py** (NEW - End-to-End)
```python
test_full_recovery_workflow()
  # 1. Create invoice
  # 2. Score as high risk
  # 3. Create recovery case
  # 4. Record promise
  # 5. Record payment
  # 6. Verify case resolved
  # 7. Check timeline

test_broken_promise_workflow()
  # 1. Create case + promise
  # 2. Advance time past promise_date
  # 3. No payment received
  # 4. Promise status = BROKEN
  # 5. Next follow-up scheduled

test_multi_invoice_case()
  # 1. Create case linked to multiple invoices
  # 2. Partial payment on one invoice
  # 3. Case remains active
  # 4. Full payment on all
  # 5. Case resolved
```

#### Regression Tests

**Run existing suite after each phase:**
- ✅ Target: 50 passed (existing baseline)
- ✅ All existing tests MUST pass
- ✅ No weakening of existing behavior

#### Tenant Isolation Tests

**For EVERY new endpoint:**
```python
async def test_{endpoint}_tenant_isolation(client, two_org_context):
    # Org A creates entity
    entity_a = await create_in_org_a(...)
    
    # Org B attempts access
    response = await client.get(f"/api/v1/{endpoint}/{entity_a.id}", headers=org_b_headers)
    
    # Expect 404 (not 403, no info leak)
    assert response.status_code == 404
```

#### Performance Tests (Deferred to Post-MVP)

```python
test_timeline_query_performance()  # <100ms for 1000 audit entries
test_broken_promises_query_performance()  # <50ms for 10k cases
```

---

## 11. APPROVED DESIGN PROPOSAL

### Summary

**Extend existing Case model** with 4 fields.  
**Add PromiseToPay table** for structured promise tracking.  
**Create Payment API** for existing Payment model.  
**Use AuditLog** for timeline.

### 1. Existing Components Reused

| Component | Usage |
|-----------|-------|
| Case model | Extended with 4 nullable fields |
| AuditLog | Timeline + recovery action tracking |
| Payment model | API created, model unchanged |
| RiskAssessment | Link via case_id, influences priority |
| Invoice | outstanding_amount drives case resolution |
| Document | Evidence linkage via case_id (existing) |

### 2. New Tables

**PromiseToPay:**
- Fields: promise_date, promised_amount, status, fulfilled_by_payment_id
- Relationships: case_id (FK), payment_id (FK, nullable)
- Indexes: (organization_id, status), (case_id), (promise_date, status)

**Total: 1 new table**

### 3. New Case Fields

```python
amount_in_recovery: Optional[Decimal]      # Nullable, tracks collection target
expected_payment_date: Optional[Date]      # Nullable, indexed, next promise date
last_contact_date: Optional[Date]          # Nullable, compliance tracking
next_follow_up_date: Optional[Date]        # Nullable, indexed, task queue driver
```

### 4. Payment Workflow

```
POST /payments → Create Payment
              → Update Invoice (paid_amount, status)
              → IF fully paid: Resolve Case
              → Check PromiseToPay fulfillment
              → Log PAYMENT_RECORDED
              → Background: rescore_on_payment()
```

### 5. Promise-to-Pay Workflow

```
POST /cases/{id}/promises → Create PromiseToPay (status=PENDING)
                         → Update Case.expected_payment_date
                         → Update Case.next_follow_up_date
                         → Log PROMISE_RECORDED

Payment received → Check matching promise
                → IF match: promise.status = FULFILLED
                → ELSE: promise.status = BROKEN

GET /cases/{id}/promises → List all promises (history)
```

### 6. Risk Integration

- RiskAssessment.case_id set when case created from high-risk invoice
- Case.priority set based on risk_score (≥80 → CRITICAL, ≥60 → HIGH, etc.)
- Risk rescoring triggered ONLY by actual payments (not case actions)

### 7. Audit/Timeline Design

**Actions:**
- CASE_CREATED, CASE_UPDATED (existing)
- PAYMENT_RECORDED (new)
- PROMISE_RECORDED, PROMISE_FULFILLED, PROMISE_BROKEN (new)
- CONTACT_RECORDED, REMINDER_SENT (new)

**Timeline API:**
```
GET /cases/{id}/timeline → Query AuditLog
                        → Include Case, Payment, Promise events
                        → Enrich with User info
                        → Order chronologically
```

### 8. MVP APIs (8 endpoints)

**Payment:**
- POST /api/v1/payments
- GET /api/v1/payments
- GET /api/v1/payments/{id}

**Promise:**
- POST /api/v1/cases/{id}/promises
- GET /api/v1/cases/{id}/promises
- PATCH /api/v1/promises/{id}

**Timeline & Actions:**
- GET /api/v1/cases/{id}/timeline
- POST /api/v1/cases/{id}/actions

### 9. Tenant Isolation Rules

**Every endpoint:**
- WHERE Entity.organization_id == tenant.organization_id
- FK traversal: case → invoice → payment (all checked)
- Return 404 for cross-tenant attempts (not 403)

**Database:**
- All tables have organization_id FK with ON DELETE CASCADE
- Indexes include organization_id as first column

### 10. Migration Plan

**Phase 1: Models & Migration** (1 day)
- Add 4 fields to Case model
- Create PromiseToPay model
- Write migration scripts
- Run migration on test DB
- Verify existing 50 tests pass

**Phase 2: Payment API** (2 days)
- Create app/schemas/payment.py
- Create app/api/v1/payments.py
- Implement POST/GET endpoints
- Wire rescore_on_payment
- Write test_payments.py (10+ tests)
- Verify all tests pass

**Phase 3: Promise-to-Pay** (1.5 days)
- Create app/schemas/promise.py
- Create app/models/promise.py (ORM)
- Implement promise endpoints
- Wire promise fulfillment check
- Write test_promises.py (8+ tests)
- Verify all tests pass

**Phase 4: Timeline & Actions** (1 day)
- Implement GET /cases/{id}/timeline
- Implement POST /cases/{id}/actions
- Write test_case_timeline.py, test_recovery_actions.py
- Verify all tests pass

**Phase 5: Integration** (1.5 days)
- Wire payment → promise check → case resolution
- Update RiskAssessment to set case_id
- Write test_recovery_integration.py (3 end-to-end tests)
- Full regression: Target 70+ tests passing

**Total: 7 days**

### 11. Test Plan

**Minimum test count: 35+**
- test_payments.py: 10 tests
- test_promises.py: 8 tests
- test_case_timeline.py: 5 tests
- test_recovery_actions.py: 4 tests
- test_cases.py (updated): +3 tests
- test_recovery_integration.py: 3 tests
- Tenant isolation: 2+ tests per new endpoint

**Regression:** All existing 50 tests MUST pass.

**Target: 85+ tests passing, 0 failed**

---

## 12. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| **Tenant breach** | Low | Critical | Use WHERE organization_id pattern everywhere, add tenant isolation tests |
| **Case migration fails** | Low | High | Fields nullable, no data loss, test on copy first |
| **Payment double-recording** | Medium | High | Add unique constraint on (invoice_id, reference) if reference used |
| **Promise state corruption** | Low | Medium | Use DB transactions, add state validation |
| **AuditLog growth** | Medium | Medium | Existing concern, plan archival separately (not recovery-specific) |
| **Broken promise queries slow** | Low | Low | Index on (promise_date, status) where status='PENDING' |
| **Race: payment/promise** | Low | Medium | Use DB transaction for payment → promise check |
| **Existing tests regress** | Low | Critical | Run suite after each phase, stop if any fail |

---

## IMPLEMENTATION DECISION

**Status: READY FOR IMPLEMENTATION** ✅

This design:
1. ✅ Extends existing Case system (no duplicate entity)
2. ✅ Adds PromiseToPay table (structured promise tracking justified)
3. ✅ Defines precise payment → invoice → case behavior
4. ✅ Separates Risk (scoring) from Recovery (workflow)
5. ✅ Proposes 8 MVP endpoints (focused, no bloat)
6. ✅ Validates all 4 Case fields as necessary
7. ✅ Uses AuditLog for timeline (no separate table)
8. ✅ Enforces tenant isolation at every layer
9. ✅ Specifies complete schema (1 new table, 4 new fields)
10. ✅ Provides comprehensive test plan (35+ new tests)

**Baseline preserved:** 50 passed, 0 failed, 0 errors

**No unresolved questions.**

---

*End of final design document.*
