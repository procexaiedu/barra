"""Ferramentas (tools) do agente LangGraph.

Catalogo P0 (4 tools): consultar_agenda, registrar_extracao, enviar_midia, escalar.
Ver docs/agente/04-tools.md. O Pix de deslocamento NAO e tool: virou side-effect
deterministico da extracao (externo sem cliente_busca + horario -> Aguardando_confirmacao
solicita o Pix; ver `dominio/atendimentos/service.py:_solicitar_pix_deslocamento_se_aplicavel`).

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

from .escalada import escalar
from .extracao import registrar_extracao
from .leitura import consultar_agenda
from .midia import enviar_midia

# Constante de modulo congelada, ordem fixa (invariante de prefixo -- agente/CLAUDE.md):
# tools = posicao 0, byte-identico p/ TODAS as modelos. Proibido build_tools(modelo) ou
# subsetting por modelo. M1 registra consultar_agenda (unica de leitura, 04 §2.2); M3 as
# tools de escrita (registrar_extracao, escalar); M5e entra com enviar_midia ANTES de escalar.
# Ordem canonica de 04 §4: leitura primeiro, escrita depois, `escalar` por ULTIMO. As tools
# sao bindadas cruas (schema function-calling OpenAI) no DeepSeek, que cacheia o prefixo automatico.
TOOLS: list[BaseTool] = [
    consultar_agenda,
    registrar_extracao,
    enviar_midia,
    escalar,
]

# Erros RECUPERAVEIS (doc oficial `tool-use` "Handling Tool Results"): as tools levantam
# ToolException e, com handle_tool_error=True, o BaseTool a converte em ToolMessage com
# status="error" -> `is_error: true` no tool_result da Anthropic, mantendo o TEXTO da excecao
# como conteudo (a instrucao de recuperacao chega ao modelo). O prefixo "ERRO: " e mantido de
# proposito: o coordenador (workers/coordenador.py) o usa p/ descartar o texto de AIMessages
# cujo tool_call falhou. Excecoes INESPERADAS (DB, bug) NAO sao ToolException e continuam
# estourando o turno (o ToolNode do langgraph so trata erro de args e re-levanta o resto).
for _tool in TOOLS:
    _tool.handle_tool_error = True
