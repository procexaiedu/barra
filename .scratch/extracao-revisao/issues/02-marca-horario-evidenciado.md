# 02 — Marca de horário evidenciado

**Spec:** `.scratch/extracao-proveniencia-horario/spec.md`

**O que construir:** o Atendimento passa a distinguir um horário que o cliente sustentou de um
palpite gerado pelo sistema. Hoje os dois são indistinguíveis: no #25 a IA perguntou "Seria agora?",
o cliente ignorou e mudou de assunto, e mesmo assim o sistema gravou 02:00 e passou a exibir esse
horário para a IA como "pedido dele".

Depois deste ticket, a IA lê "palpite seu, ele não confirmou" quando não há fala que sustente o
horário — e continua lendo o horário como pedido do cliente quando há.

**Bloqueado por:** nada — pode começar imediatamente.

**Status:** resolved

- [x] Nova coluna booleana no Atendimento, `NOT NULL DEFAULT false`, em migration de schema (sem seed)
- [x] Detector determinístico no módulo de disciplina do agente, com três gatilhos: hora explícita na fala do cliente; confirmação curta logo após bolha da IA que contém hora; aceite da sondagem de imediatismo (já computado no turno)
- [x] Regra de transição da marca: sobe para `true` sempre que houver evidência, mesmo com o valor inalterado; cai para `false` apenas quando o valor muda sem evidência nova
- [x] O fallback de tempo imediato continua gravando o horário e **não** carimba evidência
- [x] A rota de edição de dados do Atendimento (painel) carimba evidência como verdadeira
- [x] O bloco de horário do contexto dinâmico ganha o terceiro status ("palpite seu, ele não confirmou") quando não há evidência
- [x] Sem backfill: a marca nasce falsa e o detector a corrige no primeiro turno seguinte
- [x] Regressão pelo harness fiel, com grafo real e chat fake, sobre os casos reais: #34 ("Tipo 18h, 18h15" + "Perfeito") e #24 ("Umas 16 horas") evidenciam; #35 (sondagem "seria agora?" aceita) evidencia apesar do número sintético; #25 **não** evidencia, com o horário mesmo assim gravado
- [x] Regressão da promoção tardia: partindo do estado do #25, o cliente dizendo "pode ser 2h então" faz a marca subir sem o valor mudar
- [x] Teste do detector puro cobrindo os negativos que enganam: "Não conheço" (respondendo a "Campinas?") não é hora
- [x] Gate verde: lint, typecheck e testes, incluindo os que tocam banco contra o Postgres real

## Answer

Implementado em 2026-07-25 (branch `main`, local).

- Coluna `barravips.atendimentos.horario_evidenciado` (`boolean NOT NULL DEFAULT false`) —
  migration de schema `infra/sql/20260725191159_atendimentos_horario_evidenciado.sql`, sem seed e
  sem backfill. **Ainda NÃO aplicada em prod** (aplicar antes de subir o worker com este código).
- Detector determinístico: `contem_hora_explicita` / `contem_sondagem_imediatismo`
  (`agente/_disciplina.py`) + `_horario_evidenciado_no_turno` (`agente/nos/prepare_context.py`),
  com os três gatilhos. O gatilho da sondagem usa o recorte de IMEDIATISMO ("seria agora ?"), não
  o `sondagem_aceita` do State — esse também acende no "seria hoje ?", que crava o dia e não a hora.
- Transição da marca em `_marca_horario_evidenciado` (`dominio/atendimentos/service.py`): sobe com
  evidência mesmo sem o valor mudar; cai só quando o valor muda (ou é limpo) sem evidência nova. A
  comparação é com o valor JÁ PERSISTIDO (`IS DISTINCT FROM`), então o eco do belief não se auto-valida.
- Fallback de tempo imediato inalterado (grava o horário, não carimba evidência). Painel
  (`PATCH /atendimentos/{id}/dados`) carimba `true` quando o campo editado é o horário.
- `<hora>` do contexto dinâmico ganhou o terceiro status ("palpite seu, ele não confirmou —
  confirme o horário com ele antes de tratar como combinado"). O texto manda CONFIRMAR (não
  descartar) porque, sem backfill, todo atendimento aberto antes da migration entra como
  não-evidenciado até a próxima fala com hora.
- Testes: detector puro (`tests/unit/test_horario_evidenciado_detector.py`), regressão pelo harness
  fiel com grafo real e chat fake (`tests/integracao/test_horario_evidenciado.py`: #34, #24, #35,
  #25, promoção tardia, eco, queda por valor novo, carimbo do painel) e render do belief
  (`tests/test_belief_state.py`).
- Gate: ruff + mypy verdes; `pytest -m "not needs_key"` com `TEST_DATABASE_URL` contra Postgres 15
  local = 1832 passaram. As 4 falhas restantes são ambientais e pré-existentes (2 por `corpus.threads`
  ausente em DB provisionado; 2 por o `.env` mandar `DEEPSEEK_MODEL_CHAT=deepseek-chat`, que a API
  rejeita hoje — o judge do output-guard cai nelas).
