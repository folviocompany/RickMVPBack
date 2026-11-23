import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ItemExtraido(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq_bic: str | None = None
    ref_cliente: str | None = None
    codigo_produto: str | None = None
    ean: str | None = None
    descricao: str | None = None
    quantidade: int = Field(gt=0, le=1_000_000_000)
    embalagem_cx: int | None = Field(default=None, gt=0, le=1_000_000)
    valor_unitario: Decimal | None = Field(default=None, ge=0)
    valor_total: Decimal | None = Field(default=None, ge=0)
    observacao: str | None = None

    @field_validator("seq_bic", "ref_cliente", "codigo_produto", "ean", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            match = re.fullmatch(r"(\d{6,10})/\d+", normalized)
            if match:
                return match.group(1)
            return normalized or None
        return value

    @field_validator("embalagem_cx", mode="before")
    @classmethod
    def normalize_package_size(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized.isdigit():
                package_size = int(normalized)
                return package_size if package_size <= 1_000_000 else None
            return None
        if isinstance(value, int) and value > 1_000_000:
            return None
        return value

    @field_validator("valor_unitario", "valor_total", mode="before")
    @classmethod
    def normalize_decimal(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = re.sub(r"[^0-9,.-]", "", value.strip())
        if not normalized:
            return None
        if "," in normalized:
            normalized = normalized.replace(".", "").replace(",", ".")
        return normalized

    @model_validator(mode="after")
    def check_total(self):
        if self.codigo_produto:
            match = re.fullmatch(r"(\d{6,10})/\d+", self.codigo_produto)
            if match:
                self.codigo_produto = match.group(1)
        if self.valor_unitario is None or self.valor_total is None:
            return self
        expected = self.valor_unitario * self.quantidade
        tolerance = max(Decimal("0.05"), self.valor_total * Decimal("0.01"))
        if abs(expected - self.valor_total) > tolerance:
            note = "Total extraído diverge de quantidade × valor unitário"
            self.observacao = f"{self.observacao}; {note}" if self.observacao else note
        return self


class PedidoExtraido(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numero_pedido: str | None = None
    cnpj_cliente: str | None = None
    codigo_fornecedor: str | None = None
    prazo_pagamento: str | None = None
    data_emissao: str | None = None
    previsao_entrega: str | None = None
    data_limite_entrega: str | None = None
    condicao_frete: str | None = None
    itens: list[ItemExtraido] = Field(min_length=1)

    @field_validator("cnpj_cliente")
    @classmethod
    def normalize_cnpj(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        digits = re.sub(r"\D", "", value)
        if len(digits) != 14:
            raise ValueError("CNPJ do cliente deve conter 14 dígitos")
        return digits


class DocumentoExtraido(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pedidos: list[PedidoExtraido] = Field(min_length=1)
