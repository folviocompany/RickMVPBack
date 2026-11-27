import uuid

import httpx
import pytest

from app.api import extracta
from app.core.config import Settings
from app.extracta import batches
from app.extracta.models import DocumentResult
from app.main import app


@pytest.mark.asyncio
async def test_batch_isolates_invalid_files_and_saves_results(tmp_path, monkeypatch):
    settings = Settings(extracta_results_dir=tmp_path, extracta_storage="local")
    monkeypatch.setattr(extracta, "get_settings", lambda: settings)
    monkeypatch.setattr(extracta, "check_ocr", lambda _: {"available": True})
    monkeypatch.setattr(
        batches,
        "analyze_document",
        lambda content, filename, _, budget=None: DocumentResult(
            source_document_id="temporary",
            filename=filename,
            sha256="example",
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/extracta/lotes",
            files=[
                ("arquivos", ("invalid.pdf", b"invalid", "application/pdf")),
                ("arquivos", ("valid.pdf", b"%PDF-sample", "application/pdf")),
            ],
        )
        assert response.status_code == 202
        batch_id = response.json()["id"]
        result = (await client.get(f"/api/extracta/lotes/{batch_id}")).json()
        assert result["status"] == "completed"
        assert result["documents"][0]["status"] == "failed"
        assert result["documents"][1]["status"] == "needs_review"
        document = result["documents"][1]
        assert document["result"]["source_document_id"] == document["id"]
        missing = await client.get(
            f"/api/extracta/lotes/{batch_id}/documentos/{uuid.uuid4()}/arquivo"
        )
        assert missing.status_code == 404


def test_restart_marks_unfinished_documents_as_interrupted(tmp_path):
    settings = Settings(extracta_results_dir=tmp_path, extracta_storage="local")
    report = {
        "id": str(uuid.uuid4()),
        "status": "processing",
        "documents": [
            {"id": str(uuid.uuid4()), "status": "processing"},
            {"id": str(uuid.uuid4()), "status": "needs_review"},
        ],
    }
    batches.save_batch(report, settings)
    batches.recover_interrupted(settings)
    restored = batches.load_batch(uuid.UUID(report["id"]), settings)
    assert restored["status"] == "interrupted"
    assert restored["documents"][0]["status"] == "interrupted"
    assert restored["documents"][1]["status"] == "needs_review"
