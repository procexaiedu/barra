# Exports do replay do Grupo financeiro

Cada pasta aqui é **uma semana de um grupo**, no formato do export do WhatsApp (iOS), pronta para
entrar inteira pela porta única:

```bash
TEST_DATABASE_URL=... uv run python -m evals.grupo_financeiro.replay \
    --export evals/grupo_financeiro/exports/<pasta> --llm
```

O export **real** (`WhatsApp Chat - Modelo Yasmin Ruiva_ financeiro 🤑.zip`, na raiz do repo)
continua sendo o padrão do comando e a fonte de verdade da conduta. As pastas daqui não o
substituem: elas cobrem o que uma semana só não mostrou.

| pasta | o que ela exercita |
|---|---|
| `parceria_e_correcao` | duas modelos no mesmo atendimento, resposta coletiva ("Foi tudo pix amiga"), **correção por quote**, pergunta mínima respondida com o valor solto, endereço ditado no meio da conversa |
| `fechamento_parcial_e_sobra` | R$ 2.100 em pix fechados em duas partes, a **mesma foto reenviada** (dedup), sobra virando crédito da modelo, cobrança da agência registrada e quitada, e os dois buracos conhecidos (anulação por texto, pedido de fechamento em fala livre) |
| `grupo_barulhento` | o dia a dia: bom dia, figurinha, piada, combinado com cliente. O que se mede é o **silêncio** — e três armadilhas: anúncio repetido, chave Pix ditada por quem não é a modelo, e um valor solto ("3 dias de anuncio deu 420") logo antes da cobrança de verdade |
| `perfil_novo_e_cadastro` | a mulher nova sob um perfil que já existe — "Perfil duda/ bebel" (o caso real da "fran loira") contra o mesmo nome sozinho, a resposta do gestor que deveria virar cadastro, o typo que não pode zerar a interseção e duas mulheres diferentes na mesma linha |
| `cobranca_gemea_e_comprovante` | cobrança da agência com o **mesmo valor** de uma venda em pix: o comprovante cabe nos dois eixos e tem que ficar retido. Mais a foto reenviada nesse estado, a resposta em fala livre ("esse foi do site") e um fechamento para chave fora da lista |
| `renovacao_da_cobranca` | a cobrança semanal do portal, sempre pelo mesmo valor, e a modelo reenviando na segunda semana **a foto da primeira**. Mede se a mesma prova pode quitar duas dívidas |
| `madrugada_e_anulacao` | o relógio do grupo: venda às 23h47 respondida às 00h36 do dia seguinte. Áudio sem transcrição, correção por quote sobre venda de modelo convidada, o cliente que não apareceu (anulação por texto) e o rateio "cada uma" |

## Os invisíveis do export do iOS

Os `_chat.txt` daqui trazem os mesmos caracteres que o WhatsApp escreve de verdade: `~` + U+202F
no autor (`~ Cris`), U+00A0 e U+2011 no telefone (`+55 11 98765‑1234`), U+200E antes do colchete
e do `<anexado:`. Isso não é capricho de fidelidade — o autor é a **identidade** da mensagem no
replay, e um export escrito com espaço comum não exercita o mesmo caminho que a produção. Os três
exports mais antigos ainda usam espaço comum no autor; até 16/08 essa era a única grafia coberta,
e por isso o `~ Parcerias` do export **real** nunca casava com a lista de gestoras: toda mensagem
delas entrava carimbada com o número da modelo, e a tranca da chave Pix (ticket 12) era medida ao
contrário. Export sintético novo nasce com os invisíveis.

## O `cenario.json`

É o cadastro que a operação teria no painel naquela semana — o replay é closed-world, então quem
não está aqui não vira venda:

```json
{
  "dona": "Sabrina",
  "elenco": { "Sabrina": ["sabrina", "sasa"] },
  "gestoras": ["~ Rê"],
  "chave_da_casa": "a7c3e910-...",
  "nome_do_grupo": "Modelo Sabrina/ financeiro",
  "numero_da_modelo": "5571988881122"
}
```

`numero_da_modelo` **tem que ser o número que o `_chat.txt` mostra**: é ele que separa "a modelo
ditou a chave dela" de "um gestor ditou a chave da casa". Com um número de fantasia, todo cadastro
do replay cai como `de_terceiro` e o replay mede uma conduta que a produção não tem.

## `[[responde:N]]` — a citação que o WhatsApp não exporta

O export do WhatsApp **descarta a citação**: a resposta sai como mensagem solta. Isso deixava a
correção por quote (a escrita mais perigosa do módulo, porque sobrescreve dinheiro já registrado)
sem nenhum roteiro que a exercitasse ponta a ponta. Nos exports sintéticos, uma mensagem pode
começar com o marcador:

```
[04/08/2026, 19:58:44] ~ Vivi: [[responde:8]] na verdade foi 800
```

`8` é o índice (1-based) da mensagem citada, como o replay os numera na saída. O marcador é lido
pelo `chat_export.py` e nunca aparece num export real.

## Comprovantes

As imagens são **sintéticas** e geradas por `gerar_comprovantes.py` (Pillow, Python do sistema).
Comprovante real carrega PII de terceiro e commitar um arquivo é publicá-lo no histórico do git
para sempre — a mesma regra das fixtures dos testes.

Diferente das fixtures, estas são **lidas de verdade** quando o replay roda com `--ocr`: é assim
que se mede o OCR ponta a ponta (valor, data, chave de destino e titular saindo da imagem e
chegando na conciliação).
