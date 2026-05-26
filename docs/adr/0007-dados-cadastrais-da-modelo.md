# Dados cadastrais da modelo (ficha pessoal)

A tabela `barravips.modelos` só tinha dados operacionais. A gestão pede a **ficha
cadastral pessoal** da modelo — RG, CPF, endereço residencial, cor de pele, cor de
cabelo, altura e tamanho do pé. O ADR 0006 já introduziu `modelos.tipo_fisico` (eixo
único de venda) que alimenta o breakdown do **Perfil físico preferido** do cliente.
Esta decisão adiciona a ficha cadastral **sem mexer** no `tipo_fisico`, aceitando de
propósito dois conceitos físicos paralelos. Ver termos em `CONTEXT.md`. Não supersede
o 0006 — coexiste com ele.

## Decisões

- **Coexistência, papéis distintos.** `tipo_fisico` (ADR 0006) é o **balde de venda**
  (eixo único, "ele prefere ruiva") e alimenta o breakdown calculado do cliente
  (cross-modelo, painel). A ficha cadastral — `cor_pele`, `cor_cabelo`, `altura_cm`,
  `tamanho_pe`, `rg`, `cpf`, endereço residencial — descreve **quem a pessoa é**
  (gestão), é painel-only e **nunca** alimenta o breakdown do cliente **nem** a
  persona/identidade da IA. Aceitamos a redundância parcial (`tipo_fisico='ruiva'` vs
  `cor_cabelo='ruivo'`) como custo conhecido: são propósitos diferentes (como se vende ×
  quem a pessoa é).
- **Não unificar nem derivar.** Não derivamos `tipo_fisico` de `cor_pele`+`cor_cabelo`.
  O 0006 escolheu eixo único justamente para tornar o breakdown inequívoco; derivar de
  dois eixos reintroduz a ambiguidade de "morena" (cabelo vs pele) que o 0006 dissolveu.
- **Taxonomia dos enums cadastrais** (distintos do `perfil_fisico_enum` do 0006):
  - `cor_pele_enum AS ENUM ('branca','parda','negra','asiatica','indigena','outra')` —
    vocabulário consistente com o `perfil_fisico_enum` (`negra`, `asiatica`) em vez de
    `oriental` (datado) ou `preta`/`amarela` (IBGE); `indigena` explícito; `outra`
    absorve o long tail.
  - `cor_cabelo_enum AS ENUM ('loiro','castanho_claro','castanho_escuro','preto','ruivo','grisalho','colorido','outra')`.
  - Slugs ASCII como os demais enums; rótulos acentuados ficam só no front. `NULL` =
    não preenchido; `outra` = preenchido mas nenhum destes.
- **PII e segurança.** `cpf`/`rg`/endereço residencial são PII sensível. A RLS já fecha
  `barravips.modelos` em Fernando (policy `fernando_full_access` via `is_fernando()`,
  comando ALL); sem multi-user no P0 não há mascaramento por coluna a fazer. Os 9 campos
  entram **só no detalhe** (`obter_modelo`/retorno do POST/PATCH); a listagem (allowlist)
  não os expõe. Não logar valores em texto plano.
- **CPF.** Armazenado sempre como **11 dígitos limpos**. Validação estrita no backend
  (`field_validator` no schema de modelos, reusado por Create e Patch): normaliza
  removendo não-dígitos, exige 11 dígitos, valida os 2 dígitos verificadores e rejeita
  sequências repetidas (`000…`, `111…`). Inválido → 422 (handler do Pydantic); duplicado
  → 409 (`CPF_DUPLICADO`). Unicidade por **índice único parcial**
  `WHERE cpf IS NOT NULL` (permite múltiplos NULL).
- **Endereço residencial: PII mínima.** Guarda só `endereco_residencial_formatado` +
  `place_id_residencial`, **sem** lat/lng — diferente do operacional, que guarda geo para
  cálculo de deslocamento. Reusa `CampoLocalAutocomplete` (já em `components/comum/`),
  descartando lat/lng/localização-curta no handler.
- **Persona intocada nesta entrega.** A identidade da IA (`identidade.md.j2`) **não**
  passa a interpolar nenhum campo cadastral. Se um dia precisar se descrever fisicamente,
  vira task do time do agente e usaria `tipo_fisico`, não a ficha — preservando persona
  geral e o isolamento.

## Considered Options

- **Unificar/derivar `tipo_fisico` de `cor_pele`+`cor_cabelo`** (superseder o 0006):
  rejeitado — reintroduz a ambiguidade do breakdown que o 0006 resolveu e custa refatorar
  feature já shipada.
- **Adiar `cor_pele`/`cor_cabelo`:** rejeitado — a gestão pediu a ficha completa agora, e
  não há colisão real desde que os papéis fiquem separados.
- **Taxonomia da task** (`branca,parda,negra,oriental,outra`): rejeitada — `oriental` é
  datado e inconsistente com o `asiatica` já usado, e não cobre indígena.
- **IBGE puro** (`branca,preta,parda,amarela,indigena,outra`): rejeitado — `preta`/`amarela`
  divergem do vocabulário interno (`negra`/`asiatica`), criando dois termos para a mesma
  coisa no banco.
- **`cor_pele`/`cor_cabelo` na listagem:** rejeitado — duplica visualmente o badge de
  `tipo_fisico` e joga atributo sensível numa lista.

## Consequences

- Dois conceitos físicos convivem; quem lê o schema precisa deste ADR para entender a
  separação. O `CONTEXT.md` ganha uma nota distinguindo **dados cadastrais da modelo**
  (ficha pessoal) × **tipo físico** (venda) × **Perfil físico preferido** (cliente).
- Evoluir os enums depois é `ALTER TYPE ADD VALUE` (barato); renomear/remover exige
  recriar o tipo — por isso o conjunto enxuto e revisado. A taxonomia não passou por
  Rossi; se ele divergir, é adicionar valor (barato) ou recriar (caro).
- A migration `NNNN_modelos_dados_cadastrais.sql` entra no repo e é aplicada **à mão** no
  prod self-hosted (schema-only, sem seeds — `make migrate` lá aplicaria seeds). O script
  `scripts/proxima-migration.ps1` citado na task original **não existe**; o timestamp do
  arquivo é gerado manualmente no padrão `AAAAMMDDHHMMSS_…` dos demais.
- O backfill é nulo: modelos legadas nascem com os 9 campos `NULL`; a UI mostra "—" sem
  regredir.
