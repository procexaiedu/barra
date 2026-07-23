"""Contador determinístico de contrapropostas (padrão A2, agente/CLAUDE.md).

A disciplina "desconto é até DUAS contrapropostas na conversa inteira — degrau, depois teto"
(regras.md.j2 <desconto> 3/4, ADR-0031) dependia da janela de 20 msgs: contraproposta fora da
janela → LLM podia ofertar de novo. Agora a flag é MATERIALIZADA: `contar_contrapropostas`
(agente/_disciplina.py) detecta a forma canônica ("Consigo 500 se você vier hoje") no write-time
(workers/envio.py) e carimba `atendimentos.n_contrapropostas`; `_resolver_variaveis` lê a coluna
(não reescaneia as falas da IA) e o template injeta a tag instrutiva certa pra cada rodada.
"""

from typing import Any

from barra.agente._disciplina import contar_contrapropostas
from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico

# --- detector puro (agente/_disciplina.py) ------------------------------------------------------


def test_conta_contrapropostas_canonicas() -> None:
    assert contar_contrapropostas(["Consigo 500 se você vier hoje 😊"]) == 1
    assert contar_contrapropostas(["Poxa amor\n\nConsigo 450 se fechar agora"]) == 1
    # acento/caixa não escondem ("CONSIGO", "consigo R$ 400")
    assert contar_contrapropostas(["CONSIGO 400 amor"]) == 1
    assert contar_contrapropostas(["consigo r$ 400 pra hoje"]) == 1


def test_conta_ate_duas_contrapropostas_no_mesmo_atendimento() -> None:
    historico = [
        "Oii",
        "600 1h no meu local",
        "Consigo 500 se você vier hoje 😊",
        "Poxa amor não consigo",
        "Consigo 450 se fechar agora 😊",
    ]
    assert contar_contrapropostas(historico) == 2


def test_nao_flaga_recusa_nem_horario_nem_cotacao() -> None:
    # recusa da escada ("não consigo") não é contraproposta
    assert contar_contrapropostas(["Poxa amor não consigo"]) == 0
    # hora não é preço: 1-2 dígitos + h ficam fora do \d{3,}
    assert contar_contrapropostas(["Consigo às 22h amor", "consigo 14h sim"]) == 0
    # confirmação sem número e cotação de tabela (sem "consigo") ficam fora
    assert contar_contrapropostas(["Consigo sim amor", "600 1h no meu local"]) == 0
    assert contar_contrapropostas([]) == 0


# --- _resolver_variaveis lê a coluna materializada ----------------------------------------------
# A memória durável (e o reset em recorrência) deixou de vir de um scan das falas: cada atendimento
# tem sua PRÓPRIA coluna `n_contrapropostas`, carimbada no write-time. Aqui provamos só a LEITURA;
# a contagem no write-time (idempotente por bolha inserida) é coberta em test_envio_flags_disciplina.


class _FakeConnVazio:
    """Vazio em tudo: _resolver_variaveis recebe o atendimento por kwarg, não por query."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchone(self) -> None:
                return None

            async def fetchall(self) -> list[Any]:
                return []

        return _R()


async def _n_contrapropostas(atendimento: dict[str, Any]) -> int:
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
    )
    variaveis = await _resolver_variaveis(
        _FakeConnVazio(),  # type: ignore[arg-type]
        ctx,
        atendimento=atendimento,
    )
    return variaveis["n_contrapropostas"]


async def test_le_contador_da_coluna() -> None:
    assert await _n_contrapropostas({"n_contrapropostas": 2}) == 2


async def test_atendimento_novo_zera() -> None:
    # Recorrência: atendimento novo nasce com a coluna no default 0 (row sem a chave → 0).
    assert await _n_contrapropostas({}) == 0
    assert await _n_contrapropostas({"n_contrapropostas": 0}) == 0


# --- render do template -------------------------------------------------------------------------


def _render(**over: object) -> str:
    return render_contexto_dinamico(
        numero_curto=7,
        estado="Qualificado",
        slots_faltantes=[],
        proximo_passo="cravar o horário",
        pix_status="não aplicável",
        **over,
    )


def test_render_sem_contraproposta_nao_injeta_tag() -> None:
    assert "<ja_fez_contraproposta" not in _render(n_contrapropostas=0)
    assert "<ja_fez_contraproposta" not in _render()


def test_render_primeira_contraproposta_permite_segunda_rodada() -> None:
    out = _render(n_contrapropostas=1)
    assert '<ja_fez_contraproposta n="1">' in out
    assert "segunda" in out.lower() or "última" in out.lower()


def test_render_segunda_contraproposta_esgota_desconto() -> None:
    out = _render(n_contrapropostas=2)
    assert '<ja_fez_contraproposta n="2">' in out
    assert "fora_de_oferta" in out


def test_render_terceira_insistencia_trata_como_esgotado() -> None:
    # defesa: contagem >2 (não deveria acontecer, mas não pode reabrir oferta) segue como esgotado.
    out = _render(n_contrapropostas=3)
    assert '<ja_fez_contraproposta n="2">' in out
