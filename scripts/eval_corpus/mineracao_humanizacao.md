# Mineração de humanização — timing, mídia e voz por momento

Três dimensões do comportamento do Vendedor humano que **nunca tinham sido mineradas** (o índice
anterior cobria reação à cotação, perda, empurrão, reengajamento, estilo *agregado* e atos do
funil). Tudo READ-ONLY sobre `corpus.mensagens_raw` (eb01-04, 1.543 threads), pure-SQL/stdlib, sem
crédito (§0). Foco em "parecer humano" — **não** em conversão (a ponte @lid→telefone é irrecuperável;
medir desfecho aqui seria ruído).

> ⚠️ **Nada aqui vai para o prompt sem passar pelo simulador offline (`wf_simulador.js`) + §0.**
> São hipóteses de calibração com lastro de frequência, não mudanças aprovadas.

---

## Frente 1 — Timing / cadência  (ACIONÁVEL)

| Métrica | Valor (corpus humano) |
|---|---|
| Latência 1ª resposta do Vendedor (p25 / **p50** / p75 / p90) | 14s / **40s** / 148s / 472s |
| Bolhas por turno (média / p50 / p90 / máx) | **2,12** / 2 / 4 / 27 |
| Turnos com **1 bolha só** | 40,8% |
| Turnos com **3+ bolhas** | 25,8% |
| Gap entre bolhas consecutivas do Vendedor (p50 / p75) | **4s** / 9s |
| Atividade | 9h–23h, pico 21h, quiet real ~3h–7h |

**Leitura:** o humano (a) demora ~40s para a primeira resposta, (b) fragmenta o turno em ~2 bolhas
(59% das vezes manda 2+), com 4–9s entre elas. O agente hoje responde após o debounce e tende a
1 bolha "completa". Alavancas candidatas: micro-delay antes de responder e quebra em 2 bolhas
curtas em vez de um balão único. (Cadência é comportamento de entrega, calibrável no envio, não só
no prompt.)

## Frente 2 — Mídia  (OBSERVAÇÃO — não cravar contra o prompt)

- Fotos do Vendedor: 2.212 envios em **359 threads** (rajada concentrada, ~6/thread).
- Vídeos do Vendedor: 863 envios em **589 threads** (espalhado, ~1,5/thread).
- Threads com foto **e** vídeo: 167 → **422 threads têm vídeo sem nenhuma foto**.
- Ordem nas 167 com ambos: vídeo antes da foto em 94 (56%), foto antes em 57 (34%).
- Mídia vs cotação (1ª menção de preço): 245 antes / 256 depois (≈ meio a meio).

**Leitura:** `videoMessage` no corpus é **heterogêneo** (prévia, divulgação, apresentação) — 422
threads usam vídeo sem foto alguma, o que não é o caso "fotos → vídeo exclusivo ao vivo" do
CONTEXT.md. Portanto o "vídeo antes de foto em 56%" **não refuta** a regra `foto antes de vídeo`:
medem coisas diferentes. Para mexer na regra seria preciso classificar manualmente o que é cada
vídeo. **Sem ação por ora.**

## Frente 3 — Voz por momento do funil  (ACIONÁVEL — a alavanca mais limpa)

Emoji e vocativo do Vendedor **não são uniformes**; variam por ato (rotulador `rotular_turno`):

| ato | n | emoji % | emoji/msg | vocativo % | len p50 |
|---|---:|---:|---:|---:|---:|
| saudacao | 3.492 | **26,8%** | 0,270 | 29,9% | 10 |
| sondagem | 728 | **1,0%** | 0,010 | 44,8% | 16 |
| cotacao | 2.451 | 11,5% | 0,118 | **13,5%** | 19 |
| desconto | 16 | 6,2% | 0,062 | 56,2% | 33 |
| logistica | 588 | 13,1% | 0,131 | 35,0% | 17 |
| outro | 26.540 | 8,7% | 0,087 | 22,2% | 15 |
| **agregado** | 33.815 | **10,7%** | — | **23,1%** | 15 |

Vocativo dominante: **amor ≫ vida**; `gata` terciário (110 em "outro"); `gato`/`anjo`/`princesa`
praticamente ausentes — confirma a decisão de manter só amor/vida no prompt.

**Leitura:** a estilometria já apontou que o v1 está OVERcalibrado no agregado (emoji ~3×, vocativo
~1,8× o corpus). O recorte por momento mostra **onde** o humano realmente aplica:
- **Emoji = calor de abertura.** 26,8% na saudação, **1,0% na sondagem**, ~11–13% em cotação/
  logística. O humano quase não usa emoji ao sondar; usa para abrir.
- **Vocativo CAI ao falar preço.** 13,5% na cotação vs 23,1% agregado vs 30–56% em
  sondagem/desconto/logística. O humano fica mais **seco e objetivo na cotação** e mais caloroso
  ao sondar/negociar/combinar.

**Alavanca candidata:** instruir o agente a concentrar emoji na abertura/calor (não na sondagem
nem colado ao preço) e a soltar o vocativo na cotação (cotar mais seco). É calibração de
*distribuição*, não de média — o tipo de ajuste que a estilometria agregada não captura.

---

## Reproduzir

```
cd api && DATABASE_URL=<prod> uv run python ../scripts/eval_corpus/voz_por_momento.py
```

As Frentes 1 e 2 são queries SQL agregadas diretas em `corpus.mensagens_raw` (window functions de
latência/burst, `min(ts) FILTER` para ordem de mídia) — ver histórico desta sessão.
