# 07 — Primeira rodada real de medição

**Spec:** `.scratch/extracao-eval-offline/spec.md`

**O que construir:** número para as duas perguntas que hoje estão em aberto e sem evidência
nenhuma:

1. **Temperatura.** A extração roda com temperatura de sampling. O comentário no código afirma que
   chamar "sem temperatura" dá determinismo, mas omitir o parâmetro faz o provider aplicar o próprio
   default — que não é zero em nenhuma API compatível com OpenAI. A tarefa mais determinística do
   sistema roda com sampling enquanto o chat criativo roda num valor escolhido por experimento.
2. **O patch de 24/07** (que removeu a derivação do aceite a partir do valor, fez a retratação
   rebaixar e endureceu a descrição do campo) nunca foi exercitado: a última extração de produção
   aconteceu antes dele.

Entrega um relatório comparativo, não uma mudança de código.

**Bloqueado por:** 06.

**Status:** done

⚠️ **Consome crédito real** (o provider do agente ao vivo) — cai na regra de produção do CLAUDE.md
§0 e exige autorização explícita do Fernando, frase a frase, antes de rodar.
Autorizada e executada em 25/07 (270 chamadas, `deepseek-v4-flash`).

- [x] Confirmar na documentação do provider qual é o default de temperatura, antes de tratar o valor como conhecido — **1.0** (doc oficial DeepSeek; 0.0 é a recomendação dela para tarefa determinística)
- [x] Rodada com a temperatura atual e com zero, sobre o mesmo golden set, com repetição suficiente para separar melhora de dispersão — 18 itens × 5 repetições × 2 variantes
- [x] Rodada medindo o patch de 24/07 contra o comportamento anterior — rodada feita; **resultado inconclusivo por cobertura do gabarito**, e o relatório mostra por quê (ver "o que falta")
- [x] Relatório comparativo publicado no diretório da spec do eval, com a data e a configuração de cada execução — `.scratch/extracao-eval-offline/rodada-2026-07-25.md` (+ o JSON bruto ao lado)
- [x] Recomendação explícita sobre cravar a temperatura, com o número que a sustenta — a mudança de configuração em si NÃO faz parte deste ticket

## O que a entrega mudou no código

A variante `aceite-derivado-24-07` (entregue no 06) media **meio patch**: reintroduzia a derivação,
mas mantinha a descrição endurecida do campo, que veio no mesmo commit. Virou `pre-patch-24-07`,
com as duas metades.

## O que a rodada deixou aberto

- **A pergunta 2 continua sem resposta**, e agora com causa conhecida: o golden set não tem nenhum
  turno de cotação — que é onde a derivação removida agia. Precisa de (a) turnos de cotação
  rotulados e (b) janela fiel do replay em vez do recorte.
- **`.env` local com `DEEPSEEK_MODEL_CHAT=deepseek-chat`**, alias aposentado em 24/07 15:59 UTC.
  A rodada sobrescreveu o id. **Não foi verificado se produção está igual** — vale conferir.
