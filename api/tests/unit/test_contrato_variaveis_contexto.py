"""Contrato entre o dicionário de variáveis do turno e os templates que o consomem.

Os dois blocos que a IA e o extrator leem saem do MESMO dicionário de propósito (agente/CLAUDE.md,
"Regras com eco multi-site"): `contexto_dinamico.md.j2` é o que a IA lê, `ja_registrado.md.j2` é o
que o EXTRATOR lê, e `evals/extracao/janela.py:variaveis_do_bloco` reconstrói o segundo para a
bancada offline. Até aqui os três eram amarrados só por prosa — e o Jinja renderiza variável
desconhecida como VAZIA, sem erro: um rename no dicionário apagava um bloco inteiro do prompt em
silêncio, e um campo novo no bloco de estado fazia a bancada medir o extrator contra um bloco que
produção nunca mostrou.

Estes testes fecham as três pontas: toda variável declarada num template existe no dicionário, e o
espelho da bancada é EXATAMENTE o conjunto que o bloco de estado usa. Sem DB, sem crédito.
"""

import re
from datetime import UTC, datetime
from typing import Any

from evals.extracao.janela import variaveis_do_bloco
from jinja2 import meta

from barra.agente.contexto import ContextAgente
from barra.agente.ferramentas.extracao import _DESC_DATA, _DESC_HORARIO
from barra.agente.nos.prepare_context import _anexar_contexto_dinamico
from barra.agente.persona import _env
from barra.dominio.atendimentos.service import _PROXIMO_PASSO

_AGORA_UTC = datetime(2026, 7, 25, 17, 30, tzinfo=UTC)


class _FakeConnVazio:
    """Vazio em tudo: o atendimento chega por kwarg e o relógio vem injetado."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchone(self) -> None:
                return None

            async def fetchall(self) -> list[Any]:
                return []

        return _R()


def _ctx() -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]  # nenhuma query roda com o FakeConn
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=_AGORA_UTC,
    )


def _variaveis_do_template(nome: str) -> set[str]:
    """Variáveis de topo declaradas no template (jinja2.meta). Vars de laço (`{% for b in ... %}`)
    não entram — só o que precisa vir de fora."""
    fonte = _env.loader.get_source(_env, nome)[0]  # type: ignore[union-attr]
    return meta.find_undeclared_variables(_env.parse(fonte))


async def _variaveis_publicadas() -> dict[str, Any]:
    """O dicionário como o `prepare_context` o entrega aos DOIS templates — colhido no FIM de
    `_anexar_contexto_dinamico`, depois das correções que só existem lá (o A2 do dia e o OR da
    sondagem). Colher em `_resolver_variaveis` deixaria de fora justamente o que é acrescentado
    perto do render."""
    _msgs, contexto, _pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        [],
        atendimento={"estado": "Qualificado"},
    )
    return contexto.como_variaveis()


async def test_contexto_dinamico_nao_le_variavel_que_ninguem_publica() -> None:
    """O que a IA lê. Variável fora do dicionário renderiza vazia e o bloco some do prompt sem
    erro — este teste é o que transforma o rename silencioso em falha de CI."""
    faltando = _variaveis_do_template("contexto_dinamico.md.j2") - set(
        await _variaveis_publicadas()
    )

    assert not faltando, f"variáveis do contexto dinâmico sem fonte no dicionário: {faltando}"


async def test_bloco_da_modelo_nao_le_variavel_que_ninguem_publica() -> None:
    """Terceiro consumidor do MESMO dicionário: o bloco estático por-modelo, hoistado da cauda
    para a 3ª SystemMessage do prefixo (otimização de custo, traces 11/08). Mesmo modo de falha —
    variável renomeada renderiza vazia e a negação ativa (`<sem_menage>` & cia.) some do prompt
    sem erro, agora num bloco que ninguém relê no diff da cauda."""
    faltando = _variaveis_do_template("bloco_da_modelo.md.j2") - set(await _variaveis_publicadas())

    assert not faltando, f"variáveis do bloco por-modelo sem fonte no dicionário: {faltando}"


def test_bloco_da_modelo_nao_le_nada_que_varie_com_o_turno() -> None:
    """A premissa do hoist, do lado do CONTRATO (o de bytes está em `test_bloco_da_modelo.py`):
    o template só pode ler campos que saem do cadastro. Um campo por-turno lido aqui quebraria o
    prefixo cacheável a cada turno — o bloco pagaria o mesmo miss da cauda de onde saiu."""
    do_cadastro = {
        "tabela_max_horas",
        "sem_periodo_longo",
        "sem_menage",
        "sem_video_chamada",
        "sem_externo",
        "sem_fetiches",
        "disponibilidade",
    }

    extras = _variaveis_do_template("bloco_da_modelo.md.j2") - do_cadastro

    assert not extras, f"variável por-turno no bloco estático (quebra o cache do prefixo): {extras}"


async def test_escada_de_desconto_e_publicada_e_lida_pela_cauda() -> None:
    """Recorte nominal do teste acima para os campos que carregam VALOR e RODADA, não instrução: o
    número da contraproposta disponível é pré-computado no `prepare_context` e o `escada_estado`
    escolhe o bloco (a escada tem uma rodada com encontro hoje e duas nos outros dias). Um rename
    só de um dos lados apagaria o número em silêncio — e a IA voltaria a multiplicar o percentual
    de cabeça sem ninguém perceber. Conduta-only: a IA lê, o extrator NÃO — por isso os campos
    entram aqui e não no `ja_registrado.md.j2` nem no espelho da bancada."""
    publicadas = await _variaveis_publicadas()
    do_template = _variaveis_do_template("contexto_dinamico.md.j2")

    for campo in ("contraproposta_disponivel", "escada_estado", "preco_na_mesa"):
        assert campo in publicadas, campo
        assert campo in do_template, campo


async def test_condutas_do_valor_de_11_08_sao_publicadas_e_lidas_pela_cauda() -> None:
    """Mesmo recorte nominal, para os campos que o ADR-0041 acrescentou: o PAR da oferta
    condicionada ao dia (os dois números, ou nenhum) e o pacote MAIOR da tabela, que sustenta
    subir o tempo antes de descer o preço.

    Os três blocos que dependem disso são silenciosos por construção — um rename só de um lado
    apagaria o bloco do prompt sem erro nenhum, e a conduta voltaria a ser a revogada ("Seria
    hoje ?") sem ninguém perceber."""
    publicadas = await _variaveis_publicadas()
    do_template = _variaveis_do_template("contexto_dinamico.md.j2")

    for campo in (
        "oferta_se_hoje",
        "oferta_se_outro_dia",
        "pacote_maior",
        "tempo_dele_desconhecido",
    ):
        assert campo in publicadas, campo
        assert campo in do_template, campo


async def test_ja_registrado_nao_le_variavel_que_ninguem_publica() -> None:
    """O que o EXTRATOR lê, do mesmo dicionário — é isso que impede a IA e o extrator de verem
    estados diferentes."""
    faltando = _variaveis_do_template("ja_registrado.md.j2") - set(await _variaveis_publicadas())

    assert not faltando, f"variáveis do bloco de estado sem fonte no dicionário: {faltando}"


def test_bancada_offline_espelha_exatamente_o_bloco_de_estado() -> None:
    """Terceiro site, fora de `src/`: a bancada reconstrói o bloco a partir do replay em vez do
    banco. Igualdade (não subconjunto) nos dois sentidos: campo novo no template que ela não monta
    a faria medir o extrator contra um bloco que produção nunca mostrou; chave que ela monta e o
    template não lê é resto de um campo já removido."""
    do_template = _variaveis_do_template("ja_registrado.md.j2")
    da_bancada = set(variaveis_do_bloco({}))

    assert do_template == da_bancada, (
        f"espelho da bancada fora de sincronia — só no template: {do_template - da_bancada}; "
        f"só na bancada: {da_bancada - do_template}"
    )


def test_ancora_de_tempo_tem_o_mesmo_nome_nos_quatro_sites() -> None:
    """`<agenda hoje="..." agora="HH:MM">` é citada NOMINALMENTE pelas descrições dos campos de
    `registrar_extracao` para resolver tempo relativo ("daqui 1h", "amanhã"), e a janela dedicada
    da extração reusa a mesma tag. Renomear a tag ou seus atributos mata a resolução nos quatro
    sites de uma vez, em silêncio (agente/CLAUDE.md, "Regras com eco multi-site")."""
    contexto = _env.loader.get_source(_env, "contexto_dinamico.md.j2")[0]  # type: ignore[union-attr]
    ancora = _env.loader.get_source(_env, "ancora_extracao.md.j2")[0]  # type: ignore[union-attr]

    assert '<agenda hoje="' in contexto and 'agora="' in contexto
    assert '<agenda hoje="' in ancora and 'agora="' in ancora
    assert '<agenda agora="HH:MM">' in _DESC_HORARIO
    assert '<agenda hoje="..."' in _DESC_DATA


def test_fase_apontada_pelo_proximo_passo_existe_no_regras() -> None:
    """O `<proximo_passo>` do belief nomeia a fase do `<conducao_da_venda>` que vale no turno. A
    tag citada precisa EXISTIR no `regras.md.j2`: apontar pra uma que não existe não quebra nada —
    o modelo simplesmente ignora, e o roteamento some sem deixar rastro, que é o mesmo modo de
    falha silenciosa do rename de variável (agente/CLAUDE.md, "Regras com eco multi-site")."""
    regras = _env.loader.get_source(_env, "regras.md.j2")[0]  # type: ignore[union-attr]
    citadas = {tag for frase in _PROXIMO_PASSO.values() for tag in re.findall(r"<(\w+)>", frase)}

    faltando = {tag for tag in citadas if f"<{tag}>" not in regras}

    assert citadas, "o belief deixou de apontar qualquer fase — o roteamento da cauda sumiu"
    assert not faltando, f"fase apontada pelo belief que não existe no regras.md.j2: {faltando}"
