"""Aceite M4a — chunking de texto da humanização (05 §2).

Puro (sem banco, sem chave). Cobre as quatro regras de `chunk_texto`: split por `\\n\\n`,
preservação de `\\n` simples dentro de um bloco, sentença única acima do cap saindo inteira
(+ `CHUNK_OVERSIZE`) e o cap de 6 bolhas fundindo o excedente.

Gotcha de métrica: `CHUNK_OVERSIZE` é um Counter global compartilhado entre testes — lê-se o
valor ANTES e compara-se o delta. O nome já termina em `_total` (não duplicar o sufixo).
"""

from prometheus_client import REGISTRY

from barra.workers._chunking import MAX_CHARS, MAX_CHUNKS, chunk_texto


def test_linha_em_branco_separa_em_n_bolhas() -> None:
    chunks = chunk_texto("oi gato\n\ntudo bem?\n\nme conta de vc")
    assert chunks == ["oi gato", "tudo bem?", "me conta de vc"]


def test_quebra_simples_dentro_do_bloco_e_preservada() -> None:
    # lista de horários num único bloco: \n simples vira uma só mensagem multi-linha
    chunks = chunk_texto("meus horários hoje:\n14h\n16h\n18h")
    assert chunks == ["meus horários hoje:\n14h\n16h\n18h"]


def test_sentenca_unica_acima_do_cap_sai_inteira_e_conta_oversize() -> None:
    sentenca = "palavra " * 100  # ~800 chars, sem . ! ? → uma sentença só
    esperado = " ".join(sentenca.split())

    antes = REGISTRY.get_sample_value("agente_chunk_oversize_total") or 0.0
    chunks = chunk_texto(sentenca)
    depois = REGISTRY.get_sample_value("agente_chunk_oversize_total") or 0.0

    assert chunks == [esperado]
    assert len(chunks[0]) > MAX_CHARS  # saiu inteira, não foi cortada no meio
    assert depois - antes == 1.0


def test_mais_de_seis_blocos_colapsam_em_seis_fundindo_o_excedente() -> None:
    texto = "\n\n".join(f"b{i}" for i in range(8))  # 8 blocos
    chunks = chunk_texto(texto)

    assert len(chunks) == MAX_CHUNKS
    assert chunks[:5] == ["b0", "b1", "b2", "b3", "b4"]
    assert chunks[5] == "b5\n\nb6\n\nb7"  # excedente fundido no último
