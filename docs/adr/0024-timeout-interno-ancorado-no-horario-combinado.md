---
status: accepted
---

# Timeout interno do "sumiu" ancorado no horário combinado

O fluxo interno tem um timeout determinístico que marca o atendimento como `Perdido` (`motivo_perda='sumiu'`) quando o cliente envia o **Aviso de saída** mas não envia a **Foto de portaria** dentro de uma janela. Hoje (`workers/timeouts.py` `aplicar_timeout_interno`, cron a cada minuto) a janela conta **45 min puramente a partir de `aviso_saida_em`**, sem qualquer referência ao horário combinado:

```sql
WHERE tipo_atendimento = 'interno'
  AND estado = 'Aguardando_confirmacao'
  AND aviso_saida_em IS NOT NULL
  AND foto_portaria_em IS NULL
  AND aviso_saida_em < now() - interval '45 minutes'
```

A premissa embutida é "avisou que saiu ⇒ chega em ~45 min". Ela quebra quando o aviso de saída chega **bem antes** do horário combinado (ou desacoplado dele).

Caso real que motivou o ADR (rig Lucia, 18/06/2026, cenário "1. Interno — happy path"): encontro combinado para **17h** (bloqueio prévio criado), cliente sinalizou saída às **16:32**, e o timeout estourou às **~17:17** — declarando `Perdido` um atendimento que mal tinha chegado ao horário marcado. A Foto de portaria chegou ~10 min depois, com o atendimento já encerrado.

## Decisão

- **A janela do timeout passa a contar a partir do mais tarde entre o aviso de saída e o início do bloqueio combinado.** A condição vira, com um `JOIN barravips.bloqueios b ON b.id = a.bloqueio_id` (padrão que `confirmar_em_execucao` já usa):

  ```sql
  AND GREATEST(a.aviso_saida_em, b.inicio) < now() - interval '45 minutes'
  ```

  Avisar cedo deixa de penalizar: o atendimento só vira `Perdido` 45 min **após o horário combinado** (ou 45 min após o aviso, quando este vem depois do horário).

- **Mantém-se a exigência de Aviso de saída** (`aviso_saida_em IS NOT NULL`). Quem combinou mas nunca avisou segue coberto pelo `timeout_longo` (24h) e pela conversa natural com a IA — esta mudança é cirúrgica, não amplia o gatilho.

- **Tolerância inalterada em 45 min** (literal na query). Com a nova âncora, o valor passa a significar "margem de atraso após o horário combinado", não mais "deslocamento + margem".

- **Cancelamento do bloqueio inalterado:** o `cancel_bloqueio` CTE já libera o slot ao marcar `Perdido` (estado `cancelado`, salvo `em_atendimento`/`concluido`).

## Considered Options

- **Contar só do horário combinado, ignorando `aviso_saida_em`.** Mais simples, mas perde o sinal "avisou que vinha e sumiu" quando o aviso chega depois do horário (cliente atrasado que avisa 17:20 para encontro de 17h). `GREATEST` cobre os dois lados.

- **Manter contagem do aviso, mas armar o relógio só se o aviso vier perto do horário** (ex.: dentro de 45 min antes do início). Preserva a semântica atual com uma guarda, mas é menos direto e ainda mede a coisa errada (deslocamento) em vez do atraso pós-horário.

- **Aumentar a janela fixa (45 → 90 min) ainda contando do aviso.** Paliativo: reduz a frequência do problema sem resolver a raiz (segue desacoplado do horário).

## Consequences

- **`CONTEXT.md` precisa ser corrigido.** Hoje o verbete e a *Flagged ambiguity* afirmam: "timeout interno conta do envio do Aviso de saída (`aviso_saida_em`), não do horário combinado/desejado". Isso passa a estar **errado**; pela regra de precedência (ADR vence CONTEXT), este ADR é a fonte de verdade até a correção do texto.

- **Testes `needs_db` do timeout interno** que assumem contagem a partir do aviso precisam ser atualizados para a nova âncora.

- **Sem migration** — mudança só de query no worker. Deploy exige recarregar o worker (`docker service update --force <stack>_barra-worker`; nunca `restart` em Swarm). §0: deploy em prod só com autorização explícita.

- **Edge case `bloqueio_id` nulo:** no interno em `Aguardando_confirmacao` sempre há bloqueio prévio (criado na transição). Com `JOIN` simples, um atendimento sem bloqueio não dispararia este timeout (cairia no `timeout_longo`); comportamento aceitável.

## Adendo — 11/08/2026: a guarda de reserva do `timeout_longo` ancora em `bloqueios.fim`

Auditoria pré-produção (estreia da 1ª modelo real) encontrou uma interação entre este ADR e o timeout de 24 h que matava atendimento vivo.

O `timeout_longo` protege quem tem reserva em pé com um `NOT EXISTS` sobre `bloqueios`. Essa guarda ancorava no **início** da reserva (`b.inicio > now()`), então a proteção caía **no minuto exato do horário combinado** — justamente quando o cliente chega. Dentro dos 5 min do cron o atendimento virava `Perdido`/`sumiu` e o bloqueio era cancelado; a **Foto de portaria** (interno), o **comprovante de Pix** (externo) e a **Vídeo chamada já paga** (remoto, ADR 0029) chegavam órfãos, sem card para a modelo. O caso é comum, não exótico: o prompt manda cravar encontro para outro dia, e o ônus de confirmar no dia é do cliente — 24 h de silêncio entre combinar e comparecer é o fluxo normal.

**A âncora passa a ser a janela reservada (`b.fim > now()`).** Como `fim > inicio` sempre, a nova guarda é superconjunto estrito da antiga: não cria atendimento imortal — a proteção é limitada pela duração do slot e expira sozinha quando a janela termina, e quem nunca apareceu volta a morrer pelas 24 h de silêncio. Dentro da janela, quem mata o interno continua sendo o timeout de 45 min deste ADR — o único com ressurreição pela foto (ADR 0027).

Sem migration; só mudança de query no worker. Ver a emenda correspondente no ADR 0027 (a ressurreição passou a aceitar as duas fontes de timeout automático).
