# Docs de domínio

Como as skills de engenharia devem consumir a documentação de domínio deste repo ao explorar o código.

Layout: **single-context** — um `CONTEXT.md` na raiz + `docs/adr/`.

## Antes de explorar, leia

- **`CONTEXT.md`** na raiz — vocabulário da operação Elite Baby, com os `_Avoid_` de cada verbete.
- **`docs/adr/`** — leia os ADRs que tocam a área em que você vai mexer. Não há ADR por contexto; todos vivem na raiz de `docs/adr/`.

Se algum desses arquivos não existir, **siga em silêncio**. Não sinalize a ausência nem sugira criá-los de antemão. A skill `/domain-modeling` (alcançada via `/grill-with-docs` e `/improve-codebase-architecture`) os cria sob demanda, quando um termo ou uma decisão de fato se resolve.

## Estrutura de arquivos

```
/
├── CONTEXT.md
├── docs/
│   ├── adr/
│   │   ├── 0001-estrutura-monorepo.md
│   │   └── 0035-fetiche-por-pessoa-dobra-o-pacote.md
│   └── dominio/                 ← desdobramentos de verbetes do CONTEXT.md
├── api/
└── interface/
```

## Use o vocabulário do glossário

Quando sua saída nomear um conceito de domínio (título de issue, proposta de refactor, hipótese, nome de teste), use o termo como definido no `CONTEXT.md` — **Atendimento**, **Conversa cliente**, **Coordenação por modelo**, **Handoff**, **Fetiche**. Não derive para sinônimos que o glossário explicitamente evita (o campo `_Avoid_` de cada verbete lista os erros conhecidos).

Cuidado com a colisão do repo: **Modelo** (a profissional) ≠ `modelos.py` (DTOs Pydantic) ≠ o *model* do LLM.

Se o conceito que você precisa ainda não está no glossário, isso é um sinal — ou você está inventando linguagem que o projeto não usa (reconsidere), ou há uma lacuna real (registre para o `/domain-modeling`).

## Sinalize conflitos com ADR

Os ADRs vencem o `CONTEXT.md` onde divergirem (regra de precedência do próprio `CONTEXT.md`). Se sua saída contradiz um ADR vigente, exponha isso em vez de sobrescrever em silêncio:

> _Contradiz o ADR-0027 (ressurreição do interno pela Foto de portaria) — mas vale reabrir porque…_
