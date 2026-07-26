# Enxugar o `regras.md.j2` movendo disciplina para trilho determinístico

## Por que

O BP_GERAL (persona + regras) está em ~16-17k tokens de prefixo fixo por turno; o `regras.md.j2` sozinho é ~12k. O custo é irrelevante (prefixo byte-idêntico, cacheado automaticamente pelo DeepSeek) — o que o tamanho cobra é **aderência**: cada regra compete com as outras pela atenção do modelo, e regra no meio do bloco é a que mais escorrega. Vários incidentes já corrigidos (Cambuí, "só eu e você", oral sem camisinha) foram exatamente isso — a regra existia e não pegou. Cada correção virou mais um parágrafo, empurrando na direção contrária.

O único corte que não paga em aderência é o que move a regra para código: o padrão A2 (`agente/CLAUDE.md`, "Flags determinísticas de disciplina conversacional").

## Levantamento (2026-07-25)

Varredura do `regras.md.j2` contra `_disciplina.py`, `output_guard.py`, `intercept_disclosure.py` e a guarda do piso em `dominio/atendimentos/service.py`.

**Já determinístico — a prosa é eco, não a garantia.** Sonda-de-balcão, bairro fora do cadastro, chave Pix, raciocínio vazado, promessa sem limite e repetição de bolha têm rede no `output_guard`; disclosure 1ª/2ª/3ª tem `intercept_disclosure` + `disclosure_tentativas`; piso de desconto tem `_abaixo_do_piso`; escada/book/sondagem-do-dia/endereço-já-passado já têm flag A2. Nada a construir — só decidir quanto de prosa o mecanismo sustenta (issues 06 e 07).

**Candidatos novos a flag** (molde exato das 4 existentes: detector de fala isolada em `_disciplina.py` + coluna em `atendimentos` + carimbo no write-time + campo no `ContextoDoTurno` + tag no `contexto_dinamico.md.j2`): a amiga oferecida uma vez, a foto da portaria pedida uma vez, o contador de pergunta de horário, o motivo do resgate perguntado uma vez (issues 01–04).

**Um caso que é pré-computação, não flag:** o número do endereço (issue 05). O gate estrutural de estado já existe (`_libera_local_de_encontro`, a partir de `Qualificado`); falta o segundo degrau.

**Fora de escopo:** contadores sobre a fala do CLIENTE (`pedido_explicito_repetido`, `cross_modelo_fishing`) — valem muito, mas não há gancho write-time para o burst dele; é trilho novo, não extensão do padrão. `valor_defendido_em` e `apresentacao_feita_em` — o prompt não diz "uma vez" para nenhum dos dois; flag que suprime fala legítima custa mais que a repetição que evita.

## Restrições que valem para todos os issues

- **Poda nunca zera a regra.** O `output_guard` tem kill-switch (`output_guard_habilitado`) e bolha bloqueada é venda perdida — o prompt segue sendo a primeira barreira. Poda-se o detalhamento (paráfrases, justificativa narrativa), nunca a linha da regra.
- **Ordem obrigatória:** criar a flag → medir na bancada → só então podar a prosa. Nunca o contrário (`agente/CLAUDE.md`: "dedup não é deleção grátis").
- **Migration** vai em `infra/sql/NNNN_*.sql` e **não é aplicada em prod** pelo issue (CLAUDE.md §0). Atendimentos abertos antes dela ficam com a coluna nula — backfill one-shot é escrita em prod, autorização à parte.
- **Nada de scan por turno** nem prosa extra no BP_GERAL: a verdade é materializada no write-time.
- As flags de disciplina ficam **fora** do `<ja_combinado>` — não são belief, o extrator não as lê, `ja_registrado.md.j2` não muda.

## Gate de verificação

`make lint`, `make typecheck`, `make test`; `make gate-conduta` e `make evals` para qualquer issue que toque prompt.
