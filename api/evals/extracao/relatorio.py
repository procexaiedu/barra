"""Relatorio da bancada: legivel por campo e por trajetoria, com os limites do corpus dentro dele.

Os limites nao sao rodape: vem antes do numero, de proposito. Um extrator afinado em dez dias de
uma modelo com o piloto ligado pode nao generalizar — a bancada mede REGRESSAO e compara variantes
com confianca; ela nao prova qualidade absoluta, e ninguem deve ler uma porcentagem como promessa.
"""

from __future__ import annotations

from typing import Any

_TRACO = "—"

# Rotulo humano da metrica que manda em cada campo (a assimetria declarada, `metricas.CAMPOS`).
_MANDA = {"precisao": "precisão", "recall": "recall", "ambos": "ambos"}


def _num(valor: Any) -> str:
    """Uma metrica agregada (`Dispersao.como_dict`) como 'media ±desvio [min-max]'."""
    if not valor:
        return _TRACO
    corpo = f"{valor['media']:.3f} ±{valor['desvio']:.3f}"
    return (
        corpo
        if valor["min"] == valor["max"]
        else f"{corpo} [{valor['min']:.3f}-{valor['max']:.3f}]"
    )


def formatar(rel: dict[str, Any]) -> str:
    """Relatorio em texto. `rel` e o dicionario que `bancada.rodar_bancada` devolve."""
    meta = rel["meta"]
    linhas = [
        "",
        "=== Bancada offline da extração ===",
        f"extrator: {meta['extrator']}   repetições: {meta['repeticoes']}   "
        f"itens: {meta['itens']}   trajetórias: {meta['trajetorias']}",
        "",
        "LIMITES DO CORPUS (leia antes do número):",
        *(f"  - {limite}" for limite in meta.get("limites", [])),
        "  A bancada mede regressão e compara variantes; não prova qualidade absoluta.",
    ]
    if meta["extrator"] != "deepseek":
        # Sem o extrator de verdade, as variantes que mudam a ENTRADA (bloco de estado, descrição
        # do aceite, temperatura) não têm efeito — o payload vem pronto. Dito aqui para ninguém ler
        # "variantes empatadas" como resultado.
        linhas.append(
            f"  extrator `{meta['extrator']}`: variantes de entrada não mudam o payload "
            "(só a promoção de intenção, que é lida pela bancada). Use --real para compará-las."
        )
    for nome, dados in rel["variantes"].items():
        linhas += ["", f"--- variante: {nome} ---", _cabecalho()]
        for campo, m in dados["campos"].items():
            linhas.append(
                f"{campo:<20}{_MANDA.get(m['manda'], m['manda']):<10}"
                f"{_num(m['precisao']):<26}{_num(m['recall']):<26}"
                f"{m['n']:<5}{m['contagem']}"
            )
        eco = dados["eco"]
        linhas.append(
            f"eco (campo reenviado sem nada novo na conversa): {eco['reenvios']} em "
            f"{eco['itens']} itens rotulados"
            + (f" ({eco['pct']:.1f}%)" if eco["pct"] is not None else "")
        )
        if dados["trajetorias"]:
            linhas.append("trajetórias:")
            for traj in dados["trajetorias"]:
                marca = "✅" if traj["igual"] else "❌"
                linhas.append(
                    f"  {marca} {traj['id']}: prevista={traj['prevista']} "
                    f"rotulada={traj['rotulada']} "
                    f"(prefixo comum {traj['prefixo_comum']}/{len(traj['rotulada'])}, "
                    f"estado final {'igual' if traj['estado_final_igual'] else 'diferente'})"
                )
        else:
            linhas.append("trajetórias: não rodadas (exigem TEST_DATABASE_URL — use --trajetoria)")
    campos_sem_rotulo = [
        campo
        for dados in rel["variantes"].values()
        for campo, m in dados["campos"].items()
        if m["n"] == 0
    ]
    if campos_sem_rotulo:
        linhas.append("aviso: sem item rotulado para " + ", ".join(sorted(set(campos_sem_rotulo))))
    return "\n".join(linhas)


def _cabecalho() -> str:
    return f"{'campo':<20}{'manda':<10}{'precisão':<26}{'recall':<26}{'n':<5}tp/fp/fn/tn"
