from datetime import date, timedelta
from decimal import Decimal
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from qdrant_client import QdrantClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.case import Case, CaseStatus
from app.models.customer import Customer
from app.models.document import Document, DocumentChunk, DocStatus, DocType
from app.models.invoice import Invoice, InvoiceStatus
from app.models.organization import Organization
from app.models.promise import PromiseStatus, PromiseToPay
from app.models.recovery_action import RecoveryAction, RecoveryActionType
from app.models.stubs import Payment
from app.services.document_service import index_document_chunks
from app.services.vector_store import set_qdrant_client
from tests.conftest import register_user


@pytest.fixture
def recovery_copilot_qdrant():
    client = QdrantClient(location=":memory:")
    set_qdrant_client(client)
    yield client
    client.close()


async def _seed_case(db: AsyncSession, org: Organization, customer: Customer, *, number: str = "CASE-P7-001"):
    today = date.today()
    invoice = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number=f"INV-{uuid.uuid4().hex[:8]}",
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=10),
        total_amount=Decimal("1250.00"),
        paid_amount=Decimal("250.00"),
        status=InvoiceStatus.PARTIALLY_PAID,
    )
    case = Case(
        organization_id=org.id,
        customer_id=customer.id,
        invoice=invoice,
        case_number=number,
        title="Unpaid equipment invoice",
        status=CaseStatus.OPEN,
        summary="Customer disputed delivery timing; partial payment was received.",
        amount_in_recovery=Decimal("1000.00"),
        next_follow_up_date=today,
    )
    db.add_all([invoice, case])
    await db.flush()

    payment = Payment(
        organization_id=org.id,
        invoice_id=invoice.id,
        amount=Decimal("250.00"),
        payment_date=today - timedelta(days=5),
        reference="BANK-REF-P7",
    )
    promise = PromiseToPay(
        organization_id=org.id,
        case_id=case.id,
        promise_date=today + timedelta(days=5),
        promised_amount=Decimal("500.00"),
        status=PromiseStatus.PENDING,
        notes="Customer committed to the next installment.",
    )
    action = RecoveryAction(
        organization_id=org.id,
        case_id=case.id,
        created_by_user_id=case.assigned_to_user_id or "",
        action_type=RecoveryActionType.CUSTOMER_CONTACTED,
        action_date=today - timedelta(days=2),
        notes="Customer confirmed receipt of the reminder.",
    )
    # RecoveryAction requires a user foreign key; caller supplies an existing test user below.
    return invoice, case, payment, promise, action


async def _create_case_data(db, org, customer, user, case_number="CASE-P7-001"):
    invoice, case, payment, promise, action = await _seed_case(db, org, customer, number=case_number)
    action.created_by_user_id = user.id
    db.add_all([payment, promise, action])
    await db.flush()
    db.add_all([
        AuditLog(
            organization_id=org.id,
            user_id=user.id,
            action="CASE_CREATED",
            entity_type="Case",
            entity_id=case.id,
            details={"case_number": case.case_number},
        ),
        AuditLog(
            organization_id=org.id,
            user_id=user.id,
            action="PAYMENT_CREATED",
            entity_type="Payment",
            entity_id=payment.id,
            details={"invoice_id": invoice.id, "amount": "250.00", "payment_date": payment.payment_date.isoformat()},
        ),
        AuditLog(
            organization_id=org.id,
            user_id=user.id,
            action="RECOVERY_ACTION_CREATED",
            entity_type="RecoveryAction",
            entity_id=action.id,
            details={"case_id": case.id, "action_type": action.action_type.value, "notes": action.notes},
        ),
        AuditLog(
            organization_id=org.id,
            user_id=user.id,
            action="PROMISE_CREATED",
            entity_type="PromiseToPay",
            entity_id=promise.id,
            details={"case_id": case.id, "promise_date": promise.promise_date.isoformat(), "promised_amount": "500.00"},
        ),
    ])
    await db.commit()
    return invoice, case, payment, promise, action


@pytest_asyncio.fixture
async def recovery_copilot_data(db_session: AsyncSession, org: Organization, customer: Customer, user):
    return await _create_case_data(db_session, org, customer, user)


@pytest.mark.asyncio
async def test_recovery_copilot_returns_due_followups(client, auth_headers, recovery_copilot_data):
    _, seeded_case, _, _, _ = recovery_copilot_data
    seeded = (await client.get("/api/v1/cases/", headers=auth_headers)).json()
    assert any(item["id"] == seeded_case.id for item in seeded)
    assert next(item for item in seeded if item["id"] == seeded_case.id)["next_follow_up_date"] == date.today().isoformat()
    response = await client.post(
        "/api/v1/copilot/recovery-query",
        headers=auth_headers,
        json={"query": "Which cases currently need follow-up?"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grounded"] is True, body
    assert "CASE-P7-001" in body["answer"]
    assert any(source["type"] == "case" for source in body["sources"])


@pytest.mark.asyncio
async def test_recovery_copilot_case_payment_promise_and_timeline_questions(
    client, auth_headers, recovery_copilot_data
):
    queries = [
        ("What happened with case CASE-P7-001?", "Customer confirmed receipt"),
        ("Show the payment history for case CASE-P7-001", "250.00"),
        ("Which promises are pending for case CASE-P7-001?", "500.00"),
        ("Summarize the recovery activity for case CASE-P7-001", "RECOVERY_ACTION_CREATED"),
        ("Why is case CASE-P7-001 still open?", "OPEN"),
    ]
    for query, expected in queries:
        response = await client.post(
            "/api/v1/copilot/recovery-query",
            headers=auth_headers,
            json={"query": query},
        )
        assert response.status_code == 200, response.text
        assert response.json()["grounded"] is True, response.json()
        assert expected in response.json()["answer"]


@pytest.mark.asyncio
async def test_recovery_copilot_reports_insufficient_evidence(client, auth_headers):
    response = await client.post(
        "/api/v1/copilot/recovery-query",
        headers=auth_headers,
        json={"query": "What did we decide about CASE-NOT-IN-OUR-DATA?"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grounded"] is False
    assert body["sources"] == []
    assert "insufficient" in body["answer"].lower()


@pytest.mark.asyncio
async def test_recovery_copilot_never_returns_other_tenant_records(
    client,
    db_session: AsyncSession,
    auth_headers,
    org2: Organization,
    user2,
    recovery_copilot_data,
):
    other_customer = Customer(organization_id=org2.id, name="Private Customer", email="private@other.test")
    db_session.add(other_customer)
    await db_session.flush()
    _, other_case, _, _, _ = await _create_case_data(
        db_session, org2, other_customer, user2, case_number="CASE-PRIVATE-999"
    )

    response = await client.post(
        "/api/v1/copilot/recovery-query",
        headers=auth_headers,
        json={"query": f"What happened with case {other_case.case_number}?"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["grounded"] is False
    assert other_case.case_number not in response.json()["answer"]
    assert all(other_case.case_number not in str(source) for source in response.json()["sources"])


@pytest.mark.asyncio
async def test_recovery_copilot_retrieves_case_evidence_with_org_filtered_vectors(
    client,
    db_session: AsyncSession,
    org: Organization,
    auth_headers,
    recovery_copilot_data,
    recovery_copilot_qdrant,
):
    _, case, _, _, _ = recovery_copilot_data
    document = Document(
        organization_id=org.id,
        original_name="delivery-evidence.pdf",
        file_name="delivery-evidence.pdf",
        file_path="unused-in-test",
        file_size=100,
        mime_type="application/pdf",
        doc_type=DocType.CORRESPONDENCE,
        status=DocStatus.DONE,
        extracted_text="Delivery receipt confirms the equipment was received on 2026-09-01.",
        case_id=case.id,
    )
    db_session.add(document)
    await db_session.flush()
    db_session.add(DocumentChunk(
        organization_id=org.id,
        document_id=document.id,
        chunk_index=0,
        chunk_text="Delivery receipt confirms the equipment was received on 2026-09-01.",
        page_number=1,
    ))
    await db_session.commit()
    await index_document_chunks(db_session, document.id, org.id)

    response = await client.post(
        "/api/v1/copilot/recovery-query",
        headers=auth_headers,
        json={"query": f"What evidence is available for case {case.case_number}?"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grounded"] is True, body
    assert "delivery-evidence.pdf" in body["answer"]
    assert any(source["type"] == "document" for source in body["sources"])
