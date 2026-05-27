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


# Mapa BCP-47 → nome em português. Expor `pt-BR`/`en-US` cru ao LLM dilui o tom (a Bia não fala
# "BCP-47") e gasta tokens com ruído técnico. Códigos desconhecidos viram o próprio código.
_NOMES_IDIOMAS = {
    "pt-BR": "português", "pt-PT": "português", "pt": "português",
    "en-US": "inglês", "en-GB": "inglês", "en": "inglês",
    "es": "espanhol", "es-ES": "espanhol", "es-AR": "espanhol",
    "fr": "francês", "fr-FR": "francês",
    "it": "italiano", "de": "alemão",
}


def _idioma_humano(codigo: str) -> str:
    return _NOMES_IDIOMAS.get(codigo, codigo)


_env.filters["brl"] = _brl
_env.filters["idioma_humano"] = _idioma_humano


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
    """FAQ versionada (`faq.md` plano, docs/agente/03 §3.2). Idêntico para todas — entra no
    BP_GERAL fundido junto de persona+regras (ver `render_prefixo_geral`)."""
    return _env.get_template("faq.md").render()


def render_prefixo_geral(desconto_max_pct: float | None = None) -> str:
    """BP_GERAL fundido — persona+regras+FAQ num único bloco system byte-idêntico p/ todas.

    Antes eram 2 blocos system separados (persona+regras / FAQ), mas ambos têm o mesmo perfil
    (geral, TTL igual, mudam só por deploy) e consumiam 2 dos 4 breakpoints disponíveis. Fundir
    libera 1 breakpoint p/ o cache da janela de mensagens (`agente/llm.py:marcar_cache_na_penultima`).

    Caller único: `prepare_context.py`. Testes que precisam reproduzir o conteúdo do bloco geral
    devem chamar esta função (não montar a string fora — risco de byte-drift).
    """
    return f"{render_persona(desconto_max_pct)}\n\n{carregar_faq()}"


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
