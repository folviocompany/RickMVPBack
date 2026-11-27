# Extracta

## Fluxo atual

O agente inspeciona cada página, aproveita texto pesquisável quando utilizável, renderiza páginas sem texto a 300 DPI e executa OCR local com Tesseract. O perfil Atacadão reconhece múltiplas âncoras, associa linhas de mercadoria às linhas de código e une páginas pelo número do pedido e Pedido EDI.

O LangGraph coordena inspeção, OCR, reconhecimento, extração, validação e encaminhamento à conferência. Quando a extração não fecha os produtos ou não identifica o perfil, pode executar uma segunda passagem OCR com configuração alternativa. O limite é de duas passagens e dezesseis transições. A recuperação NVIDIA é opcional e desabilitada por padrão. O tracing remoto é desabilitado explicitamente. Consulte os detalhes em [Recuperação e reprocessamento](extracta-recovery.md).

## Contrato e evidências

O resultado inclui identificação própria, hash SHA256, nome do arquivo, número de páginas, perfil e versão, transições, tempos medidos, pedidos, avisos e erros. Cada item possui identificação de linha e página de origem.

Código composto, embalagem, número adicional semelhante a código de barras e campos tributários são preservados como texto bruto. Não são completados zeros nem convertidas embalagens em unidades. Quantidades e dinheiro usam Decimal. Ausência é null e não zero.

As evidências guardam texto original, página, caixa normalizada entre zero e um e estratégia utilizada. A caixa corresponde à linha de origem, não a uma localização precisa do caractere. Quando disponível, a confiança mínima das palavras reconhecidas pelo Tesseract é preservada como informação bruta do OCR e não representa probabilidade de acerto.

Total Produtos, total Pedido e soma calculada das mercadorias são independentes. A tolerância inicial da soma dos produtos é de cinco centavos. Diferenças entre Pedido e Produtos são sinalizadas; o sistema não assume uma fórmula tributária nem modifica preços para fechar o total.

Datas incompletas de entrega permanecem no formato original. Identificação da empresa emissora não é inferida do nome do arquivo. Campos do fornecedor e endereço ainda não possuem extração dedicada nesta versão e permanecem ausentes.

## Execução local

Na pasta do backend, instale o projeto com os extras de desenvolvimento.

```powershell
.venv\Scripts\Activate.ps1
pip install ".[dev]"
python run.py
```

O README descreve a instalação do executável Tesseract e dos idiomas português e inglês. Pip instala pytesseract, mas não instala esse executável.

Na pasta do frontend, execute:

```powershell
npm install
npm run dev
```

Abra `http://localhost:5173/extracta`, selecione os documentos e use `Processar`. Cada documento passa por estados reais de fila, processamento e conferência ou falha. O navegador consulta o lote periodicamente. A falha de um documento não impede os demais.

## Armazenamento e limites

As amostras ficam em `samples/atacadao`, configurável por `EXTRACTA_SAMPLES_DIR`. Os três PDFs de teste foram copiados para essa pasta e os originais foram preservados. PDFs, relatórios locais e idiomas OCR são ignorados no Git.

Cada lote e documento recebe um UUID. PDFs ficam em `EXTRACTA_RESULTS_DIR`, por padrão `data/extracta`. Resultados, evidências, revisões e aprovações ficam na tabela `extracta_lote` do PostgreSQL. Execute `alembic upgrade head` antes de iniciar a versão atualizada. A migration é aditiva e não altera os pedidos do fluxo anterior.

Relatórios locais da primeira entrega são importados no startup quando seu UUID ainda não existe no banco. Não substituem correções já salvas. Nomes recebidos nunca definem os caminhos de armazenamento. O modo `EXTRACTA_STORAGE=local` serve para testes isolados sem PostgreSQL; o padrão da aplicação é `postgres`.

Este mecanismo usa um único processo servidor, com uma fila local em memória. Um reinício preserva resultados concluídos e marca tarefas pendentes como interrompidas. Não há retomada automática nem garantia de fila durável. Falhas e interrupções podem ser reprocessadas mantendo o mesmo documento e o histórico de tentativas. Não configure múltiplos workers.

O limite padrão é de dez documentos por lote, vinte MB por arquivo e trinta páginas por documento. O OCR tem timeout de sessenta segundos por página. O servidor precisa de espaço para PDFs e relatórios. Não há autenticação nesta fase de uso local.

## API

1. `GET /api/extracta/ready` verifica o executável e os idiomas OCR.
2. `POST /api/extracta/lotes` recebe múltiplos campos multipart chamados `arquivos` e retorna o identificador do lote.
3. `GET /api/extracta/lotes/{id}` retorna estados, documentos e resultados reais.
4. `GET /api/extracta/lotes/{id}/documentos/{documento}/arquivo` permite conferir o PDF original do lote.
5. `GET /api/extracta/lotes?limit=20&offset=0` lista o histórico paginado.
6. `PATCH /api/extracta/lotes/{id}/documentos/{documento}` salva correções com revisão esperada e responsável.
7. `POST /api/extracta/lotes/{id}/documentos/{documento}/aprovar` registra a conferência.
8. `POST /api/extracta/lotes/{id}/documentos/{documento}/exportar` exporta apenas o documento selecionado.
9. `POST /api/extracta/lotes/{id}/exportar` exporta o lote inteiro após a aprovação de todos os documentos.
10. `POST /api/extracta/lotes/{id}/documentos/{documento}/reprocessar` solicita uma nova tentativa informando a revisão atual.

## Conferência e exportação

Abra um lote na tela `Histórico`. Use `Corrigir documento`, informe o responsável, ajuste os campos necessários e salve. Cada alteração mantém o valor anterior e o valor corrigido na auditoria. O resultado original da extração e suas evidências não são substituídos. O responsável é um nome informado, sem autenticação nesta versão local.

As revisões são numeradas. Uma gravação com revisão desatualizada retorna 409 para evitar que uma aba sobrescreva alterações feitas em outra. No PostgreSQL, a operação usa transação e bloqueio da linha do lote. Correções de um documento aprovado ou exportado removem sua aprovação e exigem nova conferência.

Descrição, quantidade, preço e identificação mínima do pedido são bloqueios de aprovação quando inválidos. Ausências e diferenças de totais podem ser aceitas explicitamente após conferência, com confirmação e justificativa obrigatórias. A aceitação não inventa valores nem altera os totais declarados. Valores monetários calculados são arredondados por linha para dois decimais, com ROUND_HALF_UP.

O Excel contém as abas `Pedidos`, `Itens`, `Pendencias`, `Auditoria` e `Evidencias`. Cada linha tem vínculo explícito com documento e pedido. Códigos são texto, números são valores numéricos e ausências permanecem vazias. Conteúdo textual iniciado por sinal de fórmula é gravado como texto literal. Exportar um único documento deixa o escopo registrado na planilha; o lote inteiro não é exportado se algum documento falhou ou ainda aguarda aprovação.

As aprovações nos testes são simuladas em registros temporários. Não equivalem a conferência humana dos pedidos de demonstração.

## Testes

```powershell
python -m pytest -q
python -m ruff check .
$env:RUN_LOCAL_OCR_TESTS="1"
python -m pytest tests/test_extracta_samples.py -q
```

O teste com amostras requer os PDFs locais e os idiomas OCR. Ausência das amostras ou dependências faz o teste falhar quando explicitamente habilitado. As fixtures são transcrições manuais separadas e nunca são carregadas pelo código de produção. Os arquivos são apresentados ao agente com nome alterado no teste para verificar que o nome não determina a extração.

A avaliação manual compara os códigos compostos, páginas, quantidades, preços, entrega e totais. Isso não comprova precisão de todas as descrições, embalagens, códigos adicionais, tributos ou endereços. Campos incompletos continuam sujeitos à revisão.

## Próximas entregas

Faltam avaliar a recuperação com o modelo real explicitamente habilitado, ampliar as amostras de outros layouts e validar o template de importação com o negócio.

O Excel do novo contrato é provisório. Nenhum template real de importação Salesforce foi validado. Não apresentar o novo agente como pronto para importar no Salesforce.

## Referências técnicas

[LangGraph StateGraph](https://reference.langchain.com/python/langgraph/graph/state/StateGraph) documenta o grafo de estado utilizado. A [documentação do Tesseract](https://tesseract-ocr.github.io/tessdoc/) descreve o motor OCR e seus idiomas.
