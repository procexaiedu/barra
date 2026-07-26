# 02 — A foto da portaria é pedida uma vez

**What to build:** Pedido o print da chegada ("Quando chegar me manda uma foto da portaria amor"), a IA para de recobrar. Enquanto o cliente não chega ela mantém presença curta ("Vou me arrumar rs", "Estou te esperando"), mas não repete o pedido nem emenda "vai vir mesmo?" / "chega em quanto tempo?" — que é, pelo próprio prompt, o que mais afasta nessa fase.

**Blocked by:** 01 — mesma área do carimbo no write-time; a 01 fixa o molde.

**Status:** ready-for-agent

- [ ] Coluna nova em `atendimentos` (timestamptz, first-write-wins), migration em `infra/sql/` com `COMMENT ON COLUMN`. Não aplicar em prod.
- [ ] Detector em `_disciplina.py` para o pedido da foto de chegada, cobrindo as formas que o prompt treina (o pedido na despedida do combinado e o pedido em resposta a "cheguei"/"to chegando").
- [ ] Carimbo no write-time, mesma transação, só na primeira inserção da bolha.
- [ ] Campo no `ContextoDoTurno` + tag no `contexto_dinamico.md.j2`: já pediu → não recobre, mantenha presença curta e espere.
- [ ] O trecho de `<conducao_da_venda>` sobre "pergunte uma vez, depois espere" encolhe; a instrução de **pedir** a foto (e de que um "cheguei" de texto não vale) permanece — ela é o gatilho do handoff implícito.
- [ ] `make gate-conduta` e `make evals` verdes; gate padrão verde.
