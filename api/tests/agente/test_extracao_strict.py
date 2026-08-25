"""strict tool use (Beta) na extracao forcada: schema conforme, endpoint e kill-switch.

Sem API real nem banco. O que se protege aqui e a FRONTEIRA LLM->tool: sem `strict`, o schema so e
validado depois que o modelo gerou (campo inventado -> ValidationError -> turno perdido); com
`strict`, a grammar do provider impede a geracao invalida. As regras do schema sao as da doc
`guides/tool_calls`, e o DeepSeek REJEITA o schema que nao as cumpre — entao um desvio aqui nao
degrada em silencio, quebra a extracao inteira.

Desde 13/08/2026 a flag e LIGADA por default (decisao do usuario); o kill-switch continua sendo o
env `EXTRACAO_STRICT_HABILITADA=false`, sem deploy de codigo.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from barra.agente.ferramentas.extracao import registrar_extracao
from barra.core.llm import criar_chat_deepseek, tool_strict_deepseek
from barra.settings import Settings

# guides/tool_calls: nao suportadas em strict (as duas primeiras em string, as duas ultimas em array).
_NAO_SUPORTADAS = {"minLength", "maxLength", "minItems", "maxItems"}
# `format` aceitos pela grammar (400 do provider enumera; ciclo 4): fora disso o /beta rejeita o
# schema INTEIRO — foi o `format: "date"` de `data_encontro` que derrubou toda extracao em 13/08.
_FORMATS_SUPORTADOS = {"email", "hostname", "ipv4", "ipv6", "uuid"}


def _violacoes(schema: Any, caminho: str = "") -> list[tuple[str, str]]:
    """Todo desvio das regras de strict, com o caminho onde ele esta."""
    achados: list[tuple[str, str]] = []
    if not isinstance(schema, dict):
        return achados
    if "properties" in schema:
        props = schema["properties"]
        faltando = sorted(set(props) - set(schema.get("required") or []))
        if faltando:
            achados.append((caminho or "<raiz>", f"fora de required: {faltando}"))
        if schema.get("additionalProperties") is not False:
            achados.append((caminho or "<raiz>", "additionalProperties != false"))
        for nome, sub in props.items():
            achados += _violacoes(sub, f"{caminho}.{nome}" if caminho else nome)
    for palavra in _NAO_SUPORTADAS & set(schema):
        achados.append((caminho, f"palavra nao suportada: {palavra}"))
    if "format" in schema and schema["format"] not in _FORMATS_SUPORTADOS:
        achados.append((caminho, f"format nao suportado: {schema['format']}"))
    if isinstance(schema.get("items"), dict):
        achados += _violacoes(schema["items"], f"{caminho}[]")
    for combinador in ("anyOf", "oneOf", "allOf"):
        for i, sub in enumerate(schema.get(combinador) or []):
            achados += _violacoes(sub, f"{caminho}|{combinador}{i}")
    for defs in ("$defs", "definitions"):
        for nome, sub in (schema.get(defs) or {}).items():
            achados += _violacoes(sub, f"{caminho}#{nome}")
    return achados


def test_schema_da_extracao_cumpre_as_regras_do_strict() -> None:
    """`convert_to_openai_tool(strict=True)` sozinho NAO basta: ele fecha a raiz e ignora tanto os
    objetos ANINHADOS (`sinais_qualificacao`) quanto as palavras que so o DeepSeek proibe
    (`minLength` em `proxima_acao_esperada`). Estas eram as 2 violacoes remanescentes."""
    tool = tool_strict_deepseek(registrar_extracao)
    assert tool["function"]["strict"] is True
    assert _violacoes(tool["function"]["parameters"]) == []


def test_schema_strict_nao_deixa_ref_pendurado() -> None:
    """A doc do DeepSeek documenta `$def`/`$ref` (singular), enquanto o Pydantic emite `$defs`. O
    schema tem de sair INLINE — um `$ref` sobrevivente seria rejeitado pelo validador do provider."""
    assert "$ref" not in json.dumps(tool_strict_deepseek(registrar_extracao))


def test_todo_campo_da_extracao_entra_em_required() -> None:
    """Mudanca de CONTRATO que o strict impoe: hoje "campo omitido" = "nao observei"; sob strict o
    modelo emite os 19 campos sempre, com `null` explicito. A semantica a jusante e a mesma (NULL
    preserva o anterior no UPSERT), mas o custo em tokens de saida sobe — a medicao de
    `prompt_cache_hit_tokens`/output tokens fica p/ o lote de validacao do ciclo 4.

    18 -> 19 em 14/08 com `deslocamento_por_conta_do_cliente` (quem paga a corrida no externo): o
    numero e um sensor de custo, nao um limite — cada campo novo aqui e mais um `null` explicito
    por turno sob strict, e a bateria de campos da tool e o que invalida o prefixo de cache de
    TODAS as modelos por um warmup (mesma consequencia registrada no ADR-0022)."""
    params = tool_strict_deepseek(registrar_extracao)["function"]["parameters"]
    assert set(params["required"]) == set(params["properties"])
    assert len(params["required"]) == 19


class _ChatEspiao:
    """Captura o que foi bindado (a DECLARACAO enviada ao provider)."""

    model = "deepseek-v4-flash"

    def __init__(self) -> None:
        self.bindado: Any = None

    def bind_tools(self, tools: Any, **_kwargs: Any) -> _ChatEspiao:
        self.bindado = tools
        return self


def _disparo(strict: bool) -> tuple[Any, _ChatEspiao]:
    from barra.agente.nos.extrair import DisparoExtracao

    settings = Settings(deepseek_api_key="k", extracao_strict_habilitada=strict)
    barato = _ChatEspiao()
    disparo = DisparoExtracao(_ChatEspiao(), barato, registrar_extracao, settings)
    return disparo, barato


def test_flag_off_binda_a_basetool_como_antes() -> None:
    """Kill-switch: com a flag OFF nada muda no payload — mesma BaseTool, sem `strict`. E o que
    garante que ligar/desligar e reversivel sem deploy de codigo."""
    _, barato = _disparo(strict=False)
    assert barato.bindado == [registrar_extracao]


def test_flag_on_binda_o_dict_strict() -> None:
    """Com a flag ON vai o DICT normalizado: so ele carrega `strict`/`required` completos. A
    EXECUCAO continua na BaseTool (`_executar_extracao`), que nao passa pelo bind."""
    _, barato = _disparo(strict=True)
    assert isinstance(barato.bindado[0], dict)
    assert barato.bindado[0]["function"]["strict"] is True
    assert _violacoes(barato.bindado[0]["function"]["parameters"]) == []


@pytest.mark.parametrize(
    ("beta", "esperado"),
    [(False, "https://api.deepseek.com"), (True, "https://api.deepseek.com/beta")],
)
def test_endpoint_beta_so_com_a_flag(beta: bool, esperado: str) -> None:
    """`strict` so existe no `/beta`. O chat #1 NAO vai junto: e por a extracao ter instancia
    propria (`extracao_no_modelo_barato`) que o caminho quente segue no endpoint estavel, onde o
    cache de prefixo ja e conhecido."""
    chat = criar_chat_deepseek(Settings(deepseek_api_key="k"), beta=beta)
    assert str(chat.openai_api_base).rstrip("/") == esperado


# --- default ON + kill-switch (13/08/2026) ------------------------------------------------------
# O usuario mandou LIGAR: o default do CODIGO e True. O env continua mandando nos dois sentidos —
# e o mesmo kill-switch sem deploy de sempre, so que agora quem o usa e para DESLIGAR.


def test_default_do_codigo_e_strict_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin da decisao de 13/08/2026: sem env e sem .env, strict nasce LIGADO."""
    monkeypatch.delenv("EXTRACAO_STRICT_HABILITADA", raising=False)
    s = Settings(deepseek_api_key="k", _env_file=None)  # type: ignore[call-arg]
    assert s.extracao_strict_habilitada is True


@pytest.mark.parametrize(("env", "esperado"), [("false", False), ("true", True)])
def test_kill_switch_por_env_nos_dois_sentidos(
    monkeypatch: pytest.MonkeyPatch, env: str, esperado: bool
) -> None:
    """`EXTRACAO_STRICT_HABILITADA=false` desliga sem deploy; `=true` e redundante mas valido."""
    monkeypatch.setenv("EXTRACAO_STRICT_HABILITADA", env)
    s = Settings(deepseek_api_key="k", _env_file=None)  # type: ignore[call-arg]
    assert s.extracao_strict_habilitada is esperado


def test_default_on_nao_arrasta_o_chat_1_para_o_beta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com o default ON, so o chat PROPRIO da extracao barata vai ao `/beta`; o caminho quente
    (chat #1) segue no endpoint estavel — `_criar_chat_principal` nunca passa `beta`, e o bind
    strict em `DisparoExtracao` so existe no braco barato."""
    from barra.agente.graph import _criar_chat_extracao_barata, _criar_chat_principal

    monkeypatch.delenv("EXTRACAO_STRICT_HABILITADA", raising=False)
    settings = Settings(deepseek_api_key="k", _env_file=None)  # type: ignore[call-arg]
    assert settings.extracao_strict_habilitada is True
    principal = _criar_chat_principal(settings)
    assert str(principal.openai_api_base).rstrip("/") == "https://api.deepseek.com"
    barata = _criar_chat_extracao_barata(settings)
    assert str(barata.openai_api_base).rstrip("/") == "https://api.deepseek.com/beta"
