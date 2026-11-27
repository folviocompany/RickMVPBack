import json
import os
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from openpyxl import load_workbook

from app.core.config import get_settings
from app.extracta.workflow import analyze_document

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LOCAL_OCR_TESTS") != "1",
    reason="Habilite RUN_LOCAL_OCR_TESTS=1 com amostras e Tesseract instalados",
)


def test_real_samples_against_manually_transcribed_fields():
    settings = get_settings().model_copy(update={"extracta_allow_external_ai": False})
    expected = json.loads(Path("tests/fixtures/atacadao_expected.json").read_text(encoding="utf-8"))
    for fixture in expected["documents"]:
        path = settings.extracta_samples_dir / fixture["file"]
        assert path.is_file(), f"Amostra ausente: {path}"
        result = analyze_document(path.read_bytes(), "renamed.pdf", settings)
        assert result.status != "failed", result.errors
        assert result.page_count == fixture["pages"]
        assert result.llm_calls == 0
        assert len(result.orders) == 1
        order = result.orders[0]
        assert order.order_number == fixture["number"]
        assert order.edi_order_number == fixture["edi"]
        assert order.product_total == Decimal(fixture["products"])
        assert order.order_total == Decimal(fixture["order"])
        assert order.calculated_product_total == order.product_total
        assert order.payment_days == 60
        assert order.issue_date_raw == "27/10/26"
        assert order.freight_type == "CIF"
        assert len(order.items) == len(fixture["items"])
        pairs = zip(order.items, fixture["items"], strict=True)
        for actual, (page, code, quantity, price) in pairs:
            assert actual.page_number == page
            assert actual.product_code_raw == code
            assert actual.quantity == Decimal(quantity)
            assert actual.unit_price == Decimal(price)
            assert actual.delivery_date_raw == "28/10"
        if order.order_number == "51421":
            assert order.reconciliation_difference == Decimal("275.94")
            assert [item.ipi_raw for item in order.items if item.ipi_raw == "15,0"] == [
                "15,0",
                "15,0",
            ]


@pytest.mark.asyncio
async def test_three_real_pdfs_through_batch_api(tmp_path, monkeypatch):
    from app.api import extracta
    from app.main import app

    settings = get_settings().model_copy(
        update={
            "extracta_results_dir": tmp_path,
            "extracta_storage": "local",
            "extracta_allow_external_ai": False,
        }
    )
    monkeypatch.setattr(extracta, "get_settings", lambda: settings)
    paths = sorted(settings.extracta_samples_dir.glob("*.pdf"))
    assert len(paths) == 3, "São necessárias as três amostras locais"
    files = [("arquivos", (path.name, path.read_bytes(), "application/pdf")) for path in paths]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/extracta/lotes", files=files)
        assert response.status_code == 202, response.text
        batch_id = response.json()["id"]
        report = (await client.get(f"/api/extracta/lotes/{batch_id}")).json()
        assert report["status"] == "completed"
        assert len(report["documents"]) == 3
        results = [document["result"] for document in report["documents"]]
        assert sum(result["page_count"] for result in results) == 5
        assert sum(len(order["items"]) for result in results for order in result["orders"]) == 27
        assert all(result["llm_calls"] == 0 for result in results)
        assert len({result["source_document_id"] for result in results}) == 3
        document = report["documents"][0]
        original = await client.get(
            f"/api/extracta/lotes/{batch_id}/documentos/{document['id']}/arquivo"
        )
        assert original.status_code == 200
        assert original.content == paths[0].read_bytes()
        assert (await client.post(f"/api/extracta/lotes/{batch_id}/exportar")).status_code == 409
        for document in report["documents"]:
            reviewed = await client.post(
                f"/api/extracta/lotes/{batch_id}/documentos/{document['id']}/aprovar",
                json={
                    "revision": 0,
                    "reviewer": "Teste de integração",
                    "acknowledge_issues": True,
                    "note": "Conferência simulada exclusivamente em dados temporários de teste",
                },
            )
            assert reviewed.status_code == 200, reviewed.text
        exported = await client.post(f"/api/extracta/lotes/{batch_id}/exportar")
        assert exported.status_code == 200, exported.text
        book = load_workbook(BytesIO(exported.content))
        assert book["Pedidos"].max_row == 4
        assert book["Itens"].max_row == 28
        assert {row[0] for row in book["Itens"].iter_rows(min_row=2, values_only=True)} == {
            document["id"] for document in report["documents"]
        }
        expected_items = {
            (document["id"], item["line_id"]): item
            for document in report["documents"]
            for order in document["result"]["orders"]
            for item in order["items"]
        }
        for row in book["Itens"].iter_rows(min_row=2, values_only=True):
            item = expected_items[(row[0], row[3])]
            assert row[4] == item["page_number"]
            assert row[6] == item["product_code_raw"]
            assert Decimal(str(row[10])) == Decimal(item["quantity"])
            assert Decimal(str(row[11])) == Decimal(item["unit_price"])
