# Phase 5: Recovery Workflow — Technical Plan

## Context Summary

**Completed Foundation (Phases 1-4):**
- ✅ Auth + tenant isolation
- ✅ Invoice/Case/Customer CRUD with auto-overdue classification
- ✅ Document intelligence (OCR + extraction + evidence)
- ✅ RAG copilot (Qdrant-backed, cited, injection-resistant)
- ✅ ML risk scoring (dual-mode: heuristic cold-start + ML with SHAP)
- ✅ 39/39 tests passing

**This Phase Goal:**
Turn an overdue, risk-scored case into tracked follow-up actions and grounded generated documents (reminders, dispute summaries, evidence packages).

---

## 1. WORKFLOW STATES & SCHEMA DESIGN

### Approach: Extend Case Model with Workflow Tracking

**Decision:** Add `workflow_stage` field to existing `Case` model rather than separate table.
- **Rationale:** Keeps case data cohesive; workflow is intrinsic to case lifecycle
- **Migration:** Add nullable enum column, default to 'created' for existing cases

### Workflow States (Linear + Optional Branch)

```python
class WorkflowStage(str, Enum):
    CREATED = "created"                    # Initial state
    EVIDENCE_COLLECTED = "evidence_collected"  # Documents linked, data verified
    ANALYZED = "analyzed"                  # Risk assessed, ready for action
    REMINDER_SENT = "reminder_sent"        # First reminder generated & sent
    FOLLOW_UP = "follow_up"                # Awaiting response, tracking next action
    DISPUTED = "disputed"                  # Customer disputes (optional branch)
    RESOLVED = "resolved"                  # Payment received or settled
    ESCALATED = "escalated"                # Sent to collections/legal
```

**Allowed Transitions:**
```
created → evidence_collected → analyzed → reminder_sent → follow_up → resolved
                                                    ↓
                                                disputed → resolved/escalated
                                       follow_up → escalated
```

### New Table: `case_workflow_history`

Track stage transitions with timestamps and user attribution:

```python
class CaseWorkflowHistory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "case_workflow_history"
    
    organization_id: str                   # Tenant scoping
    case_id: str                           # FK to cases
    from_stage: Optional[WorkflowStage]    # NULL for initial state
    to_stage: WorkflowStage
    changed_by_user_id: str                # Who triggered transition
    notes: Optional[str]                   # Reason/context
    # created_at from TimestampMixin provides timestamp
```

### New Table: `follow_up_tasks`

Lightweight task tracking per case:

```python
class FollowUpTask(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "follow_up_tasks"
    
    organization_id: str
    case_id: str                           # FK to cases
    assigned_to_user_id: Optional[str]     # FK to users, nullable
    due_date: date
    title: str
    notes: Optional[str]
    completed: bool = False
    completed_at: Optional[datetime] = None
```

### Schema for `GeneratedDocument` (already exists)

Extend with new doc_types:

```python
class DocType(str, Enum):
    # Existing from Phase 3:
    INVOICE_SUMMARY = "invoice_summary"
    CONTRACT_EXTRACT = "contract_extract"
    # New for Phase 5:
    PAYMENT_REMINDER = "payment_reminder"
    DISPUTE_SUMMARY = "dispute_summary"
    EVIDENCE_PACKAGE = "evidence_package"
```

Add `status` field to GeneratedDocument:

```python
class GeneratedDocument:
    # ... existing fields ...
    status: str  # "draft" | "sent" | "archived"
    sent_at: Optional[datetime] = None
    sent_by_user_id: Optional[str] = None
```

---

## 2. REMINDER GENERATION

### Approach: Grounded Template-Based Generation via LLM

**Reuse:** Phase 3 LLM abstraction (`app/services/copilot_service.py` → extract LLM client wrapper)

### Two-Tone System

**Tone 1: Friendly First Reminder**
- Language: Professional but warm
- Assumptions: Oversight, benefit of doubt
- Template constraints: Must include invoice#, amount, due date, days overdue
- Optional: Payment terms if verified in case documents

**Tone 2: Formal Final Notice**
- Language: Firm, professional, escalation signal
- Assumptions: Awareness of overdue status
- Template constraints: Same required facts + "final notice" language
- Optional: Penalty clause if extracted from contract with citation

### Generation Flow

```python
async def generate_payment_reminder(
    db: AsyncSession,
    case_id: str,
    tone: Literal["friendly", "formal"],
    org_id: str,
) -> GeneratedDocument:
    """
    1. Load case + linked invoice + customer + extracted payment terms (if any)
    2. Build verified_facts dict (only present/documented data)
    3. Construct LLM prompt with:
       - Required facts (invoice#, amount, due_date, days_overdue)
       - Optional facts (payment_terms IF extracted with evidence)
       - Strict instruction: "Do not infer or add facts not provided"
       - Tone guidance (friendly vs formal)
    4. Call LLM (reuse Phase 3 client, ~300 token limit)
    5. Post-process: verify no fabricated facts (regex check for common fabrications)
    6. Persist as GeneratedDocument with status="draft", doc_type="payment_reminder"
    7. Return for user review
    """
```

### Fact Verification Guards

- **Required facts:** Always present (from invoice model)
- **Optional facts:** Only include if `evidence_source_id` exists
  - Payment terms → check if extracted from document
  - Penalty clause → check if extracted with `field_name="penalty_clause"`
- **Forbidden inferences:** 
  - "as per our agreement" (unless contract doc_id present)
  - Specific penalty amounts (unless extracted with citation)
  - Legal threats (reserved for formal tone + explicit user edit)

### Prompt Template Structure

```
You are generating a {tone} payment reminder for PayResolve.

VERIFIED FACTS (use only these):
- Invoice Number: {invoice_number}
- Amount Due: {currency} {amount}
- Original Due Date: {due_date}
- Days Overdue: {days_overdue}
- Customer Name: {customer_name}
{optional_payment_terms}

INSTRUCTIONS:
- Write a {tone} reminder email body (subject line + body)
- Do NOT infer or add facts not listed above
- If payment terms are absent, do not mention contract clauses
- Keep under 200 words
- Professional tone, no legal advice

TONE GUIDANCE:
{tone_specific_guidance}

Generate the reminder:
```

---

## 3. DISPUTE SUMMARY GENERATION

### Approach: RAG-Based Grounded Summary

**Reuse:** Phase 3 RAG copilot pattern:
- `retrieval_service.retrieve_relevant_chunks()`
- Citation format: `[evidence source: document_id]`
- Confidence labels: `verified`, `inferred`, `missing`

### Generation Flow

```python
async def generate_dispute_summary(
    db: AsyncSession,
    case_id: str,
    org_id: str,
) -> GeneratedDocument:
    """
    1. Verify case.workflow_stage == "disputed"
    2. Retrieve all linked documents for the case
    3. Query RAG: "Summarize the customer's dispute points and any supporting documentation"
    4. Build summary with:
       - Dispute reason (from case.summary if present)
       - Cited evidence (RAG chunks with doc_id)
       - Missing information (explicit "no contract on file" if absent)
       - Legal disclaimer
    5. Persist as GeneratedDocument status="draft"
    """
```

### Disclaimer Template

```
ADMINISTRATIVE SUMMARY DISCLAIMER:
This is a system-generated summary of case documents and correspondence for 
internal administrative use only. It is NOT legal advice and does NOT constitute 
a legal assessment of the dispute's merit or likelihood of recovery. Consult 
qualified legal counsel before taking legal action.
```

### Output Structure

```markdown
## Dispute Summary: Case {case_number}

**Customer:** {customer_name}
**Invoice:** {invoice_number} — {currency} {amount}
**Dispute Filed:** {dispute_date}

### Dispute Points
{customer_stated_reasons_from_case_summary}

### Supporting Evidence
{cited_documents_from_RAG}

### Missing Information
{explicit_list_of_absent_evidence}

### Recovery Recommendation
{grounded_next_steps_based_on_evidence}

---
{disclaimer}
```

---

## 4. EVIDENCE PACKAGE EXPORT

### Format Decision: **PDF** (not ZIP)

**Rationale:**
- Existing PDF tooling from Phase 2 (PyMuPDF for extraction)
- ReportLab or WeasyPrint for generation
- Single-file delivery simpler for email/review
- Professional appearance for external use

**Alternative considered:** ZIP with individual files
- **Rejected:** Requires recipient to unzip, less cohesive
- **Use case for ZIP:** If documents need to be editable (future enhancement)

### Export Structure

```
Evidence Package: Case {case_number}
Generated: {timestamp}

Page 1: Cover Sheet
- Case summary (number, customer, invoice, dates)
- Workflow stage history
- Risk assessment timeline

Page 2-N: Document Attachments
- For each linked document:
  * Document title and upload date
  * Extracted text (if OCR'd)
  * Extracted key fields with citations
  * "MISSING" marker if document referenced but not uploaded

Page N+1: Payment Timeline
- Invoice issue/due dates
- Payment attempts (if any)
- Overdue calculation

Page N+2: Risk Assessment History
- Score evolution over time
- Contributing factors from latest assessment
- Model version used

Page N+3: Correspondence Log
- Generated reminders (with sent status)
- Dispute summary (if applicable)

Footer: "Generated by PayResolve AI - Not Legal Advice"
```

### Generation Flow

```python
async def export_evidence_package(
    db: AsyncSession,
    case_id: str,
    org_id: str,
) -> bytes:  # Returns PDF bytes
    """
    1. Load case + invoice + customer + all linked documents
    2. Load workflow history
    3. Load risk assessment history
    4. Load generated documents (reminders, summaries)
    5. Load follow-up tasks
    6. Build PDF using reportlab:
       - Cover sheet with case metadata
       - Document pages with "MISSING" markers for absent evidence
       - Payment timeline
       - Risk history chart/table
       - Correspondence log
    7. Return PDF bytes (stream to user or save as GeneratedDocument)
    """
```

### Missing Evidence Handling

```python
def render_document_page(doc_metadata, actual_document):
    if actual_document is None:
        return f"""
        [MISSING DOCUMENT]
        
        Referenced: {doc_metadata.expected_name}
        Expected Type: {doc_metadata.expected_type}
        Status: Not Uploaded
        
        This document was referenced in the case but has not been uploaded.
        """
    else:
        return actual_document.render()
```

---

## 5. FOLLOW-UP TRACKING

### Simple Task Model (Already Defined Above)

**Frontend Integration:**
- Case detail view: "Follow-Up Tasks" section
- Add task: Due date picker, assignee selector, notes field
- Mark complete: Checkbox + timestamp capture

### Dashboard "Due for Follow-Up" Query

```python
async def get_due_followups(
    db: AsyncSession,
    org_id: str,
    user_id: Optional[str] = None,
) -> List[FollowUpTask]:
    """
    Return tasks where:
    - due_date <= today + 3 days (upcoming)
    - completed = False
    - case.workflow_stage NOT IN ("resolved", "escalated")
    - optionally filter by assigned_to_user_id
    """
```

### Dashboard Widget

```
📅 Follow-Ups Due (5)
─────────────────────────
• Case #C-123: Follow up with Acme Corp
  Due: Tomorrow

• Case #C-456: Send final notice to Widget Inc
  Due: Today (overdue)

[View All Follow-Ups →]
```

---

## 6. BACKEND API ENDPOINTS

### Case Workflow

```python
@router.patch("/cases/{case_id}/stage")
async def advance_case_stage(
    case_id: str,
    payload: CaseStageUpdate,  # { to_stage: WorkflowStage, notes?: str }
    tenant: TenantContext,
    db: AsyncSession,
):
    """
    Validates transition, updates case.workflow_stage, creates workflow_history row.
    Audit-logged.
    """
```

### Document Generation

```python
@router.post("/cases/{case_id}/generate-reminder")
async def generate_reminder(
    case_id: str,
    payload: ReminderRequest,  # { tone: "friendly" | "formal" }
    tenant: TenantContext,
    db: AsyncSession,
) -> GeneratedDocumentRead:
    """
    Generates draft reminder, returns for review.
    Does NOT auto-send.
    """

@router.post("/cases/{case_id}/generate-dispute-summary")
async def generate_dispute_summary(...) -> GeneratedDocumentRead:
    """
    Requires case.workflow_stage == "disputed".
    Returns draft summary with citations.
    """

@router.get("/cases/{case_id}/export-evidence")
async def export_evidence_package(...) -> FileResponse:
    """
    Streams PDF evidence package.
    """
```

### Generated Document Actions

```python
@router.patch("/generated-documents/{doc_id}/send")
async def mark_document_sent(
    doc_id: str,
    tenant: TenantContext,
    db: AsyncSession,
):
    """
    Updates status="sent", sent_at=now(), sent_by_user_id.
    Audit-logged.
    Does NOT actually send email (that's external to system).
    """
```

### Follow-Up Tasks

```python
@router.post("/cases/{case_id}/follow-ups")
async def create_followup_task(...) -> FollowUpTaskRead

@router.patch("/follow-ups/{task_id}")
async def update_followup_task(...)  # Mark complete, update due date

@router.get("/follow-ups/due")
async def list_due_followups(...)  # Dashboard query
```

---

## 7. FRONTEND INTEGRATION

### CasesPage Case Detail View Enhancement

**Existing:** Case list table with expandable rows
**Add:** Tabbed detail view when row clicked

```
Case #C-123: Overdue Payment — Acme Corp
─────────────────────────────────────────────────────────────
[Overview] [Workflow] [Documents] [Generated] [Follow-Ups]

─── Workflow Tab ─────────────────────────────────────────────
Current Stage: [Follow-Up ▼]  [Advance Stage →]

Timeline:
✓ Created              Jan 15, 10:00 AM  by Alice
✓ Evidence Collected   Jan 16, 02:30 PM  by Alice
✓ Analyzed             Jan 16, 03:00 PM  by System (auto)
✓ Reminder Sent        Jan 17, 09:00 AM  by Alice
● Follow-Up            Jan 18, 11:00 AM  by Alice
  
─── Generated Tab ────────────────────────────────────────────
[+ Generate Reminder] [+ Generate Dispute Summary]

Generated Documents:
┌─────────────────────────────────────────────────────────┐
│ Payment Reminder (Friendly)          Draft              │
│ Generated: Jan 17, 09:00 AM                             │
│ [Preview] [Edit] [Mark as Sent]                         │
└─────────────────────────────────────────────────────────┘

─── Follow-Ups Tab ───────────────────────────────────────────
[+ Add Task]

Tasks:
☐ Follow up if no response by Jan 25
  Assigned: Alice  |  Due: Jan 25  |  [Mark Complete]

─── Overview Tab (Enhanced) ──────────────────────────────────
[Export Evidence Package] button in top-right
```

### Reminder Generation Modal

```
┌───────────────────────────────────────────────────┐
│ Generate Payment Reminder                         │
├───────────────────────────────────────────────────┤
│                                                   │
│ Tone: (•) Friendly First Reminder                │
│       ( ) Formal Final Notice                     │
│                                                   │
│ [Generate Preview]                                │
│                                                   │
│ ┌─────────────────────────────────────────────┐ │
│ │ Subject: Payment Reminder — Invoice #INV-123│ │
│ │                                             │ │
│ │ Dear Acme Corp,                             │ │
│ │                                             │ │
│ │ We noticed that Invoice #INV-123 for        │ │
│ │ $5,000.00, due on January 10, 2026, is     │ │
│ │ currently 8 days overdue.                   │ │
│ │                                             │ │
│ │ [... editable preview ...]                  │ │
│ └─────────────────────────────────────────────┘ │
│                                                   │
│ ⚠️ This is a DRAFT. Review carefully before      │
│    marking as sent. System does not auto-send.   │
│                                                   │
│ [Cancel]  [Save as Draft]  [Edit & Send]         │
└───────────────────────────────────────────────────┘
```

### Evidence Package Export

- Button on case detail view: "📄 Export Evidence Package"
- Triggers API call, streams PDF download
- Filename: `PayResolve_Case_{case_number}_Evidence_{timestamp}.pdf`

### Reuse Existing UI Patterns

- **Evidence drawer from Phase 3:** Use for document citations in dispute summary
- **Risk badge from Phase 4:** Already shows on CasesPage, link to risk history
- **Audit log display:** Show workflow transitions in timeline

---

## 8. TESTS REQUIRED

### Unit Tests

```python
# tests/test_recovery_workflow.py

async def test_reminder_omits_unverified_penalty_clause(...)
    # Case has no contract document with penalty clause
    # Generated reminder must NOT mention penalties
    
async def test_reminder_includes_verified_payment_terms(...)
    # Case has contract with extracted payment terms
    # Reminder includes terms with citation
    
async def test_workflow_stage_transition_audit_logged(...)
    # Advance stage, verify audit_log entry created
    
async def test_dispute_summary_cites_evidence(...)
    # Generate summary, verify [doc_id] citations present
    
async def test_dispute_summary_labels_missing_info(...)
    # Case missing contract, verify "no contract on file" explicit
    
async def test_evidence_package_shows_missing_marker(...)
    # Case references 3 docs, only 2 uploaded
    # PDF must show "MISSING DOCUMENT" for 3rd
    
async def test_generated_document_draft_status_default(...)
    # New reminder has status="draft"
    
async def test_mark_sent_requires_explicit_action(...)
    # Verify no auto-send path exists
    
async def test_tenant_isolation_workflow_endpoints(...)
    # Org1 cannot advance Org2's case stage
```

### Integration Tests

```python
async def test_end_to_end_reminder_flow(...)
    # Create case → collect evidence → generate reminder → review → mark sent
    
async def test_followup_appears_on_dashboard(...)
    # Create task due tomorrow → verify in /follow-ups/due
```

---

## 9. IMPLEMENTATION ORDER

### Phase 5A: Workflow Foundation (Week 1)
1. ✅ Database migration: Add workflow_stage to cases, create workflow_history table
2. ✅ CaseStageUpdate schema + endpoint
3. ✅ Audit logging integration
4. ✅ Frontend: Workflow tab with stage timeline
5. ✅ Tests: Stage transitions + audit

### Phase 5B: Reminder Generation (Week 2)
1. ✅ Extract LLM client wrapper from copilot_service (make reusable)
2. ✅ Reminder generation service with tone variants
3. ✅ Fact verification guards (check for evidence)
4. ✅ GeneratedDocument status field + endpoints
5. ✅ Frontend: Generate reminder modal with preview
6. ✅ Tests: Omission of unverified facts

### Phase 5C: Dispute & Export (Week 3)
1. ✅ Dispute summary generation (RAG-based)
2. ✅ Evidence package PDF generator (reportlab)
3. ✅ Missing evidence markers in export
4. ✅ Frontend: Dispute summary panel + export button
5. ✅ Tests: Citation presence, missing markers

### Phase 5D: Follow-Up Tracking (Week 4)
1. ✅ FollowUpTask model + CRUD endpoints
2. ✅ Dashboard due-followups query
3. ✅ Frontend: Task list on case detail + dashboard widget
4. ✅ Tests: Task completion, dashboard query

---

## 10. KEY DESIGN PRINCIPLES

### Grounded Generation (No Fabrication)
- **Every fact has a source:** Invoice model, extracted field, or RAG chunk
- **Explicit omission:** If data missing, say "not available" rather than infer
- **Post-generation verification:** Regex checks for common fabrications
- **User review required:** All generated docs start as "draft"

### Transparency & User Control
- **No auto-send:** User must explicitly mark reminder "sent"
- **Audit trail:** Every stage transition logged with user_id + timestamp
- **Legal disclaimers:** Every generated doc includes appropriate warning
- **Missing evidence visible:** Export shows gaps, not just successes

### Reuse Over Reinvention
- **LLM client:** Extract from Phase 3, don't hardcode new provider
- **RAG pattern:** Reuse retrieval_service for dispute summaries
- **UI components:** Extend existing drawer/badge patterns
- **Audit service:** Use existing log_audit_event throughout

### Tenant Isolation (Security First)
- **All queries filter by organization_id**
- **Cross-org access returns 404 (not 403 to avoid info leak)**
- **Workflow history/tasks scoped per-org**
- **Generated docs never cross tenant boundaries**

---

## 11. DELIVERABLE VALIDATION

A user can:
1. ✅ See a case's workflow stage and full transition history
2. ✅ Generate a friendly or formal reminder with verified facts only
3. ✅ Review the reminder draft before marking it sent (no auto-send)
4. ✅ Generate a dispute summary with RAG citations and explicit "missing" labels
5. ✅ Export a comprehensive PDF evidence package showing all docs + gaps
6. ✅ Create follow-up tasks and see due tasks on dashboard
7. ✅ Trace every generated claim back to verified source data
8. ✅ See legal disclaimers on all generated documents

---

## 12. DEPENDENCIES & INTEGRATION

### New Python Packages
```txt
reportlab>=4.0.0      # PDF generation
markdown>=3.5.0       # Markdown to PDF if using WeasyPrint alternative
```

### LLM Integration
- **Provider agnostic:** Use existing copilot_service abstraction
- **Fallback:** If LLM unavailable, return template-only reminder (basic substitution)
- **Token limits:** Reminder ~300 tokens, Dispute summary ~800 tokens

### Frontend Dependencies
- No new packages (uses existing React + Tailwind)
- PDF download via Blob + saveAs pattern

---

## READY TO IMPLEMENT?

This plan provides:
- ✅ Schema design (workflow_stage, workflow_history, follow_up_tasks)
- ✅ Generation approach (grounded LLM + RAG + PDF)
- ✅ Export format decision (PDF over ZIP)
- ✅ API endpoints specification
- ✅ Frontend integration points
- ✅ Test coverage requirements
- ✅ Implementation phasing

**Next step:** Confirm plan, then proceed with Phase 5A implementation (workflow foundation).
