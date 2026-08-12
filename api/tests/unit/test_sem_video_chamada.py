"""Trilho determinístico da vídeo chamada (issue 12 do refactor de prompt, ADR-0021/0029): modelo
sem a linha dela no <programas> injeta <sem_video_chamada> na cauda — a IA fica proibida por DADO,
não só por prosa, de oferecer/cotar/prometer uma chamada que a tabela dela não vende.

O gate era prosa em QUATRO sites do BP_GERAL (o parágrafo canônico do <tipos_de_encontro> mais três
condicionais negativas penduradas em outro assunto: book repetido e pedido de conteúdo no <midia>,
prova de humanidade no <protocolo_disclosure>) — prefixo byte-idêntico entre TODAS as modelos
(agente/CLAUDE.md), lido e descartado em todo turno de toda modelo que não vende chamada. Mesmo
padrão do <sem_periodo_longo>/<sem_menage>: a condição sai do CARDÁPIO (as linhas de programa que o
BP_MODELO já lê), não de um evento da conversa — por isso não é flag A2 materializada.
"""

from datetime import UTC, datetime
from typing import Any

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _carregar_bp3, _resolver_variaveis
from barra.agente.persona import (
    e_video_chamada,
    render_bloco_da_modelo,
    render_contexto_dinamico,
)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeConn:
    """Vazio em tudo: a ausência da chamada chega por kwarg (derivada dos programas já lidos em
    _carregar_bp3), não por query própria."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        return _Result([])


class _ConnCardapio:
    """Devolve o cardápio da modelo para `_carregar_bp3`: 1ª query = `modelos`, 2ª = programas,
    3ª = fetiches (a ordem das queries no nó)."""

    def __init__(self, programas: list[dict[str, Any]]) -> None:
        self._respostas = [
            [{"nome": "Manu", "idade": 25, "idiomas": [], "tipo_atendimento_aceito": ["interno"]}],
            programas,
            [],
        ]

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        return _Result(self._respostas.pop(0))


def _ctx() -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]  # não usado por _resolver_variaveis
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=datetime(2026, 7, 30, 23, 0, tzinfo=UTC),
    )


async def _contexto(sem_video_chamada: bool) -> Any:
    return await _resolver_variaveis(
        _FakeConn(),  # type: ignore[arg-type]
        _ctx(),
        atendimento={"numero_curto": 1, "estado": "Triagem", "tipo_atendimento": None},
        sem_video_chamada=sem_video_chamada,
    )


# --- a tag no bloco ESTÁTICO por-modelo ---------------------------------------------------------
#
# Hoist de custo (diagnóstico de traces 11/08): a tag é função SÓ do cadastro dela — nunca do
# turno — e passou da cauda volátil (re-enviada como cache-MISS a cada turno) para a 3ª
# SystemMessage do prefixo, `render_bloco_da_modelo`, que o DeepSeek cacheia. O que estes testes
# provam continua o mesmo e é o que importa pra segurança: a NEGAÇÃO ATIVA chega ao prompt final
# quando o cadastro não oferece — só mudou o bloco em que ela viaja. Cada teste positivo checa
# também que a tag SAIU da cauda (o byte que o hoist economiza).


async def test_sem_o_programa_injeta_a_tag_com_a_recusa_e_a_saida() -> None:
    variaveis = (await _contexto(True)).como_variaveis()
    saida = render_bloco_da_modelo(**variaveis)

    assert "<sem_video_chamada>" in saida
    assert "<sem_video_chamada>" not in render_contexto_dinamico(**variaveis)
    # A recusa que o roteiro `video_chamada_sem_programa` cobra, com a guarda de negação do
    # checker: a fala é "Não faço chamada amor", não a oferta.
    assert "Não faço chamada amor" in saida
    # E a fala de SUBSTITUIÇÃO junto da proibição (lição do incidente #36): a prova é a foto, e o
    # encontro segue. Proibir sem dar saída foi o que produziu o incidente.
    assert "FOTO" in saida
    assert "<midia>" in saida
    # A oferta que o <exemplo> de prova de humanidade traz por extenso — o exemplo concreto venceu
    # a prosa uma vez (corrida do conduta_gate 30/07), então a tag o desmonta com as mesmas palavras.
    assert "não é fala sua" in saida


async def test_com_o_programa_o_prompt_nao_diz_nada_de_chamada() -> None:
    variaveis = (await _contexto(False)).como_variaveis()

    assert "<sem_video_chamada>" not in render_bloco_da_modelo(**variaveis)
    assert "<sem_video_chamada>" not in render_contexto_dinamico(**variaveis)


# --- a condição: as MESMAS linhas de programa que o <programas> do BP_MODELO renderiza ----------


async def _sem_video_chamada_do_cardapio(programas: list[dict[str, Any]]) -> bool:
    (
        _md,
        _nome,
        _max,
        _vazio,
        _menage,
        sem_video_chamada,
        _externo,
        _end,
        _local,
        _precos,
        _cardapio,
    ) = await _carregar_bp3(
        _ConnCardapio(programas),  # type: ignore[arg-type]
        "11111111-1111-1111-1111-111111111111",
    )
    return sem_video_chamada


def _programa(nome: str) -> dict[str, Any]:
    return {"nome": nome, "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 400}


async def test_tabela_so_de_encontro_mantem_a_tag() -> None:
    assert await _sem_video_chamada_do_cardapio([_programa("Encontro")]) is True


async def test_a_linha_de_video_chamada_desliga_a_tag() -> None:
    assert (
        await _sem_video_chamada_do_cardapio([_programa("Encontro"), _programa("Vídeo chamada")])
        is False
    )


async def test_cardapio_vazio_mantem_a_tag() -> None:
    # Sem programa nenhum ela não tem o que cotar: a chamada não é dela (ao contrário do
    # <sem_periodo_longo>, onde max==0 é cadastro anormal e NÃO injeta).
    assert await _sem_video_chamada_do_cardapio([]) is True


def test_as_variantes_de_cadastro_do_nome_casam() -> None:
    # O gate do prompt sempre foi por NOME, lido pelo LLM na tabela; a derivação casa o mesmo
    # julgamento, sem acento e sem caixa (`normalizar`).
    assert e_video_chamada("Vídeo chamada")
    assert e_video_chamada("Videochamada")
    assert e_video_chamada("Chamada de vídeo")
    assert e_video_chamada("CHAMADA DE VIDEO 30min")
    assert not e_video_chamada("Encontro")
    assert not e_video_chamada("Pernoite")
    assert not e_video_chamada("Jantar")
