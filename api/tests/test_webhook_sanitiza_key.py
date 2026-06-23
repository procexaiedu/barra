"""SEC: evolution_message_id (client-controlled) sanitizado antes de virar chave de objeto MinIO.

Sem isto, um id com `../` escapa o prefixo da conversa e sobrescreve midia de OUTRA conversa
(o pipeline de Pix rele a key e a manda a vision). E a sanitizacao precisa ser INJETIVA: ids
anomalos distintos do MESMO cliente nao podem colapsar na mesma key (sobrescrita intra-conversa).
Teste puro do helper -- nao toca MinIO nem rede.
"""

from barra.webhook.routes import _segmento_objeto_seguro


def test_remove_barra_mata_a_travessia():
    out = _segmento_objeto_seguro("../../conversas/outro-uuid/mensagens/AAAA")
    assert "/" not in out  # sem barra -> impossivel mudar de prefixo (chaves S3/MinIO sao planas)


def test_id_real_do_whatsapp_passa_intacto():
    # id alfanumerico real do WhatsApp passa SEM hash (caso comum; nada descartado nem mexido).
    assert _segmento_objeto_seguro("3EB0C767D26A1D8E5F0A") == "3EB0C767D26A1D8E5F0A"
    assert _segmento_objeto_seguro("BAE5_abc-123.def") == "BAE5_abc-123.def"


def test_injetividade_ids_distintos_nao_colidem():
    # ids anomalos distintos que colapsavam na mesma key (many-to-one) agora geram keys distintas.
    a = _segmento_objeto_seguro("a/b")
    b = _segmento_objeto_seguro("a%b")
    c = _segmento_objeto_seguro("a_b")  # ja seguro -> intacto, sem hash
    assert a != b and a != c and b != c
    assert all("/" not in x for x in (a, b, c))
    # determinismo: mesmo id -> mesma key (replay-safe, espelha o turno_id determinístico)
    assert _segmento_objeto_seguro("a/b") == a


def test_degenerados_nao_viram_vazio_nem_barra():
    for ruim in ("", ".", "..", "/"):
        out = _segmento_objeto_seguro(ruim)
        assert out and "/" not in out  # nunca segmento vazio nem com barra
    # ate os degenerados ficam injetivos entre si
    assert _segmento_objeto_seguro("") != _segmento_objeto_seguro("..")


def test_chave_final_nunca_sai_do_prefixo_da_conversa():
    cid = "11111111-1111-1111-1111-111111111111"
    for ataque in ("../../etc/passwd", "..%2f..%2fx", "a/b/c", "x" * 500):
        seg = _segmento_objeto_seguro(ataque)
        key = f"conversas/{cid}/mensagens/{seg}.jpg"
        assert key.startswith(f"conversas/{cid}/mensagens/")
        # exatamente os 3 separadores do prefixo, nenhum `/` injetado pelo id do atacante.
        assert key.count("/") == 3
        assert len(seg) <= 128  # teto de comprimento (id absurdo nao estoura a key)
