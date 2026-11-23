import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session
from app.models.entities import ItemPedido, Pedido, Processamento
from app.schemas.processing import PedidoProcessadoResponse, ProcessamentoResponse
from app.services.pdf import InvalidPdfError, validate_pdf
from app.services.processing import process_pdf

router = APIRouter(prefix="/api/processamentos", tags=["processamentos"])


@router.post("", response_model=ProcessamentoResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_process(
    background_tasks: BackgroundTasks,
    arquivo: Annotated[UploadFile, File()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Processamento:
    settings = get_settings()
    limit = settings.max_upload_mb * 1024 * 1024
    content = await arquivo.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status_code=413, detail=f"PDF excede {settings.max_upload_mb} MB")

    try:
        validate_pdf(content)
    except InvalidPdfError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    process_id = uuid.uuid4()
    upload_dir = settings.upload_dir.resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{process_id}.pdf"
    await arquivo.close()
    file_path.write_bytes(content)

    process = Processamento(
        id=process_id,
        arquivo_nome=Path(arquivo.filename or "pedido.pdf").name[:300],
        arquivo_path=str(file_path),
        mensagem="PDF recebido",
    )
    session.add(process)
    await session.commit()
    await session.refresh(process)
    background_tasks.add_task(process_pdf, process.id)
    return process


@router.get("/{process_id}", response_model=ProcessamentoResponse)
async def get_process(
    process_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Processamento:
    process = await session.get(Processamento, process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="Processamento não encontrado")
    return process


@router.get("/{process_id}/pedidos", response_model=list[PedidoProcessadoResponse])
async def list_processed_orders(
    process_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PedidoProcessadoResponse]:
    process = await session.get(Processamento, process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="Processamento não encontrado")

    rows = (
        await session.execute(
            select(
                Pedido.id,
                Pedido.numero_pdf,
                Pedido.status,
                Pedido.cliente_id,
                func.count(ItemPedido.id).label("total_itens"),
                func.count(ItemPedido.id)
                .filter(ItemPedido.mapeado.is_(False))
                .label("itens_sem_mapeamento"),
            )
            .outerjoin(ItemPedido, ItemPedido.pedido_id == Pedido.id)
            .where(Pedido.processamento_id == process_id)
            .group_by(Pedido.id)
            .order_by(Pedido.criado_em)
        )
    ).all()
    return [PedidoProcessadoResponse(**row._mapping) for row in rows]
