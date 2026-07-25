# 06 — Bancada offline: replay, métricas e relatório

**Spec:** `.scratch/extracao-eval-offline/spec.md`

**O que construir:** hoje não há como responder "essa mudança no extrator melhorou?" antes de subir
para produção — e, no volume do piloto, esperar o tráfego responder leva semanas. Este ticket
entrega a bancada: reconstrói turnos históricos a partir do banco, roda o extrator sobre eles e
compara com rótulo humano.

O extrator não precisa de LLM-judge: a saída é estruturada, o rótulo é um conjunto de pares
campo-valor, a métrica é igualdade. Neste ticket a bancada roda com **extrator fake**, então não
consome crédito e entra no gate.

**Bloqueado por:** nada — pode começar imediatamente. (Nota: a reconstrução da entrada só fica
plenamente fiel depois do 05; antes disso ela é aproximada, porque a entrada atual da extração
inclui agenda, bloqueios e disponibilidade do instante, que não são reconstruíveis.)

**Status:** done

- [x] Reconstrução da entrada por replay: dado um Atendimento, produz para cada turno decisivo a tripla (conversa até o instante, snapshot no instante, agora), com o snapshot vindo da aplicação em ordem dos payloads registrados no histórico — nunca do estado atual do Atendimento
- [x] O instante do turno é injetado pelo mecanismo de clock injection existente
- [x] Métrica de nível campo, com a assimetria declarada: precisão manda no aceite de valor e no tipo do encontro; recall manda na intenção; horário reporta ambos mais a marca de evidência
- [x] Métrica de nível trajetória: comparação da sequência de estados do Atendimento com a rotulada
- [x] Relatório legível por campo e por trajetória, com os limites do corpus escritos nele (dez dias, uma modelo, piloto com cancelamento automático ligado)
- [x] Suporte a variantes desde o início: temperatura, presença do bloco de estado registrado, descrição do aceite autocontida vs. referenciada, promoção de intenção derivada (+ o patch de 24/07, que a spec pede e o issue não listava)
- [x] Suporte a repetição por item, com dispersão no relatório (não só média)
- [x] Golden set versionado, partindo das rotulagens já produzidas
- [x] Teste da ferramenta com extrator fake roteirizado: dado golden set pequeno e payload conhecido, o relatório apresenta as métricas corretas — roda sem crédito, entra no gate
- [x] Teste da reconstrução contra Atendimento semeado com histórico conhecido, contra o Postgres real com rollback
- [x] Alvo próprio de Makefile, separado dos gates de segurança e de conduta
- [x] Gate verde: lint, typecheck e testes, incluindo os que tocam banco contra o Postgres real

## Limites conhecidos da entrega

- **`sem-promocao-intencao` só vale no nível campo.** A promoção derivada mora no domínio
  (`_promover_intencao_por_evidencia`), então a trajetória sempre a exercita. Desligá-la lá exigiria
  um toggle em código de produção, fora do escopo desta medição.
- **Cobertura de rótulo por campo é desigual** (o relatório expõe o `n` de cada um): aceite 9,
  recuo 5, intenção 5, evidência 4, horário 2, tipo 2. Falta o horário fantasma do #25 e a amostra
  aleatória de turnos decisivos — a própria rotulagem inicial já registrava essa pendência.
- **Recortes, não janelas inteiras.** A `conversa` de cada item é o trecho citado na rotulagem
  humana; a janela fiel de cada turno vem do replay contra o banco (issue 07).
