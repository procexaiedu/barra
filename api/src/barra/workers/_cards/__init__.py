"""Render Jinja2 dos cards do grupo de Coordenação (não passam por humanização, 05 §6).

Templates `*.md.j2` ficam neste diretório, no mesmo padrão de `agente/persona.py`.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent),
    # Cards são texto puro de WhatsApp; markdown não precisa de escape de HTML.
    autoescape=select_autoescape(disabled_extensions=("md.j2",)),
    keep_trailing_newline=True,
)


def render_card(nome: str, /, **ctx: Any) -> str:
    """Renderiza o template `{nome}.md.j2` com as variáveis do card."""
    return _env.get_template(f"{nome}.md.j2").render(**ctx)
