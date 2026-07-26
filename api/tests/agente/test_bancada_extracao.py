"""Bancada offline da extração: a FERRAMENTA, testada com extrator fake roteirizado.

Dado um golden set pequeno e um extrator que devolve payload conhecido, o relatório precisa
apresentar as métricas corretas. O que se afirma é o comportamento externo — o relatório
produzido —, nunca a estrutura interna do cálculo.

Roda sem crédito e sem banco (o extrator é fake e o nível campo não toca Postgres), então entra
no gate padrão. O nível trajetória, que exige o banco, é `tests/integracao/test_bancada_replay.py`.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from evals.extracao.bancada import rodar_bancada
from evals.extracao.extrator import VARIANTES, ExtratorRoteirizado, esquema_extracao
from evals.extracao.golden import ItemGolden, carregar_golden
from evals.extracao.relatorio import formatar
from langchain_core.messages import BaseMessage

from barra.agente.ferramentas.extracao import SinaisQualificacao

# Golden mínimo: um item de aceite falso-positivo, um de aceite verdadeiro e um de eco. Os rótulos
# são os mesmos modos de falha do corpus, no menor tamanho em que a conta é conferível à mão.
_GOLDEN = {
    "meta": {"limites": ["dez dias", "uma modelo"], "origem": "teste"},
    "itens": [
        {
            "id": "a-cortesia",
            "atendimento": 1,
            "descricao": "cortesia não é aceite",
            "agora": "2026-07-24T10:00:00-03:00",
            "conversa": [
                {"de": "ia", "texto": "400 1h no meu local"},
                {"de": "cliente", "texto": "obrigado"},
            ],
            "registrado": {"tipo_atendimento": "interno", "valor_acordado": "400"},
            "gravado": {"sinais_qualificacao": {"aceita_valor": True}},
            "rotulo": {"aceita_valor": False},
        },
        {
            "id": "b-aceite",
            "atendimento": 2,
            "descricao": "cliente crava a hora sobre o valor cotado",
            "agora": "2026-07-24T16:00:00-03:00",
            "conversa": [
                {"de": "ia", "texto": "Posso confirmar às 18h"},
                {"de": "cliente", "texto": "Perfeito"},
            ],
            "registrado": {"tipo_atendimento": "interno"},
            "gravado": {"sinais_qualificacao": {"aceita_valor": True}},
            "rotulo": {
                "aceita_valor": True,
                "intencao": "agendamento",
                "horario_evidenciado": True,
            },
        },
        {
            "id": "c-eco",
            "atendimento": 1,
            "descricao": "o tipo já registrado volta sem nada novo na conversa",
            "agora": "2026-07-24T10:30:00-03:00",
            "conversa": [{"de": "cliente", "texto": "vc melhora no valor eu vou"}],
            "registrado": {"tipo_atendimento": "interno"},
            "gravado": {"tipo_atendimento": "interno"},
            "rotulo": {"reenvio_esperado": False},
        },
    ],
    "trajetorias": [],
}

# Extrator roteirizado: erra o aceite no item de cortesia (falso positivo), acerta no de aceite
# real e ecoa o tipo no terceiro. Precisão do aceite = 1/2; recall = 1/1.
_ROTEIRO: dict[str, dict[str, Any]] = {
    "a-cortesia": {"sinais_qualificacao": {"aceita_valor": True}},
    "b-aceite": {
        "sinais_qualificacao": {"aceita_valor": True},
        "intencao": "cotacao",
        "horario_desejado": "18:00",
    },
    "c-eco": {"tipo_atendimento": "interno"},
}


@pytest.fixture
def golden(tmp_path: Path) -> Any:
    caminho = tmp_path / "golden_set.json"
    caminho.write_text(json.dumps(_GOLDEN, ensure_ascii=False), encoding="utf-8")
    return carregar_golden(caminho)


async def test_relatorio_traz_as_metricas_do_payload_conhecido(golden: Any) -> None:
    extrator = ExtratorRoteirizado(_ROTEIRO)
    rel = await rodar_bancada(
        golden, lambda _v: extrator, variantes=[VARIANTES["base"]], repeticoes=1
    )

    campos = rel["variantes"]["base"]["campos"]
    # aceite: 2 itens rotulados, 1 falso positivo -> precisão 0.5 (a métrica que manda) e recall 1.
    assert campos["aceita_valor"]["manda"] == "precisao"
    assert campos["aceita_valor"]["n"] == 2
    assert campos["aceita_valor"]["contagem"] == "1/1/0/0"
    assert campos["aceita_valor"]["precisao"]["media"] == 0.5
    assert campos["aceita_valor"]["recall"]["media"] == 1.0
    # intenção: o payload disse 'cotacao', mas o horário evidenciado promove -> acerta o rótulo.
    assert campos["intencao"]["manda"] == "recall"
    assert campos["intencao"]["recall"]["media"] == 1.0
    # campo sem nenhum item rotulado não vira número: n=0 e métrica ausente.
    assert campos["tipo_atendimento"]["n"] == 0
    assert campos["tipo_atendimento"]["precisao"] is None
    # eco: o terceiro item reenviou o tipo que já estava no snapshot.
    assert rel["variantes"]["base"]["eco"] == {"itens": 1, "reenvios": 1, "pct": 100.0}


async def test_relatorio_escreve_os_limites_do_corpus(golden: Any) -> None:
    rel = await rodar_bancada(
        golden,
        lambda _v: ExtratorRoteirizado(_ROTEIRO),
        variantes=[VARIANTES["base"]],
        repeticoes=1,
    )
    texto = formatar(rel)

    assert "dez dias" in texto and "uma modelo" in texto
    assert "não prova qualidade absoluta" in texto
    assert "aceita_valor" in texto and "0.500" in texto
    # trajetória não rodada aparece como tal, não como zero.
    assert "não rodadas" in texto


async def test_repeticao_mostra_dispersao_e_nao_so_media(golden: Any) -> None:
    """Enquanto a extração roda com temperatura de sampling, média sozinha confunde melhora com
    sorte: o relatório precisa mostrar a dispersão entre as repetições."""

    class ExtratorInstavel:
        """Acerta o aceite do item de cortesia só na 2ª repetição."""

        nome = "instavel"

        def __init__(self) -> None:
            self.chamadas = 0

        async def __call__(self, item: ItemGolden, janela: list[BaseMessage]) -> dict[str, Any]:
            self.chamadas += 1
            if item.id == "a-cortesia" and self.chamadas > len(_GOLDEN["itens"]):
                return {}
            return dict(_ROTEIRO.get(item.id, {}))

    rel = await rodar_bancada(
        golden, lambda _v: ExtratorInstavel(), variantes=[VARIANTES["base"]], repeticoes=2
    )

    precisao = rel["variantes"]["base"]["campos"]["aceita_valor"]["precisao"]
    assert precisao["min"] == 0.5 and precisao["max"] == 1.0
    assert precisao["desvio"] > 0
    assert precisao["repeticoes"] == 2
    assert "[0.500-1.000]" in formatar(rel)


async def test_variante_sem_bloco_de_estado_muda_a_entrada_do_extrator(golden: Any) -> None:
    """A variante controla o que o extrator LÊ: sem o bloco, a cauda fica só com a âncora."""
    com_bloco = ExtratorRoteirizado(_ROTEIRO)
    sem_bloco = ExtratorRoteirizado(_ROTEIRO)

    await rodar_bancada(golden, lambda _v: com_bloco, variantes=[VARIANTES["base"]], repeticoes=1)
    await rodar_bancada(
        golden, lambda _v: sem_bloco, variantes=[VARIANTES["sem-bloco-estado"]], repeticoes=1
    )

    cauda_com = str(com_bloco.janelas[0][-1].content)
    cauda_sem = str(sem_bloco.janelas[0][-1].content)
    assert "<ja_registrado>" in cauda_com and "interno" in cauda_com
    assert "<ja_registrado>" not in cauda_sem
    assert '<agenda hoje="2026-07-24" agora="10:00"/>' in cauda_sem  # âncora do turno preservada


async def test_variante_pre_patch_24_07_reconstitui_o_aceite_derivado_do_valor(golden: Any) -> None:
    """O patch de 24/07 tirou a derivação do aceite a partir do `valor_acordado` — que é gravado já
    na cotação. A variante reconstitui o comportamento anterior: o mesmo payload, que só cotou,
    acende o aceite nos dois itens e o falso positivo da cortesia volta."""
    so_cotou = {"a-cortesia": {"valor_acordado": "400"}, "b-aceite": {"valor_acordado": "400"}}
    rel = await rodar_bancada(
        golden,
        lambda _v: ExtratorRoteirizado(so_cotou),
        variantes=[VARIANTES["base"], VARIANTES["pre-patch-24-07"]],
        repeticoes=1,
    )

    # pós-patch: cotar não marca aceite — nenhum positivo previsto (o de verdade vira falso negativo).
    assert rel["variantes"]["base"]["campos"]["aceita_valor"]["contagem"] == "0/0/1/1"
    # pré-patch: o aceite acende no turno em que a IA cotou e a cortesia vira falso positivo.
    assert rel["variantes"]["pre-patch-24-07"]["campos"]["aceita_valor"]["contagem"] == "1/1/0/0"
    assert rel["variantes"]["pre-patch-24-07"]["campos"]["aceita_valor"]["precisao"]["media"] == 0.5


def test_variante_pre_patch_24_07_usa_a_descricao_antiga_do_aceite() -> None:
    """A descrição endurecida veio no MESMO commit que tirou a derivação: uma variante que só
    reintroduz a derivação mediria meio patch."""
    antes = json.dumps(
        esquema_extracao(VARIANTES["pre-patch-24-07"].descricao_aceite), ensure_ascii=False
    )
    depois = json.dumps(esquema_extracao(), ensure_ascii=False)

    assert "agradecer não é aceitar" in depois
    assert "agradecer não é aceitar" not in antes
    assert "não apenas perguntou o preço" in antes


def test_descricao_do_aceite_em_prod_e_autocontida() -> None:
    """Quem lê a descrição do aceite é a chamada barata, que não recebe o BP_GERAL: uma referência
    a bloco de prompt chega órfã. A regra inteira precisa estar no campo — inclusive a condição de
    que pergunta de logística só vale como sim depois da recusa de desconto."""
    prod = SinaisQualificacao.model_fields["aceita_valor"].description or ""
    referenciada = VARIANTES["aceite-referenciado"].descricao_aceite or ""

    assert "<desconto>" not in prod
    # Os dois ramos da negociação de preço, porque o canônico não exige recusa: depois de um
    # degrau concedido a pergunta de logística também é sim ao valor da mesa.
    assert "recusando" in prod and "contraproposta" in prod
    # A variante existe para a comparação: é a descrição órfã que rodava antes.
    assert "<desconto>" in referenciada


async def test_variante_sem_promocao_de_intencao_derruba_o_recall(golden: Any) -> None:
    """É a medida que a variante existe para dar: sem a promoção derivada, o payload que disse
    'cotacao' com horário evidenciado vira falso negativo e o funil trava."""
    rel = await rodar_bancada(
        golden,
        lambda _v: ExtratorRoteirizado(_ROTEIRO),
        variantes=[VARIANTES["base"], VARIANTES["sem-promocao-intencao"]],
        repeticoes=1,
    )

    assert rel["variantes"]["base"]["campos"]["intencao"]["recall"]["media"] == 1.0
    assert rel["variantes"]["sem-promocao-intencao"]["campos"]["intencao"]["recall"]["media"] == 0.0


async def test_golden_set_versionado_carrega_com_os_rotulos_humanos() -> None:
    """O golden set do repositório é o gabarito: precisa carregar e trazer os modos de falha
    rotulados à mão (aceite, recuo, horário evidenciado, intenção, eco)."""
    golden = carregar_golden()

    assert golden.meta["limites"]
    rotulados = {chave for item in golden.itens for chave in item.rotulo}
    assert {
        "aceita_valor",
        "recuo",
        "horario_evidenciado",
        "intencao",
        "reenvio_esperado",
    } <= rotulados
    # baseline do corpus: 1 aceite verdadeiro entre os turnos em que a produção marcou aceite.
    aceites = [i for i in golden.itens if "aceita_valor" in i.rotulo]
    assert sum(1 for i in aceites if i.rotulo["aceita_valor"]) == 1
    assert all(i.gravado.get("sinais_qualificacao", {}).get("aceita_valor") for i in aceites)
    assert golden.trajetorias and golden.trajetorias[0].estados
