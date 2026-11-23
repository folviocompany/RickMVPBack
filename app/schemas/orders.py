import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.models.enums import StatusPedido


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class ItemPedidoResponse(ApiModel):
    id: uuid.UUID
    codigo_original: str | None
    codigo_industria: str | None
    ean: str | None
    descricao_produto: str | None
    quantidade: int
    embalagem_cx: int | None
    valor_unitario: Decimal | None
    valor_total: Decimal | None
    observacao: str | None
    mapeado: bool


class PedidoResponse(ApiModel):
    id: uuid.UUID
    nome_cliente: str | None
    cnpj_cliente: str | None
    numero_pdf: str | None
    status: StatusPedido
    arquivo_nome: str
    prazo_pagamento: str | None
    data_emissao: str | None
    previsao_entrega: str | None
    data_limite_entrega: str | None
    condicao_frete: str | None
    criado_em: datetime
    itens: list[ItemPedidoResponse]
    total_itens: int
    itens_sem_mapeamento: int
