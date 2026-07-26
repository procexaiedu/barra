# 01 — Expor as peças do contexto no estado do grafo

**Spec:** `.scratch/extracao-janela-dedicada/spec.md` (prefactor)

**O que construir:** hoje a mensagem do cliente e o contexto dinâmico são fundidos numa única
mensagem antes de o turno seguir, e depois não há como separá-los — é isso que impede a extração de
receber uma janela própria. Este ticket faz o `prepare_context` publicar as peças (âncora temporal e
o bloco de estado já renderizado) no estado do grafo, do mesmo jeito que já publica outras marcas
por-turno, **sem alterar nada do que o chat recebe**.

Nenhum comportamento visível ao cliente muda. O que muda é que o turno seguinte passa a ter as
peças disponíveis para montar a janela da extração.

**Bloqueado por:** nada — pode começar imediatamente.

**Status:** ready-for-agent

- [x] O `prepare_context` publica no estado do grafo a âncora temporal do turno (data e hora atuais já resolvidas) e o texto do bloco de estado registrado, renderizado a partir das MESMAS variáveis que alimentam o contexto dinâmico
- [x] O bloco de estado vive num template de prompt, não em string de código
- [x] O contexto dinâmico que o chat recebe permanece **byte-idêntico** ao atual — teste de render comparando a saída antes/depois
- [x] A ordem final da última mensagem do turno (lembrete → mensagem do cliente → contexto) permanece inalterada
- [x] Nenhuma query nova ao banco é introduzida
- [ ] Gate verde: lint, typecheck e testes, incluindo os que tocam banco contra o Postgres real
      → lint/typecheck/`make test` verdes (1649 passed). Os `needs_db` NÃO rodaram: sem
      `TEST_DATABASE_URL` nem Postgres local nesta máquina. A mudança não adiciona query nem SQL.

**Além do pedido no ticket (decidido na implementação):**

- A conversa CRUA (janela antes da anexação do contexto e do lembrete) também vai ao State — é a
  terceira peça irreconstruível depois da fusão.
- O bloco NÃO renderiza o dia que o A2 (`_aplicar_dia_confirmado`) só assume sem persistir: é
  renderizado ANTES dessa mutação. Apresentar suposição como gravada faria o extrator omitir
  `data_desejada` e o dia nunca chegaria ao banco (subextração).
- O bloco já nasce com os rótulos e a instrução de delta que o ticket 05 pede (palpite × pedido
  dele, cotado × aceito, registrar só o que mudou, `proxima_acao_esperada` fora do delta) — evita
  reescrever o texto no 05. Nada consome o State ainda.
