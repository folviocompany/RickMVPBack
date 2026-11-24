# Automação e conferência de Pedidos

Este repositório contém o backend em Python do sistema de automação e conferência de pedidos. A aplicação recebe arquivos PDF, extrai as informações com inteligência artificial, relaciona clientes e produtos cadastrados, salva os resultados no PostgreSQL e prepara cada pedido para revisão e exportação.

## Tecnologias utilizadas

1. Python 3.12 ou superior
2. FastAPI e Pydantic
3. SQLAlchemy e Alembic
4. PostgreSQL local ou Supabase
5. NVIDIA NIM para extração dos dados
6. OpenPyXL para geração das planilhas

## Preparação do ambiente

Abra um terminal nesta pasta e crie o ambiente virtual.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install ".[dev]"
```

Crie o arquivo de configuração local a partir do exemplo disponível.

```powershell
Copy-Item .env.example .env
```

Preencha no arquivo `.env` a conexão do PostgreSQL e a chave da NVIDIA. As configurações principais são `DATABASE_URL` e `NVIDIA_API_KEY`. Nunca coloque uma chave real no arquivo `.env.example` ou em um commit.

Depois de configurar as variáveis, prepare o banco de dados.

```powershell
alembic upgrade head
```

## Execução local

Com o ambiente virtual ativo, inicie a API com o comando abaixo.

```powershell
python run.py
```

O servidor fica disponível em `http://localhost:8080`.

A documentação interativa pode ser acessada em `http://localhost:8080/docs`.

O endereço `http://localhost:8080/ready` confirma se o banco de dados e a integração com a NVIDIA estão configurados corretamente.

## Funcionamento do processamento

1. O frontend envia um arquivo PDF.
2. O backend valida o tipo e o tamanho do arquivo.
3. O texto pesquisável é extraído diretamente do documento.
4. Quando o PDF contém apenas imagens, o serviço utiliza OCR.
5. A inteligência artificial identifica os pedidos e seus itens.
6. O sistema procura clientes e produtos correspondentes no banco.
7. Os dados são salvos e ficam disponíveis para conferência.
8. Alterações feitas pelo usuário retornam o pedido para revisão.
9. Depois da conferência, o pedido pode ser aprovado e exportado em Excel.

Cada processamento mantém sua própria identificação. Dessa forma, pedidos originados de arquivos diferentes permanecem separados no histórico.

## Recursos disponíveis

1. Recebimento e validação de arquivos PDF
2. Extração de uma ou várias páginas
3. Uso de OCR quando necessário
4. Identificação de mais de um pedido no mesmo documento
5. Histórico persistente e paginado
6. Edição dos dados do pedido e de seus itens
7. Aprovação após conferência
8. Cálculo do valor total de cada pedido
9. Exportação de planilha Excel

## Endereços da API

1. `GET /health` informa se o processo está disponível.
2. `GET /ready` verifica o banco e a configuração da inteligência artificial.
3. `POST /api/processamentos` recebe um arquivo PDF.
4. `GET /api/processamentos/{id}` informa o andamento do processamento.
5. `GET /api/processamentos/{id}/pedidos` lista os pedidos encontrados no arquivo.
6. `GET /api/pedidos` apresenta o histórico persistente.
7. `GET /api/pedidos/{id}` retorna um pedido completo.
8. `PATCH /api/pedidos/{id}` salva as correções realizadas.
9. `POST /api/pedidos/{id}/aprovar` aprova o pedido conferido.
10. `GET /api/pedidos/{id}/exportar` gera a planilha Excel.

## Testes e qualidade

Execute os testes automatizados com o ambiente virtual ativo.

```powershell
python -m pytest -q
python -m ruff check .
```

O teste de integração com o PostgreSQL pode ser executado separadamente.

```powershell
$env:RUN_INTEGRATION_TESTS="1"
python -m pytest tests\test_processing_integration.py -q
```

## Apresentação local

Antes da demonstração, confirme o endereço `/ready`, processe um dos arquivos de teste e revise os valores exibidos. O fluxo recomendado é enviar o PDF, aguardar a extração, conferir o pedido, corrigir eventuais divergências, aprovar e exportar a planilha.

Os pedidos ficam armazenados no PostgreSQL e continuam disponíveis depois que o navegador ou o servidor são reiniciados.
