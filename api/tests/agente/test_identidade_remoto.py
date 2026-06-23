"""Gap P0 (ADR 0021): o bloco <atendimento> da identidade cobre o tipo `remoto`.

Antes, uma modelo só-remoto (ou qualquer combinação com remoto) renderizava
<atendimento> vazio — a IA não era informada do que a modelo faz, furando o gate
uniforme do ADR 0021. DB-free / key-free (render puro de Jinja).
"""

from barra.agente.persona import IdentidadeModelo, render_identidade


def _ident(tipos: list[str]) -> str:
    return render_identidade(
        IdentidadeModelo(
            nome="Bia",
            idade=26,
            idiomas=["pt-BR"],
            localizacao_operacional=None,
            tipos_aceitos=tipos,
        )
    )


def test_remoto_only_renderiza_so_remoto() -> None:
    assert "Tipos aceitos: só remoto." in _ident(["remoto"])


def test_interno_remoto() -> None:
    assert "Tipos aceitos: interno e remoto." in _ident(["interno", "remoto"])


def test_externo_remoto() -> None:
    assert "Tipos aceitos: externo e remoto." in _ident(["externo", "remoto"])


def test_tres_tipos_lista_em_ordem_canonica() -> None:
    assert "Tipos aceitos: interno, externo e remoto." in _ident(["interno", "externo", "remoto"])


def test_ordem_de_entrada_nao_importa() -> None:
    # entrada fora de ordem → render sempre na ordem canônica (interno, externo, remoto).
    assert "Tipos aceitos: interno, externo e remoto." in _ident(["remoto", "externo", "interno"])


def test_regressao_interno_externo_inalterado() -> None:
    assert "Tipos aceitos: interno e externo." in _ident(["interno", "externo"])


def test_regressao_so_interno() -> None:
    assert "Tipos aceitos: só interno." in _ident(["interno"])
