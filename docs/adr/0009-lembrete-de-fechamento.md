# Lembrete de fechamento: cobrança determinística do valor final, não IA Admin

A demanda original ("após o atendimento, o sistema pergunta o valor final à modelo, ela responde e o sistema atualiza; reenvia se ela silenciar") pedia, no texto, um fluxo novo com **IA administrativa** interpretando resposta livre e mensagem direta ao WhatsApp da modelo.

Decidimos implementar isso como um **lembrete determinístico** (ver CONTEXT.md, "Lembrete de fechamento"), porque a maior parte já existe e o resto não precisa de IA:

- A modelo já fecha com `finalizado/fechado [valor]` no grupo de **Coordenação por modelo**, parseado por **regex** (`webhook/parser.py`) e aplicado por `escaladas.service.aplicar_comando` → `registrar_fechado`. O **canal correto é o grupo** (a modelo não tem identidade/DM separada), e a interpretação é determinística — NLP de resposta livre é da **IA Admin**, que é **P1**.
- O novo é só a **cobrança proativa**: um cron varre atendimentos em `Em_execucao` cujo `bloqueios.fim` já passou (+ tolerância), envia um card pedindo o valor, reenvia em intervalos fixos até um máximo de toques e, sem resposta, abre **Handoff** para Fernando. Tracking (toques/último envio) e a resolução do quote derivam de `envios_evolution`.

**Limites deliberados (para um futuro leitor não "consertar" reconstruindo a IA):**
- Sem novo estado, coluna, enum ou migration; sem LLM; sem quiet-hours; sem confirmação dupla.
- A resposta da modelo é **efetiva imediatamente** (Fernando corrige no painel via `corrigir_registro`), coerente com a decisão já registrada no domínio.
- **Não há auto-close**: silêncio total nunca marca `Perdido` (um atendimento que aconteceu não pode virar Perdido por timeout). Fica em `Em_execucao` até fechamento manual — `Em_execucao` é, por design, excluído do timeout de 24h.

**Consequências:**
- Só atendimentos com `bloqueio` (fim previsto) são cobrados; um atendimento arrastado manualmente para `Em_execucao` sem bloqueio depende de fechamento manual.
- Atrás de flag (`lembrete_valor_ativo`, default ligado): a feature é reversível. O ADR registra a escolha de rumo (determinístico vs IA Admin), não um lock-in técnico.
