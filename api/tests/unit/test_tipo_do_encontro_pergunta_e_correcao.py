"""D-C3-1 (campanha 13/08, eb02:139384791793838): "Qual o cachê? Hotel?" — o cliente perguntando
se o local DELA é hotel — virou `tipo_atendimento='externo'` + `tipo_local='hotel'` na extração,
e o belief venceu o contexto dali em diante: a IA pediu "o endereço do hotel" ao cliente, a
correção explícita dele no t10 ("Não. Quem fica no hotel é você? Onde te encontro?") foi re-ecoada
como externo em vez de gravada, e o fechamento saiu contraditório com Pix de deslocamento indevido.

Três frentes pinadas, todas sem DB e sem crédito (mesmo estilo da seção (5) de
test_aceite_do_valor_dele.py — pina o schema que o LLM VÊ):
 (1) as descrições de `tipo_atendimento`/`tipo_local` ganham a negação ativa dos campos de mesa:
     pergunta do cliente sobre o local DELA não define o arranjo, com o exemplo negativo real;
 (2) a instrução de correção — corrigir/negar um dado JÁ gravado é exatamente o que se registra —
     na descrição do campo (o `<como_ler>` do `<ja_registrado>` é pinado em test_pecas_do_turno);
 (3) o merge persistido NÃO é latch: valor novo não-nulo sobrescreve, `None` preserva, `limpar`
     zera — e o único congelamento do tipo (`_flip_de_tipo_pos_crava`, incidente #41) não alcança
     um atendimento Qualificado sem bloqueio: a correção do t10, gravada, teria valido.
"""

from uuid import uuid4

from barra.dominio.atendimentos.service import (
    _montar_upsert,
    tipo_atendimento_congelado,
)

# --- (1) e (2): o schema que o LLM vê ------------------------------------------------------------


def _descricao_da_tool(campo: str) -> str:
    from barra.agente.ferramentas.extracao import registrar_extracao

    schema = registrar_extracao.args_schema
    assert schema is not None
    descricao = schema.model_fields[campo].description
    assert descricao is not None
    return descricao


def test_tipo_atendimento_nega_a_pergunta_sobre_o_local_dela() -> None:
    """O exemplo negativo REAL do defeito ('Qual o cachê? Hotel?') mora na descrição, junto da
    regra: pergunta não define quem se desloca; só pedido/afirmação do arranjo grava."""
    desc = _descricao_da_tool("tipo_atendimento")

    assert "Qual o cachê? Hotel?" in desc
    assert "Pergunta NUNCA define quem se desloca" in desc
    assert "PEDE ou AFIRMA o arranjo" in desc
    assert "vem no meu hotel" in desc


def test_tipo_atendimento_manda_gravar_a_correcao() -> None:
    """t10 do caso real: a correção explícita foi re-ecoada como externo. A descrição distingue
    CORREÇÃO (mal-entendido gravado — regrava) de PEDIDO de mudança (tipo combinado — fica fora)."""
    desc = _descricao_da_tool("tipo_atendimento")

    assert "CORREÇÃO é diferente de pedido" in desc
    assert "Quem fica no hotel é você?" in desc
    assert "o MAIS importante de gravar" in desc


def test_tipo_local_nega_a_pergunta_sobre_o_local_dela() -> None:
    desc = _descricao_da_tool("tipo_local")

    assert "PERGUNTA não descreve local nenhum" in desc
    assert "Qual o cachê? Hotel?" in desc
    assert "O SEU local NUNCA entra aqui" in desc
    assert '`limpar: ["tipo_local"]`' in desc


# --- (3) o merge persistido: sobrescreve com valor novo, preserva no None ------------------------


def test_tipo_novo_no_payload_sobrescreve_o_gravado() -> None:
    """O UPSERT não é latch: campo não-nulo do payload entra como SET simples — um 'interno'
    explicitamente gravado pela extração vence o 'externo' antigo da coluna."""
    sets, valores = _montar_upsert({"tipo_atendimento": "interno", "tipo_local": "casa"}, set())

    assert "tipo_atendimento = %s" in sets
    assert "tipo_local = %s" in sets
    assert "interno" in valores
    assert "casa" in valores


def test_tipo_ausente_no_payload_preserva_o_gravado() -> None:
    """Fail-safe do COALESCE incremental: None/ausência nunca toca a coluna."""
    sets, _valores = _montar_upsert({"tipo_atendimento": None, "valor_acordado": 400}, set())

    assert not any(s.startswith("tipo_atendimento") for s in sets)
    assert not any(s.startswith("tipo_local") for s in sets)


def test_limpar_zera_o_tipo_e_vence_o_payload() -> None:
    sets, valores = _montar_upsert({"tipo_local": "hotel"}, {"tipo_local", "tipo_atendimento"})

    assert "tipo_local = NULL" in sets
    assert "tipo_atendimento = NULL" in sets
    assert "hotel" not in valores


def test_correcao_pre_crava_nao_e_congelada() -> None:
    """O único latch do tipo (`_flip_de_tipo_pos_crava`) só arma com horário COMBINADO — bloqueio
    prévio ou Aguardando_confirmacao. No t10 do caso real o atendimento estava Qualificado sem
    bloqueio: a correção, se a extração a tivesse gravado, teria sobrescrito o externo."""
    assert tipo_atendimento_congelado(bloqueio_id=None, estado="Qualificado") is False
    assert tipo_atendimento_congelado(bloqueio_id=None, estado="Triagem") is False


def test_flip_pos_crava_segue_congelado() -> None:
    """O outro lado do mesmo predicado é decisão pinada em código (incidente #41, 24/07): tipo
    combinado não flipa por pedido do cliente — mudança real pós-crava sai pela conduta/escalada,
    não por campo de extração. Este teste impede que a frente (3) o afrouxe por engano."""
    assert tipo_atendimento_congelado(bloqueio_id=uuid4(), estado="Qualificado") is True
    assert tipo_atendimento_congelado(bloqueio_id=None, estado="Aguardando_confirmacao") is True
