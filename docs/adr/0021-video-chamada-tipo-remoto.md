---
status: accepted
---

# Vídeo chamada: terceiro `tipo_atendimento` `remoto`, entrega espelhando o pickup

> **Nota (2026-07-03):** o pickup (ADR 0020) foi **descartado** — as menções a ele abaixo são
> contexto histórico da decisão; a mecânica do remoto descrita aqui permanece vigente por si só.

> **Nota (2026-07-04):** a regra financeira ("sem fluxo no sistema no P0; a modelo combina o
> pagamento manualmente") foi **emendada pelo ADR 0029** — o valor da vídeo chamada passa a ser
> antecipado via Pix no trilho do deslocamento. A mecânica de **entrega** decidida aqui
> (promoção pela extração, cron na hora, card go-time, pular `Confirmado`) permanece vigente.

A v1 dos prompts (12/06) já **vende** vídeo chamada como um programa normal da tabela da modelo (`<video_chamada>` em `regras.md.j2`), mas a **entrega** — a modelo fazendo a chamada ao vivo na hora marcada — não tinha caminho mecânico. O domínio só conhecia dois roteiros de entrega, ambos presenciais: **interno** (cliente vai até a modelo; confirma por Foto de portaria) e **externo** (a modelo se desloca ou o cliente a busca; o externo-Uber antecipa o Pix de deslocamento). Vídeo chamada **não é nenhum dos dois**: ninguém se desloca, não há local físico, não entra no Mapa de clientes, não tem Foto de portaria nem Pix. Uma vídeo chamada bem vendida ficava parada em `Qualificado` para sempre — sem reserva de agenda, sem pausa da IA na hora, sem card à modelo (o mesmo buraco que o pickup tinha antes do ADR 0020).

O ADR 0020 é o precedente direto: lá, um atendimento sem Pix é promovido pela extração (`Aguardando_confirmacao` + bloqueio prévio) e um cron pausa a IA no horário do encontro com um card na Coordenação por modelo. Vídeo chamada é o mesmo esqueleto **menos a presença física**. O ADR 0020 rejeitou criar um terceiro `tipo_atendimento` para o pickup com a justificativa de que "pickup ainda é externo (acontece na casa do cliente, conta para o Mapa)" — vídeo chamada é genuinamente *nenhum dos dois*, então o mesmo raciocínio agora aponta **a favor** de um terceiro valor.

Regra de negócio (a confirmar com Fernando, ver Consequences): **a entrega da vídeo chamada não tem fluxo financeiro no sistema no P0 — a modelo combina e recebe o pagamento do jeito dela. Sem Pix, sem antecipação.**

## Decisões

- **`tipo_atendimento_enum ADD VALUE 'remoto'`.** Terceiro valor do eixo de entrega. O **programa** diz *o quê* (Vídeo chamada, item de `modelo_programas` com preço/duração); o **tipo** diz *como/onde* (em lugar nenhum — sem deslocamento). O nome é `remoto` (a natureza da entrega), não `video_chamada` (o nome comercial), espelhando como `interno`/`externo` descrevem o deslocamento e não o programa: um futuro serviço sem deslocamento (sexting, áudio) é o mesmo roteiro, sem novo valor.

- **Gate uniforme em `tipo_atendimento_aceito[]`.** A modelo habilita vídeo chamada tendo `remoto` em `tipo_atendimento_aceito[]` **e** o programa Vídeo chamada em `modelo_programas` (preço/duração) — a IA checa `aceito[]` para nunca negociar um tipo que a modelo não faz, exatamente como já faz para interno/externo. O vínculo "programa Vídeo chamada ⟹ `remoto`" fica por **convenção** (prompt + extração), sem constraint de banco no P0.

- **Promoção `Qualificado → Aguardando_confirmacao` pela extração, espelhando o interno.** `_decidir_transicao` promove quando `remoto + horario_desejado` (mesma regra do interno: só o horário, sem Pix), criando o **bloqueio prévio** no mesmo ponto. `pix_status` permanece `nao_solicitado`. **Sem `enviar_pin`** (não há endereço algum). A IA sinaliza `tipo_atendimento='remoto'` no `registrar_extracao`, como qualquer campo do snapshot.

- **`Aguardando_confirmacao → Em_execucao` pelo relógio, no cron `confirmar_em_execucao`.** Novo alvo no mesmo job (espelho literal do branch de pickup): `remoto + Aguardando_confirmacao + ia_pausada=false + bloqueio.inicio <= now()` → `Em_execucao`, `ia_pausada=true` (`modelo_em_atendimento`), `responsavel_atual='modelo'`, bloqueio → `em_atendimento`, e **escalada `tipo='video_chamada'`** que hospeda o card "Hora da sua vídeo chamada com o cliente", entregue pelo `reconciliar_cards` no grupo de Coordenação. `fonte_decisao_ultima_transicao='cron_em_execucao'`. Remoto **pula `Confirmado`** — igual ao interno (Foto de portaria) e ao pickup; `Confirmado` segue significando "Pix recebido".

- **`tipo_escalada_enum ADD VALUE 'video_chamada'`.** Card de entrega próprio (texto e semântica distintos do `cliente_busca` do pickup), para que painel e métricas separem o momento de entrega remoto do presencial.

- **Guarda determinística na tool de Pix.** `pedir_pix_deslocamento` com `tipo_atendimento='remoto'` aborta com erro recuperável (espelho da guarda `_TipoNaoExterno` e da guarda de `cliente_busca` do ADR 0020): defesa em profundidade sobre a instrução do prompt.

- **Sem novos timeouts.** O timeout geral de 24h (última mensagem do cliente) cobre o sumiço antes do horário; o **Lembrete de fechamento** cobre o pós-`bloqueios.fim` (o bloqueio existe, o gatilho funciona). Fechamento normal pelo **Registro de resultado** — Valor final, repasse, comissão de vendedor e taxa de cartão incidem como em qualquer `Fechado`, sem código especial.

## Considered Options

- **Ramificar a entrega pelo programa ("o programa é Vídeo chamada"), sem mexer no enum.** Rejeitado: o eixo `tipo_atendimento` já é "qual roteiro de entrega", e cron, roteador de imagem, guarda de Pix e Mapa **todos** chaveiam nele. Branch por programa espalharia `if programa == vídeo chamada` por todos esses pontos; um valor de enum concentra a decisão.

- **Nomear o valor `video_chamada` em vez de `remoto`.** Rejeitado: vincularia o eixo de entrega ao nome comercial. Renomear um valor de enum em produção é caro (migration + dados); `remoto` como categoria não custa mais agora e absorve futuros serviços sem deslocamento.

- **Reusar a escalada `cliente_busca` para o card.** Rejeitado: o nome e o texto ("Cliente vem te buscar") são do pickup presencial — reusar misturaria os dois momentos em auditoria e métricas.

- **Validar o vínculo programa↔tipo no banco (constraint).** Rejeitado no P0: muita superfície de schema para um invariante que o prompt e a extração já garantem na prática.

- **Pausar a IA já na promoção (em vez de no horário).** Rejeitado, como no ADR 0020: entre o aceite e a hora da chamada o cliente ainda conversa, e a IA deve responder; a pausa pertence ao momento da entrega.

- **Antecipar pagamento (sinal/Pix) da vídeo chamada.** Adiado para o P1: exige decisões financeiras do Fernando e um fluxo de pago avulso que não existe hoje (`pedir_pix_deslocamento` é R$100 fixo, hard-wired para deslocamento). No P0 a modelo combina o pagamento manualmente.

## Consequences

- **Decisões de produto pendentes (Fernando), registradas como pressupostos do P0:** (a) **pagamento** na hora pela modelo, sem fluxo no sistema; (b) **repasse e comissão de vendedor** sobre vídeo chamada uniformes a qualquer `Fechado`, salvo orientação diferente; (c) **Disponibilidade** — a modelo precisa cobrir o horário das chamadas na própria Disponibilidade (gate uniforme), a confirmar se vídeo chamada merece janela própria. Se algum divergir, este ADR é emendado antes de codar a parte afetada.

- **Limitação herdada do timeout de 24h:** remoto em `Aguardando_confirmacao` está sujeito ao timeout geral como interno/pickup. Uma vídeo chamada agendada com mais de 24h de antecedência em que o cliente silencia vira `Perdido(sumiu)` antes da hora, apesar do bloqueio reservado. Aceito no P0 (piloto tende a chamadas de curto prazo); revisitar se aparecer agendamento longo recorrente.

- **Sem mudança nestes pontos, confirmada pela leitura do código:** o roteador de imagem (`workers/media.py`) ignora imagem em remoto (o branch de Pix exige `pix_status='aguardando'`, o de Foto de portaria exige `interno` — remoto cai no default/turno normal); o **Mapa de clientes** filtra `externo`, então remoto fica fora naturalmente; **Aviso de saída** e **timeout interno** são interno-only.

- **Migration antes do deploy.** `ADD VALUE 'remoto'` (tipo_atendimento) e `ADD VALUE 'video_chamada'` (tipo_escalada) precisam estar aplicadas no banco **antes** do redeploy do worker (a extração, o cron e a guarda referenciam ambos).

- **Bundle remoto + presencial no mesmo atendimento fica fora do escopo.** Cada atendimento fixa exatamente um `tipo_atendimento`; uma vídeo chamada e um presencial são atendimentos distintos (recorrência abre novo). Não se modela um atendimento misto.
