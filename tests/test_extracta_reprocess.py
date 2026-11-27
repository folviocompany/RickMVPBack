import uuid

import httpx
import pytest
from fastapi import HTTPException

from app.api import extracta
from app.core.config import Settings
from app.extracta import batches, storage
from app.extracta.batches import batch_path, prepare_reprocess
from app.extracta.models import DocumentResult
from app.main import app
from tests.test_extracta_review import sample_report


@pytest.mark.asyncio
async def test_reprocess_keeps_identity_history_and_spent_budget(tmp_path, monkeypatch):
    settings = Settings(extracta_storage="local", extracta_results_dir=tmp_path)
    monkeypatch.setattr(extracta, "get_settings", lambda: settings)
    report = sample_report()
    report["llm_calls"] = 5
    doc = report["documents"][0]
    doc.update(status="failed", processing_attempts=1, revision=2, llm_calls=2, error="OCR falhou")
    folder = batch_path(uuid.UUID(report["id"]), settings)
    folder.mkdir(parents=True)
    (folder / f"{doc['id']}.pdf").write_bytes(b"%PDF-sample")
    await storage.write_batch(report, settings)

    def analyze(content, filename, config, budget):
        assert budget.document_calls == 2
        assert budget.batch_calls == 5
        assert budget.reserve()
        # Reservation must already be durable before a provider could be contacted.
        persisted = batches.load_batch(uuid.UUID(report["id"]), settings)
        assert persisted["llm_calls"] == 6
        assert persisted["documents"][0]["llm_calls"] == 3
        return DocumentResult(source_document_id="temporary", filename=filename, sha256="hash")

    monkeypatch.setattr(batches, "analyze_document", analyze)
    base = f"/api/extracta/lotes/{report['id']}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            base + f"/documentos/{doc['id']}/reprocessar", json={"revision": 2}
        )
        assert response.status_code == 202, response.text
        latest = (await client.get(base)).json()
        assert len(latest["documents"]) == 1
        current = latest["documents"][0]
        assert current["id"] == doc["id"]
        assert current["result"]["source_document_id"] == doc["id"]
        assert current["revision"] == 3
        assert current["processing_attempts"] == 2
        assert current["llm_calls"] == 3
        assert latest["llm_calls"] == 6
        assert current["attempt_history"][0]["error"] == "OCR falhou"
        assert current["status"] == "needs_review"
        duplicate = await client.post(
            base + f"/documentos/{doc['id']}/reprocessar", json={"revision": 2}
        )
        assert duplicate.status_code == 409


def test_reprocess_does_not_replace_corrected_or_approved_document():
    report = sample_report()
    doc = report["documents"][0]
    with pytest.raises(HTTPException, match="apenas para falhas"):
        prepare_reprocess(report, doc["id"], 0, Settings())


def test_reprocess_limit_and_duplicate_queue_are_enforced():
    report = sample_report()
    doc = report["documents"][0]
    doc.update(status="failed", processing_attempts=3)
    with pytest.raises(HTTPException, match="Limite de tentativas"):
        prepare_reprocess(report, doc["id"], 0, Settings())
    doc["processing_attempts"] = 1
    prepare_reprocess(report, doc["id"], 0, Settings())
    with pytest.raises(HTTPException, match="processamento atual"):
        prepare_reprocess(report, doc["id"], 0, Settings())
