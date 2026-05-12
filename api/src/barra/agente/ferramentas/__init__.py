"""Ferramentas (tools) do agente LangGraph.

Ferramentas pendentes — adicionar quando o agente for desenvolvido:

- `enviar_localizacao(atendimento_id)`: dispara `/message/sendLocation` no
  Evolution usando `barravips.modelos.{latitude, longitude, endereco_formatado}`.
  Aplicável APENAS no fluxo INTERNO (cliente vai à modelo), na transição para
  `Aguardando_confirmacao`. Persistidos via Places Autocomplete (UI -> PATCH
  /modelos/{id}); ver `dominio/modelos/routes.py:prompt_preview` e
  `infra/sql/0028_modelos_endereco_geo.sql`. Para EXTERNO, citar apenas
  `localizacao_operacional` (bairro/cidade) — não enviar pin.
"""
