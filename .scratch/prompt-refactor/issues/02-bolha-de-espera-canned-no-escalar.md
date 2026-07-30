# 02 — A escalada que a IA decide deixa de largar o cliente no vácuo

**What to build:** quando a IA decide escalar, ela deve deixar uma bolha curta de espera antes de chamar a ferramenta. Hoje isso é só instrução em prosa: se ela não escreve nada, o cliente fica sem resposta com a IA pausada, esperando alguém que não vai falar. A bolha de espera passa a ser garantida pelo sistema (canned no post-process), como já acontece na escalada disparada pelo guard da extração.

Exceção que precisa continuar valendo: em `conteudo_ilegal` **não** existe bolha de espera — "um momento" depois de um pedido desses lê como "deixa eu ver se consigo". O motivo vem no argumento da própria chamada da ferramenta, então o canned pode distinguir sem depender do texto do modelo.

A prosa da conduta sobre isso **fica** — ela cobre o caso do `conteudo_ilegal`, que o canned não cobre.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] escalada decidida pela IA sem nenhuma bolha no turno passa a sair com uma bolha de espera do pool canned
- [x] escalada com motivo `conteudo_ilegal` sai sem bolha de espera, com a recusa seca como única bolha
- [x] escalada em que a IA já escreveu a bolha de espera não ganha uma segunda
- [x] teste cobrindo os três casos
- [x] `make test` verde

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

## Comments

Implementado em `agente/nos/post_process.py`, sem coluna, sem migration, sem detector novo — o pool
(`ESPERA_ESCALADA_CANNED`), o sorteio determinístico por `turno_id` (`escolher_espera_escalada`) e o
corte pela AIMessage que carrega o `tool_call` de `escalar` já existiam. O que mudou: o ramo
`corte is not None` deixou de ser só "zera o pós-escalar" e passou a decidir também se o turno
sairia MUDO; quando sai, injeta a mesma canned que a escalada de guarda já injetava.

Decisões que valem registro:

- **A exceção vem do arg da própria `tool_call`**, não do texto do modelo: `motivo` é enum fechado
  (`ferramentas/escalada.py`), e `conteudo_ilegal` desliga a espera. Se a IA não escrever nem a
  recusa seca, o turno segue mudo de propósito — quem cobre a fala ali é a prosa, não o canned.
- **O gate de "turno mudo" reusa `extrair_texto_do_turno`**, o mesmo filtro do coordenador, em vez
  de somar `texto_da_mensagem` cru. Motivo: o texto de uma passagem cuja tool ERROU é rascunho
  superado e não chega ao cliente — contá-lo como bolha deixaria o vácuo de pé exatamente no caso
  que o ticket existe pra matar. Coberto por teste próprio.
- **Nada de prompt mudou.** A prosa do `<quando_usar_escalar>` (bolha de espera + exceção do
  `conteudo_ilegal`) e a linha 7 do `<nucleo>` ficam como estão — BP_GERAL intocado, prefixo
  cacheado intocado. Nenhum eco multi-site do `agente/CLAUDE.md` foi tocado.
- **`output_guard` não precisou de nada**: `_CANNED_CURADAS` já isenta `ESPERA_ESCALADA_CANNED` das
  defesas de texto gerado, independente de qual ramo do `post_process` injetou.

Testes em `tests/agente/test_post_process_pausa.py` (5 novos/ajustados, puros — sem `needs_db`):
sem bolha → canned; `conteudo_ilegal` com recusa seca → nenhuma canned; `conteudo_ilegal` mudo →
segue mudo; bolha já escrita → não ganha segunda (o teste existente da escalada do turno ganhou o
`motivo` no arg e a asserção explícita de ausência de canned); passagem com tool que errou → ainda
ganha a espera.

Verificação: `make lint` ✅ · `make typecheck` ✅ · `make test` ✅ (1778 passed, 239 skipped —
skips são `needs_db` sem `TEST_DATABASE_URL`; a mudança não toca banco).

Gate pago **não rodado** (precisa de autorização humana — §0 do CLAUDE.md): `make evals` /
`evals/e2e/conduta_gate.py`. O anexo D2-1 já registra que o `conduta_gate` só mediria isto se a
massa tiver roteiro que escale — hoje ele mede `cotou`/`empurrao`/`estilo_dist`/fluxo JSD, nenhum
deles sensível à bolha de espera. Ou seja: rodá-lo não prova nada aqui; provar em e2e exigiria
roteiro novo de escalada.

**Fechamento (driver, 2026-07-30).** Diff conferido: 2 arquivos de código + este ticket, sem
vazamento de escopo e sem encostar no WIP da árvore. `make lint` ✅ · `make typecheck` ✅ (142
arquivos) · `make test` ✅ (1778 passed, 239 skipped — +4 testes). **Sem gate pago pendente**: o
`conduta_gate` mede `cotou`/`empurrao`/`estilo_dist`/fluxo JSD, nenhum sensível à bolha de espera,
e a massa não tem roteiro que escale — rodá-lo não provaria nada aqui. `Status: resolved`.
