# Go-live do Agente financeiro (spec 0005)

Colocar o Agente financeiro no ar em UM Grupo financeiro real (o primeiro é o da Yasmin,
`Modelo Yasmin Ruiva/ financeiro 🤑`). Ordem obrigatória: **schema → cadastro → env → deploy →
entrada no grupo**. Trocar a ordem produz o único erro caro deste módulo — o agente entrando num
grupo cujo banco ainda não sabe quem ele é, ou pior, respondendo antes de a operação querer.

Vocabulário e decisões: `docs/dominio/grupo-financeiro.md`, ADR-0043, `docs/specs/0005-*.md`.

> **O agente é silencioso por design.** Ele só fala quando registra, quando quita, quando é
> perguntado e uma vez por manhã. Se depois do go-live o grupo ficar em silêncio total por um dia
> com venda anunciada, isso é sintoma — vá para "Verificação" e não espere.

## 0. Pré-condição: o número da ProceX já entrega neste webhook

O número é compartilhado com o myEYE; o `webhook_router` entrega os eventos da instância da ProceX
aqui. Se o roteamento ainda não existir, nada abaixo funciona (o agente nunca é chamado). Conferir
com uma mensagem qualquer no grupo e o log do passo 4.

## 1. Schema (aplicar em prod, na ordem cronológica)

Pelo caminho canônico (`aplicar-migrations-prod.md`, nunca `make migrate` contra o prod):

```
infra/sql/20260814004920_grupo_financeiro_encanamento.sql
infra/sql/20260814012500_venda_registrada_e_nomes_de_anuncio.sql
infra/sql/20260814013400_pendencia_de_forma_de_pagamento.sql
infra/sql/20260814020000_dedup_de_conteudo_da_venda.sql
infra/sql/20260814022300_correcao_e_anulacao_da_venda.sql
infra/sql/20260814031400_comprovante_de_fechamento.sql
infra/sql/20260814043000_dados_cadastrais_da_modelo.sql
infra/sql/20260814050500_indices_quentes_do_grupo_financeiro.sql
infra/sql/20260814120000_cobranca_da_agencia.sql
infra/sql/20260814193000_dedup_de_conteudo_do_comprovante.sql
infra/sql/20260814213000_anulacao_do_comprovante.sql
infra/sql/20260814233000_comprovante_de_entrada_da_modelo.sql
```

Conferir depois (nunca confiar no retorno do script):

```sql
SELECT table_name FROM information_schema.tables
 WHERE table_schema = 'barravips'
   AND table_name IN ('grupos_financeiros','grupo_financeiro_mensagens','vendas_registradas',
                      'venda_registrada_eventos','modelo_nomes_anuncio','comprovantes_do_grupo',
                      'chaves_pix_conhecidas','cobrancas_da_agencia')
 ORDER BY 1;   -- esperado: as 8
```

## 2. Cadastro (é o que torna o agente closed-world)

Não há tela de painel para isto — o vínculo grupo↔modelo é a única coisa que autoriza o agente a
falar num grupo, e ele entra à mão de propósito.

**O caminho recomendado é o script** (idempotente, dry-run por padrão, e imprime o estado do banco
depois de escrever):

```bash
uv run --project api python scripts/cadastrar_grupo_financeiro.py \
    --modelo "Yasmin" --jid 1203634xxxxxxxxxx@g.us \
    --nome-do-grupo "Modelo Yasmin Ruiva/ financeiro" \
    --apelido bianca --apelido yasmin \
    --chave-da-casa "<chave viva>" --titular-da-casa "<titular>"
# confira a saída; repita com --confirmar
```

O SQL abaixo é o mesmo conteúdo, para quando só houver um cliente Postgres à mão.

**2.1 Descobrir o JID do grupo.** Adicione o número da ProceX ao grupo e mande qualquer mensagem
lá. O webhook loga o descarte com o JID:

```
grupo_financeiro_nao_cadastrado jid=1203634xxxxxxxxxx@g.us message_id=...
```

(É o comportamento correto de um grupo não cadastrado: ignorar com log. O agente fica mudo até o
passo 2.2 — então dá para entrar no grupo antes de cadastrar, sem risco de ele falar.)

**2.2 Nomes de anúncio da modelo.** O resolver é closed-world: sem isto, todo anúncio vira
pergunta "quem é?" no grupo. Cadastre o nome verdadeiro **e** os apelidos com que ela é anunciada
(`Perfil bianca/yasmin` → `bianca` e `yasmin`):

```sql
INSERT INTO barravips.modelo_nomes_anuncio (modelo_id, nome, nome_normalizado)
VALUES ('<modelo_id>', 'bianca', 'bianca'),
       ('<modelo_id>', 'yasmin', 'yasmin')
ON CONFLICT DO NOTHING;
```

Faça o mesmo para as **parceiras que aparecem nos anúncios deste grupo** (`Perfil sophia/julia`):
sem elas cadastradas, a venda de duas modelos registra só metade e o agente pergunta pela outra.

**2.3 O vínculo grupo↔modelo** (é isto que liga o agente):

```sql
INSERT INTO barravips.grupos_financeiros (modelo_id, jid, nome)
VALUES ('<modelo_id>', '1203634xxxxxxxxxx@g.us', 'Modelo Yasmin Ruiva/ financeiro')
ON CONFLICT (jid) DO NOTHING;
```

**2.4 A chave Pix de fechamento da casa.** Sem ela, TODO comprovante que a modelo mandar vem com
"⚠️ chave fora da lista da casa" — o alarme vira ruído e deixa de significar alguma coisa:

```sql
INSERT INTO barravips.chaves_pix_conhecidas (chave, chave_normalizada, titular, descricao)
VALUES ('<chave viva>', '<chave sem pontuacao, minuscula>', '<titular>', 'Fechamento da casa')
ON CONFLICT (chave_normalizada) DO NOTHING;
```

A chave da **agência** (destino da Cobrança da agência) **não entra aqui** — ela não é destino de
fechamento, e o pagamento de cobrança não dispara o aviso de chave (por desenho).

**Quando a casa trocar de chave**, atualize esta tabela na mesma hora. O agente não aprende chave
por mensagem de grupo, e isso é uma tranca de segurança, não um esquecimento: chave dita no grupo
pode ser golpe.

## 3. Env do stack (API **e** worker)

| Variável | Valor | Efeito se faltar |
|---|---|---|
| `GRUPO_FINANCEIRO_INSTANCIA` | instância Evolution do número da ProceX | Rotina da manhã **desligada**; webhook sem filtro de entrega espelhada (a mensagem do grupo chega 2×, e na entrega da modelo o `fromMe` se inverte) |
| `GRUPO_FINANCEIRO_ROTINA_ATIVA` | `true` (default) | Kill-switch da cobrança diária |
| `OPENROUTER_API_KEY` | a mesma do agente de venda | Sem OCR de comprovante e sem transcrição de áudio — o agente registra e fica calado |
| `OPENROUTER_MODEL_VISION_PIX` | **deixar vazia** (o default do código é o modelo medido) | Nada; a var só existe para pinar outro modelo em emergência |
| `DEEPSEEK_API_KEY` | a mesma do agente de venda | O agente volta a ler a fala do grupo pela **allowlist** — continua funcionando, mas só entende o fraseado telegráfico ("pix", "todos foram pix"). "Foi tudo no pix menos o do Igor" passa a cair no chão em silêncio |

As duas chaves são de provedores diferentes **de propósito**: o texto do grupo vai direto na
DeepSeek (cache de prefixo + modelo cravado) e a foto do comprovante vai no Gemini pelo OpenRouter
(OCR). Uma sumindo no redeploy não cega a outra — e nenhuma das duas derruba o registro de vendas,
que é determinístico.

> **Atenção ao subir esta versão: o modelo de vision mudou** (`google/gemini-3-flash-preview` →
> `google/gemini-3.1-flash-lite-preview`), e ele vale para o OCR do **agente de venda** também —
> os dois leem comprovante pelo mesmo trilho. Medido em 14/08 sobre as fotos reais do grupo:
> 99,8% dos campos contra 94,6%, metade do custo, e zero leituras truncadas. O sufixo `-preview`
> **faz parte do nome**: `google/gemini-3.1-flash-lite` (sem ele) é outro roteamento no OpenRouter
> e lê pior — devolve o valor em centavos ("65807" para R$ 658,07). Se precisar voltar atrás,
> `OPENROUTER_MODEL_VISION_PIX` pina qualquer modelo sem deploy.

Lembrete de infra: **StackGitRedeploy zera o Env do stack**; use update isolado e confira as três
variáveis depois de qualquer redeploy.

## 4. Deploy

`api` e `worker` (o cron da manhã vive no worker). Padrão da casa: bump de versão + `service
update --force`, nunca `docker restart` (worker órfão no Swarm).

## 5. Verificação, na ordem

1. **Boot**: sem erro de import e com o cron registrado (`rotina_financeira` na lista de crons).
2. **Ingestão**: mande uma mensagem qualquer no grupo → log `grupo_financeiro_...` e uma linha em
   `barravips.grupo_financeiro_mensagens`.
3. **Registro**: peça a um gestor para postar o próximo anúncio real. Esperado: `✅ Registrei: …`
   no grupo e uma linha em `vendas_registradas`.
4. **Painel**: a venda aparece em `/financeiro` (lista de Vendas registradas) e soma na receita.
5. **Manhã seguinte**: uma (e só uma) mensagem de cobrança consolidada por grupo.

```sql
-- o que o agente fez nas últimas 24h
SELECT count(*) FILTER (WHERE de_mim) AS falas_do_agente,
       count(*) FILTER (WHERE NOT de_mim) AS mensagens_do_grupo
  FROM barravips.grupo_financeiro_mensagens
 WHERE recebida_em > now() - interval '1 day';
```

Métricas: `barra_grupo_financeiro_mensagens_total`, `..._anuncios_total`,
`..._comprovantes_total`, `..._rotina_total`.

## 6. Como desligar (nesta ordem de intrusividade)

1. `GRUPO_FINANCEIRO_ROTINA_ATIVA=false` — cala a cobrança da manhã, mantém o registro.
2. `UPDATE barravips.grupos_financeiros SET ativo = false WHERE jid = '…'` — o agente volta a
   tratar o grupo como não cadastrado (ignora com log). **Efeito imediato, sem deploy.**
3. Remover o número do grupo — o último recurso, e o único visível para a operação.

Nada disso apaga o que já foi registrado: venda anulada tem rastro, cobrança quitada tem prova.
