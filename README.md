# ADI Backend — Python

Nova implementação do backend do ADI, preservando o backend Java como referência durante a migração.

## Stack

- Python 3.12+
- FastAPI + Pydantic
- SQLAlchemy + Alembic
- PostgreSQL (local ou Supabase)
- NVIDIA NIM por API compatível com OpenAI

## Início rápido

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
python run.py
```

No Windows, use `python run.py` para que o Psycopg utilize um event loop compatível. Em Linux e
no container, o comando padrão do Uvicorn continua suportado.

Não coloque chaves reais no `.env.example` nem no Git.

## Supabase

Crie um projeto vazio e copie a connection string PostgreSQL para `DATABASE_URL`, usando o
driver `postgresql+psycopg://`. Para backend persistente, prefira conexão direta ou pooler em
modo session. Aplique o schema com `alembic upgrade head`.

## Endpoints iniciais

- `GET /health` — processo disponível
- `GET /ready` — verifica banco e configuração do provedor de IA
- `POST /api/processamentos` — recebe um PDF e retorna `202 Accepted`
- `GET /api/processamentos/{id}` — acompanha status e progresso
- `GET /api/processamentos/{id}/pedidos` — lista os pedidos extraídos
- `GET /api/pedidos/{id}` — retorna o pedido completo para revisão
- `GET /api/pedidos/{id}/exportar` — gera e baixa o Excel, marcando o pedido como exportado

O processamento usa `BackgroundTasks` nesta primeira etapa. Antes do deploy definitivo ele será
movido para um worker durável, para sobreviver a reinícios e escalonamento do servidor web.

