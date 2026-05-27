"""Render dos prompts do agente.

BP1 (persona + regras) e BP2 (FAQ) são GERAIS — byte-idênticos para todas as modelos
(CONTEXT.md "IA por modelo"; docs/agente/03 §1-§3.2). O dado por-modelo (BP3: identidade +
programas) nasce aqui declarado (`IdentidadeModelo`/`render_identidade`) mas só passa a ser
consumido no M2. Templates Jinja ficam em `prompts/`.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from barra.settings import get_settings

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "prompts"),
    autoescape=select_autoescape(disabled_extensions=("md.j2",)),  # markdown não precisa de escape
    keep_trailing_newline=True,
)


def _brl(valor: Any) -> str:
    """Formata valor inteiro em BRL no padrão da persona: `R$1.500` (sem espaço, ponto como
    separador de milhar). `persona.md` `<voz>` exige exatamente esse formato; o default Python
    `{:,.0f}` usa locale americano (`R$ 1,500`) e contradiria a regra."""
    return "R$" + f"{int(valor):,}".replace(",", ".")


_env.filters["brl"] = _brl


@dataclass(frozen=True)
class IdentidadeModelo:
    """Variáveis por-modelo do BP3 (identidade óbvia + operacional).

    Declarado para o M2 (BP3); ainda não consumido no M0.
    """

    nome: str
    idade: int
    idiomas: list[str]
    localizacao_operacional: str | None
    tipos_aceitos: list[str]


@lru_cache(maxsize=8)
def render_persona(desconto_max_pct: float | None = None) -> str:
    """BP1 geral (persona + regras) — sem variáveis por-modelo, idêntico para todas.

    `desconto_max_pct` interpola o bloco <desconto> de `regras.md.j2` (ADR-0004): segue GERAL
    porque é setting global, não por-modelo. None → lê de settings (`desconto_max_pct`).
    """
    pct = get_settings().desconto_max_pct if desconto_max_pct is None else desconto_max_pct
    persona = _env.get_template("persona.md").render()
    regras = _env.get_template("regras.md.j2").render(desconto_max_pct=pct)
    return f"{persona}\n{regras}"


@lru_cache(maxsize=1)
def carregar_faq() -> str:
    """BP2 geral — FAQ versionada (`faq.md` plano, docs/agente/03 §3.2). Idêntico para todas."""
    return _env.get_template("faq.md").render()


def render_contexto_dinamico(**variaveis: Any) -> str:
    """Contexto dinâmico do turno (02 §5) — texto volátil, NÃO cacheável.

    Renderizado a cada turno e concatenado no último HumanMessage pelo prepare_context;
    nunca vira SystemMessage nem leva cache_control (fica fora do prefixo, "stable first,
    volatile last"). As variáveis são resolvidas por queries no prepare_context.
    """
    return _env.get_template("contexto_dinamico.md.j2").render(**variaveis)


def render_identidade(m: IdentidadeModelo) -> str:
    """BP3 por-modelo — identidade óbvia + tipos_aceitos (programas concatenados à parte, §3.3)."""
    return _env.get_template("identidade.md.j2").render(
        nome=m.nome,
        idade=m.idade,
        idiomas=m.idiomas,
        localizacao_operacional=m.localizacao_operacional,
        tipos_aceitos=m.tipos_aceitos,
    )


def render_programas(programas: list[dict[str, Any]]) -> str:
    """BP3 por-modelo — tabela nome/duração/preço (03 §3.3).

    Cada linha é uma combinação (programa/duração) da modelo. O schema real (pós-migrations
    0009/0010) tem duração como entidade própria (`duracoes`): `duracao_nome` vem do JOIN, não
    de `programas.duracao_horas` (coluna removida; a query do §3.3 está desatualizada). A lista
    deve chegar já ordenada de forma determinística (pré-req do cache — agente/CLAUDE.md)."""
    return _env.get_template("programas.md.j2").render(programas=programas)


def render_bp3(identidade: IdentidadeModelo, programas: list[dict[str, Any]]) -> str:
    """BP3 completo por-modelo: identidade + programas concatenados (03 §2.3)."""
    return f"{render_identidade(identidade)}\n{render_programas(programas)}"
