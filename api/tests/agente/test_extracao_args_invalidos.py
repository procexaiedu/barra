"""A fronteira LLM->tool da extracao nao derruba mais o turno por formato de campo.

Contexto (auditoria de `agente/ferramentas/`, 12/08): `registrar_extracao` e a UNICA tool que nao
passa pelo `ToolNode` — `nos/extrair.py:_executar_inline` a chama com `.ainvoke()` direto. O ToolNode
embrulha o `ValidationError` do pydantic num `ToolInvocationError` (subclasse de `ToolException`) e
o devolve como ToolMessage; a execucao inline nao tem esse embrulho. Resultado medido: 11 formas de o
modelo matar o turno inteiro — cliente sem NENHUMA resposta — escrevendo um campo no formato da fala
numa nota interna.

Duas camadas, testadas aqui separadamente porque falham por motivos diferentes:

1. `_podar_ao_schema` (via `_args_saneados`) CORRIGE o recuperavel e DESCARTA o resto, campo a
   campo, antes de invocar. E a camada que preserva dado.
2. `handle_validation_error` na tool e a rede de baixo: o que a camada 1 nao previu vira
   ToolMessage de erro (que a auto-reoferta do `extrair` consome), nunca excecao.

O teste 1 e o contrato de PRESERVACAO (o horario tem de sobreviver a `"22h"`); o teste 2 e o
contrato de NAO-MORTE (nada, nem um payload absurdo, sobe como excecao).
"""

from typing import Any

import pytest
from pydantic import ValidationError

from barra.agente.ferramentas.extracao import registrar_extracao
from barra.agente.nos.extrair import (
    _MIN_PROXIMA_ACAO,
    _args_saneados,
    _enum_permitido,
    _schema_da_extracao,
)

_SCHEMA = _schema_da_extracao(registrar_extracao)
_NOTA = "aguardar o cliente confirmar"


def _sanear(args: dict[str, Any]) -> dict[str, Any]:
    return _args_saneados({"name": "registrar_extracao", "args": dict(args), "id": "t"}, _SCHEMA)


def _valida(args: dict[str, Any]) -> list[tuple[Any, ...]]:
    """Os erros de validacao dos args, ignorando o `runtime` (injetado fora do schema do LLM)."""
    try:
        registrar_extracao.get_input_schema().model_validate({**args, "runtime": None})
    except ValidationError as exc:
        return [(er["loc"], er["type"]) for er in exc.errors() if er["loc"][:1] != ("runtime",)]
    return []


# --- 1. o que o modelo escreve na pratica, e o que tem de sobrar dali -----------------------------
# Cada caso foi observado ou e a forma natural do campo na FALA. `esperado` None = o campo pode
# sumir (nao da para converter sem chutar); dict = o valor exato que tem de sobreviver.
@pytest.mark.parametrize(
    ("args", "esperado"),
    [
        # Horario: o formato que as proprias descricoes da tool usam nos exemplos.
        ({"horario_desejado": "22h"}, {"horario_desejado": "22:00"}),
        ({"horario_desejado": "22h30"}, {"horario_desejado": "22:30"}),
        ({"horario_desejado": "22:30hs"}, {"horario_desejado": "22:30"}),
        ({"horario_desejado": "24h"}, {"horario_desejado": "00:00"}),
        # `HH:MM:SS` e o repr de `datetime.time` — o eco do estado ja gravado (achado 12/08).
        ({"horario_desejado": "17:00:00"}, {"horario_desejado": "17:00"}),
        ({"horario_desejado": "22:00"}, {"horario_desejado": "22:00"}),  # ja valido, intocado
        # Hora VAGA nao se converte: "a noite" nao e um horario, e chutar um seria pior.
        ({"horario_desejado": "a noite"}, None),
        ({"horario_desejado": "99:99"}, None),
        # Duracao/valor: numero dentro de texto de duracao e de dinheiro.
        ({"duracao_horas": "12h"}, {"duracao_horas": "12"}),
        ({"duracao_horas": "1,5h"}, {"duracao_horas": "1.5"}),
        ({"valor_acordado": "300 reais"}, {"valor_acordado": "300"}),
        ({"valor_acordado": "R$ 1.200,50"}, {"valor_acordado": "1200.50"}),
        # Nome do pacote NAO vira duracao: a duracao mora no cardapio, nao no nome.
        ({"duracao_horas": "pernoite"}, None),
        # Fora dos limites do campo (`ge=0` / `le=48`): descarta em vez de estourar.
        ({"valor_acordado": -5}, None),
        ({"duracao_horas": 100}, None),
        ({"duracao_horas": 12}, {"duracao_horas": 12}),  # dentro do limite, intocado
        # Lista escrita como string solta.
        ({"limpar": "horario_desejado"}, {"limpar": ["horario_desejado"]}),
        ({"fetiches_em_pauta": "Inversão"}, {"fetiches_em_pauta": ["Inversão"]}),
        # Objeto aninhado escrito como o NOME do sinal. Vale converter: `aceita_valor` e o unico
        # sinal de aceite do contrato, e perde-lo trava a escada de desconto.
        (
            {"sinais_qualificacao": "aceita_valor"},
            {"sinais_qualificacao": {"aceita_valor": True}},
        ),
        ({"sinais_qualificacao": "campo_que_nao_existe"}, None),
        # Data: so ISO passa. Relativo nao se resolve aqui (a ancora do relativo vive no prompt).
        ({"data_desejada": "2026-08-20"}, {"data_desejada": "2026-08-20"}),
        ({"data_desejada": "amanha"}, None),
        ({"data_desejada": "2026-13-45"}, None),
        # Enum com typo de uma letra (o caminho de `_valor_do_enum`, ja existente).
        ({"urgencia": "imediatio"}, {"urgencia": "imediato"}),
        # Booleano como string.
        ({"cotacao_apresentada": "true"}, {"cotacao_apresentada": True}),
        # Campo de TEXTO livre recebendo numero: o pydantic e estrito com `str` (`string_type`).
        ({"endereco": 123}, {"endereco": "123"}),
        ({"bairro": 7}, {"bairro": "7"}),
        # Item de lista tipado como string, recebendo numero (falha no INDICE).
        ({"fetiches_em_pauta": [1, 2]}, {"fetiches_em_pauta": ["1", "2"]}),
        ({"limpar": ["horario_desejado", 5]}, {"limpar": ["horario_desejado", "5"]}),
        # Lista recebendo objeto: nao da para converter sem inventar, descarta.
        ({"limpar": {"a": 1}}, None),
    ],
)
def test_o_saneamento_nao_deixa_o_turno_morrer(
    args: dict[str, Any], esperado: dict[str, Any] | None
) -> None:
    saneado = _sanear({"proxima_acao_esperada": _NOTA, **args})

    assert _valida(saneado) == [], f"payload saneado ainda derruba o turno: {saneado}"
    campo = next(iter(args))
    if esperado is None:
        assert campo not in saneado, f"{campo} deveria ter sido descartado, veio {saneado[campo]!r}"
    else:
        assert saneado[campo] == esperado[campo]


# --- 2. a nota interna obrigatoria nunca falta ----------------------------------------------------
@pytest.mark.parametrize("nota", ["", "  ", "ok", "a"])
def test_nota_ausente_ou_curta_vira_texto_neutro(nota: str) -> None:
    """`proxima_acao_esperada` tem `min_length=3`: vazia OU com 1-2 chars matava o turno igual."""
    saneado = _sanear({"proxima_acao_esperada": nota})

    assert _valida(saneado) == []
    assert len(saneado["proxima_acao_esperada"]) >= 3


def test_nota_valida_nao_e_substituida() -> None:
    saneado = _sanear({"proxima_acao_esperada": _NOTA})

    assert saneado["proxima_acao_esperada"] == _NOTA


# --- 3. a rede de baixo: o que a camada 1 nao previu vira ToolMessage, nao excecao ---------------
def test_a_tool_tem_rede_contra_validation_error() -> None:
    """Sem `handle_validation_error` o `ValidationError` cru sobe pelo `graph.ainvoke` e mata o
    turno — a tool nao passa pelo ToolNode, que faria esse embrulho de graca."""
    handler = registrar_extracao.handle_validation_error

    assert callable(handler), "registrar_extracao sem rede contra erro de args"
    texto = handler(ValueError("campo x invalido"))
    # O prefixo "ERRO:" e contrato com o coordenador e com `_extracao_errou` (dispara a reoferta).
    assert texto.startswith("ERRO:")
    # E uma nota de sistema, nao uma ordem que o chat possa ecoar em voz alta ao cliente.
    assert "registrar_extracao" in texto


async def test_payload_absurdo_nao_estoura_a_tool() -> None:
    """Fim a fim, sem DB: os args nem chegam ao corpo da tool (a validacao falha antes), e o que sai
    e um ToolMessage de erro. Se a rede sair, este `ainvoke` volta a levantar `ValidationError` — e
    e por isso que ele NAO esta num `pytest.raises`: a AUSENCIA da excecao e a asercao."""
    resultado = await registrar_extracao.ainvoke(
        {
            "name": "registrar_extracao",
            # `runtime` ausente de proposito: e o jeito mais simples de forcar a falha de args sem
            # precisar de pool/redis. O caminho de erro e o MESMO de um campo mal formatado.
            "args": {"proxima_acao_esperada": _NOTA},
            "id": "t1",
            "type": "tool_call",
        }
    )

    assert resultado.status == "error"
    assert str(resultado.content).startswith("ERRO:")


# --- 4. os cadeados: o que amarra as DUAS copias do contrato -------------------------------------
def test_min_proxima_acao_espelha_o_schema_da_tool() -> None:
    """`_MIN_PROXIMA_ACAO` e uma copia do `min_length` da tool -- e ate hoje ninguem as amarrava.

    O comentario de `nos/extrair.py` prometia que "o teste de regressao as amarra"; o teste nao
    existia. Sem ele, subir o `min_length` em `ferramentas/extracao.py` faz o saneamento parar de
    preencher a nota curta, e o turno volta a morrer por `ValidationError` -- pelo caminho que
    esta suite inteira existe para fechar.
    """
    do_schema = _SCHEMA[0]["proxima_acao_esperada"]["minLength"]  # type: ignore[index]

    assert _MIN_PROXIMA_ACAO == do_schema, (
        f"_MIN_PROXIMA_ACAO={_MIN_PROXIMA_ACAO} divergiu do schema da tool ({do_schema}): "
        "o saneamento vai gerar nota que a propria tool rejeita"
    )


def _enums_do_schema() -> list[tuple[str, list[str]]]:
    """Todo campo de dominio fechado do payload, lido do schema -- nao de uma lista escrita a mao.

    Varrer o schema em vez de enumerar casos e o que mantem o teste vivo quando alguem acrescenta
    um campo: o enum novo entra na varredura sozinho, sem ninguem lembrar de vir aqui.
    """
    props, defs = _SCHEMA  # type: ignore[misc]
    return [(nome, e) for nome, sub in props.items() if (e := _enum_permitido(sub, defs))]


def test_todo_enum_do_schema_e_varrido() -> None:
    """Guarda da guarda: se o schema deixar de expor enums, o teste abaixo passaria vazio."""
    assert len(_enums_do_schema()) >= 6


@pytest.mark.parametrize("campo,permitidos", _enums_do_schema())
def test_typo_de_uma_letra_em_enum_nunca_mata_o_turno(campo: str, permitidos: list[str]) -> None:
    """Para CADA valor de CADA enum, uma mutacao de 1 caractere: recupera ou descarta, nunca estoura.

    O modelo erra a grafia do proprio enum ("imediatio" por "imediato", visto ao vivo em 12/08) e o
    `Literal` levanta `ValidationError`, que derruba o turno inteiro. O que este teste fixa nao e
    QUAL das duas saidas acontece -- recuperar o typo e descartar o campo sao ambas aceitaveis, e a
    escolha e do limiar de similaridade. O que ele fixa e que a terceira saida (o turno morto) nao
    existe para nenhum valor de nenhum enum.
    """
    for valor in permitidos:
        # troca do 3o caractere: longe do comeco (que ancora o prefixo) e presente em todo valor.
        mutado = valor[:2] + ("z" if valor[2] != "z" else "x") + valor[3:]
        saneado = _sanear({campo: mutado, "proxima_acao_esperada": _NOTA})

        assert _valida(saneado) == [], f"{campo}={mutado!r} passou o saneamento e mata o turno"
        assert saneado.get(campo) in (None, *permitidos), (
            f"{campo}={mutado!r} virou {saneado.get(campo)!r}, que nao esta no dominio"
        )
