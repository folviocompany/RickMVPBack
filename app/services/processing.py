import asyncio
import uuid
from pathlib import Path

from sqlalchemy import or_, select

from app.core.config import get_settings
from app.db.session import session_factory
from app.llm.nvidia import NvidiaExtractionProvider
from app.models.entities import Cliente, ItemPedido, MapeamentoProduto, Pedido, Processamento
from app.models.enums import StatusPedido, StatusProcessamento
from app.services.ocr import NvidiaOcrService
from app.services.pdf import PdfNeedsOcrError, extract_pdf_text


async def _update_process(
    process_id: uuid.UUID,
    status: StatusProcessamento,
    progress: int,
    message: str,
    error: str | None = None,
) -> None:
    async with session_factory() as session:
        process = await session.get(Processamento, process_id)
        if process is None:
            return
        process.status = status
        process.progresso = progress
        process.mensagem = message
        process.erro = error
        await session.commit()


async def process_pdf(process_id: uuid.UUID) -> None:
    settings = get_settings()
    try:
        async with session_factory() as session:
            process = await session.get(Processamento, process_id)
            if process is None:
                return
            file_path = Path(process.arquivo_path)

        await _update_process(
            process_id, StatusProcessamento.EXTRAINDO, 10, "Extraindo texto do PDF"
        )
        content = await asyncio.to_thread(file_path.read_bytes)
        try:
            document_text = await asyncio.to_thread(extract_pdf_text, content)
        except PdfNeedsOcrError:
            await _update_process(
                process_id, StatusProcessamento.EXTRAINDO, 20, "Aplicando OCR ao PDF"
            )
            document_text = await NvidiaOcrService(settings).extract_pdf(content)

        await _update_process(
            process_id, StatusProcessamento.EXTRAINDO, 30, "Extraindo pedidos com IA"
        )
        extraction = await NvidiaExtractionProvider(settings).extract_orders(document_text)

        await _update_process(
            process_id, StatusProcessamento.MAPEANDO, 70, "Mapeando clientes e produtos"
        )
        async with session_factory() as session:
            for extracted_order in extraction.pedidos:
                client = None
                if extracted_order.cnpj_cliente:
                    client = await session.scalar(
                        select(Cliente).where(
                            Cliente.cnpj == extracted_order.cnpj_cliente,
                            Cliente.ativo.is_(True),
                        )
                    )
                order = Pedido(
                    processamento_id=process_id,
                    cliente_id=client.id if client else None,
                    cnpj_extraido=extracted_order.cnpj_cliente,
                    numero_pdf=extracted_order.numero_pedido,
                    prazo_pagamento=extracted_order.prazo_pagamento,
                    data_emissao=extracted_order.data_emissao,
                    previsao_entrega=extracted_order.previsao_entrega,
                    data_limite_entrega=extracted_order.data_limite_entrega,
                    condicao_frete=extracted_order.condicao_frete,
                    status=StatusPedido.APROVADO,
                    itens=[],
                )
                session.add(order)

                for extracted_item in extracted_order.itens:
                    mapping = None
                    if client is not None:
                        codes = [
                            value
                            for value in (
                                extracted_item.seq_bic,
                                extracted_item.ref_cliente,
                                extracted_item.codigo_produto,
                            )
                            if value
                        ]
                        criteria = []
                        if codes:
                            criteria.append(MapeamentoProduto.codigo_cliente.in_(codes))
                        if extracted_item.ean:
                            criteria.append(MapeamentoProduto.ean_cliente == extracted_item.ean)
                        if criteria:
                            mapping = await session.scalar(
                                select(MapeamentoProduto).where(
                                    MapeamentoProduto.cliente_id == client.id,
                                    or_(*criteria),
                                )
                            )

                    mapped = mapping is not None
                    if not mapped:
                        order.status = StatusPedido.REVISAO
                    original_code = (
                        extracted_item.ref_cliente
                        or extracted_item.seq_bic
                        or extracted_item.codigo_produto
                    )
                    order.itens.append(
                        ItemPedido(
                            produto_industria_id=(
                                mapping.produto_industria_id if mapping else None
                            ),
                            codigo_original=original_code,
                            ean_extraido=extracted_item.ean,
                            descricao=extracted_item.descricao,
                            quantidade=extracted_item.quantidade,
                            embalagem_cx=extracted_item.embalagem_cx,
                            valor_unitario=extracted_item.valor_unitario,
                            valor_total=extracted_item.valor_total,
                            observacao=extracted_item.observacao,
                            mapeado=mapped,
                        )
                    )

            process = await session.get(Processamento, process_id)
            if process is not None:
                process.status = StatusProcessamento.CONCLUIDO
                process.progresso = 100
                process.mensagem = f"{len(extraction.pedidos)} pedido(s) processado(s)"
            await session.commit()
    except Exception as exc:
        await _update_process(
            process_id,
            StatusProcessamento.ERRO,
            100,
            "Falha no processamento",
            error=str(exc)[:1000],
        )
