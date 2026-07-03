---
status: descartado
---

# Externo com pickup: cliente busca a modelo, sem Pix de deslocamento

> **DESCARTADO (2026-07-03, Fernando/dev).** O subcaso pickup foi removido por completo do produto:
> campo `cliente_busca` fora da extração e do upsert, branch do cron `confirmar_em_execucao`
> removido, card 🤝 removido, cenário de eval removido. Conduta vigente quando o cliente quer
> buscar a modelo de carro: a IA **redireciona** para os tipos suportados (interno, ou externo com
> Pix dela indo de Uber) e, se ele insistir, **escala** (`politica_nova_necessaria`). Ver o verbete
> "Atendimento interno, externo ou remoto" no CONTEXT.md. No banco de prod, a coluna
> `atendimentos.cliente_busca` sai por migration própria de drop; o valor `cliente_busca` do
> `tipo_escalada_enum` permanece (Postgres não remove valor de enum), inerte.
> O texto abaixo é registro histórico da decisão original.

No E2E de 10/06 o cliente fechou um pernoite dizendo que **buscaria a modelo de carro** ("te busco aí em 1h, manda seu endereço"). O domínio só conhecia dois roteiros: **interno** (cliente vai até a modelo; confirma por Foto de portaria) e **externo** (a modelo vai de Uber até o cliente; confirma por Pix de deslocamento). O pickup é **externo** — o atendimento acontece no local do cliente, conta para o Mapa de clientes — mas **não tem deslocamento da modelo**: não existe Uber para o Pix antecipar. A IA aplicou os dois scripts errados (segurou o endereço com fala de portaria de interno e pediu Pix de R$100), e mesmo com a conduta corrigida no prompt sobrou um buraco mecânico: **só `pedir_pix_deslocamento` promove externo** para `Aguardando_confirmacao` (criando o bloqueio prévio). Um pickup bem conduzido ficava parado em `Qualificado` para sempre — sem reserva de agenda, sem pausa da IA na hora do encontro, sem card à modelo.

Regra de negócio (Fernando, 10/06): **Pix de deslocamento existe apenas quando a modelo se desloca por conta própria (Uber). Cliente buscando a modelo = sem Pix.**

## Decisões

- **`atendimentos.cliente_busca boolean NOT NULL DEFAULT false`.** Sinaliza o subcaso dentro de `tipo_atendimento='externo'` — não é um terceiro tipo (o eixo interno/externo segue definindo *onde* o atendimento acontece; `cliente_busca` define *quem dirige*). Registrado pela IA via `registrar_extracao` (campo novo, opcional), como os demais campos do snapshot.
- **Promoção `Qualificado → Aguardando_confirmacao` pela extração, espelhando o interno.** `_decidir_transicao` promove quando `externo + cliente_busca + horario_desejado` (mesma regra do interno), criando o **bloqueio prévio** no mesmo ponto. `pix_status` permanece `nao_solicitado`. Sem `enviar_pin` (o card `loc_pin` segue TODO M3d); o ponto de encontro vai por texto, conduzido pelo prompt (`<externo_cliente_busca>`).
- **`Aguardando_confirmacao → Em_execucao` pelo relógio, no cron `confirmar_em_execucao`.** Novo alvo no mesmo job (a cada minuto): `externo + cliente_busca + Aguardando_confirmacao + bloqueio.inicio <= now()` → `Em_execucao`, `ia_pausada=true` (`modelo_em_atendimento`), `responsavel_atual='modelo'`, bloqueio → `em_atendimento`, e **escalada `tipo='cliente_busca'`** que hospeda o card ("Cliente vem te buscar") entregue pelo `reconciliar_cards` no grupo de Coordenação. `fonte_decisao_ultima_transicao='cron_em_execucao'` (valor existente do enum). Pickup **pula `Confirmado`** — igual ao interno (Foto de portaria); `Confirmado` segue significando "Pix recebido".
- **Invariante 01 §6.1 emendada.** De "externo em `Aguardando_confirmacao` ⟹ Pix solicitado" para "externo **sem `cliente_busca`** em `Aguardando_confirmacao` ⟹ Pix solicitado". O roteador de imagem não muda: comprovante só entra no branch Pix com `pix_status='aguardando'` (pickup fica `nao_solicitado`), e Foto de portaria segue interno-only — imagem em pickup não tem efeito de estado.
- **Guarda determinística na tool de Pix.** `pedir_pix_deslocamento` com `cliente_busca=true` aborta com erro recuperável (espelho da guarda `_TipoNaoExterno`): defesa em profundidade sobre a instrução do prompt.
- **Sem timeout novo.** O timeout geral de 24h (última mensagem do cliente) cobre o sumiço antes do horário; o **Lembrete de fechamento** cobre o pós-`bloqueios.fim` (o bloqueio existe, então o gatilho funciona). Cliente que não aparece no horário: o atendimento vai a `Em_execucao` pelo relógio e a **modelo decide pelo card** (`finalizado [valor]` / `perdido [motivo]`) — mesma limitação que o externo-Uber já tem em `Confirmado → Em_execucao`.
- **Migration antes do deploy.** `cliente_busca` + `ALTER TYPE tipo_escalada_enum ADD VALUE 'cliente_busca'` precisam estar aplicadas no banco **antes** do redeploy do worker (o cron e a extração referenciam ambos).

## Considered Options

- **Reusar `pedir_pix_deslocamento` com valor zero.** Rejeitado: enviaria a bolha/chave de Pix ao cliente, registraria `pix_status='aguardando'` (desviando o branch de imagem para validação de comprovante) e poluiria a semântica financeira.
- **Promover por uma tool nova (`confirmar_saida_externa`).** Rejeitado no P0: mais superfície de tools e mais um string crítico para o LLM acertar; a extração já carrega `horario/tipo` e o padrão interno prova que promoção-por-extração funciona.
- **Tratar pickup como `interno`.** Rejeitado: o atendimento acontece no local do cliente (conta para o Mapa, externo por definição), e o roteiro de Foto de portaria não se aplica.
- **Pausar a IA já na promoção (em vez de no horário).** Rejeitado: entre o aceite e a busca o cliente ainda conversa ("tô saindo", "qual portaria?") e a IA deve responder; a pausa pertence ao momento do encontro, como no interno (foto) e no externo-Uber (Pix recebido → modelo conduz).

## Consequences

- O painel mostra pickup como externo comum (`tipo_atendimento='externo'`); exibir o subcaso ("cliente busca") no Resumo do atendimento fica para iteração da UI.
- `cliente_busca` marcado depois de `pedir_pix_deslocamento` já ter rodado (ordem inversa, rara) **não** reclassifica: o primeiro gatilho vence e o fluxo Uber segue.
- Fixture canônica `agenda.007` passa a esperar a promoção (`Aguardando_confirmacao` + `pix_status='nao_solicitado'`).
