"""Pix de deslocamento cobrado de quem já paga o próprio uber — o carimbo que faltava.

Corrida real `c12cen_v2_20260814`, cenário `uber_dele_ida_e_volta`. A regra do operador
(`regras.md.j2`, `<tipos_de_encontro>`) é explícita: "ou você chama e ele adianta o Pix, ou ele
chama o ida e volta — nunca as duas coisas juntas". A IA OBEDECEU na fala, nos dois turnos:

    t2  "Pode sim amor" / "Mas é o uber ida e volta, senão eu fico sem a volta rs"
    t3  "Poxa, é você que chama o uber amor, então sem pix rs"
    t4  "Confirmado" / "Te espero às 15h amor 🥰"

...e no t4 o DOMÍNIO virou `pix_status` para `aguardando`, e o cliente recebeu a bolha com a chave
de R$100 no mesmo turno em que ela disse "sem pix". O gate
`_solicitar_pix_deslocamento_se_aplicavel` decidia olhando só `estado`/`tipo_atendimento`/
`pix_status`: não existia campo nenhum, em lugar nenhum do sistema, dizendo QUEM paga a corrida.

O fato é dito no t2 e o gate dispara no t4 — por isso o carimbo é PERSISTIDO (coluna
`atendimentos.deslocamento_por_conta_do_cliente`, migration 20260814175416) e não inferido do texto
do turno corrente: no turno do disparo o assunto já saiu da janela.

Os três eixos, todos com controle negativo:
  A. o gate do domínio (o defeito em si) — e a reserva de agenda, que NÃO pode cair junto;
  B. o UPSERT da extração (o tri-estado que atravessa os turnos);
  C. o prompt (senão ela reanuncia a chave nos turnos seguintes).

Offline: sem DB e sem crédito.
"""

import dataclasses as dc
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from barra.agente.ferramentas.extracao import ExtracaoPayload
from barra.agente.nos._contexto_do_turno import ContextoDoTurno
from barra.agente.persona import render_contexto_dinamico
from barra.dominio.atendimentos.service import (
    _CAMPOS_UPSERT,
    _montar_upsert,
    _solicitar_pix_deslocamento_se_aplicavel,
)

_AGORA = datetime(2026, 8, 14, 18, 0, tzinfo=UTC)
_BLOQUEIO = UUID("44444444-4444-4444-4444-444444444444")


# ---------------------------------------------------------------------------------------------
# A. o gate determinístico do Pix
# ---------------------------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeConn:
    """Devolve a linha do atendimento no primeiro SELECT e registra todo SQL que passar.

    O gate faz exatamente uma leitura; o que vem depois (UPDATE do `pix_status`, INSERT do evento)
    é escrita, e é a PRESENÇA dessas escritas que o teste afirma ou nega.
    """

    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row
        self.sqls: list[str] = []

    async def execute(self, sql: str, params: Any = None) -> _FakeResult:
        self.sqls.append(" ".join(sql.split()))
        return _FakeResult(self._row if sql.lstrip().upper().startswith("SELECT") else None)


def _atendimento(**over: Any) -> dict[str, Any]:
    """O externo do cenário no turno do disparo: hora combinada, Pix ainda não pedido."""
    base: dict[str, Any] = {
        "id": uuid4(),
        "modelo_id": uuid4(),
        "estado": "Aguardando_confirmacao",
        "tipo_atendimento": "externo",
        "pix_status": "nao_solicitado",
        "bloqueio_id": _BLOQUEIO,
        "data_desejada": None,
        "horario_desejado": None,
        "duracao_horas": None,
        "valor_acordado": None,
        "deslocamento_por_conta_do_cliente": None,
    }
    return {**base, **over}


async def _rodar(atendimento: dict[str, Any]) -> tuple[dict[str, Any], _FakeConn]:
    conn = _FakeConn(atendimento)
    extra: dict[str, Any] = {}
    await _solicitar_pix_deslocamento_se_aplicavel(
        conn,  # type: ignore[arg-type]
        atendimento["id"],
        extra,
        agora=_AGORA,
    )
    return extra, conn


def _pediu_pix(extra: dict[str, Any], conn: _FakeConn) -> bool:
    """As duas metades do pedido, que andam sempre juntas: a marca no banco e o sinal que o
    coordenador lê para anexar a bolha com a chave (`_SQL_PIX_DO_TURNO` casa
    `resultado->>'pix_solicitado' = 'true'`)."""
    marcou = any("SET pix_status = 'aguardando'" in s for s in conn.sqls)
    assert marcou == bool(extra.get("pix_solicitado")), "banco e resultado da tool discordaram"
    return marcou


async def test_externo_normal_continua_pedindo_o_pix() -> None:
    """CONTROLE NEGATIVO — o caminho que NÃO pode mudar.

    Externo em que ninguém falou de quem chama o uber (coluna NULL, o estado de todo atendimento
    anterior à migration): a corrida é dela, o Pix é adiantado, tudo como sempre foi.
    """
    extra, conn = await _rodar(_atendimento())

    assert _pediu_pix(extra, conn) is True
    assert extra["pix_valor"]


async def test_externo_com_a_corrida_por_conta_dele_nao_pede_o_pix() -> None:
    """O defeito: ele chama e paga o ida e volta, então não há o que adiantar.

    Sem `pix_solicitado` no resultado da tool o coordenador não acha a linha de
    `_SQL_PIX_DO_TURNO` — e a bolha com a chave, que é o que chegava ao cliente junto do "então
    sem pix rs", simplesmente não é anexada.
    """
    extra, conn = await _rodar(_atendimento(deslocamento_por_conta_do_cliente=True))

    assert _pediu_pix(extra, conn) is False
    assert "pix_valor" not in extra
    assert not any("pix_solicitado" in s for s in conn.sqls), (
        "gravou o evento de um Pix que não foi"
    )


async def test_ele_devolvendo_a_corrida_o_pix_volta() -> None:
    """CONTROLE NEGATIVO do tri-estado: `False` não é "desconhecido", é retratação dele
    ("pode chamar você mesma"). A corrida voltou a ser dela — o Pix volta com ela."""
    extra, conn = await _rodar(_atendimento(deslocamento_por_conta_do_cliente=False))

    assert _pediu_pix(extra, conn) is True


async def test_a_marca_dispensa_o_pix_mas_nao_a_reserva_de_agenda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Por que o early-return mora DEPOIS de `criar_bloqueio_previo` e não no topo da função.

    A reserva do slot do externo-Uber só acontece dentro deste gate — o bloco da transição
    (`registrar_extracao_ia`) exclui `externo` de propósito. Retornar antes dela deixaria o
    encontro combinado SEM slot bloqueado, e todo o trilho que depende de `bloqueio_id`
    (remarcação segura, liberação da reserva, buffer de deslocamento) passaria a se comportar como
    se não houvesse encontro. O que a corrida dele dispensa é o PIX, nunca a agenda.
    """
    chamadas: list[dict[str, Any]] = []

    async def _fake_criar_bloqueio_previo(
        conn: Any, *, atendimento: dict[str, Any], agora: Any = None
    ) -> None:
        chamadas.append(atendimento)

    monkeypatch.setattr(
        "barra.dominio.agenda.service.criar_bloqueio_previo", _fake_criar_bloqueio_previo
    )

    extra, conn = await _rodar(
        _atendimento(bloqueio_id=None, deslocamento_por_conta_do_cliente=True)
    )

    assert len(chamadas) == 1, "a reserva de agenda do externo caiu junto com o Pix"
    assert _pediu_pix(extra, conn) is False


async def test_remoto_ignora_a_marca() -> None:
    """CONTROLE NEGATIVO do escopo: no remoto (ADR-0029) o Pix é o valor da CHAMADA, não
    transporte — ninguém se desloca, e o campo não tem sentido lá. Uma marca herdada de um turno
    em que o atendimento era externo não pode desligar a cobrança da vídeo chamada."""
    extra, conn = await _rodar(
        _atendimento(
            tipo_atendimento="remoto",
            valor_acordado=400,
            deslocamento_por_conta_do_cliente=True,
        )
    )

    assert _pediu_pix(extra, conn) is True
    assert extra["pix_valor"] == "400"


# ---------------------------------------------------------------------------------------------
# B. o UPSERT: o carimbo tem de ATRAVESSAR os turnos (ele diz no t2, o gate roda no t4)
# ---------------------------------------------------------------------------------------------


def test_campo_omitido_nao_apaga_o_carimbo_do_turno_anterior() -> None:
    """O coração da correção. `None` é o default do arg, então `exclude_defaults` o tira do
    payload e o UPSERT nem toca a coluna — o "sim" do t2 sobrevive ao t3 mudo e chega ao t4.

    Com um `bool = False` (o formato dos outros dois booleanos da tool) todo turno em que ninguém
    falasse de transporte REGRAVARIA `False`, e o carimbo morreria antes do gate: o defeito de
    volta, agora com campo novo.
    """
    payload = ExtracaoPayload(proxima_acao_esperada="confirmar o horário")
    dados = payload.model_dump(mode="json", exclude_defaults=True)

    assert "deslocamento_por_conta_do_cliente" not in dados

    sets, _valores = _montar_upsert(dados, set())

    assert not any("deslocamento_por_conta_do_cliente" in s for s in sets)


@pytest.mark.parametrize("valor", [True, False])
def test_declaracao_explicita_grava_os_dois_sentidos(valor: bool) -> None:
    """`True` (ele chama) e `False` (ele devolveu a corrida) são declarações dele e as duas
    escrevem — só a AUSÊNCIA preserva."""
    payload = ExtracaoPayload(
        proxima_acao_esperada="confirmar o horário", deslocamento_por_conta_do_cliente=valor
    )
    dados = payload.model_dump(mode="json", exclude_defaults=True)

    sets, valores = _montar_upsert(dados, set())

    assert "deslocamento_por_conta_do_cliente = %s" in sets
    assert valores[sets.index("deslocamento_por_conta_do_cliente = %s")] is valor


def test_limpar_devolve_o_campo_a_desconhecido() -> None:
    """`limpar` continua sendo o canal de retratação genérico: NULL = ninguém tocou no assunto,
    e o gate volta ao comportamento padrão (pede o Pix)."""
    sets, _valores = _montar_upsert(
        {"deslocamento_por_conta_do_cliente": True}, {"deslocamento_por_conta_do_cliente"}
    )

    assert "deslocamento_por_conta_do_cliente = NULL" in sets


def test_o_campo_tem_coluna_no_upsert() -> None:
    """Amarra os dois nomes: o arg da tool e a coluna do UPSERT são a MESMA string — `_CAMPOS_UPSERT`
    monta o SQL por nome, então um rename só de um lado grava em silêncio no lugar nenhum."""
    assert "deslocamento_por_conta_do_cliente" in _CAMPOS_UPSERT
    assert "deslocamento_por_conta_do_cliente" in ExtracaoPayload.model_fields


# ---------------------------------------------------------------------------------------------
# C. o prompt: com o Pix fora da mesa ela não pode reanunciar a chave
# ---------------------------------------------------------------------------------------------

_NEUTRO: dict[str, Any] = {
    "agora": _AGORA,
    "data_atual": "2026-08-14",
    "hora_atual": "15:00",
    "escada_estado": "inteira",
    "estado": "Aguardando_confirmacao",
    "tipo_atendimento": "externo",
    "pix_status": "ainda não pedido",
}


def _contexto(**over: Any) -> ContextoDoTurno:
    """Preenchimento neutro dos campos obrigatórios (mesmo helper de
    `test_espelho_carimbo_template.py`): o que interessa entra por override."""
    valores: dict[str, Any] = {}
    for campo in dc.fields(ContextoDoTurno):
        if campo.default is not dc.MISSING or campo.default_factory is not dc.MISSING:
            continue
        if campo.name in _NEUTRO:
            valores[campo.name] = _NEUTRO[campo.name]
        elif campo.name in over:
            continue
        else:
            tipo = campo.type
            valores[campo.name] = (
                False
                if tipo is bool
                else 0
                if tipo in (int, float)
                else []
                if getattr(tipo, "__origin__", None) is list
                else None
            )
    return ContextoDoTurno(**{**valores, **over})


def _bloco_pix(**over: Any) -> str:
    texto = render_contexto_dinamico(**_contexto(**over).como_variaveis())
    inicio = texto.index("<pix_deslocamento")
    return texto[inicio : texto.index("</pix_deslocamento>")]


def test_bloco_dispensado_tira_o_pix_da_mesa() -> None:
    """Sem isto o `<pix_deslocamento>` seguiria mandando "a sua parte é o valor do uber e o aviso
    de que a chave vem" — ela reanunciaria, turno após turno, um Pix que o sistema já não cobra, e
    o contexto contradiria a própria fala dela ("então sem pix rs")."""
    bloco = _bloco_pix(pix_deslocamento_dispensado=True)

    assert 'status="dispensado"' in bloco
    assert "NÃO existe Pix de deslocamento" in bloco
    # O que NÃO se perde junto: o ida e volta é condição dela, não uma exigência do Pix.
    assert "IDA E VOLTA" in bloco


def test_externo_sem_a_marca_mantem_o_bloco_de_sempre() -> None:
    """CONTROLE NEGATIVO do prompt: o externo normal continua lendo a conduta da chave."""
    bloco = _bloco_pix()

    assert 'status="dispensado"' not in bloco
    assert "A chave Pix quem despacha é o sistema" in bloco


def test_chave_ja_despachada_nao_vira_dispensado() -> None:
    """O cruzamento que o `prepare_context` compõe (`pix_deslocamento_dispensado` = a marca E o
    Pix ainda não pedido): decidido DEPOIS de a bolha ter saído, o dispensado mandaria "não peça
    comprovante" com a chave já nas mãos do cliente — possivelmente já paga. Aí vale a conduta de
    sempre, que é também o que o domínio faz (o gate só olha a coluna enquanto `pix_status` é
    'nao_solicitado')."""
    bloco = _bloco_pix(
        deslocamento_por_conta_do_cliente=True,
        pix_deslocamento_dispensado=False,
        pix_status="aguardando comprovante",
    )

    assert 'status="dispensado"' not in bloco
    assert "não reanuncie" in bloco


def test_bloco_do_extrator_mostra_o_carimbo_para_ele_poder_corrigir() -> None:
    """O `<ja_registrado>` é o único lugar em que o EXTRATOR vê o que está gravado. Sem o campo
    ali ele não tem como enxergar a RETRATAÇÃO ("pode chamar você mesma"), que exige regravar
    `False` — campo invisível no bloco de estado é campo que ninguém corrige."""
    from barra.agente.persona import render_ja_registrado

    ligado = render_ja_registrado(deslocamento_por_conta_do_cliente=True)
    desligado = render_ja_registrado(deslocamento_por_conta_do_cliente=False)

    assert "<deslocamento_por_conta_do_cliente>" in ligado
    assert "false" in ligado, "o extrator precisa saber COMO desfazer o carimbo"
    assert "<deslocamento_por_conta_do_cliente>" not in desligado
