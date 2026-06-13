---
status: accepted
---

# Gatilho do reengajamento ancorado no evento real da cotação

O `CONTEXT.md` ("Reengajamento") promete reabrir "um cliente que **recebeu a cotação** e silenciou". A implementação afrouxou essa promessa para **proxies** que não leem a conversa: o cron `reengajar_silenciosos` (`api/src/barra/workers/timeouts.py:126-210`) dispara em `estado IN ('Triagem','Qualificado')` + `intencao IN ('cotacao','agendamento')` + última mensagem **do cliente** entre `reengajamento_delay_min` e 24h. O próprio `docs/agente/07 §4.5` admite que `intencao IN (...)` é "proxy de cotação apresentada".

O proxy erra porque nenhum dos seus sinais é o evento que ele quer aproximar:

- **`intencao='cotacao'` ≠ "a IA cotou".** Esse campo é escrito pela IA via `registrar_extracao` (`api/src/barra/agente/ferramentas/extracao.py:108,133`) e significa "o cliente **quer** saber o preço" — pode ser marcado no mesmo turno em que o cliente pergunta o valor, **antes** de qualquer preço sair. O cron então cutuca quem nunca foi cotado, com um card ("ainda quer marcar?") sem nexo.
- **`Qualificado` ≠ "cotação apresentada".** `_decidir_transicao` (`api/src/barra/dominio/atendimentos/service.py:471-504`) só promove a `Qualificado` com `intencao='agendamento'` **+** `horario_desejado` **+** `tipo_atendimento` — bem **depois** da cotação. A cotação-e-some típica (a perda nº1, ~55% — `docs/agente/11`) acontece em **`Triagem`**: o cliente recebeu o preço e nunca deu um horário. Restringir o gatilho a `Qualificado` mataria justamente o caso-alvo.
- **O relógio conta da última msg do cliente**, que normalmente é *anterior* à cotação (o cliente pergunta → a IA cota → o cliente some). O `reengajamento_delay_min` (30 min) pode então estourar quase junto com o preço, ou antes de ele sair.

A consequência é que o gatilho dispara **antes de cotar**, **não verifica se o preço foi a última coisa** e, por ser canned, o texto fixo erra junto quando o gatilho erra (`docs/agente/11` lista os três como buracos do design).

O flywheel offline (`docs/agente/11`, ponto 5) fechou o que **não** muda: o texto canned `pergunta_leve` curta, sem desconto e sem mídia a frio é o movimento vencedor (validado sobre 1019 cutucadas reais; a política "~30 min" também). A melhoria é **só no gatilho** — torná-lo cirúrgico reduz o volume ao caso canônico e reduz o risco de toque deslocado que parece bot.

## A descoberta que força o desenho

**Não existe hoje marcador de "a IA cotou".** Não há tool de cotar (a IA cota em texto livre — `regras.md.j2:14-31`), não há coluna `cotacao_enviada_em`, e `valor_acordado` é o valor **acordado** (passo 4 do funil, `regras.md.j2:6-17`), não o **cotado** (passo 3) — a IA não é instruída a gravá-lo no turno da cotação. Logo, "cotou" **não é derivável** de nenhum campo existente. O redesign **obriga** a introduzir um sinal dedicado de "cotação apresentada".

## Decisões

- **Nova coluna `atendimentos.cotacao_enviada_em timestamptz`.** Marca o instante em que a IA apresentou o preço pela primeira vez. Imutável após o primeiro carimbo (COALESCE preserva o primeiro), espelhando `reengajado_em`/`aviso_saida_em`.

- **Sinal explícito da IA na tool `registrar_extracao`, não regex.** Novo arg booleano (ex.: `cotacao_apresentada`) que a IA marca `True` no turno em que cota; `registrar_extracao_ia` carimba `cotacao_enviada_em=now()` na primeira vez (não re-carimba). A detecção fica na **fonte do fato** — a IA é quem cota e sabe quando. A descrição do arg restringe ao evento real ("você está apresentando valor + duração ao cliente neste turno"), na mesma natureza factual dos campos que a tool já reporta (`intencao`, `valor_acordado`, `sinais_qualificacao`).

- **Gatilho novo do `reengajar_silenciosos`, ancorado na cotação:**
  - `cotacao_enviada_em IS NOT NULL` (a IA apresentou preço) — **substitui** o filtro `intencao IN ('cotacao','agendamento')`.
  - **Nenhuma mensagem do cliente com `created_at > cotacao_enviada_em`** (silêncio genuíno desde a cotação).
  - `now() - cotacao_enviada_em` entre `reengajamento_delay_min` e 24h — o relógio passa a contar **da cotação**, não da última msg do cliente.
  - Inalterados: `estado IN ('Triagem','Qualificado')` (funil aberto pré-confirmação), `ia_pausada=false`, `reengajado_em IS NULL`, hora local BRT em `[operacao_hora_inicio, operacao_hora_fim)`, CTE atômica `FOR UPDATE SKIP LOCKED` + `UPDATE reengajado_em=now()` (1 toque), e `escolher_reengajamento()` (texto canned mantido).

- **O texto canned não muda.** `_canned.py:REENGAJAMENTO_CANNED` e o bloco `<reengajamento>` em `regras.md.j2` ficam como estão — validados pelo flywheel. Buraco #3 se resolve por consequência: com gatilho preciso, o card fixo passa a casar com o contexto.

## Considered Options

- **Regex de preço (`R$`/valor) na última mensagem `direcao='ia'`.** Rejeitado. Zero impacto no cache e sem mexer na tool, mas frágil nas duas pontas: **falso-positivo** quando a última fala da IA é o "Pix de R$100" do deslocamento (externo, `regras.md.j2:48-55`) e **falso-negativo** quando a IA cota sem cifrão ("500 reais", "quinhentos"). E o modo de falha é o **inseguro** — cutucar quem não devia parece bot. O sinal explícito falha para o lado **seguro**: se a IA esquece o flag, apenas deixamos de cutucar alguém que poderíamos.

- **Derivar `cotacao_enviada_em` de `valor_acordado` (primeira vez que é setado).** Rejeitado: `valor_acordado` é o valor **acordado** no fechamento, não o cotado; cai tarde no funil e perderia a cotação-e-some em `Triagem`, que é o alvo.

- **Restringir o gatilho a `Qualificado` (remover `Triagem`).** Rejeitado: `Qualificado` exige agendamento + horário + tipo — é depois da cotação. Mataria a perda nº1.

- **Excluir despedida/objeção explícita pós-preço ("vou pensar e te chamo").** Desnecessário com este desenho: qualquer resposta do cliente após a cotação é uma mensagem com `created_at > cotacao_enviada_em`, então o filtro "nenhuma msg do cliente desde a cotação" já as exclui (inclusive "já marquei"). O residual é só "cotou, cliente não disse **nada**" — exatamente o caso-alvo.

## Consequences

- **Migration antes do deploy.** A coluna `cotacao_enviada_em` precisa estar aplicada **antes** do redeploy do worker (o cron a referencia). Migration de **schema** apenas (sem seed); aplicar manualmente via psycopg em prod (`make migrate` é proibido em prod — aplicaria seeds).

- **Invalidação única do cache de prompt.** Adicionar o arg `cotacao_apresentada` muda o schema das tools (BP_TOOLS), o que invalida o prefixo de cache de **todas** as modelos por um warmup (`api/src/barra/agente/CLAUDE.md`, "Invariante de prefixo global"). É um write-rate alto **pontual**, esperado e auto-cicatrizante — não um invalidador silencioso em regime.

- **Cobertura do gatilho depende da IA marcar o flag.** Se a IA cota mas esquece `cotacao_apresentada`, o atendimento não é reengajado (falha segura). Mitigação no prompt: instrução clara no turno de cotação; observável via métrica (atendimentos com `intencao='cotacao'` e `valor_acordado` mas sem `cotacao_enviada_em`).

- **Reduz o volume de reengajamento** ao caso canônico (cotou → silêncio total). Esperado e desejado: menos toques, menos risco de card deslocado. Acompanhar `REENGAJAMENTO.labels("enviado")` antes/depois ao **ligar** o reengajamento (`reengajamento_ativo`, hoje OFF — decisão de produto do Fernando, independente deste ADR).

- **O relógio de 24h (`timeout_longo`) não muda** — segue contando da última msg do cliente e encerrando como `Perdido(sumiu)`. Como a última msg do cliente é ≤ `cotacao_enviada_em`, um atendimento que ultrapassa 24h-da-cotação já saiu de `Triagem/Qualificado` (virou Perdido), então o limite superior de 24h-da-cotação é consistente com a guarda de estado.

- **`docs/agente/07 §4.5` e o `CONTEXT.md` ("Reengajamento") devem ser atualizados** para descrever o gatilho ancorado na cotação em vez do proxy de `intencao`.
