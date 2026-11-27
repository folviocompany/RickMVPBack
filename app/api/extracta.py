import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.extracta import storage
from app.extracta.batches import batch_path, prepare_reprocess, run_batch
from app.extracta.excel import generate_batch_excel
from app.extracta.ocr import check_ocr
from app.extracta.review import (
    Approval,
    DocumentCorrection,
    approve,
    audit,
    correct,
    find_document,
    with_review,
)

router = APIRouter(prefix="/api/extracta", tags=["extracta"])


@router.get("/ready")
async def readiness():
    settings = get_settings()
    return {
        **await asyncio.to_thread(check_ocr, settings),
        "external_ai_enabled": settings.extracta_allow_external_ai,
        "llm_configured": bool(settings.nvidia_api_key and settings.nvidia_model),
    }


class ReprocessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)


@router.post("/lotes/{batch_id}/documentos/{doc_id}/reprocessar", status_code=202)
async def reprocess_document(
    batch_id: uuid.UUID,
    doc_id: uuid.UUID,
    payload: ReprocessRequest,
    background_tasks: BackgroundTasks,
):
    settings = get_settings()
    path = batch_path(batch_id, settings) / f"{doc_id}.pdf"
    if not path.is_file():
        raise HTTPException(409, "PDF original ausente; não é possível reprocessar")
    try:
        report = await storage.mutate_batch(
            batch_id,
            settings,
            lambda report: prepare_reprocess(
                report,
                str(doc_id),
                payload.revision,
                settings,
            ),
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, "Lote não encontrado") from exc
    background_tasks.add_task(run_batch, batch_id, settings)
    return with_review(report)


@router.post("/lotes", status_code=202)
async def create_batch(
    background_tasks: BackgroundTasks,
    arquivos: Annotated[list[UploadFile], File()],
):
    settings = get_settings()
    if len(arquivos) > settings.extracta_max_documents_per_batch:
        raise HTTPException(422, "Quantidade de documentos excede o limite do lote")
    readiness = await asyncio.to_thread(check_ocr, settings)
    if not readiness["available"]:
        raise HTTPException(503, readiness["message"])
    batch_id = uuid.uuid4()
    folder = batch_path(batch_id, settings)
    folder.mkdir(parents=True, exist_ok=True)
    report = {
        "id": str(batch_id),
        "status": "pending",
        "created_at": datetime.now(UTC).isoformat(),
        "documents": [],
    }
    limit = settings.max_upload_mb * 1024 * 1024
    for upload in arquivos:
        doc_id = str(uuid.uuid4())
        filename = Path((upload.filename or "documento.pdf").replace("\\", "/")).name[:300]
        content = await upload.read(limit + 1)
        await upload.close()
        doc = {"id": doc_id, "filename": filename, "status": "pending"}
        if len(content) > limit:
            doc.update(status="failed", error="Arquivo excede o limite de tamanho")
        elif not content.startswith(b"%PDF-"):
            doc.update(status="failed", error="Arquivo sem assinatura PDF")
        else:
            await asyncio.to_thread((folder / f"{doc_id}.pdf").write_bytes, content)
        report["documents"].append(doc)
    await storage.write_batch(report, settings)
    background_tasks.add_task(run_batch, batch_id, settings)
    return report


@router.get("/lotes/{batch_id}")
async def get_batch(batch_id: uuid.UUID):
    try:
        settings = get_settings()
        report = with_review(await storage.read_batch(batch_id, settings))
        for doc in report["documents"]:
            doc["can_reprocess"] = (
                report["status"] in {"completed", "interrupted"}
                and doc["status"] in {"failed", "interrupted"}
                and doc.get("processing_attempts", 1 if doc.get("result") else 0)
                < settings.extracta_max_processing_attempts
                and (batch_path(batch_id, settings) / f"{doc['id']}.pdf").is_file()
            )
        return report
    except FileNotFoundError as exc:
        raise HTTPException(404, "Lote não encontrado") from exc


@router.get("/lotes")
async def history(
    limit: Annotated[int, Query(ge=1, le=100)] = 30, offset: Annotated[int, Query(ge=0)] = 0
):
    reports = await storage.list_batches(get_settings(), limit, offset)
    return [
        {
            "id": report["id"],
            "created_at": report["created_at"],
            "status": report["status"],
            "documents": [
                {
                    "id": doc["id"],
                    "filename": doc["filename"],
                    "status": doc["status"],
                    "orders": len(doc.get("result", {}).get("orders", [])),
                }
                for doc in report["documents"]
            ],
        }
        for report in reports
    ]


@router.patch("/lotes/{batch_id}/documentos/{doc_id}")
async def correct_document(batch_id: uuid.UUID, doc_id: uuid.UUID, payload: DocumentCorrection):
    try:
        report = await storage.mutate_batch(
            batch_id,
            get_settings(),
            lambda report: correct(report, str(doc_id), payload),
        )
        return with_review(report)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Lote não encontrado") from exc


@router.post("/lotes/{batch_id}/documentos/{doc_id}/aprovar")
async def approve_document(batch_id: uuid.UUID, doc_id: uuid.UUID, payload: Approval):
    try:
        report = await storage.mutate_batch(
            batch_id,
            get_settings(),
            lambda report: approve(report, str(doc_id), payload),
        )
        return with_review(report)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Lote não encontrado") from exc


async def export_selected(batch_id: uuid.UUID, doc_id: uuid.UUID | None = None):
    content = None

    def export(report):
        nonlocal content
        if report["status"] != "completed":
            raise HTTPException(409, "Aguarde o término do lote")
        documents = [find_document(report, str(doc_id))] if doc_id else report["documents"]
        if not documents or any(
            doc["status"] not in {"validated", "exported"} or not doc.get("approval")
            for doc in documents
        ):
            raise HTTPException(409, "Todos os documentos selecionados precisam ser aprovados")
        for doc in documents:
            audit(doc, "exported", doc["approval"]["reviewer"], "Exportação final conferida")
            doc["status"] = "exported"
        content = generate_batch_excel(report, documents)

    try:
        await storage.mutate_batch(batch_id, get_settings(), export)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Lote não encontrado") from exc
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="extracta_{batch_id}.xlsx"'},
    )


@router.post("/lotes/{batch_id}/exportar")
async def export_batch(batch_id: uuid.UUID):
    return await export_selected(batch_id)


@router.post("/lotes/{batch_id}/documentos/{doc_id}/exportar")
async def export_document(batch_id: uuid.UUID, doc_id: uuid.UUID):
    return await export_selected(batch_id, doc_id)


@router.get("/lotes/{batch_id}/documentos/{doc_id}/arquivo")
async def original_document(batch_id: uuid.UUID, doc_id: uuid.UUID):
    settings = get_settings()
    report = await get_batch(batch_id)
    document = next((doc for doc in report["documents"] if doc["id"] == str(doc_id)), None)
    path = batch_path(batch_id, settings) / f"{doc_id}.pdf"
    if document is None or not path.is_file():
        raise HTTPException(404, "Documento não encontrado neste lote")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document["filename"],
        content_disposition_type="inline",
    )
