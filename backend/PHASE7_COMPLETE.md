# Phase 7 Complete: Recovery Copilot / RAG

## Architecture

Phase 7 adds a recovery-focused query path to the existing Copilot router. Recovery records are retrieved directly from SQL because cases, invoices, payments, promises, recovery actions, and audit entries are structured current-state data. Existing Qdrant semantic retrieval is reused only for uploaded document/evidence questions; no new vector architecture, model provider, conversation store, or frontend surface was added.

Endpoint: `POST /api/v1/copilot/recovery-query`

Request uses the existing `CopilotQueryRequest` shape (`query`). The response contains an answer, source references, and a `grounded` flag.

## Retrieval strategy

- Follow-up queries retrieve open cases whose `next_follow_up_date` is due.
- Case-specific queries resolve explicit case numbers or UUIDs, then retrieve linked customer, invoice, payment, promise, recovery action, and audit records.
- Customer activity questions filter the customer and all related cases by the authenticated organization.
- Evidence/document questions use the existing `retrieve_context` -> Qdrant path, which applies the organization filter in the vector query. A specific case filter is sent when the question resolves to one case.
- Answers are deterministic summaries of retrieved fields and events. They label retrieved facts/document evidence and generated summaries; they do not invoke an external LLM or supply generic factual fallbacks.

## Tenant isolation

- The endpoint uses the existing `get_current_tenant` dependency; organization selection and membership validation remain unchanged.
- Every SQL retrieval for cases, customers, invoices, payments, promises, recovery actions, and audit events includes `organization_id` in its query predicate.
- Related records are retrieved only by IDs obtained from organization-filtered parent records, and tenant predicates are still applied to those child queries.
- Document evidence uses the existing Qdrant hard `organization_id` filter at vector retrieval time, not post-generation filtering.
- A foreign case reference that is absent from the caller's organization returns insufficient evidence with no sources.
- This endpoint does not persist conversations or log retrieved sensitive content.

## Copilot behavior

- Unknown or unavailable data returns an explicit insufficient-evidence response, no sources, and `grounded: false`.
- Returned source references identify cases or documents. Answers distinguish `[RETRIEVED FACT]`, `[GENERATED SUMMARY FROM RETRIEVED FACTS]`, and `[RETRIEVED DOCUMENT EVIDENCE]`.
- Payment history is read from existing Payment records; invoice totals/status remain authoritative current-state fields and are not altered.
- Promise status is reported as stored. The Copilot does not change promise lifecycle state or infer matching payments.

## Files changed

- `app/api/v1/copilot.py`
- `app/schemas/copilot.py`
- `app/services/recovery_copilot_service.py`
- `tests/test_recovery_copilot.py`
- `PHASE7_COMPLETE.md`

## Tests and results

- Phase 7 tests: `pytest tests/test_recovery_copilot.py -q` — 5 passed.
- Phase 7 plus existing document RAG tests: `pytest tests/test_recovery_copilot.py tests/test_rag_copilot.py -q` — 11 passed.
- Phase 1–7 recovery and document regression: `pytest tests/test_recovery_models.py tests/test_cases.py tests/test_invoices.py tests/test_payments.py tests/test_promises.py tests/test_recovery_actions.py tests/test_timeline.py tests/test_recovery_dashboard.py tests/test_recovery_automation.py tests/test_documents.py tests/test_rag_copilot.py tests/test_recovery_copilot.py -q` — 94 passed.
- Full backend suite: `pytest -q` — 119 passed, 4 warnings in 551.94 seconds. The warnings are existing SHAP/LightGBM TreeExplainer output warnings in risk tests.

## Known limitations

- Question handling is intentionally small and deterministic. It recognizes explicit case numbers/UUIDs and common recovery question categories; it is not a general-purpose natural-language planner.
- Customer name extraction from free-form text is heuristic. Queries can use exact case identifiers for unambiguous case-specific retrieval.
- Uploaded document evidence is available only for documents already indexed in Qdrant. Existing backfill behavior is unchanged.
- Conversation history is not persisted or used; the current Copilot query path also does not implement conversation turns.
- Case-specific answers summarize retrieved records but do not infer the causal reason for a case status beyond stored case summary and invoice/payment facts.
