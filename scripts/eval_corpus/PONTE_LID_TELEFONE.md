# Ponte `@lid` → telefone do corpus — FECHADO (23/06/2026)

Registro de decisão sobre a ponte entre o **corpus de conversas** (`corpus.*` / `fichas_threads.jsonl`,
chaveado por `<id>@lid`) e o **desfecho real + R$** do painel (`barravips.clientes`, chaveado por telefone
E.164). Objetivo original: refazer "o que converte" **ponderado por dinheiro** (money-weighted), cruzando
conversa × receita.

**Veredito: a ponte está morta e fica fechada.** Não vale mais perseguir. O trabalho de corpus segue pela
ponte que está **viva** — `corpus → desfecho_proxy` (ver "Pivô" abaixo).

> Não confundir com o **risco de `@lid` no webhook ao vivo**, que é problema **diferente e já resolvido**:
> `_resolver_identidade_cliente` (em `api/src/barra/webhook/routes.py`) pega o E.164 real do `remoteJidAlt`
> e rejeita `@lid` sem alt (`lid_sem_telefone`, fail-closed). Mergeado na `main`. Ver memória
> `lid_webhook_grava_como_telefone_risco`.

## Por que está morta (evidência, 13/06/2026)

O telefone por trás do `@lid` das 4 instâncias eb01–04 **não existe de forma recuperável** no banco
`evolution_v3` (extração antiga, pré-migração LID + privacidade `@lid`). Esgotadas as vias de junção:

| Via tentada | Resultado |
|---|---|
| `Message.key.remoteJidAlt` (telefone embutido) das eb | ≈0 (eb01 0/127, eb02 7/548, eb03 0/176, eb04 0/682) — extração pré-migração, campo zerado |
| Cross-map global lid→pn (todas as instâncias) aplicado às eb | **25/1367 = 1,8%** — `@lid` não é tão global na prática |
| Tabela `IsOnWhatsapp` (mapa dedicado lid↔remoteJid) | 0/1367 |
| Tabela `Contact` das eb | só `@lid`, nenhum telefone |

## Probe de confirmação EXECUTADO (23/06/2026) — autorizado, read-only

Sondagem read-only do `evolution_v3` de prod (docker exec `psql` no container `postgres_postgres.1`,
env Portainer id 1) para cravar o número. Achados:

1. **`Session.creds` NÃO contém o `lidMapping`** — é só o creds do dono (3255 chars, sem signal key
   store). A premissa "lidMapping nas creds Baileys" era falsa: esse mapa não é persistido no Postgres.
2. **Instâncias NÃO estão deslogadas** — `Instance.connectionStatus`: eb01/eb02/eb03 = `open`, eb04 =
   `connecting`. A premissa anterior ("provavelmente deslogadas") estava errada — porém **irrelevante**
   ao resultado.
3. **Fontes reais de lid→pn medidas agora:**
   - `Message.key.remoteJidAlt` (telefone no recebimento) dos `@lid` das eb: **17/1368**.
   - Cross-map global (`remoteJidAlt` de TODAS as instâncias) aplicado aos `@lid` das eb: **34/1368**.
   - `IsOnWhatsapp` (diretório global lid→pn, 4176 linhas): **0** de interseção com os `@lid` das eb
     (`@lid` é device-scoped, não global — confirma o achado de 13/06).
4. **Cobertura final no corpus: 32/1348 = 2,37%** (34 pares globais, 32 presentes em
   `fichas_threads.jsonl`). Dos 32, só 4 são `convertido_provavel` — amostra sem valor estatístico.

**Veredito confirmado: morta.** O número (≈2,4%) bate com a estimativa de 13/06 (1,8%); o probe não mudou
nada, só cravou. Mensagens históricas não recebem backfill de `remoteJidAlt` (é setado no recebimento), e o
diretório global não cobre esses `@lid` — nem instâncias abertas reconstroem o histórico.

A **única** via teórica restante: consultar o WhatsApp ao vivo (`onWhatsApp`/resolução de LID pelas instâncias
abertas) contra os ~1300 contatos. **Descartada** — gera tráfego dos números de produção das modelos, não é
read-only, arrisca flag de conta, e ainda assim não desbloquearia money-weighted. Fora de cogitação.

> Nota PII: os 32 telefones recuperados NÃO são persistidos aqui (dado real de cliente). Só o agregado fica
> registrado. A ponte fica fechada.

## Pivô — a ponte que está VIVA: `corpus → desfecho_proxy`

O `@lid` nunca nos deu o telefone, mas **não precisa**: o `desfecho_proxy` (rótulo de desfecho inferido por
LLM, por thread, dentro do próprio corpus) substitui o join por R$ para as alavancas de produto. É confiável
nos extremos e não toca prod. Números atuais (`fichas_threads.jsonl`, **1512 threads**, 23/06):

**Distribuição de `desfecho_proxy`:**

| desfecho_proxy | n | % |
|---|---:|---:|
| sem_cotacao | 415 | 27,4% |
| qualificado_sem_prova | 324 | 21,4% |
| ambiguo | 315 | 20,8% |
| perdido_sumiu | 231 | 15,3% |
| convertido_provavel | 202 | 13,4% |
| perdido_objecao | 25 | 1,7% |

**Alavanca #1 — vazamento de topo de funil.** **45,9%** dos threads morrem **antes da cotação**
(`saudacao_only` 24,1% + `sondagem` 21,8%); `desfecho_proxy='sem_cotacao'` = **27,4%**. Maior buraco do
funil e nunca priorizado.

**Alavanca #2 — onde a conversão acontece (proxy por estágio):**

| estagio_max | n | convertido_provavel |
|---|---:|---:|
| saudacao_only | 364 | 0,3% |
| sondagem | 329 | 0,6% |
| cotou | 377 | 2,4% |
| negociou | 168 | 16,1% |
| **prova_vinda** | 155 | **85,8%** |
| combinou | 119 | 25,2% |

O salto está em `prova_vinda` (mídia/prova de vinda) — chegar lá é o que correlaciona com fechar.

**Alavanca #3 — objeções reais (achatado, n threads):** `horario` 191 > `preco` 149 > `local_distancia` 57.
Horário pesa mais que preço — contraintuitivo, dimensiona onde a IA precisa ser boa.

> Limites honestos do proxy: `desfecho_proxy` é inferência por LLM, confiável nos extremos
> (silenciou→perdido, prova_vinda→convertido), ruidosa no meio (`ambiguo` 20,8%). Não é receita; é o melhor
> sinal de produto disponível **sem** o telefone. Para money-weighted de verdade, só com dado novo
> capturado ao vivo já com E.164 (webhook corrigido) acumulando em prod.

## Ver também
- Memória `corpus_lid_telefone_irrecuperavel` (esta decisão)
- Memória `lid_webhook_grava_como_telefone_risco` (o risco ao vivo, já corrigido)
- `ATLAS.md`, `fichas_threads.jsonl` (o corpus)
