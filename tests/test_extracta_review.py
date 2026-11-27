import copy
import uuid
from io import BytesIO

import httpx
import pytest
from fastapi import HTTPException
from openpyxl import load_workbook

from app.api import extracta
from app.core.config import Settings
from app.extracta import storage
from app.extracta.models import DocumentItem, DocumentOrder, DocumentResult, Evidence
from app.extracta.review import (
    Approval,
    DocumentCorrection,
    ItemCorrection,
    OrderCorrection,
    approve,
    correct,
    recalculate,
)
from app.main import app


def sample_report():
    doc_id = str(uuid.uuid4())
    result = DocumentResult(
        source_document_id=doc_id,
        filename="sample.pdf",
        sha256="test",
        profile_id="atacadao_purchase_order",
        profile_version="0.1.0",
        orders=[
            DocumentOrder(
                order_number="001",
                edi_order_number="0001",
                product_total="10.00",
                order_total="11.50",
                items=[
                    DocumentItem(
                        line_id="p1-l1",
                        page_number=1,
                        description='=HYPERLINK("bad")',
                        product_code_raw="00001234/123",
                        packaging_raw="CXA 0001X0012X1UND",
                        quantity="2",
                        unit_price="5.00",
                        evidence={
                            "quantity": Evidence(
                                page_number=1,
                                text="2 5,00",
                                bbox=(0, 0, 1, 1),
                                strategy="ocr",
                            )
                        },
                    )
                ],
            )
        ],
    ).model_dump(mode="json")
    recalculate(result)
    return {
        "id": str(uuid.uuid4()),
        "status": "completed",
        "created_at": "2026-11-26",
        "documents": [
            {"id": doc_id, "filename": "sample.pdf", "status": "needs_review", "result": result}
        ],
    }


def approval(revision=0):
    return Approval(
        revision=revision,
        reviewer="Conferente Teste",
        acknowledge_issues=True,
        note="Valores e ausências conferidos com o documento original",
    )


def test_approval_requires_explicit_acknowledgement_and_note():
    report = sample_report()
    doc = report["documents"][0]
    with pytest.raises(HTTPException, match="Confirme as pendências"):
        approve(report, doc["id"], Approval(revision=0, reviewer="Teste"))
    approve(report, doc["id"], approval())
    assert doc["status"] == "validated"
    assert doc["result"]["orders"][0]["order_total"] == "11.50"
    assert doc["approval"]["acknowledged_issues"]


def test_correction_preserves_extraction_evidence_and_invalidates_approval():
    report = sample_report()
    doc = report["documents"][0]
    original = copy.deepcopy(doc["result"])
    approve(report, doc["id"], approval())
    correct(
        report,
        doc["id"],
        DocumentCorrection(
            revision=1,
            reviewer="Teste",
            orders=[
                OrderCorrection(
                    order_index=0,
                    items=[
                        ItemCorrection(line_id="p1-l1", quantity="3"),
                    ],
                )
            ],
        ),
    )
    assert doc["status"] == "needs_review"
    assert "approval" not in doc
    assert doc["extraction_result"]["orders"] == original["orders"]
    order = doc["result"]["orders"][0]
    assert order["calculated_product_total"] == "15.00"
    assert order["order_total"] == "11.50"
    assert order["items"][0]["evidence"]["quantity"]["text"] == "2 5,00"
    assert doc["audit"][-1]["changes"][0]["before"] == "2"
    assert doc["audit"][-1]["changes"][0]["after"] == "3"


def test_stale_revision_is_rejected():
    report = sample_report()
    doc = report["documents"][0]
    approve(report, doc["id"], approval())
    with pytest.raises(HTTPException) as exc:
        approve(report, doc["id"], approval())
    assert exc.value.status_code == 409


def test_missing_price_blocks_approval_even_with_acknowledgement():
    report = sample_report()
    doc = report["documents"][0]
    doc["result"]["orders"][0]["items"][0]["unit_price"] = None
    with pytest.raises(HTTPException, match="preço inválido"):
        approve(report, doc["id"], approval())


@pytest.mark.asyncio
async def test_api_correction_approval_export_and_history(tmp_path, monkeypatch):
    settings = Settings(extracta_results_dir=tmp_path, extracta_storage="local")
    monkeypatch.setattr(extracta, "get_settings", lambda: settings)
    report = sample_report()
    await storage.write_batch(report, settings)
    batch_id = report["id"]
    doc_id = report["documents"][0]["id"]
    base = f"/api/extracta/lotes/{batch_id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        blocked = await client.post(base + "/exportar")
        assert blocked.status_code == 409
        reviewed = await client.post(
            base + f"/documentos/{doc_id}/aprovar", json=approval().model_dump(mode="json")
        )
        assert reviewed.status_code == 200, reviewed.text
        response = await client.post(base + "/exportar")
        assert response.status_code == 200
        book = load_workbook(BytesIO(response.content), data_only=False)
        assert book.sheetnames == ["Pedidos", "Itens", "Pendencias", "Auditoria", "Evidencias"]
        assert book["Pedidos"]["E2"].value == "001"
        assert book["Pedidos"]["O2"].value == 10
        assert book["Pedidos"]["Q2"].value == 11.5
        assert book["Itens"]["G2"].value == "00001234/123"
        assert book["Itens"]["G2"].data_type == "s"
        assert book["Itens"]["F2"].value.startswith("=HYPERLINK")
        assert book["Itens"]["F2"].data_type == "s"
        assert book["Itens"]["I2"].value is None
        assert book["Itens"]["K2"].data_type == "n"
        history = (await client.get("/api/extracta/lotes")).json()
        assert history[0]["id"] == batch_id
        assert history[0]["documents"][0]["status"] == "exported"
        assert "result" not in history[0]["documents"][0]
        edit = await client.patch(
            base + f"/documentos/{doc_id}",
            json={
                "revision": 2,
                "reviewer": "Teste",
                "orders": [
                    {"order_index": 0, "items": [{"line_id": "p1-l1", "unit_price": "6.00"}]}
                ],
            },
        )
        assert edit.status_code == 200, edit.text
        assert (await client.post(base + "/exportar")).status_code == 409
