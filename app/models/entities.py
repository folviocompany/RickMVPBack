import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import StatusPedido, StatusProcessamento


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def now() -> datetime:
    return datetime.now().astimezone()


class ExtractaLote(Base):
    __tablename__ = "extracta_lote"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    report: Mapped[dict] = mapped_column(JSONB)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )


class Industria(Base):
    __tablename__ = "industria"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    nome: Mapped[str] = mapped_column(String(150))
    cnpj: Mapped[str] = mapped_column(String(14), unique=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RazaoSocial(Base):
    __tablename__ = "razao_social"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    industria_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("industria.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200))
    cnpj_base: Mapped[str] = mapped_column(String(8), index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Cliente(Base):
    __tablename__ = "cliente"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    razao_social_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("razao_social.id"), index=True)
    cnpj: Mapped[str] = mapped_column(String(14), unique=True, index=True)
    nome_fantasia: Mapped[str | None] = mapped_column(String(200))
    bandeira: Mapped[str | None] = mapped_column(String(100))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProdutoIndustria(Base):
    __tablename__ = "produto_industria"
    __table_args__ = (UniqueConstraint("industria_id", "codigo"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    industria_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("industria.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(50))
    ean: Mapped[str | None] = mapped_column(String(14), index=True)
    descricao: Mapped[str] = mapped_column(String(300))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MapeamentoProduto(Base):
    __tablename__ = "mapeamento_produto"
    __table_args__ = (
        UniqueConstraint("cliente_id", "codigo_cliente"),
        UniqueConstraint("cliente_id", "ean_cliente"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    cliente_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cliente.id"), index=True)
    produto_industria_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("produto_industria.id"))
    codigo_cliente: Mapped[str | None] = mapped_column(String(50))
    ean_cliente: Mapped[str | None] = mapped_column(String(14))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Processamento(Base):
    __tablename__ = "processamento"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    arquivo_nome: Mapped[str] = mapped_column(String(300))
    arquivo_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[StatusProcessamento] = mapped_column(
        Enum(StatusProcessamento, name="status_processamento"), default=StatusProcessamento.RECEBIDO
    )
    progresso: Mapped[int] = mapped_column(Integer, default=0)
    mensagem: Mapped[str | None] = mapped_column(String(500))
    erro: Mapped[str | None] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )


class Pedido(Base):
    __tablename__ = "pedido"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    processamento_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("processamento.id"), index=True)
    cliente_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cliente.id"), index=True)
    cnpj_extraido: Mapped[str | None] = mapped_column(String(14))
    numero_pdf: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[StatusPedido] = mapped_column(
        Enum(StatusPedido, name="status_pedido"), default=StatusPedido.PENDENTE
    )
    prazo_pagamento: Mapped[str | None] = mapped_column(String(50))
    data_emissao: Mapped[str | None] = mapped_column(String(20))
    previsao_entrega: Mapped[str | None] = mapped_column(String(20))
    data_limite_entrega: Mapped[str | None] = mapped_column(String(20))
    condicao_frete: Mapped[str | None] = mapped_column(String(30))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )
    itens: Mapped[list["ItemPedido"]] = relationship(
        back_populates="pedido", cascade="all, delete-orphan"
    )


class ItemPedido(Base):
    __tablename__ = "item_pedido"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    pedido_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pedido.id", ondelete="CASCADE"), index=True
    )
    produto_industria_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("produto_industria.id")
    )
    codigo_original: Mapped[str | None] = mapped_column(String(50))
    ean_extraido: Mapped[str | None] = mapped_column(String(14))
    descricao: Mapped[str | None] = mapped_column(Text)
    quantidade: Mapped[int] = mapped_column(Integer)
    embalagem_cx: Mapped[int | None] = mapped_column(Integer)
    valor_unitario: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    valor_total: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    observacao: Mapped[str | None] = mapped_column(Text)
    mapeado: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    pedido: Mapped[Pedido] = relationship(back_populates="itens")
