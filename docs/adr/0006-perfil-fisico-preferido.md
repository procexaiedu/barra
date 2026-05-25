# Perfil físico preferido do cliente

A operação quer registrar e enxergar o **perfil físico preferido** do cliente (loira,
morena, ruiva, negra, asiática) para fechar a "persona" do cliente — junto com ticket
médio, localização e programas. Há duas leituras: a **declarada** (informada por Fernando)
e a **calculada** (derivada do histórico de fechados: "consumiu 6 ruivas e 2 loiras"). A
calculada exige classificar as modelos por tipo físico, o que hoje não existe. Ver termo em
`CONTEXT.md`.

## Decisões

- **Eixo único, lista plana.** Um único conceito "tipo físico" com uma lista plana, em vez
  de eixos normalizados (cor de cabelo + etnia + biotipo). Espelha como a operação fala
  ("ele prefere ruiva") e torna o cálculo inequívoco. A ambiguidade de "morena"
  (cabelo vs pele) dissolve-se: no eixo único ela é só um rótulo de balde usado de forma
  consistente. Biotipo (sarada/plus) fica **de fora** de propósito.
- **`perfil_fisico_enum` no Postgres** `('loira','morena','ruiva','negra','asiatica','outra')`.
  Slugs ASCII como os outros enums; rótulos acentuados/respeitosos só no front
  (`Loira, Morena, Ruiva, Negra, Asiática, Outra`). `outra` = classificada mas nenhuma destas
  (distinto de NULL = ainda não classificada).
- **Modelo recebe 1 valor; cliente declara N.** `modelos.tipo_fisico perfil_fisico_enum NULL`
  (sem backfill — modelos existentes nascem NULL). `clientes.perfis_preferidos
  perfil_fisico_enum[] NOT NULL DEFAULT '{}'` (array vazio = sem preferência; nenhum valor de
  enum próprio para "sem preferência").
- **Preferência calculada = breakdown puro, não rótulo inferido.** Conta só atendimentos
  `Fechado` (= efetivamente "consumiu"), agrupa por `modelo.tipo_fisico`, conta sessões,
  ordena desc. **Não** declara um vencedor ("prefere X") — o cliente reserva quem está
  disponível/cabe no bolso, não pura preferência, e inferir um rótulo afirmaria mais do que o
  dado sustenta. O humano lê a distribuição.
- **Cobertura explícita.** O breakdown inclui a contagem de fechados com modelo NULL como
  "não classificadas: N". Sem isso, "ruiva 6" parece forte escondendo 10 fechados de modelos
  não classificadas enquanto o cadastro amadurece.
- **Dado global do cliente, exclusivo do painel/Fernando.** A preferência (declarada e
  calculada) vive no nível do **cliente** (cross-modelo) e é manipulada/lida apenas no painel.
  A **IA conversacional por modelo nunca lê o breakdown** — seria agregação cross-modelo,
  violando o isolamento por par cliente-modelo do `CONTEXT.md` — **nem escreve** a preferência.
  A leitura/escrita "em linguagem natural" do plano é da **IA Admin (P1)**, que não existe no
  P0; fica adiada.
- **Filtro só pela declarada, semântica OR, sem toggle.** Lista de clientes filtra com
  `perfis_preferidos && ARRAY[...]::perfil_fisico_enum[]` (overlap). Sem AND/OR exposto na UI —
  AND quase nunca é o que se quer para preferências, e o toggle é configurabilidade não pedida.
- **Lado das modelos: form + badge, sem motor.** Campo `tipo_fisico` no criar/editar modelo e
  badge do tipo no detalhe/lista (Fernando vê a cobertura). **Fora:** filtro de modelos por
  tipo e motor de "recomendação de modelo" (essa é a visão de persona, não uma entrega).

## Considered Options

- **Taxonomia multi-eixo** (cor_cabelo + etnia + biotipo): mais "correto" e desfaz a
  ambiguidade de "morena", mas ninguém pediu rastrear três eixos e o cálculo viraria
  "preferência por eixo" (qual exibir?). Rejeitado — complexidade especulativa.
- **Tabela de lookup** (`perfis_fisicos` editável em runtime) ou **text + constante no app**:
  o lookup deixaria Fernando criar categorias sem deploy, mas adiciona junção N:N e joins, e
  nenhum outro lookup assim existe no projeto. Rejeitado a favor do enum, alinhado à convenção
  dominante; o custo é que evoluir a lista é migration manual.
- **Rótulo inferido** ("prefere ruiva" acima de um limiar): mais "pronto", mas exige calibrar
  limiar e arrisca afirmar preferência que é só disponibilidade. Rejeitado.
- **Filtro com toggle AND/OR** (lê o plano ao pé da letra): rejeitado por ergonomia/escopo.
- **Ignorar modelos NULL em silêncio no breakdown**: mais limpo visualmente, mas engana
  quando a cobertura é baixa. Rejeitado.
- **IA conversacional captura/lê a preferência**: violaria o isolamento por par (modelo B
  leria preferência derivada do histórico com modelo A). Rejeitado; adiado para a IA Admin (P1).

## Consequences

- A lista v1 está **fechada e decidida aqui**: `loira | morena | ruiva | negra | asiatica | outra`.
  Não aguarda aval externo — `outra` absorve o long tail (indígena, parda etc.) sem criar baldes
  sobrepostos. Categorias como `branca` (colide com `loira`/`ruiva`), `parda` (colide com
  `morena`/`negra`) e `oriental` (sinônimo de `asiatica`) ficam **fora** de propósito: reintroduzem
  a sobreposição que torna o breakdown ambíguo. Evoluir depois é `ALTER TYPE ADD VALUE` (barato);
  remover/renomear exige recriar o tipo — por isso o conjunto enxuto.
- Sem backfill das modelos, o breakdown nasce parcial e a linha "não classificadas" carrega o
  peso até o cadastro amadurecer.
- A migration `infra/sql/NNNN_perfil_fisico.sql` (enum + ALTER em `modelos` e `clientes`) entra
  no repo e é aplicada **à mão** no prod self-hosted — `make migrate` lá aplicaria seeds.
- O cálculo entra na query de `ClienteDetalhe` (`/crm/clientes/{id}`), que já é uma agregação
  cross-modelo do painel — consistente com "dado exclusivo do painel".
- O front precisa de um seletor multi-valor (não há nativo); reusa o padrão de chips toggle do
  `DetalheCliente` num `SeletorPerfis`, e o `Combobox` existente para o valor único da modelo.
- O guardrail de isolamento deve ser respeitado quando a IA Admin chegar (P1): ela opera no
  escopo global (Fernando↔IA) e pode tocar o campo; a IA por modelo, nunca.
