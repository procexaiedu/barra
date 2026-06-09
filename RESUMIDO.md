# Revisão da camada de prompt e tools do agente — branch `revisao-prompt-agente`

**Resultado:** 9 arquivos editados (6 templates de prompt, 2 docstrings de tool, 1 snapshot
regenerado), todos cirúrgicos — correção de 1 contradição real, 1 drift entre arquivos, erros de
PT-BR no texto instrucional e referências `escalar` sem motivo. **Gate offline verde**: `make lint`
(All checks passed), `make typecheck` (Success: no issues found in 120 source files), `make test`
(**963 passed**, 103 skipped `needs_db`/sem env — esperado, nada toca banco). Verificado por 2
checagens independentes: render real de todos os `.j2` com variáveis de exemplo (prefixo geral
segue byte-estável) e revisão do `domain-isolation-reviewer` (nenhuma violação de invariante; a
única dúvida levantada foi corrigida — ver `regras.md.j2` abaixo).

## O que mudou, por arquivo

### `prompts/persona.md`
- Linha do idioma: corrigidos "extrangeiros"→"estrangeiro" e "portugues"→"português", e o texto
  agora bate com `<bilingue>` das regras (inglês puro → inglês; espanhol → segue em PT). Antes,
  "use o idioma do cliente" contradizia a regra do espanhol.
- "espere ele dirigir" → "Espere ele dirigir." (capitalização no texto instrucional).
- Regra de valores agora admite o formato curto da cotação ("800 1h") — antes `<voz>` exigia
  sempre "R$1.500" enquanto os exemplos de `<cotacao>` usavam número seco (contradição interna).

### `prompts/faq.md`
- Fallback: "escale para Fernando" → `escalar(motivo="politica_nova_necessaria")` — aponta a tool
  e o motivo exatos (mesmo destino: o motivo roteia para Fernando), em vez de instrução vaga.

### `prompts/regras.md.j2`
- `<pix_externo>`: removida a linha solta "Confirmação só vem após Pix validado pelo sistema" —
  contradizia o domínio ("nunca trava por Pix": duvidoso também avança). Fundida no bullet do
  comprovante como "a confirmação vem do sistema quando o comprovante chega".
- `<plano_externo_atipico>`: "qual **sua** orçamento ?" → "qual **seu** orçamento ?" (2×).
- `<quando_usar_escalar>`: frase de abertura reestruturada (parêntese no meio do "quando (...):"
  quebrava a leitura).
- `<tools_disponiveis>`: menção duplicada de `registrar_extracao` consolidada num lugar só; a
  ordem dos parágrafos agora é leitura → escrita → conduta pós-tool. Após apontamento do revisor,
  a obrigação "em TODO turno, uma única vez" foi mantida explícita (a 1ª versão da fusão a tinha
  enfraquecido para "uma vez por turno").

### `prompts/reminder.md.j2`
- Drift corrigido: o reminder ainda mandava usar `"amor"/"querido"` como marca registrada, mas o
  persona.md atual tem regra de dosagem contra "amor" em toda bolha. Agora diz "carinho na dose
  certa (sem 'amor' no fim de toda bolha)". Variável `{{ fase }}` intacta.

### `prompts/identidade.md.j2`
- "use a tool `escalar`" → `escalar(motivo="fora_de_oferta")` (tipo de atendimento não aceito =
  serviço fora do que oferece; roteia para a modelo, coerente com o mapeamento do domínio).

### `prompts/programas.md.j2`
- Ramo sem programas: "A modelo ainda não tem..." (3ª pessoa, quebrava o enquadramento "você É a
  modelo") → "Você ainda não tem programas cadastrados"; "escale para Fernando" →
  `escalar(motivo="politica_nova_necessaria")` (mesmo destino, instrução acionável).

### `ferramentas/pix.py` (só docstring — superfície de prompt)
- **Contradição real corrigida:** o exemplo da docstring dizia "pra **garantir teu horário**,
  manda o pixzinho" — exatamente o enquadramento que `<pix_externo>` proíbe como factualmente
  errado (o Pix adianta o custo do deslocamento; o horário já fica combinado antes). Trocado pelo
  exemplo aprovado das regras ("pra eu já chamar o uber e ir te encontrar...") + nota explícita do
  enquadramento correto. Era a tool dizendo uma coisa e as regras outra — o pior tipo de conflito.
- "(string crítico)" removido do texto visível ao LLM (jargão de engenharia; a instrução "você
  NÃO redigita a chave" já carrega a regra).

### `ferramentas/midia.py` (só docstring)
- Removidas referências a documentos internos ("05 §5") que vazavam no prompt visível ao LLM;
  removida a repetição de "mande fotos primeiro" (já está no corpo da docstring). A orientação de
  legenda ("exclusivo/gravado agora") e o view-once permanecem.

### `tests/agente/snapshots/tools.json`
- Regenerado via `TOOLS_SNAPSHOT_UPDATE=1` (caminho sancionado pelo próprio teste) — reflete as
  docstrings novas de `pedir_pix_deslocamento` e `enviar_midia`. Nenhum schema/strict/example
  mudou; `cache_control` segue só na última tool.

## O que decidi NÃO mudar (e por quê)

- **Arquitetura de cache** (BP_TOOLS→BP_GERAL→BP_MODELO→BP_JANELA, fusão BP_GERAL, prewarm,
  ordem determinística): já está exatamente conforme a prática da Anthropic (prefix-match, stable
  first / volatile last, cache na última tool, conteúdo volátil no último HumanMessage). Nada a
  corrigir.
- **Schemas/assinaturas das tools, `STRICT_TOOLS`, `INPUT_EXAMPLES`**: invariante do pedido;
  além disso a exclusão de `input_examples` em `registrar_extracao` é decisão medida (regressão
  comprovada em 2026-05-29).
- **Tamanho do `regras.md.j2`**: além das fusões acima, não enxuguei mais. As seções têm "Por
  quê:" curtos (boa prática — racional ajuda o modelo a generalizar) e exemplos vindos do corpus
  real; cortar seria reescrever o domínio, não melhorar o prompt.
- **Typos/estilo nos exemplos de fala** (`"meu cache"`, "horario" sem acento, "que te de certo"):
  voz do corpus real, deliberada — corrigir "melhoraria" o português e pioraria a persona. Só
  corrigi erros no texto *instrucional* (a voz que fala COM o modelo, não a voz DELA).
- **Enum `MotivoEscalada` exposto com motivos internos** (`exaustao_iteracoes`, `timeout_grafo`,
  legados): mudar o schema é vetado; a conduta já lista ao LLM só os motivos que ele deve usar.
- **`aup_saida.md`, `contexto_dinamico.md.j2`, `fetiches.md.j2`, `escalada.py`,
  `extracao.py`, `leitura.py`**: revisados, sem problema encontrado — bem escritos e já
  prescritivos sobre quando usar/não usar.
- **WIP não-commitado de cache TTL** (`agente/llm.py`, `nos/prepare_context.py`,
  `tests/agente/test_prepare_context.py`): trabalho em andamento de outra frente; deixado intacto
  no working tree, fora do meu commit.

## Pontos que pedem decisão do Fernando

1. **Motivo do `escalar` quando a modelo não tem programas** (`programas.md.j2`): usei
   `politica_nova_necessaria` (roteia para Fernando, igual ao comportamento anterior). Se preferir
   outro motivo (ex.: `outro`), é troca de uma linha.
2. **Custo de cache no deploy**: mudar persona/regras/FAQ/docstrings invalida o cache do prefixo
   global (tools + BP_GERAL) uma vez — write a frio no primeiro turno pós-deploy (o prewarm de
   startup cobre). Normal de qualquer deploy de prompt; só lembrando que o redeploy precisa ser
   `service update --force` no barra-worker.
3. **Evals ao vivo**: as mudanças são de redação/consistência, sem intenção de mudar conduta, mas
   o juiz definitivo são as 24 canônicas (★API, custa crédito) — rodar quando autorizado.
