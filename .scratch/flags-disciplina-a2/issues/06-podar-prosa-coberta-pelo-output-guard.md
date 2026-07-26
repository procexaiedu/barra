# 06 — Podar a prosa que o output_guard já garante

**What to build:** As regras do `regras.md.j2` que já têm rede determinística na saída deixam de ser explicadas em parágrafo e passam a valer em uma linha. A conduta observável não muda: o que hoje segura essas regras na prática é o scan do `output_guard`, não o texto.

Alvos, com o detector que já os cobre:

| regra | detector |
|---|---|
| sonda-de-balcão e suas paráfrases (`<conducao_da_venda>`, abertura) | sonda de balcão |
| bairro/região fora do cadastro (`<tipos_de_encontro>`, degrau 1) | eco de região |
| chave Pix nunca sai dela (`<nucleo>` 10 e `<tipos_de_encontro>`) | chave Pix |
| nada de raciocínio ou rótulo interno (`<nucleo>` 10 e `<nucleo_final>`) | marcador de raciocínio |
| "quantas finalizações" sem número (`<girias_do_cliente>`) | promessa sem limite |
| não repetir a mesma pergunta em loop | bolhas repetidas |

**Blocked by:** None — pode começar imediatamente.

**Status:** ready-for-agent

- [x] Cada regra da tabela fica com **uma linha** no prompt — a proibição em si, sem as paráfrases nem a justificativa narrativa. Nenhuma delas some: o `output_guard` tem kill-switch e bolha bloqueada é venda perdida, então o prompt segue sendo a primeira barreira.
- [x] O bloco `<nucleo>`/`<nucleo_final>` mantém o sanduíche primacy+recency das regras que hoje ecoa — a poda é do detalhamento no corpo, não do eco (ver "Regras com eco multi-site" em `agente/CLAUDE.md`).
- [ ] `make gate-conduta` e `make evals` verdes, comparados contra a baseline antes da poda; nenhuma regressão nas rubricas que cobrem estas regras. — **BLOQUEADO**: sem `TEST_DATABASE_URL` no `.env` (o gate pede o self-hosted de prod) e `make evals` gasta crédito Anthropic. Autorização §0 pendente.
- [ ] Estilometria sem deriva relevante (a poda não pode mudar a voz). — **BLOQUEADO** pelo mesmo motivo (exige rodar o agente).
- [x] Registro no PR de quantos tokens saíram do `regras.md.j2`. — ver "Resultado" abaixo.
- [x] Gate padrão verde. — `ruff` · `mypy` (141 arquivos) · 1729 testes, 0 falhas.

## Resultado (2026-07-26)

Baseline medida contra o arquivo imediatamente **antes** das podas (já com a reestruturação em sub-tags de `<conducao_da_venda>`, que veio de outra frente), não contra `HEAD` — senão o número misturaria os dois trabalhos. Tokenizador `cl100k_base`.

| arquivo | antes | depois | delta |
|---|---|---|---|
| `regras.md.j2` | 14908 | 14699 | **−209** (−1,40 %) |
| `persona.md` | 4424 | 4354 | −70 (−1,58 %) |
| BP_GERAL | 19332 | 19053 | **−279** (−1,44 %) |

Cinco podas efetivas. A 6ª linha da tabela ("nada de raciocínio ou rótulo interno") **não tinha o que podar**: seus dois sites são `<nucleo>` 10 e `<nucleo_final>`, que são exatamente o sanduíche que o 2º checkbox manda preservar, e já eram one-liners.

A regra de bolha repetida mora no `persona.md` `<voz>` ("Sem loop"), não no `regras.md.j2` — daí a segunda linha da tabela de tokens.

**Dois recuos, apontados pelo code review e aceitos:**

1. **Caps restaurado na regra de bairro.** A poda tinha rebaixado "você NUNCA a troca" para "nunca". `agente/CLAUDE.md` ("Escala léxica de dureza") lista bairro-fora-do-cadastro nominalmente entre os failure-modes comprovados que justificam caps (alucinação "Cambuí", cluster nao_contidos 23/07).
2. **Ramo restaurado no `persona.md`.** A poda tinha comido "ele só confirma ('ok', 'ah ta', 'fechado') → você não re-manda nada — fica quieta ou fecha com uma bolha curta e nova". O `bolhas_repetidas` do `output_guard` só casa bolha quase-idêntica a uma já enviada: não impede reafirmar com texto **novo** quando ela devia calar. Sem rede determinística, cortar violaria "poda nunca zera a regra" (`spec.md`). Custou a economia do `persona.md` (era −102).

**Risco em aberto, para o gate resolver:** a poda da sonda-de-balcão tirou 5 das 6 paráfrases. `_RE_SONDA_BALCAO` casa todas as removidas, mas é o caso literal de "dedup não é deleção grátis — gate por simulador/eval antes de tirar, nunca mecânico" (`agente/CLAUDE.md`). Enquanto `gate-conduta`/`evals` não rodarem, essa poda é a mais exposta das cinco.
