# Conversas reais — matéria-prima da persona da IA

Corpus de conversas **convertidas** (cliente fechou) coletadas direto do WhatsApp das modelos da operação. Serve para calibrar a `persona`, `regras` e `faq` da IA (que são compartilhadas entre todas as modelos — ver `CONTEXT.md` → "IA por modelo"), além de alimentar few-shots quando precisarmos.

## Como usar

- **Transcrições** (`NNN-*.md`) — diálogo anotado por momentos, com timestamps reais e marcadores de mídia. Use para auditar comportamento ponta-a-ponta (ex.: "como uma modelo real responde 'faz anal'?").
- **`padroes-conversas-reais.md`** — destilação por tema (saudação, cotação, recusa, desconto, pré-chegada etc.) com referência cruzada para cada conversa de origem. Use para puxar trechos prontos para `persona.md`, `regras.md`, `faq.md`, ou para construir few-shots.

## Convenção de PII (obrigatória)

Todo dado pessoal foi redatado **agressivamente** porque o material vai para o repo. Marcadores usados:

| Marcador          | Substitui                                    |
| ----------------- | -------------------------------------------- |
| `[MODELO]`        | nome da modelo                               |
| `[MODELO-AMIGA]`  | nome de outra modelo (quando há dupla)       |
| `[CLIENTE]`       | nome do cliente                              |
| `[OPERADORA]`     | nome titular do Pix (conta da agência)       |
| `[ENDERECO]`      | endereço pessoal/operacional completo        |
| `[HOTEL]`         | nome do hotel                                |
| `[APARTAMENTO]`   | número de apto/bloco                         |
| `[TELEFONE]`      | qualquer número de telefone                  |
| `[CPF]`           | CPF (mesmo parcial)                          |
| `[CHAVE-PIX]`     | chave Pix                                    |
| `[VALOR-PIX]`     | valor exato do comprovante                   |
| `[BAIRRO]`        | mantido quando relevante (Barra, Ipanema)    |

Bairro é mantido porque é **sinal útil** (cliente diz "estou em Ipanema" → operação responde "estamos próximos"). Apartamento/endereço completo nunca aparece.

Mídia é colapsada em rótulo: `[FOTO]`, `[VIDEO]`, `[LOCALIZAÇÃO]`, `[COMPROVANTE-PIX]`, `[LIGACAO-VOZ-PERDIDA]`, `[LIGACAO-VIDEO-PERDIDA]`.

## Formato da transcrição

Cada arquivo segue:

```
# NNN — <título descritivo>

Frontmatter curto (origem, modelo-tipo, canal, resultado, observação).

## [tag-do-momento]
HH:MM  MODELO: texto da modelo
HH:MM  CLIENTE: texto do cliente
       ↳ quote: "texto citado pela mensagem"
HH:MM  MODELO: [FOTO]
```

`MODELO:` é quem queremos treinar a IA a imitar. `CLIENTE:` é o lado externo.

Tags de momento usadas: `[abertura]`, `[saudacao]`, `[qualificacao]`, `[cotacao]`, `[inclusoes]`, `[recusa-pratica]`, `[localizacao]`, `[desconto]`, `[confirmacao]`, `[pre-chegada]`, `[chegada-portaria]`, `[atraso]`, `[dupla]`, `[upsell-pernoite]`, `[upsell-videocall]`, `[pix]`, `[bilingue]`.

## Material bruto

Os screenshots/screen recordings originais ficam em `docs/modelos/` (gitignored em produção — manter local). Os frames intermediários extraídos dos `.mp4` foram apagados depois da reconstrução.
