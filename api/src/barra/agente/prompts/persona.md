# Persona da modelo

> Bloco cacheado pelo Anthropic (cache_control: ephemeral, TTL 1h).
> Conteúdo virá do perfil cadastrado em `dominio/modelos/`.

<!--
Campos estruturados disponíveis para interpolação (ver
`dominio/modelos/routes.py:prompt_preview` e a tabela `barravips.modelos`):

- nome, idade, idiomas, tipo_atendimento_aceito (já injetados)
- localizacao_operacional (já injetado) — string curta "bairro, cidade"
  usada no fluxo EXTERNO para descrever a área que a modelo cobre.
- endereco_formatado, latitude, longitude, place_id — persistidos via Places
  Autocomplete; ainda NÃO interpolados. Consumir quando a ferramenta
  `enviar_localizacao` do fluxo INTERNO for criada (`agente/ferramentas/`).
-->
