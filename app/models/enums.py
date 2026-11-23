from enum import StrEnum


class StatusPedido(StrEnum):
    PENDENTE = "PENDENTE"
    PROCESSANDO = "PROCESSANDO"
    REVISAO = "REVISAO"
    APROVADO = "APROVADO"
    EXPORTADO = "EXPORTADO"
    ERRO = "ERRO"


class StatusProcessamento(StrEnum):
    RECEBIDO = "RECEBIDO"
    EXTRAINDO = "EXTRAINDO"
    MAPEANDO = "MAPEANDO"
    CONCLUIDO = "CONCLUIDO"
    PARCIAL = "PARCIAL"
    ERRO = "ERRO"
