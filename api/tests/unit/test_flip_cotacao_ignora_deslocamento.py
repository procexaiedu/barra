"""`_sem_valores_de_deslocamento`: o R$ do Pix/uber não satisfaz o flip de `cotacao_apresentada`.

Revisão de domínio da rodada 1 (achado 5): `texto_tem_cotacao` casa `R$`+dígito incondicionalmente
(falso-positivo conhecido e barato no CARIMBO do envio, ADR-0022) — mas na ENTRADA da extração o
flip satisfaz o guard `CotacaoAusente`, e "manda o pix de R$100 pra garantir" liberaria a reserva
com o preço do programa nunca dito. O helper apaga só o `R$<n>` colado em palavra de deslocamento;
a cotação legítima (inclusive a que menciona o uber na sequência) segue passando.
"""

from barra.agente.ferramentas.extracao import _sem_valores_de_deslocamento
from barra.dominio.atendimentos.service import texto_tem_cotacao


def _flip(texto: str) -> bool:
    return texto_tem_cotacao(_sem_valores_de_deslocamento(texto))


def test_pix_de_deslocamento_nao_conta_como_cotacao() -> None:
    assert _flip("me manda o pix de R$100 pra garantir amor") is False


def test_valor_do_uber_nao_conta_como_cotacao() -> None:
    assert _flip("o uber fica R$100, me confirma?") is False


def test_valor_seguido_da_palavra_pix_nao_conta() -> None:
    assert _flip("são R$100 do pix, tá?") is False


def test_cotacao_legitima_com_cifrao_segue_passando() -> None:
    assert _flip("a 1h fica R$800 no meu local amor") is True


def test_cotacao_que_menciona_uber_na_sequencia_segue_passando() -> None:
    # A janela pós-valor é curta de propósito: o "pix do uber por fora" vem depois da cotação.
    assert _flip("fica R$800 a hora amor, e o pix do uber vai por fora") is True


def test_formato_numero_seco_da_persona_nao_e_afetado() -> None:
    # Caminho 2 do backstop (valor seco + duração/local) não passa pelo helper de R$.
    assert _flip("600 1h no meu local, 900 2h + uber") is True


def test_so_pix_sem_cotacao_nenhuma_nao_passa() -> None:
    assert _flip("te mando minha chave pix já já") is False
