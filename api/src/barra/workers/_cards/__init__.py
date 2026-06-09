"""Render Jinja2 dos cards do grupo de Coordenação (não passam por humanização, 05 §6).

Templates `*.md.j2` ficam neste diretório, no mesmo padrão de `agente/persona.py`. A gramática
única dos cards está em `docs/ux/coordenacao-grupo-ux.md §4`.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from barra.core.moeda import formatar_brl

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent),
    # Cards são texto puro de WhatsApp; markdown não precisa de escape de HTML.
    autoescape=select_autoescape(disabled_extensions=("md.j2",)),
    keep_trailing_newline=True,
    # Blocos de controle (`{% set %}`, `{% if %}`) ocupam linha própria nos templates; sem isto
    # cada um deixaria uma linha em branco no card. trim_blocks/lstrip_blocks os tornam invisíveis.
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["moeda"] = formatar_brl


def render_card(nome: str, /, **ctx: Any) -> str:
    """Renderiza o template `{nome}.md.j2` com as variáveis do card."""
    return _env.get_template(f"{nome}.md.j2").render(**ctx)
