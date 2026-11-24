import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.models.enums import StatusPedido

MAX_MONEY_VALUE = Decimal("9999999999999.99")


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
    processamento_id: uuid.UUID
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
    total_valor: Decimal


class ItemPedidoUpdate(ApiModel):
    id: uuid.UUID
    codigo_original: str | None = Field(default=None, max_length=50)
    ean: str | None = Field(default=None, max_length=14)
    descricao_produto: str | None = None
    quantidade: int | None = Field(default=None, gt=0, le=1_000_000_000)
    embalagem_cx: int | None = Field(default=None, gt=0, le=1_000_000)
    valor_unitario: Decimal | None = Field(default=None, ge=0, le=MAX_MONEY_VALUE)
    valor_total: Decimal | None = Field(default=None, ge=0, le=MAX_MONEY_VALUE)
    observacao: str | None = None

    @field_validator("quantidade")
    @classmethod
    def require_quantity_when_provided(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("Quantidade não pode ser vazia")
        return value


class PedidoUpdate(ApiModel):
    numero_pdf: str | None = Field(default=None, max_length=100)
    cnpj_cliente: str | None = Field(default=None, max_length=18)
    prazo_pagamento: str | None = Field(default=None, max_length=50)
    data_emissao: str | None = Field(default=None, max_length=20)
    previsao_entrega: str | None = Field(default=None, max_length=20)
    data_limite_entrega: str | None = Field(default=None, max_length=20)
    condicao_frete: str | None = Field(default=None, max_length=30)
    itens: list[ItemPedidoUpdate] | None = None

    @field_validator("cnpj_cliente")
    @classmethod
    def normalize_cnpj(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        digits = "".join(character for character in value if character.isdigit())
        if len(digits) != 14:
            raise ValueError("CNPJ deve conter 14 dígitos")
        return digits
