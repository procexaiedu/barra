# 03 — Promoção Triagem → Qualificado por evidência

**Spec:** `.scratch/extracao-promocao-intencao/spec.md`

**O que construir:** cliente que já combinou horário deixa de ficar preso em `Triagem`. Hoje a
transição exige que o extrator julgue a intenção como agendamento, e ele erra sistematicamente para
baixo: em produção, 9 Atendimentos têm aceite de valor com intenção abaixo de agendamento, contra
apenas 4 com agendamento gravado. O #34 é o retrato — tipo interno, horário 18:00, aceite real, e
ficou em Triagem.

Como o ponto de encontro só entra no contexto a partir de `Qualificado`, o efeito prático é que a IA
passa a ter o endereço cadastrado para responder "onde é?" — em vez de alucinar bairro, como no #27.

**Bloqueado por:** 02 (a promoção usa a marca de evidência; sem ela, um horário fantasma passa a
promover e o freio acidental que existe hoje desaparece).

**Status:** resolved

- [x] A intenção passa a ser derivada no serviço de atendimentos: horário desejado presente **e** evidenciado ⇒ intenção sobe para agendamento
- [x] A derivação absorve o piso de intenção pontual que hoje vive no nó de extração — a sondagem aceita passa a ser apenas mais uma fonte de evidência de horário, não regra própria
- [x] As pré-condições da máquina de estados permanecem inalteradas (fonte única entre FSM e belief-state preservada)
- [x] A monotonicidade da intenção é preservada; a retratação explícita segue sendo o canal de desqualificação
- [x] Regressão pelo harness fiel: #34, #24 e #35 promovem; #25 (horário sem evidência) e #19 (sem horário, com recuo) permanecem em Triagem
- [x] Regressão da cascata externa: Atendimento externo com cotação enviada, horário evidenciado e tipo chega a `Aguardando_confirmacao` e enfileira a solicitação de Pix de deslocamento **uma única vez**
- [x] Regressão do guard de cotação: mesma cascata sem preço dito continua barrada, sem reserva
- [x] Teste afirmando que FSM e belief-state continuam derivando da mesma tabela de pré-condições
- [x] Gate verde: lint, typecheck e testes, incluindo os que tocam banco contra o Postgres real

## Answer

Implementado em 2026-07-25 (branch `main`, local). Sem migration nova — usa a coluna do issue 02.

- `_promover_intencao_por_evidencia` (`dominio/atendimentos/service.py`): um `UPDATE ... SET
  intencao = 'agendamento' WHERE horario_desejado IS NOT NULL AND horario_evidenciado`, rodado
  **depois** do UPSERT e **antes** da FSM ler a linha. Ficar depois do UPSERT é o que deixa o
  predicado ler o horário e a marca **como ficaram** (inclusive o horário que o fallback de tempo
  imediato acabou de gravar) sem reimplementar em Python a transição que `_marca_horario_evidenciado`
  já expressa em SQL. E, por ler a **marca** (não só a evidência do turno), também promove o
  atendimento que o operador carimbou pelo painel ou que já nascera evidenciado antes — o predicado
  é reavaliado a cada turno.
- Monotonicidade preservada de graça (`agendamento` é o topo; o `CASE` de `_montar_upsert` segue
  intacto) e `limpar` vence: com retratação explícita no turno (`limpar: ["intencao"]`) a promoção
  não roda.
- Piso pontual removido do nó `extrair` (`_aplicar_piso_intencao`) — e com ele a sobra
  `sondagem_aceita` (State + `_sondagem_aceita_no_turno`), que existia só para alimentá-lo. Efeito
  assumido: "seria **hoje** ?" + "sim" deixa de forçar `agendamento` sozinho (crava o dia, não a
  hora); "seria **agora** ?" + "sim" segue promovendo, agora como evidência de horário (#35).
- Pré-condições da FSM intocadas. Testes: `tests/integracao/test_promocao_intencao.py` (harness
  fiel — #34 com o `<local_de_encontro>` chegando ao contexto do turno seguinte, #24, #35, marca já
  persistida, #25, #19, cascata externa com `pix_solicitado` uma vez, cascata sem cotação barrada) e
  `test_precondicoes_de_triagem_seguem_pedindo_intencao_e_nao_evidencia` (belief × FSM).
- O chat fake roteirizado do harness fiel saiu para `tests/integracao/_chat_fake.py` (era cópia
  literal entre os dois arquivos de regressão).
- Gate: ruff + mypy verdes; `pytest -m "not needs_key"` com `TEST_DATABASE_URL` contra Postgres 16
  local = **1837 passaram**. As mesmas 4 falhas ambientais pré-existentes do issue 02 (2 por
  `corpus.threads` ausente em DB provisionado; 2 por o `.env` mandar `DEEPSEEK_MODEL_CHAT=deepseek-chat`,
  hoje rejeitado pela API) — conferidas contra o `HEAD` sem estas mudanças.
- ⚠️ Prod: a migration do issue 02 (`20260725191159_atendimentos_horario_evidenciado.sql`) continua
  **não aplicada em prod**; sem ela este código quebra no UPDATE. Aplicar antes de subir o worker.
