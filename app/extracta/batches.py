"""Fila local simples. Um processo servidor; interrupções não são retomadas automaticamente."""

import asyncio
import copy
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException

from app.core.config import Settings
from app.extracta.recovery import CallBudget
from app.extracta.review import find_document
from app.extracta.storage import read_batch, write_batch
from app.extracta.workflow import analyze_document

_batch_lock = asyncio.Lock()


def batch_path(batch_id: uuid.UUID, settings: Settings) -> Path:
    return settings.extracta_results_dir.resolve() / str(batch_id)


def save_batch(report: dict, settings: Settings) -> None:
    folder = batch_path(uuid.UUID(report["id"]), settings)
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / "report.tmp"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, folder / "report.json")


def load_batch(batch_id: uuid.UUID, settings: Settings) -> dict:
    return json.loads((batch_path(batch_id, settings) / "report.json").read_text(encoding="utf-8"))


def recover_interrupted(settings: Settings) -> None:
    root = settings.extracta_results_dir.resolve()
    if not root.is_dir():
        return
    for path in root.glob("*/report.json"):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if report["status"] in {"pending", "processing"}:
                report["status"] = "interrupted"
                for doc in report["documents"]:
                    if doc["status"] in {"pending", "processing"}:
                        doc["status"] = "interrupted"
                        doc["error"] = "Servidor reiniciado. Envie novamente o documento."
                save_batch(report, settings)
        except (OSError, ValueError, KeyError):
            continue


async def run_batch(batch_id: uuid.UUID, settings: Settings) -> None:
    async with _batch_lock:
        report = await read_batch(batch_id, settings)
        report["status"] = "processing"
        await write_batch(report, settings)
        for doc in report["documents"]:
            if doc["status"] != "pending":
                continue
            doc["status"] = "processing"
            doc["processing_attempts"] = doc.get("processing_attempts", 0) + 1
            await write_batch(report, settings)
            try:
                path = batch_path(batch_id, settings) / f"{doc['id']}.pdf"
                content = await asyncio.to_thread(path.read_bytes)
                loop = asyncio.get_running_loop()

                async def persist_calls(budget, document=doc):
                    document["llm_calls"] = budget.document_calls
                    report["llm_calls"] = budget.batch_calls
                    await write_batch(report, settings)

                budget = CallBudget(
                    settings.extracta_max_llm_calls_per_document,
                    settings.extracta_max_llm_calls_per_batch,
                    document_calls=doc.get("llm_calls", 0),
                    batch_calls=report.get("llm_calls", 0),
                    cache=doc.setdefault("recovery_cache", {}),
                    on_reserve=lambda current, persist=persist_calls, event_loop=loop: (
                        asyncio.run_coroutine_threadsafe(
                            persist(current),
                            event_loop,
                        ).result()
                    ),
                )
                result = await asyncio.to_thread(
                    analyze_document,
                    content,
                    doc["filename"],
                    settings,
                    budget,
                )
                result.source_document_id = doc["id"]
                doc["result"] = result.model_dump(mode="json")
                doc["extraction_result"] = copy.deepcopy(doc["result"])
                doc.setdefault("revision", 0)
                doc["status"] = result.status
                doc.pop("error", None)
            except Exception:
                doc["status"] = "failed"
                doc["error"] = "Falha inesperada no documento. Os demais serão processados."
            await write_batch(report, settings)
        report["status"] = "completed"
        report["finished_at"] = datetime.now(UTC).isoformat()
        await write_batch(report, settings)


def prepare_reprocess(report: dict, doc_id: str, revision: int, settings: Settings):
    doc = find_document(report, doc_id)
    if report["status"] not in {"completed", "interrupted"}:
        raise HTTPException(409, "Aguarde o processamento atual terminar")
    if doc["status"] not in {"failed", "interrupted"}:
        raise HTTPException(409, "Reprocessamento disponível apenas para falhas ou interrupções")
    if revision != doc.get("revision", 0):
        raise HTTPException(409, "O documento mudou. Atualize a tela")
    attempts = doc.get("processing_attempts", 1 if doc.get("result") else 0)
    if attempts >= settings.extracta_max_processing_attempts:
        raise HTTPException(409, "Limite de tentativas atingido; confira a causa da falha")
    doc.setdefault("attempt_history", []).append(
        {
            "at": datetime.now(UTC).isoformat(),
            "status": doc["status"],
            "result": copy.deepcopy(doc.get("result")),
            "error": doc.get("error"),
            "processing_attempts": attempts,
            "revision": doc.get("revision", 0),
            "llm_calls": doc.get("llm_calls", 0),
        }
    )
    doc["processing_attempts"] = attempts
    doc["status"] = report["status"] = "pending"
    doc["revision"] = doc.get("revision", 0) + 1
    doc.pop("approval", None)
    report.pop("finished_at", None)
