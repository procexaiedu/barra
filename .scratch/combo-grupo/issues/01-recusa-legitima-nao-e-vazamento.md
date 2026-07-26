# 01 — Recusa legítima deixa de ser tratada como vazamento

**O que construir:** a IA precisa poder recusar um terceiro que o cliente quer trazer — *"não faço programa com outra pessoa"*, *"não faço programa pra outra pessoa assim"* — sem que o `output_guard` barre a bolha, abra **Handoff** e pause a IA. A admissão de estado (*"tô ocupada com outra pessoa"*, *"estou com um cliente"*), que é vazamento de verdade, continua barrada.

Hoje o marcador de vazamento casa `"com (outra|mais uma) pessoa"` **solto**, sem distinguir a recusa da admissão. No atendimento **#36** (24/07, cliente `5511948769550`, modelo Tatiane) isso barrou a conduta CORRETA duas vezes e matou o lead: `motivo_escalada = output_leak_outro_cliente`, `ia_pausada = true` desde 01h10, com o cliente tendo perguntado *"qual seu local?"* e *"talvez eu já amanhã"* sem resposta.

O fix já existe no working tree (`agente/nos/output_guard.py`): o padrão passa a exigir o `tô/estou` antes e nenhum `não` no meio. **Falta teste e commit.** Também faz parte deste ticket devolver o #36 à IA (**Devolução para IA**), já que ele está preso por um handoff que não deveria ter existido.

Este é o único ticket que corrige uma perda já materializada — os demais previnem perdas futuras.

**Bloqueado por:** nenhum — pode começar imediatamente.

**Status:** ready-for-agent

- [ ] Recusa de terceiro contendo "com outra pessoa"/"com mais uma pessoa" passa pelo gate e é enviada ao cliente
- [ ] Admissão de estado ("tô com outra pessoa", "estou com um cliente", "estou atendendo") continua barrando e abrindo handoff
- [ ] "estou te atendendo" / "estou atendendo você" (o próprio interlocutor) segue passando
- [ ] Casos cobertos em `tests/agente/test_output_guard.py`, sem `needs_key`
- [ ] Atendimento #36 devolvido para a IA, com o motivo do handoff registrado como falso-positivo
- [ ] Métrica de `OUTPUT_LEAK_DETECTADO` não dispara nos casos de recusa
