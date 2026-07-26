# 07 — Cliente fecha e o Combo de grupo é materializado

**O que construir:** quando o cliente topa horário e valor, o combo vira realidade de uma vez — um **Atendimento** para cada mulher, cada um com seu `#N`, seu estado, seu valor e seu **Bloqueio**, todos amarrados pelo mesmo `combo_id`. Até esse instante **nada** foi reservado: a oferta não trava agenda de ninguém.

A reserva só no sim é deliberada, e espelha o **bloqueio prévio** — que também não nasce na cotação, nasce quando o horário é combinado. O custo é uma corrida real: a convidada pode ser tomada entre a oferta e o sim, pela IA dela ou por Fernando. Quando isso acontece, a criação falha para aquela convidada e a ferramenta devolve `ERRO:` — e a conduta **já sabe** o que fazer: *"nunca confirme ao cliente algo que o sistema recusou"*, e a falha *"não existe pra ele"* (vira desculpa de gente). Nada pode persistir pela metade.

Os N atendimentos têm o **mesmo Cliente** (o comprador) e **Modelos distintas**, então o invariante "no máximo um Atendimento aberto por par" continua intacto. Os outros homens do grupo **não viram dado** — mesma leitura do **Menage** caso (a), invertida.

Schema: uma coluna `combo_id` nullable em `atendimentos`, nula em 100% dos atendimentos normais. Migration sequencial em `infra/sql/`, **schema-only, nunca seed** — e `make migrate` continua proibido contra produção.

**Bloqueado por:** 06 (a oferta precisa existir para haver o que fechar).

**Status:** ready-for-agent

- [ ] Migration adiciona `combo_id` nullable, idempotente e sem tocar em seed
- [ ] Sim do cliente cria N Atendimentos irmãos com o mesmo `combo_id` e N Bloqueios válidos
- [ ] Numeração `#N` por modelo permanece correta em cada atendimento criado
- [ ] Toda a validação de Disponibilidade, sobreposição e buffer é a que já existe — sem caminho paralelo
- [ ] Convidada tomada entre a oferta e o sim produz `ERRO:`, a IA recua e **nada** persiste (transação revertida)
- [ ] Atendimentos normais seguem com `combo_id` nulo e comportamento idêntico ao de hoje
- [ ] Repasse, **Comissão de vendedor** e **Taxa de cartão** calculados por atendimento, sem caso especial
- [ ] Testes `needs_db` cobrindo criação, corrida e reversão
