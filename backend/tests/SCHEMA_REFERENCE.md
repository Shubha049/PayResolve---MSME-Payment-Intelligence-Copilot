# Schema Reference for test_risk.py

## User
- Fields: email, hashed_password, full_name, is_active, id, created_at, updated_at
- **NO organization_id field**
- Association with Organization via OrganizationMember

## Organization
- Fields: name, slug, id, created_at, updated_at

## OrganizationMember
- Fields: organization_id, user_id, role, id, created_at, updated_at

## Customer
- Fields: organization_id, name, tax_id, email, phone, address, id, created_at, updated_at

## Invoice
- Fields: organization_id, customer_id, invoice_number, issue_date, due_date, currency, **total_amount**, paid_amount, status, notes, id, created_at, updated_at
- **Use total_amount NOT amount**

## Case
- Fields: organization_id, customer_id, invoice_id, **case_number**, title, status, priority, assigned_to_user_id, **summary**, id, created_at, updated_at
- **Use summary NOT description**
- **case_number is REQUIRED**

## Payment
- Fields: organization_id, invoice_id, **amount**, payment_date, reference, id, created_at, updated_at
- **Payment uses amount (not total_amount)**

## RiskAssessment
- Fields: organization_id, invoice_id, customer_id, case_id, risk_score, risk_category, top_factors, model_version, scoring_method, id, created_at, updated_at

## Enums

### InvoiceStatus
- DRAFT, ISSUED, PARTIALLY_PAID, PAID, OVERDUE, DISPUTED, WRITTEN_OFF
- **NO PENDING** - use ISSUED instead

### CaseStatus
- OPEN, EVIDENCE_GATHERING, REMINDER_SENT, IN_DISPUTE, ESCALATED, RESOLVED, CLOSED

### CasePriority  
- LOW, MEDIUM, HIGH, CRITICAL

## Auth Token Creation
```python
from app.services.auth_service import create_access_token
# Token payload needs organization_id from membership, not user
# For tests, get org_id from fixture org.id
token = create_access_token(subject=user.id, organization_id=org.id)
```
