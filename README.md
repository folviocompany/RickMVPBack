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

## Roteiro de demonstração local

Inicie a API em um terminal:

```powershell
cd backend-python
.venv\Scripts\Activate.ps1
alembic upgrade head
python run.py
```

Confirme que banco e NVIDIA estão disponíveis em `http://localhost:8080/ready`. A documentação
interativa da API fica em `http://localhost:8080/docs`.

Em outro terminal, inicie o frontend:

```powershell
cd frontend
npm install
npm run dev
```

Abra `http://localhost:5173`, entre em **Novo pedido**, selecione o PDF e acompanhe o progresso.
Ao concluir, confira número do pedido, prazo, frete, códigos, quantidades e preços antes de exportar
o Excel. PDFs com clientes ou produtos ainda não cadastrados aparecem como pendentes de revisão;
isso é esperado e evita aprovar automaticamente um mapeamento desconhecido.

Matriz de referência validada para os PDFs de demonstração:

| Documento | Pedido | Itens esperados |
| --- | ---: | ---: |
| Teste 1 - Loja 1 | 51417 | 12 |
| Teste 1 - Loja 2 | 51419 | 2 |
| Teste 1 - Loja 3 | 51421 | 13 |

## Deploy no Render

O repositório contém um `render.yaml` preparado para criar um Web Service Docker gratuito.

1. No Render, escolha **New > Blueprint** e conecte o repositório
   `folviocompany/RickMVPBack`.
2. Confirme a branch `main` e aplique o Blueprint.
3. Preencha as variáveis solicitadas pelo painel:

   - `DATABASE_URL`: connection string PostgreSQL do Supabase, preferencialmente pelo pooler em
     modo session e com SSL habilitado.
   - `NVIDIA_API_KEY`: chave da API NVIDIA.
   - `FRONTEND_ORIGINS`: URL HTTPS do frontend publicado. Enquanto o frontend não estiver no ar,
     use temporariamente `http://localhost:5173` para testes locais.

O Render fornece `PORT` automaticamente. O container executa `alembic upgrade head` antes de
iniciar o Uvicorn, portanto as migrations são aplicadas em cada deploy. O health check utiliza
`GET /health`.

Os PDFs são gravados temporariamente em `/tmp/adi-uploads`. Isso é suficiente para o fluxo atual,
pois os pedidos extraídos ficam no PostgreSQL, mas um processamento em andamento não sobrevive a
reinícios. Antes do uso em produção, mova o processamento para um worker durável e adicione
autenticação para impedir consumo não autorizado da API NVIDIA.

Depois do deploy, valide:

```text
https://SEU-SERVICO.onrender.com/health
https://SEU-SERVICO.onrender.com/ready
https://SEU-SERVICO.onrender.com/docs
```

