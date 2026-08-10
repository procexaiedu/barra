"""Renderizacao em texto do relatorio de graduacao -- o que `make graduacao` imprime.

Formatacao pura (recebe o DTO, devolve string): nao toca banco, nao decide nada. Existe separada
do `service` para o teste poder afirmar o TEXTO sem subir Postgres, e para o dia em que a mesma
apuracao virar rota HTTP (o DTO ja e a resposta; so o render fica para tras).
"""

from __future__ import annotations

from .schemas import RelatorioGraduacao

_LARGURA = 88
# Indeterminado tem simbolo PROPRIO: colapsa-lo em "nao" seria dizer que o criterio reprovou,
# quando o que aconteceu foi que falta instrumento para medi-lo.
_MARCA = {True: "[ OK ]", False: "[FALHA]", None: "[ ?  ]"}


def _pct(v: float | None, casas: int = 1) -> str:
    return "--" if v is None else f"{v:.{casas}f}%"


def _cabecalho(titulo: str) -> str:
    return f"\n{titulo}\n{'-' * len(titulo)}"


def _quebrar(texto: str, recuo: str) -> str:
    """Quebra em `_LARGURA` colunas preservando o recuo -- sem depender de textwrap."""
    linhas: list[str] = []
    atual = recuo
    for palavra in texto.split():
        if len(atual) + len(palavra) + 1 > _LARGURA and atual.strip():
            linhas.append(atual)
            atual = recuo + palavra
        else:
            atual = f"{atual} {palavra}" if atual.strip() else recuo + palavra
    if atual.strip():
        linhas.append(atual)
    return "\n".join(linhas)


def _campo(rotulo: str, valor: str) -> str:
    """Uma linha `rotulo : valor` na coluna fixa -- os quatro criterios alinham entre si."""
    return f"   {rotulo:<25}: {valor}"


def renderizar(rel: RelatorioGraduacao) -> str:
    p = rel.conversas
    i = rel.incidentes
    t = rel.taxa_gate
    c = rel.conversao

    linhas: list[str] = [
        "=" * _LARGURA,
        "GRADUACAO DO PILOTO -- ADR-0034 (4 criterios)",
        "=" * _LARGURA,
        _campo("gerado em", f"{rel.gerado_em:%Y-%m-%d %H:%M} UTC"),
        _campo(
            "inicio do piloto",
            f"{rel.piloto_inicio_em:%Y-%m-%d %H:%M} UTC ({rel.piloto_inicio_origem})"
            if rel.piloto_inicio_em
            else "AUSENTE -- nenhum turno da IA para cliente real",
        ),
        "",
        # A palavra final e do humano: o relatorio afirma o estado dos criterios, nao a decisao.
        f"VEREDITO DOS DADOS: {'APTO (os 4 criterios batem)' if rel.apto else 'NAO APTO'}"
        "  -- a decisao de graduar continua humana",
    ]

    linhas.append(_cabecalho(f"1. Conversas completas conduzidas pela IA {_MARCA[p.atende]}"))
    linhas.append(_campo(f"completas (>= {p.limiar})", str(p.completas)))
    linhas.append(_campo("com atendimento", str(p.com_atendimento)))
    linhas.append(_campo("ainda em curso", str(p.em_curso)))

    linhas.append(_cabecalho(f"2. Incidentes criticos nao-contidos {_MARCA[i.atende]}"))
    linhas.append(_campo("total (limiar: zero)", str(i.total)))
    linhas.append(_campo("abertos / triados", f"{i.abertos} / {i.triados}"))
    linhas.append(_campo("turnos julgados (amostra)", str(i.turnos_julgados)))

    linhas.append(_cabecalho(f"3. Taxa do gate {_MARCA[t.atende]}"))
    linhas.append(_campo("tendencia", t.tendencia))
    linhas.append(
        _campo(
            "inclinacao",
            "--" if t.inclinacao_pp_semana is None else f"{t.inclinacao_pp_semana:+.2f} pp/semana",
        )
    )
    linhas.append(
        _campo(
            "taxa da ultima semana",
            _pct(None if t.taxa_atual is None else t.taxa_atual * 100),
        )
    )
    if t.semanas:
        linhas.append("   serie semanal:")
        linhas.append("     semana      aborts  julgados  universo   taxa")
        for s in t.semanas:
            linhas.append(
                f"     {s.semana:%Y-%m-%d}  {s.aborts:>6}  {s.julgados:>8}  "
                f"{s.universo:>8}  {s.taxa * 100:>5.1f}%"
            )

    linhas.append(_cabecalho(f"4. Conversao vs baseline do vendedor {_MARCA[c.atende]}"))
    linhas.append(_campo("fechados / terminais", f"{c.fechados} / {c.terminais}"))
    linhas.append(_campo("conversao da IA", _pct(c.conversao_pct)))
    linhas.append(
        _campo(
            "baseline do vendedor",
            _pct(c.baseline_pct)
            + (
                f"  (n={c.baseline_amostra_n}, fonte: {c.baseline_fonte})"
                if c.baseline_pct is not None
                else "  -- NAO REGISTRADO"
            ),
        )
    )
    linhas.append(
        _campo(
            f"razao (>= {c.limiar_razao:.0%})",
            "--" if c.razao is None else f"{c.razao:.2f}",
        )
    )

    if rel.gaps:
        linhas.append(_cabecalho("Gaps -- o que estes numeros NAO respondem"))
        for gap in rel.gaps:
            linhas.append(_quebrar(f"* {gap}", "   "))

    linhas.append("")
    return "\n".join(linhas)
