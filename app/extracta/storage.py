"""PostgreSQL is authoritative; local storage is an isolated development/test adapter."""

import asyncio
import copy
import json
import uuid

from sqlalchemy import select

from app.core.config import Settings
from app.db.session import session_factory
from app.models.entities import ExtractaLote

_local_lock = asyncio.Lock()


async def read_batch(batch_id: uuid.UUID, settings: Settings) -> dict:
    if settings.extracta_storage == "local":
        from app.extracta.batches import load_batch

        return load_batch(batch_id, settings)
    async with session_factory() as session:
        row = await session.get(ExtractaLote, batch_id)
        if row is None:
            raise FileNotFoundError("Lote não encontrado")
        return copy.deepcopy(row.report)


async def write_batch(report: dict, settings: Settings) -> None:
    if settings.extracta_storage == "local":
        from app.extracta.batches import save_batch

        save_batch(report, settings)
        return
    async with session_factory() as session:
        row = await session.get(ExtractaLote, uuid.UUID(report["id"]))
        if row is None:
            session.add(ExtractaLote(id=uuid.UUID(report["id"]), report=copy.deepcopy(report)))
        else:
            row.report = copy.deepcopy(report)
        await session.commit()


async def list_batches(settings: Settings, limit: int, offset: int) -> list[dict]:
    if settings.extracta_storage == "local":
        reports = []
        for path in settings.extracta_results_dir.glob("*/report.json"):
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        return sorted(reports, key=lambda report: report["created_at"], reverse=True)[
            offset : offset + limit
        ]
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(ExtractaLote)
                    .order_by(ExtractaLote.criado_em.desc(), ExtractaLote.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return [copy.deepcopy(row.report) for row in rows]


async def mutate_batch(batch_id: uuid.UUID, settings: Settings, mutation) -> dict:
    if settings.extracta_storage == "local":
        async with _local_lock:
            report = await read_batch(batch_id, settings)
            mutation(report)
            await write_batch(report, settings)
            return report
    async with session_factory() as session:
        row = (
            await session.execute(
                select(ExtractaLote).where(ExtractaLote.id == batch_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise FileNotFoundError("Lote não encontrado")
        report = copy.deepcopy(row.report)
        mutation(report)
        row.report = report
        await session.commit()
        return report


async def recover_database(settings: Settings) -> None:
    if settings.extracta_storage == "local":
        return
    async with session_factory() as session:
        # Import reports from the first delivery once, without replacing database edits.
        from sqlalchemy.dialects.postgresql import insert

        from app.models.entities import now

        for path in settings.extracta_results_dir.glob("*/report.json"):
            report = json.loads(path.read_text(encoding="utf-8"))
            await session.execute(
                insert(ExtractaLote)
                .values(
                    id=uuid.UUID(report["id"]),
                    report=report,
                    criado_em=now(),
                    atualizado_em=now(),
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
        rows = (
            (
                await session.execute(
                    select(ExtractaLote).where(
                        ExtractaLote.report["status"].astext.in_(["pending", "processing"])
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            report = copy.deepcopy(row.report)
            report["status"] = "interrupted"
            for doc in report["documents"]:
                if doc["status"] in {"pending", "processing"}:
                    doc["status"] = "interrupted"
                    doc["error"] = "Servidor reiniciado. Reprocesse o documento."
            row.report = report
        await session.commit()
