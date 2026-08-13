"""Entrada do extrator: a MESMA janela dedicada que o no `extrair` monta em producao.

Nada aqui reimplementa a montagem: `_janela_para_extracao` (nos/extrair.py) e
`render_ja_registrado` (persona) sao os de prod, chamados com as pecas do turno reconstruidas
(conversa crua, ancora temporal, bloco de estado). O que este modulo faz e a TRADUCAO do item do
golden set para essas pecas — e a aplicacao dos payloads em ordem que produz o snapshot de cada
turno intermediario.

O snapshot NAO sai do estado atual do Atendimento (esse e o resultado final e nao reproduz turno
intermediario): sai de `aplicar_payload`, que espelha o UPSERT do dominio nos campos que o bloco
`<ja_registrado>` renderiza. Espelhar e uma divida assumida — o dominio (`registrar_extracao_ia`)
segue sendo a fonte de verdade, e a trajetoria (nivel de impacto) roda contra ELE, nao contra isto.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

# Privados de proposito: a fidelidade da bancada vem de exercitar o codigo de prod, nao uma copia.
from barra.agente.nos.extrair import _janela_para_extracao
from barra.agente.nos.prepare_context import (
    _horario_evidenciado_no_turno,
    _num_humano,
    _recuo_no_turno,
)
from barra.agente.persona import render_ja_registrado

from .golden import Fala, ItemGolden

# Campos do snapshot que o bloco `<ja_registrado>` renderiza (+ os dois booleanos que o rotulam).
# `aceita_valor` chega achatado: no banco ele vive dentro de `sinais_qualificacao`.
CAMPOS_SNAPSHOT = (
    "intencao",
    "urgencia",
    "tipo_atendimento",
    "data_desejada",
    "horario_desejado",
    "horario_evidenciado",
    "endereco",
    "bairro",
    "valor_acordado",
    "duracao_horas",
    "aceita_valor",
)

# Campos que o payload pode reenviar sem nada novo na conversa (o eco medido no piloto).
CAMPOS_ECO = (
    "intencao",
    "urgencia",
    "tipo_atendimento",
    "data_desejada",
    "horario_desejado",
    "endereco",
    "bairro",
    "valor_acordado",
    "duracao_horas",
)


def mensagens_da_conversa(conversa: list[Fala]) -> list[BaseMessage]:
    """Falas -> mensagens LangChain, no mesmo mapeamento de `traduzir_mensagens` (cliente ->
    HumanMessage, IA -> AIMessage). Os detectores do turno leem esta lista."""
    return [
        HumanMessage(content=f.texto) if f.de == "cliente" else AIMessage(content=f.texto)
        for f in conversa
    ]


def variaveis_do_bloco(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Snapshot -> variaveis do template `ja_registrado.md.j2`.

    Mesmos nomes que `_resolver_variaveis` publica (o template e o de prod): `valor_fechado`/
    `duracao_fechada` vem do numero seco, e `valor_aceito` e o sinal que separa cotado de aceito.

    `fetiches_do_cadastro` (os nomes canonicos do cardapio dela, que em prod o `prepare_context`
    tira das linhas ja lidas pelo BP_MODELO) sai VAZIO por padrao: o golden set do replay nao
    carrega o cadastro da modelo, entao a tag nao renderiza — o item que quiser medir a traducao
    de vocabulario ("pegging" -> "Inversao") precisa por os nomes no proprio snapshot. Divida
    assumida e explicita, no mesmo espirito do `aplicar_payload` (espelho, nao fonte de verdade).
    """
    return {
        "tipo_atendimento": snapshot.get("tipo_atendimento"),
        "intencao": snapshot.get("intencao"),
        "data_desejada": snapshot.get("data_desejada"),
        "horario_desejado": snapshot.get("horario_desejado"),
        "horario_evidenciado": bool(snapshot.get("horario_evidenciado")),
        "endereco": snapshot.get("endereco"),
        "bairro": snapshot.get("bairro"),
        "valor_fechado": _numero_seco(snapshot.get("valor_acordado")),
        "valor_aceito": bool(snapshot.get("aceita_valor")),
        "duracao_fechada": _numero_seco(snapshot.get("duracao_horas")),
        "forma_pagamento": snapshot.get("forma_pagamento"),
        "urgencia": snapshot.get("urgencia"),
        "fetiches_do_cadastro": tuple(snapshot.get("fetiches_do_cadastro") or ()),
    }


def _numero_seco(valor: Any) -> str | None:
    """Valor numerico do snapshot (str/Decimal/None) no formato do template ("400.00" -> "400")."""
    if valor is None:
        return None
    return _num_humano(valor if isinstance(valor, Decimal) else Decimal(str(valor)))


def montar_janela(item: ItemGolden, *, bloco_estado: bool = True) -> list[BaseMessage]:
    """Janela dedicada do turno: system minimo + conversa crua + (ancora + `<ja_registrado>`).

    `bloco_estado=False` e a variante que mede o efeito da janela dedicada: a cauda fica so com a
    ancora temporal. O `messages` vai vazio porque `_janela_para_extracao` usa a `conversa_crua`
    do State quando ela existe — que e exatamente o caminho de prod.
    """
    state: dict[str, Any] = {
        "conversa_crua": mensagens_da_conversa(item.conversa),
        "agora_turno": item.agora_brt,
        "ja_registrado": render_ja_registrado(**variaveis_do_bloco(item.registrado))
        if bloco_estado
        else "",
    }
    return _janela_para_extracao([], state, system_minimo=True)  # type: ignore[arg-type]


def detectores_do_turno(item: ItemGolden) -> tuple[bool, bool]:
    """`(horario_evidenciado, recuo_detectado)` — os dois detectores DETERMINISTICOS do turno.

    Nao saem do payload de proposito (o payload e o canal contaminado pelo eco do belief): em prod
    o `prepare_context` os computa sobre a janela limpa e a extracao os repassa ao dominio. Aqui
    rodam sobre a mesma conversa do item, entao a bancada tambem os MEDE contra o rotulo humano.
    """
    mensagens = mensagens_da_conversa(item.conversa)
    return _horario_evidenciado_no_turno(mensagens), _recuo_no_turno(mensagens)


def aplicar_payload(
    snapshot: dict[str, Any],
    payload: dict[str, Any],
    *,
    horario_evidenciado: bool,
    recuo: bool = False,
) -> dict[str, Any]:
    """Aplica um payload de extracao ao snapshot — o replay que reproduz turnos intermediarios.

    Espelha `registrar_extracao_ia` nos campos do bloco, na MESMA ordem que ele: UPSERT (`limpar`
    zera e vence o payload; campo nao-nulo sobrescreve, nulo preserva; `intencao` e MONOTONICA,
    nunca rebaixa de 'agendamento'), marca de proveniencia do horario (acende com evidencia do
    turno, apaga quando o VALOR muda sem ela) e so entao a promocao da intencao por evidencia.

    `aceita_valor` sobe pelo sinal explicito do extrator e desce por `limpar` do `valor_acordado`
    ou pelo detector de `recuo` do turno — nunca deriva do `valor_acordado` presente (patch 24/07:
    ele e gravado ja na cotacao).

    Espelho e divida assumida: `test_bancada_replay.py` amarra esta funcao ao dominio.
    """
    novo = dict(snapshot)
    limpar = set(payload.get("limpar") or [])
    sinais = payload.get("sinais_qualificacao") or {}

    horario_anterior = novo.get("horario_desejado")
    for campo in CAMPOS_SNAPSHOT:
        if campo in limpar:
            novo[campo] = None
        elif campo in payload and payload[campo] is not None:
            if campo == "intencao" and novo.get("intencao") == "agendamento":
                continue  # monotonica: o extrator barato erra sistematicamente para BAIXO
            novo[campo] = payload[campo]

    if "valor_acordado" in limpar or recuo:
        novo["aceita_valor"] = False
    elif sinais.get("aceita_valor"):
        novo["aceita_valor"] = True

    if horario_evidenciado:
        novo["horario_evidenciado"] = True
    elif novo.get("horario_desejado") != horario_anterior:
        novo["horario_evidenciado"] = False

    # Promocao por evidencia (`_promover_intencao_por_evidencia`): roda sobre a linha JA
    # atualizada, entao le o horario e a marca como ficaram. `limpar` vence — a retratacao
    # explicita do cliente nao e desfeita pela promocao.
    if (
        "intencao" not in limpar
        and novo.get("horario_desejado") is not None
        and novo.get("horario_evidenciado")
    ):
        novo["intencao"] = "agendamento"
    return novo
