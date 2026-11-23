import uuid
from io import BytesIO
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.entities import Cliente, ItemPedido, Pedido, Processamento, ProdutoIndustria
from app.models.enums import StatusPedido
from app.schemas.orders import ItemPedidoResponse, PedidoResponse
from app.services.excel import generate_order_excel

router = APIRouter(prefix="/api/pedidos", tags=["pedidos"])


async def load_order(order_id: uuid.UUID, session: AsyncSession) -> PedidoResponse:
    row = (
        await session.execute(
            select(Pedido, Cliente, Processamento)
            .outerjoin(Cliente, Cliente.id == Pedido.cliente_id)
            .join(Processamento, Processamento.id == Pedido.processamento_id)
            .where(Pedido.id == order_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    order, client, process = row
    item_rows = (
        await session.execute(
            select(ItemPedido, ProdutoIndustria)
            .outerjoin(ProdutoIndustria, ProdutoIndustria.id == ItemPedido.produto_industria_id)
            .where(ItemPedido.pedido_id == order.id)
            .order_by(ItemPedido.criado_em, ItemPedido.id)
        )
    ).all()
    items = [
        ItemPedidoResponse(
            id=item.id,
            codigo_original=item.codigo_original,
            codigo_industria=product.codigo if product else None,
            ean=product.ean if product else item.ean_extraido,
            descricao_produto=product.descricao if product else item.descricao,
            quantidade=item.quantidade,
            embalagem_cx=item.embalagem_cx,
            valor_unitario=item.valor_unitario,
            valor_total=item.valor_total,
            observacao=item.observacao,
            mapeado=item.mapeado,
        )
        for item, product in item_rows
    ]
    return PedidoResponse(
        id=order.id,
        nome_cliente=client.nome_fantasia if client else None,
        cnpj_cliente=client.cnpj if client else order.cnpj_extraido,
        numero_pdf=order.numero_pdf,
        status=order.status,
        arquivo_nome=process.arquivo_nome,
        prazo_pagamento=order.prazo_pagamento,
        data_emissao=order.data_emissao,
        previsao_entrega=order.previsao_entrega,
        data_limite_entrega=order.data_limite_entrega,
        condicao_frete=order.condicao_frete,
        criado_em=order.criado_em,
        itens=items,
        total_itens=len(items),
        itens_sem_mapeamento=sum(not item.mapeado for item in items),
    )


@router.get("/{order_id}", response_model=PedidoResponse)
async def get_order(
    order_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PedidoResponse:
    return await load_order(order_id, session)


@router.get("/{order_id}/exportar")
async def export_order(
    order_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StreamingResponse:
    order = await load_order(order_id, session)
    content = generate_order_excel(order)

    entity = await session.get(Pedido, order_id)
    if entity is not None:
        entity.status = StatusPedido.EXPORTADO
        await session.commit()

    number = order.numero_pdf or "sem_numero"
    filename = quote(f"pedido_{number}.xlsx")
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
