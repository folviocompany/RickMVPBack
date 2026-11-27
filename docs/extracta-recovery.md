# Recuperação e reprocessamento

## Novas tentativas

Use `Reprocessar este documento` quando uma falha ou interrupção ocorrer em um PDF cujo original ainda esteja disponível. O lote e o documento mantêm seus identificadores. O histórico guarda resultado, erro, revisão e contadores anteriores. Documentos corrigidos ou aprovados não são substituídos por esse caminho.

O limite padrão é de três tentativas no total por documento. Solicitações simultâneas ou com revisão antiga são rejeitadas. Arquivos inválidos que não foram armazenados precisam ser enviados novamente. Orçamentos de chamadas já consumidos não são zerados por uma nova tentativa.

## Habilitação da recuperação externa

O padrão `EXTRACTA_ALLOW_EXTERNAL_AI=false` mantém o novo agente local. Para permitir o envio mínimo de trechos de OCR, configure explicitamente essa variável como `true`, mantenha `NVIDIA_API_KEY` no `.env` e informe o modelo em `NVIDIA_MODEL`. Essa habilitação autoriza o envio dos trechos selecionados à API configurada. Confira a política dos documentos antes de habilitar.

O agente envia somente linhas associadas a campos ausentes, com destinos restritos. Não envia imagens, o PDF inteiro, nome do arquivo ou conversa. Perfis desconhecidos sem pedidos locais seguem para revisão. Não há execução de código ou tool calling pela IA.

Cada resposta passa por Pydantic. O campo precisa ter sido solicitado, a citação deve existir literalmente na linha e sustentar o valor. Números seguem as regras locais. Candidatos sem evidência são descartados. Sugestões válidas só preenchem o rascunho quando a pessoa escolhe `Usar sugestão na edição`. Salvar registra a mudança na auditoria e continua exigindo aprovação.

## Limites e falhas

Os padrões são três chamadas por documento e nove por lote, incluindo retries. A reserva é salva antes do envio. Existe no máximo um retry por recuperação, somente para falhas transitórias. Erros 401, 403, 400 e respostas inválidas não geram repetição cega. Em 429, Retry After é respeitado; uma espera acima de cinco segundos encerra a recuperação e mantém o resultado local.

O timeout HTTP é de vinte segundos por operação. Novas tentativas respeitam uma janela de quarenta e cinco segundos. Há limite de sete mil caracteres de instruções e contexto, 1024 tokens de saída e 256 KB de resposta. Esses valores são limites de engenharia, não cotas nem garantia de gratuidade do provedor.

Sugestões ficam em cache dentro do próprio documento. A chave considera hash do PDF, perfil e versão, configuração OCR, modelo, formato e trechos. Documentos diferentes não compartilham o cache. Chamadas e tokens informados pelo provedor são registrados; ausências não são preenchidas com estimativas.

O formato padrão é `EXTRACTA_LLM_RESPONSE_FORMAT=json_object`. O suporte varia conforme modelo e endpoint. Se o modelo não aceitar esse formato, o modo `text` continua exigindo JSON válido e o mesmo schema Python. Não há troca automática de modelo após erro. Consulte a [referência oficial NVIDIA NIM](https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html).

## Validação desta entrega

Foram utilizados mocks para verificar IA desabilitada, respostas sem evidência, 401, 403, 429, timeout, cache, limites e isolamento. O teste de reprocessamento confirmou o mesmo documento, histórico anterior preservado e contadores salvos antes de uma chamada simulada.

Nenhum documento real foi enviado à NVIDIA nesta entrega. A compatibilidade do modelo configurado ainda precisa de uma avaliação real explicitamente habilitada. Os testes locais de OCR forçam a recuperação externa desabilitada, independentemente da configuração de uso da aplicação.
