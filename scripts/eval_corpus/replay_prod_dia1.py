"""Replay dos atendimentos reais de prod (21-22/07, Tatiane) contra o agente NOVO (código local).

Cada cenário reencena um problema apontado na reunião Fernando/Boris/Rossi de 22/07 e roda pelo
caminho FIEL de prod (evals.harness_fiel: processar_turno + enviar_turno, DB local, Evolution spy,
fakeredis). Checks determinísticos (regex sobre texto normalizado + estado/ia_pausada) dizem se o
fix resolveu. §0: gasta crédito DeepSeek (autorizado pelo usuário para esta rodada); NÃO toca
WhatsApp, Redis nem banco de prod — cada cenário roda numa transação com ROLLBACK.

Uso (de api/):  TEST_DATABASE_URL=postgresql://postgres@localhost:5544/barra \
                PYTHONPATH=. uv run python <este arquivo> [--so cenario1,cenario2]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente._normalizar import normalizar
from barra.agente.graph import build_graph
from evals.harness import _get_or_create, seedar
from evals.harness_fiel import ResultadoFiel, rodar_turno_fiel

AGORA = datetime(2026, 7, 22, 23, 0, tzinfo=UTC)  # 20:00 BRT

MODELO_BASE: dict[str, Any] = {
    "nome": "Tatiane",
    "idade": 20,
    "localizacao_operacional": "Centro de Campinas (Cambuí)",
    "endereco_formatado": "Rua Santos Dumont, 291 - Centro, Campinas-SP",
    "tipo_atendimento_aceito": ["interno"],
}
NOME_LOCAL = "Hotel Sirius"

# Cadastro real de prod: só Completo 800 1h + Normal 400 1h.
PROGRAMAS_PROD = [
    {"nome": "Completo", "duracao_nome": "1 hora", "horas": 1, "preco": 800, "ordem": 1},
    {"nome": "Normal", "duracao_nome": "1 hora", "horas": 1, "preco": 400, "ordem": 1},
]
# Cenário pós-cadastro dos preços longos (pendência do Fernando; valores plausíveis só p/ eval).
PROGRAMAS_PERNOITE = PROGRAMAS_PROD + [
    {"nome": "Normal", "duracao_nome": "6 horas", "horas": 6, "preco": 1600, "ordem": 6},
    {"nome": "Normal", "duracao_nome": "8 horas", "horas": 8, "preco": 2000, "ordem": 8},
    {"nome": "Normal", "duracao_nome": "Pernoite", "horas": 12, "preco": 2500, "ordem": 12},
]
FETICHES = ["Beijo na boca", "Oral sem camisinha"]

Check = tuple[str, Callable[[ResultadoFiel], bool]]


def _n(res: ResultadoFiel) -> str:
    return normalizar(res.resposta)


def contem(*termos: str) -> Callable[[ResultadoFiel], bool]:
    return lambda r: any(t in _n(r) for t in termos)


def nao_contem(*termos: str) -> Callable[[ResultadoFiel], bool]:
    return lambda r: all(t not in _n(r) for t in termos)


def sem_regex(padrao: str) -> Callable[[ResultadoFiel], bool]:
    rx = re.compile(padrao)
    return lambda r: not rx.search(_n(r))


def com_regex(padrao: str) -> Callable[[ResultadoFiel], bool]:
    rx = re.compile(padrao)
    return lambda r: bool(rx.search(_n(r)))


def respondeu(r: ResultadoFiel) -> bool:
    return bool(r.resposta.strip())


def precos_só_da_tabela(*permitidos: str) -> Callable[[ResultadoFiel], bool]:
    """Nenhum número de 3-4 dígitos fora do conjunto permitido (anti preço inventado).
    Colapsa separador de milhar antes ("2.500" é 2500, não um 500 avulso)."""
    ok = set(permitidos)

    def check(r: ResultadoFiel) -> bool:
        texto = re.sub(r"(?<=\d)\.(?=\d)", "", _n(r))
        return all(m in ok for m in re.findall(r"\b\d{3,4}\b", texto))

    return check


@dataclass
class Turno:
    cliente: str
    checks: list[Check] = field(default_factory=list)


@dataclass
class Cenario:
    nome: str
    problema: str  # o que a reunião apontou
    turnos: list[Turno]
    programas: list[dict[str, Any]] = field(default_factory=lambda: PROGRAMAS_PROD)
    fetiches_pagos: list[str] = field(default_factory=list)  # preco sentinela 1.00 (ADR-0030)
    disponibilidade: list[dict[str, Any]] = field(default_factory=list)  # ADR 0005; vazio = sempre


CENARIOS: list[Cenario] = [
    Cenario(
        nome="endereco_triagem",
        problema="#12/Alexandre: vazou 'Rua Santos Dumont, 291' + 'é um prédio, sala mesmo' em Triagem",
        turnos=[
            Turno("boa noite", [("respondeu", respondeu)]),
            Turno(
                "onde você atende?",
                [
                    ("sem_rua_numero", nao_contem("santos dumont", "291")),
                    ("sem_sala_predio", nao_contem("sala", "predio")),
                    ("respondeu", respondeu),
                ],
            ),
            Turno(
                "é apartamento ou casa? e qual o valor?",
                [
                    ("sem_rua_numero", nao_contem("santos dumont", "291")),
                    ("sem_sala_predio", nao_contem("sala", "predio")),
                    ("enquadra_hotel", contem("hotel")),
                    ("um_preco_so", lambda r: not ("800" in _n(r) and "400" in _n(r))),
                    ("cota_o_normal", contem("400")),
                ],
            ),
        ],
    ),
    Cenario(
        nome="completo_segunda_venda",
        problema="final 54: despejou 'completo 800 / normal 400' juntos na apresentação",
        turnos=[
            Turno("oi, tudo bem?", []),
            Turno(
                "quais são seus serviços amor?",
                [
                    ("nao_despeja_dois_precos", lambda r: not ("800" in _n(r) and "400" in _n(r))),
                    ("respondeu", respondeu),
                ],
            ),
            Turno(
                "quanto é?",
                [
                    ("cota_um_preco", lambda r: not ("800" in _n(r) and "400" in _n(r))),
                    ("porta_de_entrada_400", contem("400")),
                    ("preco_da_tabela_nao_do_exemplo", precos_só_da_tabela("400", "800")),
                ],
            ),
            Turno(
                "você é completa? faz completo?",
                [("agora_sim_completo", contem("800")), ("respondeu", respondeu)],
            ),
        ],
    ),
    Cenario(
        nome="balada_happy_hour",
        problema="final 54: 'não acompanho em balada nem restaurante, só recebo no meu local'",
        turnos=[
            Turno("oi gata", []),
            Turno(
                "terá um happy hour na minha empresa esse fim de semana, vamos num restaurante e "
                "depois num barzinho, gostaria que me acompanhasse",
                [
                    ("nao_recusa_seco", nao_contem("nao acompanho", "so recebo", "nao costumo acompanhar")),
                    # tabela só tem 1h: prometer pernoite (qualquer flexão/artigo) é pacote inexistente
                    ("nao_oferece_pacote_inexistente",
                     sem_regex(r"fech\w{0,5} (o|um) pernoite|pernoite,? te acompanho|o pernoite e |pernoite \d")),
                    ("sem_preco_inventado", precos_só_da_tabela("400", "800")),
                    ("respondeu", respondeu),
                ],
            ),
        ],
    ),
    Cenario(
        nome="balada_com_tabela",
        problema="pós-cadastro dos períodos longos: convite social converte em pernoite da tabela",
        programas=PROGRAMAS_PERNOITE,
        turnos=[
            Turno("oi gata", []),
            Turno(
                "terá um happy hour na minha empresa esse fim de semana, vamos num restaurante e "
                "depois num barzinho, gostaria que me acompanhasse",
                [
                    ("nao_recusa_seco", nao_contem("nao acompanho", "so recebo", "nao costumo acompanhar")),
                    # "período maior/mais longo" é a fraseologia ditada pelo Fernando na reunião
                    ("converte_em_periodo_longo",
                     com_regex(r"pernoite|6 ?h|8 ?h|noite|periodo maior|periodo mais longo")),
                    ("preco_da_tabela", precos_só_da_tabela("400", "800", "1600", "2000", "2500")),
                ],
            ),
        ],
    ),
    Cenario(
        nome="pernoite_sem_tabela",
        problema="#10: 'pernoite não tenho' 3x, inventou '3h 800', e o 1500/5h caiu no vácuo (escalada silenciosa)",
        turnos=[
            Turno("adorei suas fotos, gostaria de ficar uma noite com você, tem possibilidade?", [
                ("sem_preco_inventado", precos_só_da_tabela("400", "800")),
                ("respondeu", respondeu),
            ]),
            Turno(
                "poxa que pena... te dou 1500 pelas 5 horas, fechado?",
                [
                    ("anti_vacuo", respondeu),
                    ("sem_preco_inventado", precos_só_da_tabela("400", "800", "1500")),
                    ("nao_cravou_fechamento", nao_contem("fechamos", "confirmado", "fechado entao")),
                ],
            ),
        ],
    ),
    Cenario(
        nome="pernoite_com_tabela",
        problema="reunião: pernoite sem objeção de preço → entusiasmo + induzir 6h+, nunca perguntar o tempo",
        programas=PROGRAMAS_PERNOITE,
        turnos=[
            Turno("oi linda, tudo bem?", []),
            Turno(
                "gostaria de passar a noite inteira com você, é possível?",
                [
                    ("nao_nega_pernoite", sem_regex(r"pernoite nao|nao tenho (esse )?pacote|nao consigo esse periodo")),
                    ("induz_periodo_longo", com_regex(r"\b(6 ?h|6 horas|8 ?h|8 horas|pernoite|noite)\b")),
                    ("preco_da_tabela", precos_só_da_tabela("400", "800", "1600", "2000", "2500")),
                    ("nao_pergunta_tempo", nao_contem("quanto tempo", "qual seria o horario que voce pensou")),
                ],
            ),
        ],
    ),
    Cenario(
        nome="recem_chegada",
        problema="cliente 'é de Campinas mesmo? DDD de fora' → respondeu 'sou sim' (devia ser recém-chegada)",
        turnos=[
            Turno("oi, tudo bem?", []),
            Turno(
                "você é de campinas mesmo? vi que seu ddd é de fora",
                [
                    ("nao_afirma_local", sem_regex(r"\bsou sim\b|sou daqui|sou de campinas")),
                    ("assume_recem_chegada", contem("cheguei", "de fora", "pouco tempo", "pouquinho", "mudei", "conhecendo")),
                ],
            ),
        ],
    ),
    Cenario(
        nome="atende_sozinha",
        problema="'atende sozinha?' é pergunta de segurança: 'só eu' — nunca oferecer amiga nesse momento",
        turnos=[
            Turno("oi", []),
            Turno(
                "você atende sozinha ou tem mais gente aí?",
                [
                    ("discricao", contem("so eu", "sozinha")),
                    ("sem_amiga_aqui", nao_contem("amiga", "dupla")),
                ],
            ),
        ],
    ),
    Cenario(
        nome="esfregadinha",
        problema="'esfregadinha/deixar na bct' → respondeu 'faço sim, tudo incluso' (furo na linha do sem-camisinha)",
        turnos=[
            Turno("oi gata, quanto é?", [
                ("preco_da_tabela_nao_do_exemplo", precos_só_da_tabela("400", "800")),
            ]),
            Turno("faz completo? quanto fica?", [
                ("preco_da_tabela_nao_do_exemplo", precos_só_da_tabela("400", "800")),
            ]),
            Turno(
                "uma esfregadinha gata, deixar na bct, no atendimento pode? sem nada mesmo",
                [
                    ("recusa", contem("nao")),
                    ("com_camisinha", contem("camisinha", "seguro")),
                    ("nunca_tudo_incluso", nao_contem("tudo incluso", "faco sim", "tudo ja esta incluso")),
                ],
            ),
        ],
    ),
    Cenario(
        nome="pergunta_nao_e_aceite",
        problema="#9: 'é o mesmo valor?' foi tratado como aceite → 'fechamos o completo' + reafirmou 2x após 'ainda não'",
        turnos=[
            Turno("boa noite", []),
            Turno("quanto você cobra?", [
                ("preco_da_tabela_nao_do_exemplo", precos_só_da_tabela("400", "800")),
            ]),
            Turno(
                "só queria mamar um pouquinho nos seus peitos, é o mesmo valor?",
                [
                    ("nao_crava_fechamento", nao_contem("fechamos", "confirmado", "fechado entao")),
                    ("responde_a_pergunta", respondeu),
                ],
            ),
            Turno(
                "ainda não, estou analisando aqui",
                [
                    ("recua_sem_fechar", nao_contem("fechamos", "confirmado", "combinado entao")),
                    ("respondeu", respondeu),
                ],
            ),
        ],
    ),
    Cenario(
        nome="descricao_normal_e_limite",
        problema="dupla negação ininteligível no normal + 'sem limite' na finalização",
        turnos=[
            Turno("oi, qual a diferença do completo pro normal?", [
                ("sem_dupla_negacao", sem_regex(r"sem [a-z ]{0,30} sem ")),
                ("descreve_pelo_incluso", contem("incluso", "beijo", "oral", "anal")),
                # Bruno 22/07: "400 ou 800 não entendi" levou vaguidão ("mais coisas inclusas",
                # "mais leve/mais intenso"). A diferença concreta é anal incluso no completo.
                ("diferenca_concreta_anal", contem("anal")),
                ("sem_vaguidao", nao_contem("mais intenso", "mais coisas")),
            ]),
            Turno("e quantas vezes posso finalizar? tem limite?", [
                ("nunca_sem_limite", nao_contem("sem limite")),
                ("respondeu", respondeu),
            ]),
        ],
    ),
    Cenario(
        nome="faz_anal_cota_completo",
        problema="anal vive dentro do Completo quando ele existe na tabela: cota o completo, não extra avulso",
        turnos=[
            Turno("oi gata, quanto é?", [("porta_de_entrada_400", contem("400"))]),
            Turno("vc faz anal?", [
                ("responde_pelo_completo", contem("completo")),
                ("cota_o_completo", contem("800")),
                ("sem_preco_inventado", precos_só_da_tabela("400", "800")),
            ]),
        ],
    ),
    Cenario(
        nome="primo_duas_pessoas",
        problema="Elias 22/07: 'meu primo e eu, seria 2' — cobra por duas pessoas, mas rotulou de 'casal'",
        fetiches_pagos=["Casal"],
        turnos=[
            Turno("oi, quanto é?", [("respondeu", respondeu)]),
            Turno("é que ainda esta meu primo e eu. seria 2. ai fica ruim assim", [
                ("sem_rotulo_casal", nao_contem("casal")),
                ("cobra_pelos_dois", contem("1600", "voces dois", "os dois", "por dois")),
                # Conta do dobro: totais legítimos são 800 (normal) e 1600 (completo);
                # "1200" foi soma errada do DeepSeek em replay (800+400).
                ("conta_certa", precos_só_da_tabela("400", "800", "1600")),
                ("respondeu", respondeu),
            ]),
        ],
    ),
    Cenario(
        nome="anuncio_150",
        problema="Elias 22/07: 'no app falou 150' — o anúncio não valida preço; mesma escada",
        turnos=[
            Turno("oi, quanto cobra?", [("cota_400", contem("400"))]),
            Turno("no app falou 150", [
                ("nao_valida_150", sem_regex(r"consigo (o |por )?150|fech\w{0,5} (em |por )?150|150 (ta|esta) bom")),
                ("sem_preco_fora_da_escada", precos_só_da_tabela("400", "800", "350", "300", "150")),
            ]),
        ],
    ),
    Cenario(
        nome="resgate_despedida_sem_orcamento",
        problema="Elias 22/07: resgate de despedida com 'qual valor você tinha em mente?' (orçamento proibido)",
        turnos=[
            Turno("boa noite, qual o valor?", [("cota_400", contem("400"))]),
            Turno("hmm vou ficar pra proxima então, obrigado", [
                ("nunca_pede_orcamento", nao_contem("em mente", "orcamento", "quanto voce pode")),
                ("respondeu", respondeu),
            ]),
        ],
    ),
    Cenario(
        nome="saudacao_leve",
        problema="reunião: 'o tudo bem não é necessário você perguntar' — abertura leve, sem devolver questionário",
        turnos=[
            Turno("olá tudo bem?", [
                ("nao_devolve_tudo_bem", sem_regex(r"tudo bem ?\?")),
                ("respondeu", respondeu),
            ]),
            Turno("quanto é?", [("cota_400", contem("400"))]),
        ],
    ),
    Cenario(
        nome="pergunta_de_horario",
        problema="prod 21/07: 'a partir de que horas você atende?' respondido com valor, nada a ver",
        disponibilidade=[
            {"dia_semana": d, "hora_inicio": "10:00", "hora_fim": "23:00"} for d in range(7)
        ],
        turnos=[
            Turno("oi gata", [("respondeu", respondeu)]),
            Turno("a partir de que horas você atende amanhã?", [
                ("responde_com_horario", com_regex(r"10 ?h|10:00|as 10|das 10|de manha")),
                ("sem_preco_nao_pedido", nao_contem("400", "800")),
            ]),
        ],
    ),
    Cenario(
        nome="pin_fica_longe",
        problema="ETA fabricada ('uns 15-20min daqui') a partir de pin cego — nunca estimar distância/tempo",
        turnos=[
            Turno("oi gata, to afim de você", [("respondeu", respondeu)]),
            Turno(
                "[pin de localização: Rua Equador, 500 · lat -22.901234, long -47.062100]",
                [("sem_eta_inventada", sem_regex(r"\d+ ?(min|minutos)\b|\d+ ?km|\d+-\d+ ?min"))],
            ),
            Turno("fica longe de você?", [
                ("sem_eta_inventada", sem_regex(r"\d+ ?(min|minutos)\b|\d+ ?km|\d+-\d+ ?min")),
                ("responde_pela_regiao", respondeu),
            ]),
        ],
    ),
]


async def _seed_fetiches(
    conn: AsyncConnection[Any], modelo_id: Any, pagos: list[str] | None = None
) -> None:
    for i, nome in enumerate(FETICHES):
        fid = await _get_or_create(conn, "fetiches", nome, colunas={"ordem": 100 + i})
        await conn.execute(
            "INSERT INTO barravips.modelo_fetiches (modelo_id, fetiche_id, preco) "
            "VALUES (%s, %s, NULL) ON CONFLICT DO NOTHING",
            (modelo_id, fid),
        )
    # Pago/calculado (sentinela 1.00): como o "Casal" real de prod — o BP3 renderiza o extra
    # pelo preço do programa (dobro), não pelo valor gravado.
    for j, nome in enumerate(pagos or []):
        fid = await _get_or_create(conn, "fetiches", nome, colunas={"ordem": 200 + j})
        await conn.execute(
            "INSERT INTO barravips.modelo_fetiches (modelo_id, fetiche_id, preco) "
            "VALUES (%s, %s, 1.00) ON CONFLICT DO NOTHING",
            (modelo_id, fid),
        )


async def rodar_cenario(cenario: Cenario, graph: Any, url: str) -> dict[str, Any]:
    conn = await AsyncConnection.connect(
        url, autocommit=False, row_factory=dict_row, prepare_threshold=None
    )
    transcript: list[dict[str, Any]] = []
    falhas: list[str] = []
    try:
        # Anti-janela-embaralhada (memória replay_agente_terminal): numa transação única o now()
        # empata em todas as linhas de `mensagens` e o ORDER BY cai no uuid4 aleatório. Default
        # clock_timestamp() dá created_at estritamente crescente; o ROLLBACK desfaz o ALTER.
        await conn.execute(
            "ALTER TABLE barravips.mensagens ALTER COLUMN created_at SET DEFAULT clock_timestamp()"
        )
        modelo_spec: dict[str, Any] = {**MODELO_BASE, "programas": cenario.programas}
        if cenario.disponibilidade:
            modelo_spec["disponibilidade"] = cenario.disponibilidade
        fixture = {
            "cenario": {
                "modelo": modelo_spec,
                "atendimento": {"estado": "Novo"},
            }
        }
        cen = await seedar(conn, fixture)
        await conn.execute(
            "UPDATE barravips.modelos SET nome_local = %s WHERE id = %s",
            (NOME_LOCAL, cen.modelo_id),
        )
        await _seed_fetiches(conn, cen.modelo_id, cenario.fetiches_pagos)

        for turno in cenario.turnos:
            res = await rodar_turno_fiel(conn, cen, turno.cliente, graph=graph, agora=AGORA)
            resultados = {}
            for rotulo, fn in turno.checks:
                ok = bool(fn(res))
                resultados[rotulo] = ok
                if not ok:
                    falhas.append(f"{cenario.nome}/{turno.cliente[:30]}…/{rotulo}")
            transcript.append(
                {
                    "cliente": turno.cliente,
                    "ia": res.textos,
                    "estado": res.estado,
                    "ia_pausada": res.ia_pausada,
                    "checks": resultados,
                }
            )
            print(f"  [{cenario.nome}] cliente: {turno.cliente[:60]}")
            for t in res.textos:
                print(f"      ela: {t}")
            if not res.textos:
                print(f"      ela: (sem resposta) ia_pausada={res.ia_pausada}")
            ruins = [k for k, v in resultados.items() if not v]
            print(f"      estado={res.estado} pausada={res.ia_pausada} "
                  f"checks={'OK' if not ruins else 'FALHOU: ' + ', '.join(ruins)}")
    finally:
        await conn.rollback()
        await conn.close()
    return {"cenario": cenario.nome, "problema": cenario.problema,
            "transcript": transcript, "falhas": falhas}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--so", help="lista de cenários separados por vírgula")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "replay_prod_dia1_resultado.json"))
    args = ap.parse_args()

    url = os.environ["TEST_DATABASE_URL"]
    escolhidos = [c for c in CENARIOS if not args.so or c.nome in args.so.split(",")]
    graph = build_graph()

    resultados = []
    for cenario in escolhidos:
        print(f"\n=== {cenario.nome} — {cenario.problema}")
        resultados.append(await rodar_cenario(cenario, graph, url))

    todas_falhas = [f for r in resultados for f in r["falhas"]]
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(resultados, fh, ensure_ascii=False, indent=2, default=str)

    print("\n" + "=" * 70)
    for r in resultados:
        status = "PASS" if not r["falhas"] else "FAIL"
        print(f"{status}  {r['cenario']}" + (f"  ({len(r['falhas'])} checks)" if r["falhas"] else ""))
    print(f"\nresultado completo: {args.out}")
    sys.exit(1 if todas_falhas else 0)


if __name__ == "__main__":
    asyncio.run(main())
