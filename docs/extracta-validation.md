# Avaliação inicial do Extracta

Data da avaliação: 26/11/2026.

## Ambiente e baseline

Antes das alterações, o backend passou em vinte e dois testes, com uma integração opcional não executada na baseline. O frontend passou em nove testes. As árvores dos dois repositórios estavam limpas.

Foram instalados LangGraph 1.2.24, pytesseract 0.3.13, Pillow 12.3.0 e Tesseract 5.4.0. Os idiomas disponíveis foram confirmados como português e inglês. A inferência NVIDIA e o tracing remoto não participaram da avaliação.

## Amostras

Os três originais foram copiados para `samples/atacadao`. A inspeção confirmou cinco páginas, zero caracteres pesquisáveis e nenhuma imagem incorporada retornada por `get_images`. As páginas foram renderizadas integralmente para OCR. Os PDFs não foram enviados a serviços externos.

Loja 1 e Loja 2 foram usadas no desenvolvimento. Loja 3 foi avaliada depois do ajuste das regras nas duas primeiras. Seu primeiro resultado foi preservado em `tmp/extracta/loja3-first-evaluation.json`. Como ela já havia sido utilizada no projeto anterior, não é uma avaliação cega independente.

## Resultado medido

1. Loja 1: duas páginas, pedido 51417, EDI 2051417, doze mercadorias, soma calculada de R$ 22.115,82 e total declarado de R$ 22.115,82. Tempo total de 5,26 segundos, sendo 5,20 segundos de OCR.
2. Loja 2: uma página, pedido 51419, EDI 2051419, duas mercadorias, soma calculada de R$ 5.806,24 e total declarado de R$ 5.806,24. Tempo total de 2,50 segundos, sendo 2,47 segundos de OCR.
3. Loja 3: duas páginas, pedido 51421, EDI 2051421, treze mercadorias, soma calculada de R$ 21.442,84 e total declarado de R$ 21.718,78. A diferença de R$ 275,94 foi sinalizada para conferência. Tempo total de 5,35 segundos, sendo 5,31 segundos de OCR.

Cada documento usou uma passagem OCR e zero chamadas LLM. O tempo somado dessas três execuções foi de aproximadamente 13,11 segundos. Esses valores variam conforme computador e carga. Não incluem intervenção humana nem representam economia comprovada em relação ao processo manual.

A primeira execução da Loja 3 encontrou treze mercadorias e somou R$ 21.442,84 em 5,70 segundos. Nenhuma regra de produção foi ajustada com seu conteúdo após essa avaliação.

## Verificação por campo

As fixtures foram transcritas manualmente das cinco páginas renderizadas. Os testes conferem individualmente página de origem, código composto, quantidade, preço unitário e data bruta de entrega em cada uma das vinte e sete mercadorias. Foram verificadas 135 correspondências nesses cinco campos, todas corretas nessa execução.

Também passaram as comparações de número, EDI, páginas, pagamento de sessenta dias, emissão 27/10/26, frete CIF e totais dos três documentos. Na Loja 3, as duas linhas com IPI bruto 15,0 foram identificadas. Nenhum imposto foi recalculado para forçar a diferença entre os totais.

Isso não significa cem por cento de precisão de todo o documento. Descrições, embalagens, códigos adicionais e todas as colunas tributárias ainda não têm fixtures completas de avaliação por campo. Não foram contadas ausências como acertos. Fornecedor e local de entrega não são extraídos nesta versão; ficam ausentes e sinalizados. A empresa emissora não foi reconhecida na Loja 3 e permaneceu ausente.

Uma linha na Loja 1 e uma na Loja 3 apresentaram ambiguidade nas colunas de tributos/peso. Esses campos foram deixados ausentes com aviso. Os demais itens não foram descartados por esse motivo.

Todos os três documentos foram encaminhados à revisão. A taxa de aprovação automática é zero de três, por política desta primeira entrega. Não há medição de tempo de intervenção humana nem comparação com digitação manual.

## Testes de integração

O teste da API recebe os três PDFs no mesmo lote, verifica cinco páginas, vinte e sete linhas, três identificadores documentais diferentes e zero chamadas externas. Também recupera o PDF original pelo identificador do lote e confirma que seus bytes foram preservados.

Os testes adicionais cobrem PDF inválido, perfil desconhecido, limite de páginas, repetição legítima de código em páginas diferentes, separação de pedidos, vírgula decimal, falha individual no lote e marcação de tarefas interrompidas após reinício.

O fluxo anterior com PostgreSQL também foi executado e passou. Não foi gerada uma nova planilha do contrato Extracta nesta etapa. Exportação e aprovação com evidências continuam pendentes; o Excel anterior permanece vinculado ao fluxo anterior.

## Arquivos locais e reprodução

O relatório completo da avaliação está em `tmp/extracta/evaluation-final.json`. A primeira execução de desenvolvimento, incluindo a falha de resolução do caminho dos idiomas no Windows, ficou em `tmp/extracta/development-first.json`. O problema foi corrigido antes da avaliação final.

```powershell
$env:RUN_LOCAL_OCR_TESTS="1"
python -m pytest tests/test_extracta_samples.py -q
python -m scripts.evaluate_extracta 'samples/atacadao/Teste 1 - Loja 1.pdf' 'samples/atacadao/Teste 1 - Loja 2.pdf' 'samples/atacadao/Teste 1 - Loja 3.pdf'
```

Os resultados completos ficam apenas no computador. O Git recebe o código, a documentação e as fixtures de teste, conforme a autorização para usar estas amostras sem dados sensíveis.

## Segunda entrega: persistência e conferência

O contrato Extracta passou a ser persistido no PostgreSQL, em uma tabela própria criada por migration aditiva. Os testes verificaram gravação e leitura do relatório, conservação do estado aprovado e rejeição de gravações com revisão desatualizada. Duas aprovações concorrentes da mesma revisão foram executadas: uma foi salva e a outra recebeu 409.

O teste com os três PDFs foi ampliado. Depois da extração das cinco páginas e vinte e sete mercadorias, o teste confirmou que a exportação estava bloqueada, registrou aprovações simuladas nos dados temporários e gerou um XLSX. A planilha foi reaberta com OpenPyXL. Foram verificadas três linhas de pedidos, vinte e sete linhas de itens, identificadores documentais, página, código, quantidade e preço de cada mercadoria.

Os testes de exportação também confirmaram que códigos com zeros à esquerda são texto, ausências permanecem vazias, quantidades e preços são números e um texto iniciado por fórmula não vira fórmula executável. Totais dos produtos e valores declarados do pedido permanecem em colunas diferentes. O Excel contém auditoria e evidências.

Resultado da suíte completa nesta entrega: quarenta testes do backend aprovados, incluindo OCR real, PostgreSQL e fluxo anterior. No frontend, treze testes aprovados. Ruff, ESLint e build passaram. Foram observados avisos de depreciação de asyncio em uma dependência transitiva do LangGraph no Python 3.14, sem falha dos testes.

As aprovações realizadas por testes não representam conferência comercial dos documentos reais. Não foi validado um template Salesforce. O formato Excel continua provisório. Recuperação NVIDIA e reprocessamento sem duplicação seguem pendentes.

## Terceira entrega: recuperação e novas tentativas

O reprocessamento foi implementado para falhas e interrupções, preservando lote, documento, revisões, resultados anteriores e contadores de chamadas. O teste confirmou que não há criação de um segundo documento e que um resultado já corrigido ou aprovado não é substituído por esse caminho.

A recuperação NVIDIA passou a fornecer sugestões restritas a campos ausentes, com evidência textual verificável e validação local. Sugestões não alteram os valores extraídos. O teste da interface confirmou que uma sugestão entra somente no rascunho após ação explícita.

Foram testados erros 401, 403, 400 e 429, timeout, orçamento esgotado, reserva anterior ao envio, resposta sem evidência, cache por conteúdo e configuração, isolamento entre documentos, redirecionamento e tamanho máximo de resposta. As respostas externas foram simuladas. Nenhum documento real foi enviado à NVIDIA. A configuração local foi verificada e permanece com recuperação externa desabilitada.

Resultado da suíte completa: cinquenta e cinco testes do backend aprovados, incluindo PDFs reais e PostgreSQL. Quinze testes do frontend aprovados. Lint e build passaram. A compatibilidade real do modelo NVIDIA configurado continua pendente de avaliação explicitamente habilitada. Os detalhes de configuração e limites estão em [Recuperação e reprocessamento](extracta-recovery.md).
