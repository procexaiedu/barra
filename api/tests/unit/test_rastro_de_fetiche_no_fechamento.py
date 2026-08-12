"""Rastro do fetiche da conversa até o fechamento (pendência 4 do ADR-0030).

A extração registra `fetiches_em_pauta` (nomes do CADASTRO da modelo) e o fechamento materializa
`atendimento_fetiches` com `preco_snapshot = extra_de_fetiche(...)` — o mesmo site de conta do
painel, para o breakdown dizer que parte do `valor_final` era extra (achado 10c do diagnóstico de
11/08/2026: R$800 com 1h chegava sem contar que R$350 eram a Inversão).

Sem DB e sem crédito: um FakeConn responde as queries por fragmento do SQL.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from barra.agente.ferramentas.extracao import ExtracaoPayload, registrar_extracao
from barra.dominio.atendimentos.service import registrar_fetiches_do_fechamento

_ATENDIMENTO = UUID("11111111-1111-1111-1111-111111111111")
_MODELO = UUID("22222222-2222-2222-2222-222222222222")
_PROGRAMA = uuid4()
_INVERSAO = uuid4()
_BEIJO = uuid4()
_MENAGE = uuid4()
_GARGANTA = uuid4()


class _Result:
    def __init__(self, rows: list[dict[str, Any]], rowcount: int = 0) -> None:
        self._rows = rows
        self.rowcount = rowcount

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Responde por fragmento do SQL; guarda os INSERTs em `inseridos`.

    `ja_vinculados` simula a UNIQUE (atendimento_id, fetiche_id): um par já presente devolve
    rowcount 0, exatamente como o `ON CONFLICT DO NOTHING` faria.
    """

    def __init__(
        self,
        *,
        turnos: list[list[str]],
        cardapio: list[dict[str, Any]],
        servicos: list[dict[str, Any]] | None = None,
        duracao_horas: Decimal | None = None,
        precos_tabela: tuple[Decimal | None, Decimal | None] = (None, None),
        uma_hora: Decimal | None = None,
        ja_vinculados: set[Any] | None = None,
    ) -> None:
        self.turnos = turnos
        self.cardapio = cardapio
        self.servicos = servicos or []
        # O que o extra derivado PODE ler: a duracao fechada, o(s) preco(s) de tabela da modelo
        # naquela duracao e a linha de 1h do programa vendido (ADR-0038). `valor_acordado` NAO e
        # consultado -- se algum dia voltar a ser, a query cai no `AssertionError` de `execute`.
        self.duracao_horas = duracao_horas
        self.precos_tabela = precos_tabela
        self.uma_hora = uma_hora
        self.ja_vinculados = ja_vinculados or set()
        self.inseridos: list[tuple[Any, Decimal | None]] = []

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        if "fetiches_em_pauta" in sql:
            return _Result([{"nomes": nomes} for nomes in self.turnos])
        if "modelo_fetiches" in sql:
            return _Result(self.cardapio)
        if "atendimento_servicos" in sql:
            return _Result(self.servicos)
        if "SELECT modelo_id, duracao_horas" in sql:
            return _Result([{"modelo_id": _MODELO, "duracao_horas": self.duracao_horas}])
        if "mp.programa_id = %s" in sql:  # a linha de 1h daquele programa (ADR-0038)
            if self.uma_hora is None:
                return _Result([])
            return _Result([{"preco": self.uma_hora, "preco_minimo": None}])
        if "modelo_programas" in sql:
            menor, maior = self.precos_tabela
            linhas = [
                {"programa_id": _PROGRAMA, "preco": p, "preco_minimo": None}
                for p in (menor, maior)
                if p is not None
            ]
            return _Result(linhas)
        if "INSERT INTO barravips.atendimento_fetiches" in sql:
            _, fetiche_id, preco = params
            if fetiche_id in self.ja_vinculados:
                return _Result([], rowcount=0)
            self.ja_vinculados.add(fetiche_id)
            self.inseridos.append((fetiche_id, preco))
            return _Result([], rowcount=1)
        raise AssertionError(f"query nao esperada: {sql}")


def _cardapio() -> list[dict[str, Any]]:
    return [
        # Preço real cadastrado (o regime da Lucia): o extra é FIXO, independe da duração.
        {
            "fetiche_id": _INVERSAO,
            "nome": "Inversão",
            "preco": Decimal("350"),
            "cobra_por_pessoa": False,
        },
        # NULL = incluso: entra no rastro com snapshot NULL.
        {
            "fetiche_id": _BEIJO,
            "nome": "Beijo na boca",
            "preco": None,
            "cobra_por_pessoa": False,
        },
        # Sentinel de flag (`preco` < R$10): "pago" sem valor -> extra derivado. Composicao
        # (`cobra_por_pessoa`) deriva pela MESMA linha de 1h dos atos desde o ADR-0039 -- antes
        # ela dobrava o pacote e era o unico regime que dispensava a 1h.
        {
            "fetiche_id": _MENAGE,
            "nome": "Ménage",
            "preco": Decimal("1"),
            "cobra_por_pessoa": True,
        },
        # Sentinel de flag num ATO: o extra é a linha de 1h do programa vendido (ADR-0038).
        {
            "fetiche_id": _GARGANTA,
            "nome": "Garganta profunda",
            "preco": Decimal("1"),
            "cobra_por_pessoa": False,
        },
    ]


# --- o slot na extração ---------------------------------------------------------------------


def test_slot_existe_no_schema_da_tool_com_descricao_do_cardapio() -> None:
    """O extrator precisa VER o campo (e a regra do closed-world) no schema enviado ao LLM."""
    schema = registrar_extracao.args_schema
    assert schema is not None
    campo = schema.model_fields["fetiches_em_pauta"]
    assert campo.description is not None
    assert "cardápio" in campo.description or "tabela" in campo.description


def test_slot_ausente_nao_entra_no_payload_gravado() -> None:
    """`exclude_defaults` mantém a lista vazia FORA do evento — turno sem fetiche não escreve
    chave nenhuma, e o fechamento não tem o que resolver."""
    payload = ExtracaoPayload(proxima_acao_esperada="seguir qualificando")
    assert "fetiches_em_pauta" not in payload.model_dump(mode="json", exclude_defaults=True)
    payload = ExtracaoPayload(proxima_acao_esperada="cotar", fetiches_em_pauta=["Inversão"])
    dados = payload.model_dump(mode="json", exclude_defaults=True)
    assert dados["fetiches_em_pauta"] == ["Inversão"]


# --- a gravação no fechamento ---------------------------------------------------------------


async def test_preco_cadastrado_vira_snapshot_fixo() -> None:
    """Inversão a R$350 com pacote de 1h/R$450: o snapshot é o CADASTRO (350), não o preço-hora
    do pacote — é a divergência que fez o cliente responder "não era 750?"."""
    conn = _FakeConn(
        turnos=[["Inversão"]],
        cardapio=_cardapio(),
        duracao_horas=Decimal("1"),
        precos_tabela=(Decimal("450"), Decimal("450")),
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 1  # type: ignore[arg-type]
    assert conn.inseridos == [(_INVERSAO, Decimal("350"))]


async def test_fetiche_incluso_grava_snapshot_nulo() -> None:
    conn = _FakeConn(turnos=[["beijo na boca"]], cardapio=_cardapio())
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 1  # type: ignore[arg-type]
    assert conn.inseridos == [(_BEIJO, None)]


async def test_sentinel_de_flag_cai_no_fallback_derivado_da_linha_de_uma_hora() -> None:
    """`preco=1` é a flag "pago" do painel, não um valor: o extra vem da linha de 1h do programa
    vendido. Ménage é `cobra_por_pessoa` e desde o ADR-0039 passa por essa MESMA conta — 400 (a
    1h), nunca os 800 do pacote inteiro que o regime "dobra" gravava."""
    conn = _FakeConn(
        turnos=[["Ménage"]],
        cardapio=_cardapio(),
        duracao_horas=Decimal("2"),
        precos_tabela=(Decimal("800"), None),
        uma_hora=Decimal("400"),
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 1  # type: ignore[arg-type]
    assert conn.inseridos == [(_MENAGE, Decimal("400"))]


async def test_composicao_sem_linha_de_uma_hora_e_descartada() -> None:
    """Caminho de descarte NOVO do ADR-0039. O regime antigo (o pacote inteiro) não dependia da
    1h e gravava; agora a composição some pelo mesmo fail-closed dos atos, com o warning."""
    conn = _FakeConn(
        turnos=[["Ménage"]],
        cardapio=_cardapio(),
        duracao_horas=Decimal("2"),
        precos_tabela=(Decimal("800"), None),
        uma_hora=None,
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 0  # type: ignore[arg-type]
    assert conn.inseridos == []


async def test_pacote_vem_de_atendimento_servicos_quando_o_painel_registrou() -> None:
    """Mesma base do painel (`routes.py:adicionar_fetiche`): serviço registrado tem precedência
    sobre o que a `duracao_horas` do atendimento diria.

    O discriminador é a PORTA da duração: o serviço vendido é o pernoite (12h, elegível) e a
    `duracao_horas` do atendimento é meia hora (não leva fetiche pago). Se a precedência
    invertesse, o Ménage seria descartado em vez de gravado.
    """
    conn = _FakeConn(
        turnos=[["Ménage"]],
        cardapio=_cardapio(),
        servicos=[
            {
                "programa_id": _PROGRAMA,
                "preco_snapshot": Decimal("3600"),
                "horas": Decimal("12"),
            }
        ],
        duracao_horas=Decimal("0.5"),
        precos_tabela=(Decimal("250"), None),
        uma_hora=Decimal("400"),
    )
    await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO)  # type: ignore[arg-type]
    assert conn.inseridos == [(_MENAGE, Decimal("400"))]


async def test_nome_fora_do_cadastro_e_descartado_em_silencio() -> None:
    """Closed-world: o extrator alucinou um item que a modelo não tem — nada é gravado (só o
    warning), e os nomes válidos do MESMO turno seguem entrando."""
    conn = _FakeConn(
        turnos=[["Chuva dourada", "Inversão"]],
        cardapio=_cardapio(),
        duracao_horas=Decimal("1"),
        precos_tabela=(Decimal("400"), Decimal("400")),
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 1  # type: ignore[arg-type]
    assert conn.inseridos == [(_INVERSAO, Decimal("350"))]


async def test_nome_casa_sem_acento_e_sem_caixa() -> None:
    """O extrator escreve "inversao"; o cadastro diz "Inversão" — mesmo item."""
    conn = _FakeConn(
        turnos=[["  INVERSAO "]],
        cardapio=_cardapio(),
        duracao_horas=Decimal("1"),
        precos_tabela=(Decimal("400"), Decimal("400")),
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 1  # type: ignore[arg-type]
    assert conn.inseridos == [(_INVERSAO, Decimal("350"))]


async def test_slot_ausente_nao_grava_nada() -> None:
    """Nenhum evento com o slot: o fechamento nem consulta o cardápio."""
    conn = _FakeConn(turnos=[], cardapio=_cardapio())
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 0  # type: ignore[arg-type]
    assert conn.inseridos == []


async def test_mesmo_nome_em_varios_turnos_grava_uma_linha_so() -> None:
    """A leitura é a UNIÃO dos turnos (monotônica): repetir o pedido não vira duas linhas."""
    conn = _FakeConn(
        turnos=[["Inversão"], ["inversao", "Beijo na boca"]],
        cardapio=_cardapio(),
        duracao_horas=Decimal("1"),
        precos_tabela=(Decimal("400"), Decimal("400")),
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 2  # type: ignore[arg-type]
    assert conn.inseridos == [(_INVERSAO, Decimal("350")), (_BEIJO, None)]


async def test_fechamento_reexecutado_nao_duplica() -> None:
    """Idempotência pela UNIQUE (atendimento_id, fetiche_id) + ON CONFLICT DO NOTHING: a segunda
    passada não insere nada — inclusive o vínculo que Fernando já tenha feito à mão no painel,
    com o preço que ELE decidiu, fica de pé."""
    conn = _FakeConn(
        turnos=[["Inversão"]],
        cardapio=_cardapio(),
        duracao_horas=Decimal("1"),
        precos_tabela=(Decimal("450"), Decimal("450")),
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 1  # type: ignore[arg-type]
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 0  # type: ignore[arg-type]
    assert conn.inseridos == [(_INVERSAO, Decimal("350"))]


async def test_pago_sem_preco_e_sem_pacote_nao_grava_linha_mentirosa() -> None:
    """Sem cadastro e sem pacote não há extra a derivar — gravar NULL diria "incluso", que é
    falso. Fica de fora (warning), e os outros itens do turno seguem."""
    conn = _FakeConn(
        turnos=[["Ménage", "Beijo na boca"]],
        cardapio=_cardapio(),
        duracao_horas=None,
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 1  # type: ignore[arg-type]
    assert conn.inseridos == [(_BEIJO, None)]


# --- a base do fallback derivado é o PREÇO DE TABELA, nunca o Valor final --------------------


async def test_fallback_deriva_da_tabela_e_nao_do_valor_acordado() -> None:
    """O caso motivador do ADR-0030: R$800 fechados = pacote de R$400 (1h) + a Inversão.

    `valor_acordado` é o Valor FINAL (já traz extra e desconto dentro) e não pode ser base de
    nada — usá-lo inflaria o próprio extra. O `_FakeConn` nem responde `valor_acordado`: se a
    query voltar, o teste estoura.
    """
    conn = _FakeConn(
        turnos=[["Ménage"]],
        cardapio=_cardapio(),
        duracao_horas=Decimal("1"),
        precos_tabela=(Decimal("400"), None),
        uma_hora=Decimal("400"),
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 1  # type: ignore[arg-type]
    # A 1h da TABELA: 400. Nunca 800 (que era o Valor final).
    assert conn.inseridos == [(_MENAGE, Decimal("400"))]


async def test_duracao_sem_programa_na_tabela_descarta_com_warning() -> None:
    """Fail-closed igual ao teto/degrau: sem programa naquela duração não há preço de tabela."""
    conn = _FakeConn(
        turnos=[["Ménage", "Beijo na boca"]],
        cardapio=_cardapio(),
        duracao_horas=Decimal("1"),
        precos_tabela=(None, None),
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 1  # type: ignore[arg-type]
    assert conn.inseridos == [(_BEIJO, None)]


async def test_ato_derivado_grava_a_linha_de_uma_hora_do_programa() -> None:
    """ADR-0038: ato pago sem preço cadastrado vale a 1h do MESMO programa — R$400 no pernoite de
    R$2.000, o mesmo que valeria na 1h. O preço-hora de antes gravaria R$167."""
    conn = _FakeConn(
        turnos=[["Garganta profunda"]],
        cardapio=_cardapio(),
        duracao_horas=Decimal("12"),
        precos_tabela=(Decimal("2000"), None),
        uma_hora=Decimal("400"),
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 1  # type: ignore[arg-type]
    assert conn.inseridos == [(_GARGANTA, Decimal("400"))]


async def test_ato_derivado_sem_linha_de_uma_hora_descarta_com_warning() -> None:
    """Fail-closed do ADR-0038: o extra É a uma hora. Programa sem ela cadastrada não tem extra —
    e gravar NULL diria "incluso". Fica de fora; os outros itens do turno seguem."""
    conn = _FakeConn(
        turnos=[["Garganta profunda", "Beijo na boca"]],
        cardapio=_cardapio(),
        duracao_horas=Decimal("2"),
        precos_tabela=(Decimal("800"), None),
        uma_hora=None,
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 1  # type: ignore[arg-type]
    assert conn.inseridos == [(_BEIJO, None)]


async def test_duracao_com_mais_de_um_preco_de_tabela_descarta_com_warning() -> None:
    """Dois programas com preços diferentes na mesma duração: não dá para dizer QUAL foi vendido,
    então não se inventa base (mesma condição de `teto_de_contraproposta`)."""
    conn = _FakeConn(
        turnos=[["Ménage"]],
        cardapio=_cardapio(),
        duracao_horas=Decimal("1"),
        precos_tabela=(Decimal("400"), Decimal("600")),
    )
    assert await registrar_fetiches_do_fechamento(conn, _ATENDIMENTO) == 0  # type: ignore[arg-type]
    assert conn.inseridos == []
