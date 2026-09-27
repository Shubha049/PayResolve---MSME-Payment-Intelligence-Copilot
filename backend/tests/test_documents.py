import io
import pytest
import fitz  # PyMuPDF
from httpx import AsyncClient
from sqlalchemy import select

from app.models.document import Document, DocumentChunk, DocStatus, DocType
from app.services.document_service import process_document, extract_fields_with_evidence, chunk_text
from tests.conftest import register_user, login_user


def _create_sample_pdf(text: str) -> bytes:
    """Generate an in-memory PDF containing the specified text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text, fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.mark.asyncio
async def test_upload_valid_pdf(client: AsyncClient):
    await register_user(client, "doc_user1@test.com", "Password123!", "Doc User 1", "Doc Corp A")
    token = await login_user(client, "doc_user1@test.com", "Password123!")
    headers = {"Authorization": f"Bearer {token}"}

    sample_text = (
        "TAX INVOICE\n"
        "Invoice No: INV-2024-001\n"
        "Date of Invoice: 2024-10-15\n"
        "Due Date: 2024-11-15\n"
        "Billed By: Apex Tech Solutions\n"
        "Bill To: Stellar Retail Ltd\n"
        "Total Amount: $1,250.00\n"
    )
    pdf_bytes = _create_sample_pdf(sample_text)

    files = {"file": ("test_invoice.pdf", pdf_bytes, "application/pdf")}
    resp = await client.post("/api/v1/documents/upload", headers=headers, files=files)
    assert resp.status_code == 202, resp.text
    data = resp.json()

    assert data["original_name"] == "test_invoice.pdf"
    assert data["mime_type"] == "application/pdf"
    assert data["status"] in ("PENDING", "PROCESSING", "DONE")
    doc_id = data["id"]

    # Fetch document detail
    detail_resp = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["id"] == doc_id


@pytest.mark.asyncio
async def test_upload_disallowed_extension(client: AsyncClient):
    await register_user(client, "doc_user1@test.com", "Password123!", "Doc User 1", "Doc Corp A")
    token = await login_user(client, "doc_user1@test.com", "Password123!")
    headers = {"Authorization": f"Bearer {token}"}

    files = {"file": ("malicious.exe", b"MZexecutabledata", "application/x-msdownload")}
    resp = await client.post("/api/v1/documents/upload", headers=headers, files=files)
    assert resp.status_code == 400
    assert "not allowed" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_path_traversal(client: AsyncClient):
    await register_user(client, "doc_user1@test.com", "Password123!", "Doc User 1", "Doc Corp A")
    token = await login_user(client, "doc_user1@test.com", "Password123!")
    headers = {"Authorization": f"Bearer {token}"}

    files = {"file": ("../../etc/passwd.pdf", b"%PDF-dummy", "application/pdf")}
    resp = await client.post("/api/v1/documents/upload", headers=headers, files=files)
    assert resp.status_code == 400
    assert "path traversal" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_extraction_pipeline_with_evidence():
    # Test document extraction and evidence tracking directly
    sample_text = (
        "TAX INVOICE\n"
        "Invoice No: INV-9988\n"
        "Date of Invoice: 2024-05-10\n"
        "Due Date: 2024-06-10\n"
        "From: Global Logistics Inc\n"
        "Bill To: Delta Systems\n"
        "Grand Total: $8,750.50\n"
    )
    pdf_bytes = _create_sample_pdf(sample_text)

    # Test extract_fields_with_evidence directly
    fields = extract_fields_with_evidence(sample_text, page_count=1)
    assert fields["invoice_number"]["status"] == "verified"
    assert fields["invoice_number"]["value"] == "INV-9988"
    assert fields["invoice_number"]["page"] == 1
    assert "INV-9988" in fields["invoice_number"]["source_text"]

    assert fields["total_amount"]["status"] == "verified"
    assert fields["total_amount"]["value"] == 8750.50
    assert fields["total_amount"]["confidence"] >= 0.80

    assert fields["due_date"]["status"] == "verified"
    assert fields["due_date"]["value"] == "2024-06-10"

    assert fields["vendor"]["status"] == "inferred"
    assert "Global Logistics" in fields["vendor"]["value"]

    assert fields["buyer"]["status"] == "inferred"
    assert "Delta Systems" in fields["buyer"]["value"]

    # Test chunking
    chunks = chunk_text(sample_text, page_count=1)
    assert len(chunks) >= 1
    assert chunks[0]["page_number"] == 1
    assert "TAX INVOICE" in chunks[0]["chunk_text"]


@pytest.mark.asyncio
async def test_no_fabrication_on_empty_document():
    # If a document doesn't have amounts or invoice numbers, it must return status="missing"
    random_text = "Just a general note about our upcoming meeting on Friday afternoon."
    fields = extract_fields_with_evidence(random_text, page_count=1)

    assert fields["invoice_number"]["status"] == "missing"
    assert fields["invoice_number"]["value"] is None
    assert fields["total_amount"]["status"] == "missing"
    assert fields["total_amount"]["value"] is None
    assert fields["due_date"]["status"] == "missing"
    assert fields["due_date"]["value"] is None


@pytest.mark.asyncio
async def test_documents_tenancy_isolation(client: AsyncClient):
    # Org A user
    await register_user(client, "org_a_user@test.com", "Password123!", "Alice A", "Company A")
    token_a = await login_user(client, "org_a_user@test.com", "Password123!")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Org B user
    await register_user(client, "org_b_user@test.com", "Password123!", "Bob B", "Company B")
    token_b = await login_user(client, "org_b_user@test.com", "Password123!")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Alice uploads a document
    pdf_bytes = _create_sample_pdf("Invoice No: INV-AAA-01\nTotal Due: $500.00")
    files = {"file": ("alice_doc.pdf", pdf_bytes, "application/pdf")}
    resp = await client.post("/api/v1/documents/upload", headers=headers_a, files=files)
    assert resp.status_code == 202
    doc_id = resp.json()["id"]

    # Bob tries to access Alice's document
    detail_resp = await client.get(f"/api/v1/documents/{doc_id}", headers=headers_b)
    assert detail_resp.status_code == 404

    # Bob tries to access chunks
    chunks_resp = await client.get(f"/api/v1/documents/{doc_id}/chunks", headers=headers_b)
    assert chunks_resp.status_code == 404

    # Bob tries to delete Alice's document
    del_resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=headers_b)
    assert del_resp.status_code == 404

    # Alice can view and list her document
    list_resp = await client.get("/api/v1/documents/", headers=headers_a)
    assert list_resp.status_code == 200
    doc_ids = [d["id"] for d in list_resp.json()]
    assert doc_id in doc_ids

    # Bob's list does not contain Alice's document
    bob_list = await client.get("/api/v1/documents/", headers=headers_b)
    assert bob_list.status_code == 200
    bob_ids = [d["id"] for d in bob_list.json()]
    assert doc_id not in bob_ids

    # Alice can delete her document
    alice_del = await client.delete(f"/api/v1/documents/{doc_id}", headers=headers_a)
    assert alice_del.status_code == 204
