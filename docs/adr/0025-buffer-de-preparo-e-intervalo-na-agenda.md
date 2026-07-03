---
status: accepted
---

# Buffer de preparo/intervalo como regra dura da agenda

A operação tem duas necessidades reais de folga ao redor de um atendimento que hoje não são garantidas:

1. **Preparo** — a modelo precisa de tempo para se arrumar antes de receber. No rig (18/06/2026) a IA verbalizou isso emergentemente: *"pode dar um tempinho pra eu me arrumar e fechar? 30 min fica pra umas 17h"*. Não há cálculo determinístico: a IA inventa o tempo em linguagem natural (alimentada por `regras.md.j2` `<indisponibilidade>` e pelo tom da persona).
2. **Intervalo entre atendimentos** — a modelo precisa de respiro/deslocamento entre um cliente e o próximo.

Hoje existe `agenda_buffer_proximo_livre_min = 30` (`settings.py`), mas ele é **só sugestão**: entra no pré-cálculo do `proximo_livre` (contexto dinâmico) e nada mais. A reserva em si não o respeita — a constraint `bloqueios_sem_sobreposicao` usa `tstzrange(inicio, fim, '[)')` (half-open), então **bloqueios adjacentes colados são permitidos** (um termina 17h, outro começa 17h), e o `criar_bloqueio_previo` reserva exatamente a duração do programa, sem antecedência mínima a partir de "agora".

## Decisão

- **O buffer vira regra dura da reservabilidade** (não só sugestão), reusando o parâmetro existente (`agenda_buffer_proximo_livre_min = 30`, global; provável renome para `agenda_buffer_min`). Assim o número que a IA **oferece** (`proximo_livre`) passa a ser exatamente o que o sistema **garante**.

- **Invisível na agenda** — não materializa blocos de "preparo"/"descanso". Implementa-se por **checagem-com-buffer** na criação do bloqueio; o painel segue mostrando só o atendimento. (Materializar estendendo o bloqueio quebraria o **Lembrete de fechamento**, que dispara em `bloqueios.fim`, e o `proximo_livre`.)

- **Duas faces, mesmo parâmetro:**
  1. **Antecedência mínima:** todo bloqueio novo tem `inicio ≥ arredonda_acima(now + buffer)`, ajustado à Disponibilidade e a bloqueios existentes (reusa a lógica de `regras_cobrem`/`proximo_livre`).
  2. **Gap entre atendimentos:** reservar `[inicio, fim]` é rejeitado se existe vizinho ativo `[i2, f2]` com `inicio < f2 + buffer AND i2 < fim + buffer` (garante gap ≥ buffer, **não** 2×). Adjacência colada deixa de ser reservável.

- **IA trava, Fernando força:** `criar_bloqueio_previo` (IA) nunca viola o buffer — reoferece outro horário (já trata `ConflitoAgenda`). A criação manual do Fernando (`POST/PATCH /bloqueios`) ganha **override explícito** (salva + alerta não-bloqueante), espelhando o padrão de bloqueio fora da Disponibilidade.

- **IA proativa:** `prepare_context` expõe um campo determinístico `<horario_minimo inicio="...">` (= antecedência mínima já ajustada). A prompt instrui a **ancorar nele** para pedidos imediatos, com flavor leve permitido (*"a partir das X, só me arrumar rapidinho"*) e **sem inventar minutos**. Mudança de prompt passa por simulador + gate antes de qualquer deploy.

## Considered Options

- **Materializar blocos visíveis de preparo/descanso** adjacentes ao atendimento. Comunica melhor no painel, mas exige linhas extras + sincronização (cancelar/concluir junto) e cuidado para não quebrar `bloqueios.fim`. Rejeitado por complexidade (§2): garantir o tempo não exige exibi-lo.

- **Buffer por tipo de atendimento** (interno/externo/remoto) ou **por modelo**. Mais fiel (externo tem deslocamento; ritmos diferentes), mas custa parâmetros/coluna/UI. Adiado: começa global, calibra depois. **(Parcialmente revisto — ver emenda 2026-06-26: a antecedência passou a separar quem-se-desloca; o gap segue global.)**

- **Dois parâmetros distintos** (antecedência ≠ gap). Mais flexível, mais config para manter. Um valor único basta no P0.

- **Manter tudo como sugestão e só calibrar a fala da IA.** Mudança mínima, mas não dá garantia operacional — era exatamente o estado que motivou o ADR.

- **Só reativo (deixar a IA propor e ser rejeitada por `ConflitoAgenda`).** Sem `horario_minimo` no contexto a IA promete um horário e volta atrás com o cliente — UX ruim no momento mais sensível.

## Consequences

- **Muda comportamento de agenda documentado:** bloqueios colados (adjacência `fim == inicio`) deixam de ser reserváveis pela IA; o verbete **Bloqueio** do `CONTEXT.md` deve registrar o gap mínimo. A constraint `bloqueios_sem_sobreposicao` permanece como backstop de sobreposição real; o gap é aplicado na camada de aplicação (sob o advisory lock que já serializa o booking por modelo).

- **Externo:** 30 min global pode ser curto para o deslocamento da modelo até o cliente; aceito por ora (Pix de deslocamento + horário combinado amortecem), calibrável quando houver dados.

- **Prompt + contexto dinâmico mudam** (`prepare_context` ganha `horario_minimo`; `regras.md.j2` ganha a regra de ancoragem). Toca o agente → exige simulador + gate antes de deploy; deploy recarrega o worker. §0.

- **Sem migration** — a regra vive na aplicação e no setting já existente; nenhum schema novo.

- **Testes** de `criar_bloqueio_previo` e da disponibilidade/sobreposição precisam cobrir antecedência mínima e gap (incluindo o caso de adjacência que antes passava).

## Emenda (2026-06-26) — Antecedência por deslocamento

A antecedência mínima global de 30 min adiava o atendimento mesmo com a modelo **ociosa** num **interno** onde o cliente já estava chegando ("pode dar um tempinho pra eu me arrumar? umas 6h30"), enquanto o vendedor humano recebe agora ("posso passar o ap?"). A borda noturna piorava: à noite `now + 30` caía fora da Disponibilidade vigente e o `horario_minimo` saltava para a manhã seguinte. A causa é a fusão das **duas faces** num único parâmetro: o gap entre atendimentos (30 é certo) arrastava junto a antecedência-de-agora (que para quem **não se desloca** deveria ser ~0).

**Decisão da emenda:** desmembrar **só a antecedência-de-agora** por deslocamento da modelo; o **gap entre atendimentos permanece global** (`agenda_buffer_min`, 30).

- Novo setting `agenda_antecedencia_sem_deslocamento_min` (default **0**, global). Aplica-se quando a modelo **não** se desloca: **interno** e **remoto** (vídeo chamada). (A menção original ao externo-pickup saiu com o descarte do ADR 0020.)
- **Externo-Uber** (externo com a modelo se deslocando + Pix de deslocamento) mantém a antecedência = `agenda_buffer_min` (30): o piso amortece o preparo + a saída. A IA negocia ETA por cima; lead por distância real (geocoding) fica para o futuro.
- O **gap entre atendimentos** (`existe_vizinho_no_buffer` / o skip de vizinho no `proximo_livre`) **não muda**: segue `agenda_buffer_min` para todos os tipos. A adjacência colada continua não-reservável.
- O branch por-tipo vive **dentro** de `criar_bloqueio_previo` (lê `tipo_atendimento` do `atendimento`), servindo aos dois call-sites (a promoção do interno/remoto e o bloco de Pix do externo-Uber) sem plumbing novo. A âncora proativa (`horario_minimo` em `prepare_context`) usa a **mesma** antecedência por-tipo, senão âncora ≠ gate.

**Consequências da emenda:** sem migration de DB (campo pydantic em `settings.py`). Toca o agente (`prepare_context`, `regras.md.j2`, `contexto_dinamico.md.j2`) → simulador + gate antes de deploy; deploy recarrega o worker (§0). Para os tipos sem deslocamento, o `horario_minimo` passa a ≈ `agora` (arredondado pra meia-hora), o que de-buga a borda noturna automaticamente (`now + 0` cai dentro da Disponibilidade vigente, sem saltar pra manhã).
