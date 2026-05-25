"""Ferramentas (tools) do agente LangGraph.

Catalogo P0 (5 tools): consultar_agenda, registrar_extracao, pedir_pix_deslocamento,
enviar_midia, escalar. Ver docs/agente/04-tools.md.

NAO e tool: o pin de endereco do fluxo INTERNO e side-effect deterministico da
transicao interno -> Aguardando_confirmacao (decisao grilling 2026-05-23, 04 §3.1) --
um pin (`/message/sendLocation`) e estruturado e a IA nao o expressa como texto, entao
o sistema o despacha de qualquer forma. `registrar_extracao_ia` sinaliza `enviar_pin=True`
e o wrapper enfileira `evolution:card {tipo: loc_pin}`; um worker dispara o sendLocation
usando `barravips.modelos.{latitude, longitude, endereco_formatado}` (Places Autocomplete
via UI -> PATCH /modelos/{id}; ver `dominio/modelos/routes.py:prompt_preview` e
`infra/sql/0028_modelos_endereco_geo.sql`). Para EXTERNO, citar apenas
`localizacao_operacional` (bairro/cidade) -- nao enviar pin.
"""

from langchain_core.tools import BaseTool

from .leitura import consultar_agenda

# Constante de modulo congelada, ordem fixa (invariante de prefixo -- agente/CLAUDE.md):
# tools = posicao 0, byte-identico p/ TODAS as modelos. Proibido build_tools(modelo) ou
# subsetting por modelo. M1 registra consultar_agenda (unica de leitura, 04 §2.2); M3 as
# tools de escrita (registrar_extracao, pedir_pix_deslocamento, enviar_midia, escalar).
TOOLS: list[BaseTool] = [consultar_agenda]
