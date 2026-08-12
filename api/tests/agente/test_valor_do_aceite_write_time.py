"""ADR-0040 no write-time: a venda fechada no número DELE vira `valor_acordado` lendo a BOLHA.

O caso vivo (trace 93fa67dd, sessão 4833f23e): a IA cotou 800 por 2h, o cliente disse "faz 700 que
eu vou" e ela aceitou ("Tabom, 700 então / Te espero às 20h amor") — conduta certa, `preco_minimo`
600. O banco ficou com `estado=Aguardando_confirmacao`, `n_contrapropostas=1`, `duracao_horas=2`,
`horario_desejado=20:00` e **`valor_acordado=None`**. A causa é estrutural, não um caso isolado do
aceite: a ordem dos nós é `llm` → `extrair` → `output_guard`, e a janela da extração exclui por
contrato a fala da IA do turno corrente — ela viu só o 700 DELE e o registrou como algo a avaliar
("proxima_acao_esperada: Avaliar a contraproposta de 700 do cliente"). Do ponto de vista dela não
havia aceite nenhum. Sempre que o valor da venda for decidido pela FALA DA IA do próprio turno, a
extração é cega para ele.

O conserto usa a porta que já funcionou no MESMO turno: `n_contrapropostas` andou para 1 porque é
carimbado no write-time (`workers/envio.py`), lendo a bolha depois de pronta. O valor vai pela mesma
porta, com um predicado de DUAS pernas:

  (a) `valor_dele_no_prompt` — o carimbo do `<valor_dele_serve>` deste turno (prepare_context →
      State). O sistema já provou, contra a tabela, que o número é DELE e cai em `[piso, mesa)`;
  (b) o número saindo como OFERTA na bolha DESPACHADA (`precos_ofertados_na_fala`, que descarta
      cláusula negada).

Nenhuma das duas basta sozinha, e é isso que separa aceite de menção — sem (a), "acima do piso"
viraria prova de aceite, que é exatamente o bug do valor fantasma (a IA RECUSOU 300, acima do piso,
e o extrator gravou 300); sem (b), bastaria o sistema ter MANDADO aceitar.

Aqui roda o `enviar_turno` REAL contra fakes (sem rede, sem DB): o que se prova é o predicado e o
ponto de leitura — a bolha que o Evolution de fato mandou.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis

from barra.workers.envio import enviar_turno


class _RngMantem:
    """rng determinístico p/ os thinnings de voz (emoji/vocativo): 0.0 < keep → sempre mantém."""

    def random(self) -> float:
        return 0.0


@pytest.fixture(autouse=True)
def _sem_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _noop)
    monkeypatch.setattr("barra.workers._saida_guard._RNG", _RngMantem())
    yield


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.rowcount = len(rows)

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConn:
    """Responde `_carregar_destino` e o INSERT da bolha COM `RETURNING 1` (o `inseriu` do write-time
    depende dele — sem a linha de volta nenhuma flag é carimbada) e registra os UPDATEs que tocam
    `valor_acordado`."""

    def __init__(self, destino: dict[str, Any]) -> None:
        self._destino = destino
        self.valores_gravados: list[int] = []

    async def execute(self, query: str, params: Any = None) -> _Result:
        if "FROM barravips.conversas" in query:
            return _Result([self._destino])
        if "FROM barravips.mensagens" in query and "direcao = 'cliente'" in query:
            return _Result([])
        if "INSERT INTO barravips.mensagens" in query:
            return _Result([{"?column?": 1}])  # inseriu de verdade (não é retry)
        if "UPDATE barravips.atendimentos" in query and "valor_acordado" in query:
            assert params is not None
            self.valores_gravados.append(int(params[0]))
            return _Result([{"ok": 1}])
        return _Result([])

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield None


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_FakeConn]:
        yield self._conn


class _FakeEvolution:
    def __init__(self) -> None:
        self.textos: list[str] = []
        self._n = 0

    async def marcar_lida(self, **_k: Any) -> None:
        return None

    async def set_presence(self, **_k: Any) -> None:
        return None

    async def enviar_texto(self, *, texto: str, **_k: Any) -> str:
        self._n += 1
        self.textos.append(texto)
        return f"mid-{self._n}"

    async def enviar_midia(self, **_k: Any) -> str:  # pragma: no cover - sem mídia nestes casos
        raise AssertionError("estes casos não mandam mídia")


def _destino() -> dict[str, Any]:
    return {
        "evolution_instance_id": "inst-1",
        "evolution_chat_id": "5521999@s.whatsapp.net",
        "atendimento_id": uuid4(),
        "ia_pausada": False,
        "endereco_formatado": None,
        "nome_local": None,
        "localizacao_operacional": None,
    }


async def _despachar(
    chunks: list[str], *, valor_dele_no_prompt: int | None
) -> tuple[list[int], list[str]]:
    """Roda o `enviar_turno` real e devolve (valores gravados, bolhas que saíram no Evolution)."""
    turno_id, conversa_id = f"turno-{uuid4().hex}", str(uuid4())
    conn = _FakeConn(_destino())
    evolution = _FakeEvolution()
    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)
    ctx: dict[str, Any] = {
        "redis": redis,
        "db_pool": _FakePool(conn),
        "evolution": evolution,
        "minio": None,
    }
    await enviar_turno(
        ctx,
        conversa_id=conversa_id,
        turno_id=turno_id,
        chunks=chunks,
        midias=[],
        msg_ids_cliente=["evo-1"],
        chars_inbound=20,
        critico=False,
        valor_dele_no_prompt=valor_dele_no_prompt,
    )
    return conn.valores_gravados, evolution.textos


# --- o aceite grava, em qualquer forma natural do sim -----------------------------------------


@pytest.mark.parametrize(
    "bolhas",
    [
        # a fala do trace, e as duas outras ilustrações do <valor_dele_serve>. A FORMA é livre de
        # propósito (prescrever UMA frase foi recusado pelo dono do produto: vira tique) — quem
        # tem de estar lá é o NÚMERO, colado num token de fechamento ou de concessão.
        ["Tabom, 700 então", "Te espero às 20h amor"],
        ["Fechado 700 amor", "Consigo às 21h, fecha ?"],
        ["Faço 700 sim", "Seria que horas ?"],
        ["Consigo 700 sim amor", "Te espero às 22h"],
    ],
)
async def test_aceite_do_valor_dele_vira_valor_acordado(bolhas: list[str]) -> None:
    """Cliente propôs 700 sobre os 800 cotados (piso 600) e ela aceitou: a venda existe no banco."""
    gravados, _ = await _despachar(bolhas, valor_dele_no_prompt=700)
    assert gravados == [700]


async def test_grava_uma_vez_so_mesmo_com_o_numero_em_duas_bolhas() -> None:
    """O número repetido no turno não vira duas escritas: o UPDATE é por valor (`IS DISTINCT
    FROM`), e o segundo passa a ser no-op no banco — aqui a garantia é que o predicado é por bolha
    e o valor gravado é sempre o MESMO número, nunca um segundo."""
    gravados, _ = await _despachar(
        ["Tabom, 700 então", "Fechado 700 amor"], valor_dele_no_prompt=700
    )
    assert set(gravados) == {700}


# --- o que NÃO pode gravar ---------------------------------------------------------------------


async def test_cotacao_normal_nao_grava_valor() -> None:
    """ "400 1h no meu local" não é aceite de nada — é a cotação canônica. Sem o carimbo do
    `<valor_dele_serve>` o caminho nem arma, que é o estado de QUASE TODO turno: o bloco só entra
    quando o cliente nomeou um número que já serve."""
    gravados, _ = await _despachar(["400 1h no meu local"], valor_dele_no_prompt=None)
    assert gravados == []


async def test_cotacao_de_outro_numero_nao_grava_o_valor_do_aceite() -> None:
    """Mesmo com o bloco no prompt mandando aceitar 700, uma bolha que só COTA outro número não
    fecha venda nenhuma: o predicado exige o número DELE saindo na fala, não um preço qualquer."""
    gravados, _ = await _despachar(["400 1h no meu local"], valor_dele_no_prompt=700)
    assert gravados == []


async def test_recusa_nao_grava_valor() -> None:
    """ "não consigo 700 não" CITA o 700 e não OFERTA nada. É a lição do valor fantasma pelo
    avesso: ali o extrator gravou o 300 que a IA tinha acabado de recusar. A cláusula negada é
    filtrada dos dois lados (pt-BR nega antes e depois), então nem o sistema mandando aceitar
    transforma uma recusa em venda."""
    for recusa in (
        ["Poxa amor, não consigo 700 não"],
        ["Não consigo fechar 700 amor", "Meu valor é 800"],
    ):
        gravados, _ = await _despachar(recusa, valor_dele_no_prompt=700)
        assert gravados == [], recusa


async def test_valor_abaixo_do_piso_nao_entra_por_esta_porta() -> None:
    """O piso é julgado ANTES, na `aceite_do_valor_dele`: pedido abaixo dele devolve
    `abaixo_do_piso`, o `<valor_dele_serve>` não renderiza e o carimbo nasce None. Aqui a prova é
    que a porta do write-time não tem um segundo julgamento próprio para contradizer aquele — sem
    carimbo, mesmo uma bolha que aceita com todas as letras não grava."""
    gravados, _ = await _despachar(["Fechado 500 amor"], valor_dele_no_prompt=None)
    assert gravados == []


async def test_bolha_regenerada_vale_a_final_nao_a_descartada() -> None:
    """O output_guard descarta e regenera (no trace, a 1ª resposta caiu por repetição). O que vale
    é a bolha FINAL: a decisão é tomada DENTRO do laço de despacho, sobre o `conteudo` que foi ao
    Evolution — o rascunho descartado nem chega ao `enviar_turno`.

    O par abaixo é o discriminante: com o mesmo carimbo de 700, o rascunho que fecha num número
    inventado não grava nada e a regen que fecha no número DELE grava 700."""
    gravados_rascunho, _ = await _despachar(["Tabom, 650 então"], valor_dele_no_prompt=700)
    gravados_final, saiu = await _despachar(["Tabom, 700 então"], valor_dele_no_prompt=700)
    assert gravados_rascunho == []
    assert gravados_final == [700]
    assert saiu == ["Tabom, 700 então"]
