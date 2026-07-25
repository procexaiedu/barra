"""Janela dedicada da extração: o extrator para de ler o próprio belief-state como se fosse fala
do cliente (spec `.scratch/extracao-janela-dedicada/spec.md`).

Casos REAIS do piloto, pelo caminho de produção (harness fiel: `processar_turno` → `enviar_turno`)
com o GRAFO REAL e o chat do LLM substituído por um fake roteirizado — determinístico e SEM
consumir crédito (§0). O que se afirma é a ENTRADA que chega ao extrator (é o que a mudança
controla; o que o modelo faz com ela é assunto da bancada offline) e o que o Atendimento passa a
valer depois do turno:

  - #41 eco de tipo   -> o tipo combinado não aparece na conversa, só no bloco rotulado da cauda
  - mudança real      -> o horário novo do cliente é registrado e chega ao Atendimento
  - #25 palpite       -> a cauda rotula o horário como palpite e a omissão preserva o valor
  - conversa longa    -> acima do limiar do lembrete, a janela da extração é a mesma da curta

DB real (TEST_DATABASE_URL), ROLLBACK no teardown. `needs_db`, SEM `needs_key`.
"""

import os
from collections.abc import AsyncIterator
from datetime import datetime, time
from typing import Any

import pytest
import pytest_asyncio
from _chat_fake import ChatRoteirizado
from evals.harness import seedar
from evals.harness_fiel import rodar_turno_fiel
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.dominio.agenda.service import BRT
from barra.settings import get_settings

pytestmark = pytest.mark.needs_db

# Mesmo relógio dos outros testes de harness fiel: 00:30, dia inteiro livre à frente.
_AGORA = datetime(2026, 12, 1, 0, 30, tzinfo=BRT)


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    connection = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        yield connection
    finally:
        try:
            await connection.rollback()
        finally:
            await connection.close()


@pytest.fixture(autouse=True)
def _sem_output_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """O output-guard chama o LLM-judge de AUP (crédito real, §0) e, sem chave, bloqueia+escala por
    default seguro — pausaria a IA. Fora do escopo destes testes."""
    monkeypatch.setattr(get_settings(), "output_guard_habilitado", False)


async def _cenario(
    conn: AsyncConnection[dict[str, Any]], historico: list[dict[str, str]] | None = None, **kw: Any
) -> Any:
    return await seedar(
        conn,
        {
            "cenario": {
                "modelo": {"nome": "Lia"},
                "atendimento": {
                    "estado": "Qualificado",
                    "tipo_atendimento": "interno",
                    "cotacao_enviada": True,
                }
                | kw,
            },
            "historico": historico or [],
        },
    )


def _conversa_e_cauda(chat: ChatRoteirizado) -> tuple[str, str]:
    """Parte a janela dedicada do último turno em (conversa que o extrator leu, cauda de estado)."""
    janela = chat.janelas_extracao[-1]
    return "\n".join(str(m.content) for m in janela[:-1]), str(janela[-1].content)


async def _atendimento(
    conn: AsyncConnection[dict[str, Any]], atendimento_id: Any
) -> dict[str, Any]:
    res = await conn.execute(
        "SELECT estado, tipo_atendimento, horario_desejado, horario_evidenciado "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


# --- eco de tipo (#41) ------------------------------------------------------------------------


async def test_tipo_combinado_nao_chega_como_fala_ao_extrator(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#41: o tipo do encontro foi reafirmado em TODOS os turnos, inclusive nos que o cliente só
    falava de fetiche. Ele nunca disse nada sobre quem se desloca — o extrator estava lendo o
    belief colado na cauda. Agora o tipo só existe no bloco rotulado como estado do sistema."""
    cen = await _cenario(conn)
    chat = ChatRoteirizado(
        ["Faço sim amor 🥰"],
        [{"proxima_acao_esperada": "confirmar o horario"}],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(
            conn, cen, "atendimento so oral penetração ou com anal também", agora=_AGORA
        )

    conversa, cauda = _conversa_e_cauda(chat)
    assert "interno" not in conversa  # nada na conversa diz quem se desloca
    assert "<situacao_do_atendimento" not in conversa  # o belief não vem colado na fala dele
    assert "<lembrete_silencioso>" not in conversa
    assert "<tipo>interno</tipo>" in cauda
    assert "NÃO fala do cliente" in cauda and "só se ELE MUDOU" in cauda
    depois = await _atendimento(conn, cen.atendimento_id)
    assert depois["tipo_atendimento"] == "interno"  # extração sem tipo preserva o gravado
    assert depois["estado"] == "Qualificado"


# --- mudança real -----------------------------------------------------------------------------


async def test_mudanca_real_do_cliente_chega_ao_atendimento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O simétrico: cortar o eco não pode cortar a observação. O cliente pede outro horário e o
    campo é registrado normalmente."""
    cen = await _cenario(conn)
    await conn.execute(
        "UPDATE barravips.atendimentos SET horario_desejado = %s, data_desejada = %s WHERE id = %s",
        (time(16, 0), _AGORA.date(), cen.atendimento_id),
    )
    chat = ChatRoteirizado(
        ["Fechou amor, 20h 🥰"],
        [{"horario_desejado": "20:00", "proxima_acao_esperada": "confirmar o horario"}],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, "consegue às 20h?", agora=_AGORA)

    conversa, _cauda = _conversa_e_cauda(chat)
    assert "consegue às 20h?" in conversa  # a fala dele chega crua
    depois = await _atendimento(conn, cen.atendimento_id)
    assert depois["horario_desejado"] == time(20, 0)
    assert depois["horario_evidenciado"] is True  # hora explícita dele


# --- #25: o palpite do sistema volta rotulado -------------------------------------------------


async def test_palpite_do_sistema_volta_rotulado_e_a_omissao_preserva(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#25: o fallback de tempo imediato gravou 02:00 e o extrator mandou 02:00 no payload por três
    turnos — um valor sintetizado pelo sistema voltando carimbado como observação do cliente. O
    horário agora chega rotulado como palpite, fora da conversa; omiti-lo preserva o gravado."""
    cen = await _cenario(conn)
    await conn.execute(
        "UPDATE barravips.atendimentos SET horario_desejado = %s, data_desejada = %s, "
        "horario_evidenciado = false WHERE id = %s",
        (time(2, 0), _AGORA.date(), cen.atendimento_id),
    )
    chat = ChatRoteirizado(
        ["Faço sim amor 🥰"],
        [{"proxima_acao_esperada": "confirmar o horario"}],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, "vc faz massagem?", agora=_AGORA)

    conversa, cauda = _conversa_e_cauda(chat)
    assert "02:00" not in conversa  # o palpite não vem como fala
    assert "palpite do sistema" in cauda and "02:00" in cauda
    depois = await _atendimento(conn, cen.atendimento_id)
    assert depois["horario_desejado"] == time(2, 0)  # omitido = preservado (snapshot incremental)
    assert depois["horario_evidenciado"] is False


# --- conversa longa: sem variância por comprimento --------------------------------------------


async def test_conversa_longa_nao_muda_a_janela_da_extracao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Acima do limiar do lembrete de persona (≥8 falas da IA) o CHAT recebe o
    <lembrete_silencioso>; o extrator, que não fala com o cliente, recebe a mesma janela da
    conversa curta. Antes ele herdava conduta por acidente, só em conversa longa."""
    historico: list[dict[str, str]] = []
    for i in range(9):
        historico.append({"direcao": "cliente", "texto": f"pergunta {i}"})
        historico.append({"direcao": "ia", "texto": f"resposta {i} amor 🥰"})
    cen = await _cenario(conn, historico)
    chat = ChatRoteirizado(
        ["Faço sim amor 🥰"],
        [{"proxima_acao_esperada": "confirmar o horario"}],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, "vc faz massagem?", agora=_AGORA)

    assert "<lembrete_silencioso>" in chat.contexto_do_ultimo_turno()  # o chat recebeu
    conversa, cauda = _conversa_e_cauda(chat)
    assert "<lembrete_silencioso>" not in conversa  # o extrator, não
    assert "<situacao_do_atendimento" not in conversa
    assert "<ja_registrado>" in cauda
