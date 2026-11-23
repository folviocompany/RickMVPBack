import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import StatusPedido, StatusProcessamento


class ProcessamentoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    arquivo_nome: str
    status: StatusProcessamento
    progresso: int
    mensagem: str | None
    erro: str | None
    criado_em: datetime
    atualizado_em: datetime


class PedidoProcessadoResponse(BaseModel):
    id: uuid.UUID
    numero_pdf: str | None
    status: StatusPedido
    cliente_id: uuid.UUID | None
    total_itens: int
    itens_sem_mapeamento: int
