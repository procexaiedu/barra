---
status: accepted
---

# Fetiche da modelo

O cliente pediu registrar "o que a modelo faz e o que não faz" — o que ele chamou de "feitiço" e esclareceu ser **fetiche** (o que o cliente pode pedir). Decidimos modelar como um **catálogo global** de fetiches curado no painel + uma marcação **sim/não por modelo**, sem preço próprio (o preço segue em programa+duração), e **expor ao contexto da IA por modelo** — porque, ao contrário do nível e da ficha cadastral, a IA precisa dele para responder "você faz X?" na venda. É o cardápio da própria modelo ("coisa dela"), não dado de cliente, então não fere o isolamento por par.

## Decisões

- **Catálogo global + flag por modelo.** Tabela `fetiches` (lista curada no painel, como `programas`) + `modelo_fetiches (modelo_id, fetiche_id, faz boolean)`. Marcação binária **sim/não** (Fernando confirmou "sim/não"). **Sem preço por fetiche** — preço continua no **Preço de tabela** (programa × duração); o fetiche não é item precificável.
- **Alimenta a IA por modelo.** A lista de fetiches que a modelo **faz** (e os que **não faz**) entra no contexto por-modelo (`agente/nos/prepare_context`, junto de identidade/programas/tipo de atendimento), para a IA responder com naturalidade o que a modelo aceita e recusar o que não aceita sem inventar. É uma das **"coisas dela"** (varia por modelo), não a persona (geral e compartilhada).
- **Eixo próprio, distinto do que já existe.** Não é `tipo_atendimento_aceito` (interno/externo = logística do encontro) nem `programa` (duração+preço) nem ficha cadastral (RG/medidas). Catálogo separado.
- **Exceção deliberada à regra "a ficha não vaza para a IA".** A ficha cadastral (ADR 0007) e o **nível** (ADR/Lane A) são painel-only e a IA nunca lê. O fetiche **é lido pela IA** porque é cardápio de venda, não PII de gestão. Isolamento preservado: é dado da própria modelo, exposto só ao painel e à IA daquela modelo — nunca cruza dado de cliente entre modelos.
- **Novos fetiches nascem "não" para modelos existentes** (sem backfill presumindo que a modelo faz). A ausência de marcação = não faz / indefinido, tratado como "não faz" pela IA.

## Considered Options

- **Estender `tipo_atendimento_aceito` (text[]) com os fetiches.** Rejeitado: esse campo é interno/externo (logística), eixo diferente; misturar polui a semântica e os filtros.
- **Preço por fetiche / "monta a tabela de preços automaticamente"** (premissa da task transcrita). Rejeitado: Fernando confirmou flags sim/não; o preço já é modelado por programa × duração. O fetiche define o cardápio, não o preço.
- **Texto livre por modelo.** Rejeitado: a IA não consulta texto livre com precisão e o admin não cura a lista; catálogo estruturado dá resposta consistente e curadoria central.
- **Painel-only (não enviar à IA), como o nível.** Rejeitado: Fernando confirmou que a IA precisa para vender; é cardápio, não PII de gestão.

## Consequences

- **Tabelas `fetiches` + `modelo_fetiches`** (migration manual no prod self-hosted). Seção sim/não no cadastro/edição da modelo + tela de admin do catálogo global.
- **`agente/nos/prepare_context` (BP3) passa a incluir os fetiches da modelo** (faz / não faz) no contexto por-modelo. Isso muda o conteúdo cacheado por-modelo do prompt (impacto de cache — ver memórias de cache do agente); aceitável.
- **Dado sensível/explícito:** garantir que só aparece no painel e no contexto da IA da própria modelo; nunca em telas públicas nem em agregações cross-modelo.
- **CONTEXT.md** ganha o termo **Fetiche** (com "feitiço" como alias a evitar) e a relação que o distingue do nível/ficha/perfil físico (que a IA não lê).
- Depende da integração da Lane A (cadastro da modelo) por tocar nos mesmos arquivos de cadastro — implementar **depois** que a Lane A entrar, para evitar colisão.
