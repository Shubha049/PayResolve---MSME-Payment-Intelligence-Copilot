import logging
import re
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.case import Case, CaseStatus
from app.models.customer import Customer
from app.models.document import Document
from app.models.invoice import Invoice
from app.models.promise import PromiseToPay
from app.models.recovery_action import RecoveryAction
from app.models.stubs import Payment
from app.services.retrieval_service import retrieve_context

logger = logging.getLogger(__name__)

INSUFFICIENT_EVIDENCE = "There is insufficient current PayResolve data to answer that question."


def _money(value: Any) -> str:
    return f"{value:.2f}"


def _case_reference(query: str) -> str | None:
    match = re.search(r"\bCASE[-_][A-Za-z0-9-]+\b", query, re.IGNORECASE)
    if match:
        return match.group(0).replace("_", "-")
    uuid_match = re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", query, re.IGNORECASE)
    return uuid_match.group(0) if uuid_match else None


def _customer_reference(query: str) -> str | None:
    match = re.search(r"(?:customer|client)\s+['\"]?([A-Za-z][A-Za-z0-9 &.'-]{1,60})", query, re.IGNORECASE)
    if not match:
        return None
    candidate = match.group(1).strip(" .!?'\"")
    candidate = re.split(r"\b(?:with|about|for|who|which|and|has|have|currently)\b", candidate, maxsplit=1, flags=re.IGNORECASE)[0]
    return candidate.strip() or None


async def answer_recovery_question(
    db: AsyncSession,
    organization_id: str,
    query: str,
) -> dict[str, Any]:
    query_lower = query.lower()
    case_ref = _case_reference(query)
    customer_ref = _customer_reference(query)
    case_stmt = select(Case).where(Case.organization_id == organization_id)

    if case_ref:
        case_stmt = case_stmt.where(
            or_(Case.case_number.ilike(f"%{case_ref}%"), Case.id == case_ref)
        )
    elif customer_ref:
        case_stmt = case_stmt.join(Customer, Customer.id == Case.customer_id).where(
            Customer.organization_id == organization_id,
            Customer.name.ilike(f"%{customer_ref}%"),
        )

    if any(term in query_lower for term in ("follow-up", "follow up", "need follow", "due follow")):
        case_stmt = case_stmt.where(
            Case.status.notin_([CaseStatus.RESOLVED, CaseStatus.CLOSED]),
            Case.next_follow_up_date <= date.today(),
        )

    case_stmt = case_stmt.order_by(Case.case_number).limit(25)
    cases = (await db.execute(case_stmt)).scalars().all()
    if not cases:
        if not case_ref and any(
            term in query_lower for term in ("document", "evidence", "receipt", "contract", "uploaded")
        ):
            try:
                hits = retrieve_context(org_id=organization_id, query=query, top_k=3)
            except Exception as exc:
                logger.warning("Recovery evidence retrieval unavailable: %s", type(exc).__name__)
                hits = []
            if hits:
                sources = [
                    {
                        "type": "document",
                        "id": str(hit.get("document_id", "")),
                        "label": f"{hit.get('document_name', 'Document')}, page {hit.get('page_number', 1)}",
                    }
                    for hit in hits
                ]
                evidence = "; ".join(
                    f"{hit.get('document_name', 'Document')}, page {hit.get('page_number', 1)}: "
                    f"{hit.get('chunk_text', '').strip()[:240]}"
                    for hit in hits
                )
                return {
                    "answer": f"[RETRIEVED DOCUMENT EVIDENCE] {evidence}",
                    "sources": sources,
                    "grounded": True,
                }
        return {"answer": INSUFFICIENT_EVIDENCE, "sources": [], "grounded": False}

    case_ids = [case.id for case in cases]
    customers = (
        await db.execute(
            select(Customer).where(
                Customer.organization_id == organization_id,
                Customer.id.in_({case.customer_id for case in cases}),
            )
        )
    ).scalars().all()
    customer_by_id = {customer.id: customer for customer in customers}

    invoices = (
        await db.execute(
            select(Invoice).where(
                Invoice.organization_id == organization_id,
                Invoice.id.in_({case.invoice_id for case in cases if case.invoice_id}),
            )
        )
    ).scalars().all() if any(case.invoice_id for case in cases) else []
    invoice_by_id = {invoice.id: invoice for invoice in invoices}
    invoice_ids = list(invoice_by_id)

    payments = (
        await db.execute(
            select(Payment).where(
                Payment.organization_id == organization_id,
                Payment.invoice_id.in_(invoice_ids),
            ).order_by(Payment.payment_date.desc(), Payment.id)
        )
    ).scalars().all() if invoice_ids else []
    promises = (
        await db.execute(
            select(PromiseToPay).where(
                PromiseToPay.organization_id == organization_id,
                PromiseToPay.case_id.in_(case_ids),
            ).order_by(PromiseToPay.promise_date)
        )
    ).scalars().all()
    actions = (
        await db.execute(
            select(RecoveryAction).where(
                RecoveryAction.organization_id == organization_id,
                RecoveryAction.case_id.in_(case_ids),
            ).order_by(RecoveryAction.action_date.desc(), RecoveryAction.id)
        )
    ).scalars().all()

    action_ids = [action.id for action in actions]
    promise_ids = [promise.id for promise in promises]
    payment_ids = [payment.id for payment in payments]
    relevant_entity_ids = set(case_ids + action_ids + promise_ids + payment_ids + invoice_ids)
    audit_rows = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.organization_id == organization_id,
                or_(
                    AuditLog.entity_id.in_(relevant_entity_ids),
                    AuditLog.details["case_id"].as_string().in_(case_ids),
                    AuditLog.details["invoice_id"].as_string().in_(invoice_ids or [""]),
                ),
            ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(100)
        )
    ).scalars().all()

    source_items: list[dict[str, str]] = []
    answer_parts: list[str] = []
    for case in cases:
        customer = customer_by_id.get(case.customer_id)
        invoice = invoice_by_id.get(case.invoice_id) if case.invoice_id else None
        case_label = f"{case.case_number} ({case.title})"
        source_items.append({"type": "case", "id": case.id, "label": case_label})

        if any(term in query_lower for term in ("follow-up", "follow up", "need follow", "due follow")):
            if case.next_follow_up_date:
                answer_parts.append(
                    f"[RETRIEVED FACT] Case {case_label} for {customer.name if customer else 'an unknown customer'} "
                    f"is {case.status.value} with follow-up due {case.next_follow_up_date.isoformat()}."
                )
            continue

        if any(term in query_lower for term in ("payment history", "payments", "payment history")):
            case_payments = [payment for payment in payments if invoice and payment.invoice_id == invoice.id]
            if not case_payments:
                answer_parts.append(f"[RETRIEVED FACT] No payment records were found for case {case_label}.")
            else:
                payment_facts = "; ".join(
                    f"{payment.payment_date.isoformat()}: {_money(payment.amount)}"
                    + (f" (reference {payment.reference})" if payment.reference else "")
                    for payment in case_payments
                )
                answer_parts.append(f"[RETRIEVED FACT] Payments recorded for case {case_label}: {payment_facts}.")
            continue

        if "promise" in query_lower:
            case_promises = [promise for promise in promises if promise.case_id == case.id]
            if "pending" in query_lower:
                case_promises = [promise for promise in case_promises if promise.status.value == "PENDING"]
            if not case_promises:
                answer_parts.append(f"[RETRIEVED FACT] No matching promises were found for case {case_label}.")
            else:
                promise_facts = "; ".join(
                    f"{promise.status.value} promise for {_money(promise.promised_amount)} due {promise.promise_date.isoformat()}"
                    for promise in case_promises
                )
                answer_parts.append(f"[RETRIEVED FACT] {case_label}: {promise_facts}.")
            continue

        if any(term in query_lower for term in ("timeline", "activity", "what happened", "summarize", "history")):
            case_related_ids = {case.id}
            if case.invoice_id:
                case_related_ids.add(case.invoice_id)
            case_related_ids.update(action.id for action in actions if action.case_id == case.id)
            case_related_ids.update(promise.id for promise in promises if promise.case_id == case.id)
            if invoice:
                case_related_ids.update(payment.id for payment in payments if payment.invoice_id == invoice.id)
            case_audits = [
                audit for audit in audit_rows
                if audit.entity_id in case_related_ids
                or (audit.details or {}).get("case_id") == case.id
                or (invoice and (audit.details or {}).get("invoice_id") == invoice.id)
            ]
            case_actions = [action for action in actions if action.case_id == case.id]
            if case_actions:
                details = "; ".join(
                    f"{action.action_date.isoformat()} {action.action_type.value}: {action.notes or 'no note recorded'}"
                    for action in case_actions
                )
                event_names = "; ".join(event.action for event in case_audits[:10])
                answer_parts.append(
                    f"[RETRIEVED FACT] Recovery actions for {case_label}: {details}. "
                    f"Recorded audit events: {event_names or 'none found'}."
                )
            elif case_audits:
                events = "; ".join(f"{event.action} ({event.entity_type})" for event in case_audits[:10])
                answer_parts.append(f"[RETRIEVED FACT] Recorded audit events for {case_label}: {events}.")
            continue

        if "why" in query_lower and any(term in query_lower for term in ("open", "status", "case")):
            explanation = case.summary or "No reason for the current status is recorded in the case summary."
            answer_parts.append(
                f"[RETRIEVED FACT] Case {case_label} is {case.status.value}. "
                f"Recorded case summary: {explanation}"
            )
            if invoice:
                answer_parts.append(
                    f"[RETRIEVED FACT] Its invoice is {invoice.status.value}, with "
                    f"{_money(invoice.paid_amount)} paid of {_money(invoice.total_amount)}."
                )
            continue

        if "customer" in query_lower and any(term in query_lower for term in ("activity", "summarize", "summary")):
            answer_parts.append(f"[GENERATED SUMMARY FROM RETRIEVED FACTS] Case {case_label} for {customer.name if customer else 'an unknown customer'} is {case.status.value}.")
            continue

        answer_parts.append(f"[RETRIEVED FACT] Case {case_label} is {case.status.value}.")

    document_hits: list[dict[str, Any]] = []
    if any(term in query_lower for term in ("document", "evidence", "receipt", "contract", "uploaded")):
        try:
            document_hits = retrieve_context(
                org_id=organization_id,
                query=query,
                top_k=3,
                case_id=case_ids[0] if len(case_ids) == 1 else None,
            )
        except Exception as exc:
            logger.warning("Recovery evidence retrieval unavailable: %s", type(exc).__name__)

        for hit in document_hits:
            source_items.append({
                "type": "document",
                "id": str(hit.get("document_id", "")),
                "label": f"{hit.get('document_name', 'Document')}, page {hit.get('page_number', 1)}",
            })
        if document_hits:
            snippets = "; ".join(
                f"{hit.get('document_name', 'Document')}, page {hit.get('page_number', 1)}: "
                f"{hit.get('chunk_text', '').strip()[:240]}"
                for hit in document_hits
            )
            answer_parts.append(f"[RETRIEVED DOCUMENT EVIDENCE] {snippets}")

    if not answer_parts:
        return {"answer": INSUFFICIENT_EVIDENCE, "sources": [], "grounded": False}

    answer = " ".join(answer_parts)
    return {"answer": answer, "sources": source_items, "grounded": True}
