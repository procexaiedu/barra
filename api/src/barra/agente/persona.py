"""Render dos prompts do agente.

BP1 (persona + regras) é GERAL — byte-idêntico para todas as modelos
(CONTEXT.md "IA por modelo"; docs/agente/03 §1-§3.2). O dado por-modelo (BP3: identidade +
programas) nasce aqui declarado (`IdentidadeModelo`/`render_identidade`) mas só passa a ser
consumido no M2. Templates Jinja ficam em `prompts/`.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from barra.settings import get_settings

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "prompts"),
    autoescape=select_autoescape(disabled_extensions=("md.j2",)),  # markdown não precisa de escape
    keep_trailing_newline=True,
)


def brl(valor: Any) -> str:
    """Formata valor inteiro em BRL no padrão da persona: `R$1.500` (sem espaço, ponto como
    separador de milhar). `persona.md` `<voz>` exige exatamente esse formato; o default Python
    `{:,.0f}` usa locale americano (`R$ 1,500`) e contradiria a regra.

    `Decimal(str(valor))` antes do `int` aceita os formatos que chegam do JSONB de idempotência
    (string `"100.00"`, de `settings.pix_deslocamento_valor`) sem o `int("100.00")` crashar."""
    return "R$" + f"{int(Decimal(str(valor))):,}".replace(",", ".")


# Mapa BCP-47 → nome em português. Expor `pt-BR`/`en-US` cru ao LLM dilui o tom (a Bia não fala
# "BCP-47") e gasta tokens com ruído técnico. Códigos desconhecidos viram o próprio código.
_NOMES_IDIOMAS = {
    "pt-BR": "português",
    "pt-PT": "português",
    "pt": "português",
    "en-US": "inglês",
    "en-GB": "inglês",
    "en": "inglês",
    "es": "espanhol",
    "es-ES": "espanhol",
    "es-AR": "espanhol",
    "fr": "francês",
    "fr-FR": "francês",
    "it": "italiano",
    "de": "alemão",
}


def _idioma_humano(codigo: str) -> str:
    return _NOMES_IDIOMAS.get(codigo, codigo)


# Mesmo fuso (America/Sao_Paulo) que o SQL usa para `agora`/`hoje` no mesmo bloco <agenda>
# (prepare_context: `current_timestamp AT TIME ZONE 'America/Sao_Paulo'`). Os datetimes de agenda
# (horario_minimo, bloqueios) chegam aware-UTC do psycopg/proximo_livre — o cálculo roda em UTC
# (comparação com blocos é por instante), mas o cliente lê em horário local. Converter só aqui, na
# fronteira de render, com o MESMO ZoneInfo do âncora: sem isso a hora sai +3h e a IA recusa
# horários válidos da tarde; um offset fixo divergiria do âncora se o DST voltasse.
_FUSO_BR = ZoneInfo("America/Sao_Paulo")


def _brt(dt: datetime | None, fmt: str) -> str:
    """Formata um datetime de agenda em horário de Brasília para o contexto do turno.

    Aware (current_timestamp / proximo_livre preservam o tzinfo da sessão, UTC) é convertido;
    naive é assumido já-local. None vira string vazia (os blocos do template já guardam com `if`)."""
    if dt is None:
        return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone(_FUSO_BR)
    return dt.strftime(fmt)


_env.filters["brl"] = brl
_env.filters["idioma_humano"] = _idioma_humano
_env.filters["brt"] = _brt


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
    # Endereço OPERACIONAL (ponto de encontro: cliente vem até você / te busca de carro). Não é
    # o residencial (`endereco_residencial_formatado`, PII sensível — a IA nunca lê). Default
    # None: modelo sem endereço cadastrado não renderiza a linha.
    endereco_formatado: str | None = None
    # Nome do local do ponto de encontro (ex.: "Hotel Vitória"), do displayName do Google Places.
    # A IA cita junto do endereço no interno. None quando não é estabelecimento nomeado.
    nome_local: str | None = None


@lru_cache(maxsize=8)
def render_persona(
    desconto_degrau_pct: float | None = None, desconto_teto_pct: float | None = None
) -> str:
    """BP1 geral (persona + regras) — sem variáveis por-modelo, idêntico para todas.

    `desconto_degrau_pct`/`desconto_teto_pct` interpolam o bloco <desconto> de `regras.md.j2`
    (ADR-0031: escalada de 2 rodadas — degrau na 1ª contraproposta, teto na 2ª e última): seguem
    GERAL porque são settings globais, não por-modelo. None → lê de settings.
    """
    s = get_settings()
    degrau = s.desconto_degrau_pct if desconto_degrau_pct is None else desconto_degrau_pct
    teto = s.desconto_teto_pct if desconto_teto_pct is None else desconto_teto_pct
    persona = _env.get_template("persona.md").render()
    regras = _env.get_template("regras.md.j2").render(
        desconto_degrau_pct=degrau,
        desconto_teto_pct=teto,
        pix_valor=brl(s.pix_deslocamento_valor),
    )
    return f"{persona}\n{regras}"


def render_prefixo_geral(
    desconto_degrau_pct: float | None = None, desconto_teto_pct: float | None = None
) -> str:
    """BP_GERAL — persona+regras num único bloco system byte-idêntico p/ todas.

    É o prefixo geral global: byte-idêntico entre todas as modelos, ele e o BP_MODELO formam o
    prefixo que o DeepSeek cacheia automaticamente no provider (a disciplina de byte-identidade é
    o que mantém o cache quente).

    Caller único: `prepare_context.py`. Testes que precisam reproduzir o conteúdo do bloco geral
    devem chamar esta função (não montar a string fora — risco de byte-drift).
    """
    return render_persona(desconto_degrau_pct, desconto_teto_pct)


def render_contexto_dinamico(**variaveis: Any) -> str:
    """Contexto dinâmico do turno (02 §5) — texto volátil, NÃO cacheável.

    Renderizado a cada turno e concatenado no último HumanMessage pelo prepare_context;
    nunca vira SystemMessage nem leva cache_control (fica fora do prefixo, "stable first,
    volatile last"). As variáveis são resolvidas por queries no prepare_context.
    """
    return _env.get_template("contexto_dinamico.md.j2").render(**variaveis)


def render_reminder(fase: str | None, nome: str | None = None) -> str:
    """Reminder anti-drift (03 §10) — texto volátil, NÃO cacheável.

    Reinjeta o núcleo da voz perto do fim da janela em conversas longas, em primeira pessoa
    (sem meta-vocabulário tipo "a persona"/"IA"). O prepare_context o prepende ao último
    HumanMessage, dentro de <lembrete_silencioso> (coberto por <instrucoes_meta> em
    regras.md.j2), na cauda volátil — fora do prefixo cacheável.

    `nome` (da modelo, vindo do BP_MODELO) reancora a IDENTIDADE no fim da janela longa, como
    continuidade de self ("você, {nome} — mulher real, no seu WhatsApp"), sem nunca citar
    "IA"/"robô" — mencionar a negação primaria o tópico (white-bear) e poderia AUMENTAR o
    disclosure-leak. Por-modelo/volátil → fica na cauda, nunca no prefixo BP_GERAL byte-idêntico.
    None → o template omite a âncora (comportamento histórico).
    """
    return _env.get_template("reminder.md.j2").render(fase=fase, nome=nome)


def render_aup_saida() -> str:
    """Constituição do output-guard de AUP (ADR 0016 / Etapa 2). Markdown puro, sem variável.

    Prompt PRÓPRIO do judge de saída: NÃO interpola dado por-modelo e NÃO entra em
    BP_GERAL/BP_MODELO/BP_JANELA — logo não afeta o cache hit-rate do chat principal.
    """
    return _env.get_template("aup_saida.md").render()


def render_judge_pos_envio() -> str:
    """Rubrica do judge PÓS-ENVIO (produção assistida, semana 1). Markdown puro, sem variável.

    Prompt PRÓPRIO do judge de telemetria (workers/judge_pos_envio.py): NÃO interpola dado
    por-modelo e NÃO entra em BP_GERAL/BP_MODELO — não afeta o cache hit-rate do chat principal.
    """
    return _env.get_template("judge_pos_envio.md").render()


def render_identidade(m: IdentidadeModelo) -> str:
    """BP3 por-modelo — identidade óbvia + tipos_aceitos (programas concatenados à parte, §3.3)."""
    return _env.get_template("identidade.md.j2").render(
        nome=m.nome,
        idade=m.idade,
        idiomas=m.idiomas,
        localizacao_operacional=m.localizacao_operacional,
        tipos_aceitos=m.tipos_aceitos,
        endereco_formatado=m.endereco_formatado,
        nome_local=m.nome_local,
    )


def render_programas(programas: list[dict[str, Any]]) -> str:
    """BP3 por-modelo — tabela nome/duração/preço (03 §3.3).

    Cada linha é uma combinação (programa/duração) da modelo. O schema real (pós-migrations
    0009/0010) tem duração como entidade própria (`duracoes`): `duracao_nome` vem do JOIN, não
    de `programas.duracao_horas` (coluna removida; a query do §3.3 está desatualizada). A lista
    deve chegar já ordenada de forma determinística (pré-req do cache — agente/CLAUDE.md)."""
    return _env.get_template("programas.md.j2").render(programas=programas)


def render_fetiches(fetiches: list[dict[str, Any]]) -> str:
    """BP3 por-modelo — cardápio de fetiches que a modelo FAZ (ADR 0014 revisado).

    Cada item é um fetiche vinculado, com preço opcional: `preco` None = incluso (faz sem custo
    extra); preenchido = extra pago que a IA cota ("+R$X"). A ausência de um fetiche da lista
    significa que ela NÃO faz — a IA recusa de forma aberta, sem lista de negativos no prompt.
    A lista deve chegar ordenada de forma determinística (pré-req do cache — agente/CLAUDE.md)."""
    return _env.get_template("fetiches.md.j2").render(fetiches=fetiches)


def render_bp3(
    identidade: IdentidadeModelo,
    programas: list[dict[str, Any]],
    fetiches: list[dict[str, Any]],
) -> str:
    """BP3 completo por-modelo: identidade + programas + fetiches concatenados (03 §2.3)."""
    return f"{render_identidade(identidade)}\n{render_programas(programas)}\n{render_fetiches(fetiches)}"
