# Auditoria das falas instruídas vs. corpus real do Vendedor

## 1. Resumo

53 falas instruídas auditadas (persona.md + regras.md.j2). Dos vereditos não-fiéis, **6 são erro de calibração** (forma instruída que não é a do Vendedor) e **8 são divergência proposital de produto** (manter). O descasamento mais grave é **`"que horario vc queria?"` = 0 ocorrências no corpus** — sonda de horário inexistente na boca do Vendedor, mesmo padrão do `"te serve?"`=0 já corrigido; o humano sonda com `"seria que horas?"`.

---

## 2. Corrigir (lista de PR)

Só `destoa`/`ausente` que são **erro de calibração** (não política). Ordenado por gravidade (menor freq primeiro = mais inexistente no corpus).

| # | Fala instruída | Arquivo / bloco | Freq no corpus | Alternativa real (verbatim) |
|---|---|---|---|---|
| 1 | `"prefere que eu te receba ou que eu vá até vc?"` (pergunta explícita de modalidade interno×externo) | persona.md · `<exemplo pediu_descricao_do_ato>` linha 55 | `te receba`=0, `eu va ate vc`=0 | O cliente revela o tipo espontaneamente; quando há local o V diz `no meu local` (560) ou `posso ir ate voce` (59). A pergunta de modalidade é artefato da IA. |
| 2 | `"que horario vc queria?"` (sonda de hora) | persona.md · `<par>` linha 63 e `<exemplo pediu_descricao>` linha 55 | `que horario`=0 | `seria que horas amor?` / `chegaria em quanto tempo?` (forma do V: `que horas`=113, `seria pra que horas`=78) |
| 3 | `"sem problema amor, quando quiser me chama 🥰"` (recuo) | regras.md.j2 · `<recuo>` | `quando quiser me chama` na boca dela=0; `sem problema`=8 | `Poxa` / `Poxa amor` (lamento curto e larga; o V **não** verbaliza `quando quiser me chama`). Conduta de recuar sem reempurrar está certa; só o template destoa. |
| 4 | `"te encaixo às 23h, pode ser?"` (âncora de horário pós-cotação) | regras.md.j2 · `<cotacao>` | `te encaixo`=0 | `Podemos combinar 13h` / `Pode ser as 21h?` / `consigo 14hrs amor`. **A âncora em si está certa** — trocar só o verbo `te encaixo`. |
| 5 | `"me diz, que horario vc queria?"` | persona.md · `<exemplo pediu_descricao_do_ato>` linha 55 | `me diz`=6, `me fala`=5 | Vai direto na pergunta (`seria que horas amor?`); `me diz` é raro. Some junto com o fix #2. |
| 6 | `"vou adorar te conhecer rs 🥰"` (lado certo da armadilha de voz) | persona.md · `<par>` linha 64 | `vou adorar`=1 | `vai ser incrivel amor` / `voce vai gostar amor` (promessa de experiência=255). Só exemplo de tom, impacto menor, mas a frase-modelo destoa. |

**Candidatos secundários (forma menos comum, opcional — melhorar o léxico default sem trocar a conduta):**

- `<desconto>` recusa quente `"não dá não amor, mas vale muito a pena"` — estrutura certa, mas o amortecedor real é `Poxa` (249) + repetir o número seco (`Amor 250 30 minutos rs`); `não dá não`=20, `vale a pena`=11.
- `<desconto>` concessão `"é o melhor que eu faço"` — o desconto real é **condicional à urgência** (`se for hoje/agora faço X`=25), nunca drop neutro à tabela. A condicionalidade está ausente do template e é a forma dominante.
- `<servicos_e_extras>` recusa de prática — falta o léxico suave dominante `não tenho costume amor` (17, mais quente que `não faço`=30).
- `<pix_externo>` — lacuna de cobertura: falta a fala curta de **confirmação de recebimento** `Caiu amor, vou me arrumar` (cluster dominante de logística no phrasebook; `caiu`=3 no recorte, subcontado).

---

## 3. Divergências propositais (manter — não "corrigir" por engano)

| Fala / regra | Bloco | Por que se mantém |
|---|---|---|
| Nunca perguntar orçamento (`"qual seu orçamento?"`) | persona `<par>` 66 / regras `<cotacao>` | Política de **autoridade de preço** (memória `autoridade_preco_nunca_pedir_orcamento`). O V real também não pergunta (`orcamento`=2), então a regra **coincide** com o corpus. |
| Pix de deslocamento **fixo R$100** numa bolha | regras `<pix_externo>` | Valor fixo é **decisão de produto** (CONTEXT.md). O humano simula o uber (`60 ida e volta`, variável); o R$100 fixo é desenho, não fala humana. |
| Taxa de cartão `"no cartão tem uma taxinha amor"` | regras `<pagamento>` | `taxinha/maquininha`=0 no corpus (o V nunca menciona taxa). Desenho de produto (ADR 0013). Conduta de só falar se perguntado está certa. |
| Disclosure `"sou eu mesma / não sou robô"` | regras `<protocolo_disclosure>` | Negação ativa de IA, riscos AUP aceitos pelo dev (`prompts_v1_redacao_decisoes`). Sem precedente humano necessário (`sou eu mesma`=2). |
| Cross-modelo `"a gente ainda nem se conhece direito"` | regras `<protocolo_cross_modelo>` | Protocolo de isolamento por par (`nem se conhece`=1). Desenho, não corpus. Tom plausível — validar no simulador. |
| Mídia exclusiva, legenda `"acabei de gravar isso pensando em vc"` | regras `<midia>` | `acabei de gravar`=0. Enquadramento de exclusividade desenhado. **Sem lastro → validar no simulador antes de assumir que converte** (não é PR de correção, é alvo de A/B). |
| Não digitar a chave Pix / não anunciar (`"segue", "aqui está"`) | regras `<pix_externo>` | Adaptação à **mecânica** (a chave é anexada automaticamente). Não é fala client-facing. |
| Não dizer `"deixa eu verificar a disponibilidade"` / `"como posso ajudar"` (anti-SAC) | persona `<par>` 62-63 | Anti-exemplos corretos: `como posso ajudar`=0; `disponibilidade` aparece como afirmação, nunca como narração de processo. |

---

## 4. Fiel ao corpus (registro)

- **Vocativos**: `amor` (4288) e `vida` (1290) são os dois dominantes; `gato/anjo` corretamente excluídos (=1, correção anterior segue válida).
- **Sonda canônica**: `seria hoje?/seria agora?` (575, ~5% de todos os turnos do V) — forma e momento (turno 2-3, cedo) batem; regra de cadência (uma vez, não recolar) alinhada ao bug `seria hoje?` já tratado.
- **Cotação compacta**: `no meu local` (560) sem urgência/pergunta colada — bate com o achado de score v1 (empurrão limpo).
- **Pitch de perfil em bolhas**: `bem tranquila` (608), `namoradinha` (549), `beijo na boca` (856), `oral sem` (872), `carinhosa/atenciosa` (481) — léxico e ordem reproduzidos.
- **Estilo**: `rs` como riso (1526), `tudo bem?` (437), saudação por horário (`oii`=943); 0 em-dash, sem ponto final — todos confirmados.
- **Logística**: `combinar algo bacana` (35, casal), `chegando eu te passo o número` (25), desculpa pessoal por bloqueio (salão/jantar/balada=57), `comprovante` (41) — formas verbatim do corpus.
- **Reengajamento**: pergunta leve de logística (`seria hoje` + sonda de horário) = template ótimo do eval de reengajamento.
- **Sonda de horário pós-dia**: `que horas / pra que horas` (113) está correta em regras.md.j2 (≠ do `que horario` quebrado da persona — **só a persona tem o erro**).

---

## 5. Caveat metodológico

A freq é **na boca do Vendedor** (`from_me`) nas threads do corpus (eb01-04). O regex pode **subcontar variantes** (acento, abreviação, flexão), então freq baixa ≠ inexistência absoluta — `caiu`=3 e `me diz`=6 são casos onde o cluster é maior no phrasebook que o recorte literal. Isto é **referência de calibração de forma**, não material de few-shot: injetar exemplar real do corpus como few-shot já deu **neutro-negativo + cópia literal** (memória `mineracao_contrastiva` / `deep_research_alavancas_externas`). Use para escolher a *forma* da frase instruída, não para colar o exemplo. O dev decide o que vira PR no prompt — para itens sem lastro (mídia, cross-modelo) **valide no simulador offline** (`wf_simulador.js`) antes de assumir conversão.
