---
status: accepted
amends: ADR-0030 (reabre a alternativa "multiplicador por fetiche" que o 0030 deixou em aberto)
---

# ADR-0035 — Fetiche "por pessoa" (casal/menage) dobra o pacote

## Contexto

O ADR-0030 fixou o preço de todo fetiche pago como o **preço-hora efetivo do pacote vendido**
(`preco_tabela ÷ horas`), uniforme entre fetiches, e **rejeitou por ora** um multiplicador por
fetiche — mas registrou o gatilho de reabertura: *"reabrir se aparecer um fetiche que realmente
precise valer mais que os outros"*.

Na revisão da mecânica de preço com o dono do domínio (2026-07-23), esse caso apareceu. Existem
**dois regimes** de fetiche, não um:

- **Fetiche-ato** (inversão, golden shower, etc.): soma **1 hora do serviço**, uma vez — o
  preço-hora do pacote. É o regime do ADR-0030 e continua correto.
- **Fetiche por-pessoa** (casal — o cliente traz um acompanhante — e menage): é cobrado **por
  pessoa**. São 2 pessoas, então **dobra o pacote inteiro**, não soma só 1 hora.

Exemplo (serviço a R$100/h): 3h = R$300. Com inversão (ato) → +R$100 = R$400. Com casal
(por-pessoa) → +R$300 = R$600. Em **1h os dois coincidem** (o pacote de 1h é igual ao preço-hora),
o que explica por que o 0030 não notou a diferença — todos os exemplos daquela reunião eram de 1h.

Isso também resolve a contradição viva entre `CONTEXT.md` (verbete Menage: "dobro do pacote"),
`regras.md.j2:194` ("mesma conta, sem tabela especial") e a migration
`20260720233000_menage_pago_correcao_dado` ("não existe multiplicador especial 'dobro'"): a leitura
correta é **dobra o pacote inteiro**, e as três fontes que dizem o contrário serão corrigidas.

## Decisão

- **Novo regime "por pessoa"** para o fetiche pago: quando ligado, o extra é o **pacote inteiro**
  (`preco_extra = preco_tabela`), não o preço-hora. Equivale a 2 pessoas (o pacote base + 1
  acompanhante). **Fixo em 2** — trio/grupo é raro e a IA **escala** em vez de cotar sozinha.
- **Flag no catálogo GLOBAL de fetiches** (`barravips.fetiches.cobra_por_pessoa boolean`), não em
  `modelo_fetiches`: ser "por pessoa" é propriedade do fetiche, igual para todas as modelos (só o
  incluso/pago é por-modelo). Curada por Fernando. Marcados na migration: **Casal** e **Menage**.
- **`calcular_preco_extra_fetiche` ganha `cobra_por_pessoa` (default `False`)** — retrocompatível:
  o regime ato do ADR-0030 é o default, o por-pessoa é opt-in pela flag lida no registro do
  atendimento (`dominio/atendimentos/routes.py:adicionar_fetiche`).
- Mantém-se do ADR-0030: o valor não é gravado por modelo, é calculado do pacote vendido; não
  auto-soma o Valor final (entra só no breakdown); desconto de fechamento incide sobre o pacote.

## Alternativas rejeitadas

- **Manter tudo em preço-hora (status quo do ADR-0030).** Rejeitado — subcobra casal/menage em
  qualquer duração > 1h (o dono do domínio confirmou que dobra por pessoa).
- **Multiplicador numérico livre por fetiche (×N).** Rejeitado por ora — todos os casos concretos
  são 2 pessoas (dobra); N>2 a IA escala. Um booleano cobre o pedido sem grau de liberdade extra.
- **Flag por modelo (`modelo_fetiches`).** Rejeitado — "por pessoa" não varia por modelo; é do
  fetiche. Guardar por-modelo abriria divergência sem ganho.

## Consequências

- Migration `20260723064620_fetiche_cobra_por_pessoa.sql`: adiciona a coluna e marca Casal/Menage.
- **Fixes de system prompt do agente (rodada seguinte, ainda não feitos):** a tabela renderizada
  em `fetiches.md.j2`/`persona.py:render_fetiches` precisa separar ato de por-pessoa (hoje trata
  todos como ato), e a conduta em `regras.md.j2:194` (`<menage>`) e `:45` precisa refletir "dobra o
  pacote". Até lá, o registro/breakdown já dobra, mas a **fala da IA ainda cota preço-hora** — por
  isso o deploy só vale com a rodada de prompt junto.
- `CONTEXT.md` (verbetes Fetiche/Menage) a ajustar para descrever os dois regimes.
