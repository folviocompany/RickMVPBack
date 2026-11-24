import os
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import BackgroundTasks
from openpyxl import load_workbook
from sqlalchemy import delete

from app.api.orders import approve_order, export_order, get_order, list_orders, update_order
from app.api.processing import create_process, get_process, list_processed_orders
from app.db.session import session_factory
from app.llm.nvidia import NvidiaExtractionProvider
from app.models.entities import (
    Cliente,
    Industria,
    ItemPedido,
    MapeamentoProduto,
    Pedido,
    Processamento,
    ProdutoIndustria,
    RazaoSocial,
)
from app.schemas.extraction import DocumentoExtraido
from app.schemas.orders import PedidoUpdate
from tests.pdf_factory import MemoryUpload, make_pdf

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION_TESTS") != "1",
        reason="set RUN_INTEGRATION_TESTS=1 to use the configured test database",
    ),
]


async def _complete_pdf_flow_with_mocked_nvidia(monkeypatch):
    ids = {name: uuid.uuid4() for name in ("industria", "razao", "cliente", "produto")}
    process_id = None

    async def fake_extract(self, document_text: str) -> DocumentoExtraido:
        assert "PÁGINA 1" in document_text
        assert "PÁGINA 2" in document_text
        return DocumentoExtraido.model_validate(
            {
                "pedidos": [
                    {
                        "numero_pedido": "TESTE-001",
                        "cnpj_cliente": "99.999.999/0001-99",
                        "prazo_pagamento": "28",
                        "condicao_frete": "CIF",
                        "itens": [
                            {
                                "seq_bic": "109703",
                                "ref_cliente": "0068",
                                "descricao": "Produto mapeado",
                                "quantidade": 10,
                                "valor_unitario": "5.00",
                                "valor_total": "50.00",
                            },
                            {
                                "seq_bic": "999999",
                                "descricao": "Produto para revisão",
                                "quantidade": 2,
                                "valor_unitario": "8.00",
                            },
                        ],
                    }
                ]
            }
        )

    monkeypatch.setattr(NvidiaExtractionProvider, "extract_orders", fake_extract)

    try:
        async with session_factory() as session:
            session.add(
                Industria(id=ids["industria"], nome="Industria Teste ADI", cnpj="88888888000188")
            )
            await session.flush()
            session.add(
                RazaoSocial(
                    id=ids["razao"],
                    industria_id=ids["industria"],
                    nome="Razao Teste ADI",
                    cnpj_base="99999999",
                )
            )
            await session.flush()
            session.add(
                Cliente(
                    id=ids["cliente"],
                    razao_social_id=ids["razao"],
                    cnpj="99999999000199",
                    nome_fantasia="Cliente Teste ADI",
                )
            )
            session.add(
                ProdutoIndustria(
                    id=ids["produto"],
                    industria_id=ids["industria"],
                    codigo="BIC-TESTE-001",
                    descricao="Produto Teste ADI",
                )
            )
            await session.flush()
            session.add(
                MapeamentoProduto(
                    cliente_id=ids["cliente"],
                    produto_industria_id=ids["produto"],
                    codigo_cliente="0068",
                )
            )
            await session.commit()

        pdf = make_pdf("PEDIDO TESTE-001", "CONTINUACAO COM ITENS")
        upload = MemoryUpload("pedido-teste.pdf", pdf)
        background_tasks = BackgroundTasks()
        async with session_factory() as session:
            process = await create_process(background_tasks, upload, session)
            process_id = process.id

        await background_tasks()

        async with session_factory() as session:
            status_result = await get_process(process_id, session)
            assert status_result.status.value == "CONCLUIDO", status_result.erro
            assert status_result.progresso == 100

            orders = await list_processed_orders(process_id, session)
            assert len(orders) == 1
            assert orders[0].status.value == "REVISAO"
            assert orders[0].total_itens == 2
            assert orders[0].itens_sem_mapeamento == 1

            detail = await get_order(orders[0].id, session)
            assert detail.processamento_id == process_id
            assert detail.nome_cliente == "Cliente Teste ADI"
            assert detail.cnpj_cliente == "99999999000199"
            assert detail.numero_pdf == "TESTE-001"
            assert detail.total_valor == 66
            assert detail.itens[0].codigo_industria == "BIC-TESTE-001"
            assert detail.itens[1].codigo_industria is None

            history = await list_orders(session, limit=50, offset=0)
            assert any(order.id == orders[0].id for order in history)

            updated = await update_order(
                orders[0].id,
                PedidoUpdate.model_validate(
                    {
                        "numeroPdf": "TESTE-001-CORRIGIDO",
                        "cnpjCliente": "11.111.111/0001-11",
                        "prazoPagamento": "35",
                        "itens": [
                            {
                                "id": str(detail.itens[1].id),
                                "quantidade": 3,
                                "valorUnitario": "9.50",
                                "valorTotal": "28.50",
                            }
                        ],
                    }
                ),
                session,
            )
            assert updated.numero_pdf == "TESTE-001-CORRIGIDO"
            assert updated.cnpj_cliente == "11111111000111"
            assert updated.nome_cliente is None
            assert updated.prazo_pagamento == "35"
            assert updated.itens[1].quantidade == 3
            assert updated.itens[1].valor_total == 28.5
            assert updated.total_valor == 78.5

            approved = await approve_order(orders[0].id, session)
            assert approved.status.value == "APROVADO"

            export = await export_order(orders[0].id, session)
            content = b"".join([chunk async for chunk in export.body_iterator])
            workbook = load_workbook(filename=BytesIO(content), read_only=True)
            assert workbook["Pedido"]["A1"].value == "Cód. Cliente"
            assert workbook["Pedido"].max_row == 4

            exported = await get_order(orders[0].id, session)
            assert exported.status.value == "EXPORTADO"

            revised = await update_order(
                orders[0].id,
                PedidoUpdate(numero_pdf="TESTE-001-REVISADO"),
                session,
            )
            assert revised.status.value == "REVISAO"

    finally:
        async with session_factory() as session:
            if process_id is not None:
                order_ids = [
                    row[0]
                    for row in (
                        await session.execute(
                            Pedido.__table__.select()
                            .with_only_columns(Pedido.id)
                            .where(Pedido.processamento_id == process_id)
                        )
                    ).all()
                ]
                if order_ids:
                    await session.execute(
                        delete(ItemPedido).where(ItemPedido.pedido_id.in_(order_ids))
                    )
                    await session.execute(delete(Pedido).where(Pedido.id.in_(order_ids)))
                await session.execute(delete(Processamento).where(Processamento.id == process_id))
            await session.execute(
                delete(MapeamentoProduto).where(MapeamentoProduto.cliente_id == ids["cliente"])
            )
            await session.execute(
                delete(ProdutoIndustria).where(ProdutoIndustria.id == ids["produto"])
            )
            await session.execute(delete(Cliente).where(Cliente.id == ids["cliente"]))
            await session.execute(delete(RazaoSocial).where(RazaoSocial.id == ids["razao"]))
            await session.execute(delete(Industria).where(Industria.id == ids["industria"]))
            await session.commit()

        if process_id is not None:
            path = Path("data/uploads") / f"{process_id}.pdf"
            path.unlink(missing_ok=True)


def test_complete_pdf_flow_with_mocked_nvidia(monkeypatch):
    from tests.async_runner import run_async

    run_async(_complete_pdf_flow_with_mocked_nvidia(monkeypatch))
