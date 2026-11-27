import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete

from app.core.config import Settings
from app.db.session import engine, session_factory
from app.extracta import storage
from app.extracta.review import approve
from app.models.entities import ExtractaLote
from tests.async_runner import run_async
from tests.test_extracta_review import approval, sample_report


@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="Habilite RUN_INTEGRATION_TESTS=1 para usar PostgreSQL",
)
def test_postgres_persists_reports_and_rolls_back_conflicting_review(tmp_path):
    async def scenario():
        settings = Settings(extracta_results_dir=tmp_path, extracta_storage="postgres")
        report = sample_report()
        batch_id = uuid.UUID(report["id"])
        doc_id = report["documents"][0]["id"]
        try:
            await storage.write_batch(report, settings)
            await storage.recover_database(settings)
            loaded = await storage.read_batch(batch_id, settings)
            assert loaded == report
            await storage.mutate_batch(
                batch_id, settings, lambda current: approve(current, doc_id, approval())
            )
            with pytest.raises(Exception, match="documento mudou"):
                await storage.mutate_batch(
                    batch_id, settings, lambda current: approve(current, doc_id, approval())
                )
            latest = await storage.read_batch(batch_id, settings)
            assert latest["documents"][0]["revision"] == 1
            assert latest["documents"][0]["status"] == "validated"
            operations = await asyncio.gather(
                *[
                    storage.mutate_batch(
                        batch_id,
                        settings,
                        lambda current: approve(current, doc_id, approval(revision=1)),
                    )
                    for _ in range(2)
                ],
                return_exceptions=True,
            )
            assert sum(isinstance(result, dict) for result in operations) == 1
            assert sum(getattr(result, "status_code", None) == 409 for result in operations) == 1
        finally:
            async with session_factory() as session:
                await session.execute(delete(ExtractaLote).where(ExtractaLote.id == batch_id))
                await session.commit()
            await engine.dispose()

    run_async(scenario())
