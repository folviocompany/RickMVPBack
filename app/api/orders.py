import uuid
from decimal import Decimal
from io import BytesIO
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.entities import Cliente, ItemPedido, Pedido, Processamento, ProdutoIndustria
from app.models.enums import StatusPedido
from app.schemas.orders import ItemPedidoResponse, PedidoResponse, PedidoUpdate
from app.services.excel import generate_order_excel

router = APIRouter(prefix="/api/pedidos", tags=["pedidos"])


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _item_total(item: ItemPedidoResponse) -> Decimal:
    if item.valor_total is not None:
        return item.valor_total
    if item.valor_unitario is not None:
        return item.valor_unitario * item.quantidade
    return Decimal("0")


async def load_order(order_id: uuid.UUID, session: AsyncSession) -> PedidoResponse:
    orders = await load_orders([order_id], session)
    if not orders:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return orders[0]


async def load_orders(
    order_ids: list[uuid.UUID],
    session: AsyncSession,
) -> list[PedidoResponse]:
    if not order_ids:
        return []

    rows = (
        await session.execute(
            select(Pedido, Cliente, Processamento)
            .outerjoin(Cliente, Cliente.id == Pedido.cliente_id)
            .join(Processamento, Processamento.id == Pedido.processamento_id)
            .where(Pedido.id.in_(order_ids))
        )
    ).all()
    order_rows = {order.id: (order, client, process) for order, client, process in rows}
    item_rows = (
        await session.execute(
            select(ItemPedido, ProdutoIndustria)
            .outerjoin(ProdutoIndustria, ProdutoIndustria.id == ItemPedido.produto_industria_id)
            .where(ItemPedido.pedido_id.in_(order_ids))
            .order_by(ItemPedido.pedido_id, ItemPedido.criado_em, ItemPedido.id)
        )
    ).all()
    items_by_order: dict[uuid.UUID, list[ItemPedidoResponse]] = {
        order_id: [] for order_id in order_ids
    }
    for item, product in item_rows:
        items_by_order[item.pedido_id].append(ItemPedidoResponse(
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
        ))

    result = []
    for order_id in order_ids:
        row = order_rows.get(order_id)
        if row is None:
            continue
        order, client, process = row
        items = items_by_order[order_id]
        result.append(PedidoResponse(
            id=order.id,
            processamento_id=order.processamento_id,
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
            total_valor=sum((_item_total(item) for item in items), start=Decimal("0")),
        ))
    return result


@router.get("", response_model=list[PedidoResponse])
async def list_orders(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: StatusPedido | None = None,
) -> list[PedidoResponse]:
    query = select(Pedido.id)
    if status is not None:
        query = query.where(Pedido.status == status)
    ids = (
        await session.execute(
            query.order_by(Pedido.criado_em.desc(), Pedido.id.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return await load_orders(list(ids), session)


@router.get("/{order_id}", response_model=PedidoResponse)
async def get_order(
    order_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PedidoResponse:
    return await load_order(order_id, session)


@router.patch("/{order_id}", response_model=PedidoResponse)
async def update_order(
    order_id: uuid.UUID,
    payload: PedidoUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PedidoResponse:
    order = await session.get(Pedido, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    values = payload.model_dump(exclude_unset=True, exclude={"itens"}, by_alias=False)
    field_map = {
        "numero_pdf": "numero_pdf",
        "cnpj_cliente": "cnpj_extraido",
        "prazo_pagamento": "prazo_pagamento",
        "data_emissao": "data_emissao",
        "previsao_entrega": "previsao_entrega",
        "data_limite_entrega": "data_limite_entrega",
        "condicao_frete": "condicao_frete",
    }
    for source, target in field_map.items():
        if source in values:
            setattr(order, target, _clean_text(values[source]))

    if "cnpj_cliente" in values:
        cnpj = values["cnpj_cliente"]
        client_id = None
        if cnpj is not None:
            client_id = (
                await session.execute(
                    select(Cliente.id).where(Cliente.cnpj == cnpj, Cliente.ativo.is_(True))
                )
            ).scalar_one_or_none()
        order.cliente_id = client_id

    if payload.itens is not None:
        item_ids = [item.id for item in payload.itens]
        entities = (
            await session.execute(
                select(ItemPedido).where(
                    ItemPedido.pedido_id == order_id,
                    ItemPedido.id.in_(item_ids),
                )
            )
        ).scalars().all()
        by_id = {item.id: item for item in entities}
        if len(by_id) != len(set(item_ids)):
            raise HTTPException(status_code=422, detail="Um ou mais itens não pertencem ao pedido")

        item_field_map = {
            "codigo_original": "codigo_original",
            "ean": "ean_extraido",
            "descricao_produto": "descricao",
            "quantidade": "quantidade",
            "embalagem_cx": "embalagem_cx",
            "valor_unitario": "valor_unitario",
            "valor_total": "valor_total",
            "observacao": "observacao",
        }
        for item_payload in payload.itens:
            item = by_id[item_payload.id]
            item_values = item_payload.model_dump(
                exclude_unset=True,
                exclude={"id"},
                by_alias=False,
            )
            for source, target in item_field_map.items():
                if source not in item_values:
                    continue
                value = item_values[source]
                if source in {"codigo_original", "ean", "descricao_produto", "observacao"}:
                    value = _clean_text(value)
                setattr(item, target, value)
            if (
                {"quantidade", "valor_unitario"} & item_values.keys()
                and "valor_total" not in item_values
            ):
                item.valor_total = (
                    item.valor_unitario * item.quantidade
                    if item.valor_unitario is not None
                    else None
                )

    has_changes = bool(values) or bool(payload.itens)
    if has_changes and order.status in {StatusPedido.APROVADO, StatusPedido.EXPORTADO}:
        order.status = StatusPedido.REVISAO
    await session.commit()
    return await load_order(order_id, session)


@router.post("/{order_id}/aprovar", response_model=PedidoResponse)
async def approve_order(
    order_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PedidoResponse:
    order = await session.get(Pedido, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    order.status = StatusPedido.APROVADO
    await session.commit()
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
