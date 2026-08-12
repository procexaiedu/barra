"""Render dos prompts do agente.

BP1 (persona + regras) é GERAL — byte-idêntico para todas as modelos
(CONTEXT.md "IA por modelo"; docs/agente/03 §1-§3.2). O dado por-modelo (BP3: identidade +
programas) nasce aqui declarado (`IdentidadeModelo`/`render_identidade`) mas só passa a ser
consumido no M2. Templates Jinja ficam em `prompts/`.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

# `e_video_chamada` DESCEU para `core/` (11/08/2026) e é reexportado aqui: o predicado tem
# consumidor em `dominio/` (a leitura de tabela que alimenta a escada de desconto), e `dominio/`
# não importa `barra.agente`. Quem já importava de `persona` (nos/prepare_context) não muda.
from barra.core.catalogo import e_video_chamada as e_video_chamada  # reexport explícito (mypy)
from barra.dominio.atendimentos.service import (
    DURACAO_MINIMA_FETICHE_PAGO,
    LinhaDeTabela,
    aceita_fetiche_pago,
    extra_de_fetiche,
    preco_cadastrado_de_fetiche,
)
from barra.settings import get_settings

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "prompts"),
    autoescape=select_autoescape(disabled_extensions=("md.j2",)),  # markdown não precisa de escape
    keep_trailing_newline=True,
)


def brl(valor: Any) -> str:
    """Formata valor inteiro em BRL no padrão da persona: `R$1.500` (sem espaço, ponto como
    separador de milhar). `persona.md` `<voz>` exige exatamente esse formato; o default Python
    `{:,.0f}` usa locale americano (`R$ 1,500`) e contradiria a regra.

    `Decimal(str(valor))` antes do `int` aceita os formatos que chegam do JSONB de idempotência
    (string `"100.00"`, de `settings.pix_deslocamento_valor`) sem o `int("100.00")` crashar."""
    return "R$" + f"{int(Decimal(str(valor))):,}".replace(",", ".")


# Mapa BCP-47 → nome em português. Expor `pt-BR`/`en-US` cru ao LLM dilui o tom (a Bia não fala
# "BCP-47") e gasta tokens com ruído técnico. Códigos desconhecidos viram o próprio código.
_NOMES_IDIOMAS = {
    "pt-BR": "português",
    "pt-PT": "português",
    "pt": "português",
    "en-US": "inglês",
    "en-GB": "inglês",
    "en": "inglês",
    "es": "espanhol",
    "es-ES": "espanhol",
    "es-AR": "espanhol",
    "fr": "francês",
    "fr-FR": "francês",
    "it": "italiano",
    "de": "alemão",
}


def _idioma_humano(codigo: str) -> str:
    return _NOMES_IDIOMAS.get(codigo, codigo)


# Mesmo fuso (America/Sao_Paulo) que o SQL usa para `agora`/`hoje` no mesmo bloco <agenda>
# (prepare_context: `current_timestamp AT TIME ZONE 'America/Sao_Paulo'`). Os datetimes de agenda
# (horario_minimo, bloqueios) chegam aware-UTC do psycopg/proximo_livre — o cálculo roda em UTC
# (comparação com blocos é por instante), mas o cliente lê em horário local. Converter só aqui, na
# fronteira de render, com o MESMO ZoneInfo do âncora: sem isso a hora sai +3h e a IA recusa
# horários válidos da tarde; um offset fixo divergiria do âncora se o DST voltasse.
_FUSO_BR = ZoneInfo("America/Sao_Paulo")

# Abreviações PT-BR fixas p/ o `%a` do filtro `brt` (índice = `date.weekday()`, 0=segunda).
# `strftime("%a")` depende do locale do SO — no locale C (default de container) a <agenda> saía
# "Tue 11/08"/"Thu 13/08" e a IA podia ecoar o inglês pro cliente. Mapa determinístico, sem
# `setlocale` (que é global ao processo e racy com o worker async).
_DIAS_SEMANA_PT = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")


def _brt(dt: datetime | None, fmt: str) -> str:
    """Formata um datetime de agenda em horário de Brasília para o contexto do turno.

    Aware (current_timestamp / proximo_livre preservam o tzinfo da sessão, UTC) é convertido;
    naive é assumido já-local. None vira string vazia (os blocos do template já guardam com `if`).
    `%a` sai do mapa PT-BR fixo acima, nunca do locale."""
    if dt is None:
        return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone(_FUSO_BR)
    if "%a" in fmt:
        fmt = fmt.replace("%a", _DIAS_SEMANA_PT[dt.weekday()])
    return dt.strftime(fmt)


def _duracao_humana(minutos: int) -> str:
    """Minutos -> duração curta pra IA verbalizar: acima de 2h vira horas arredondadas ("~36h"),
    abaixo fica em minutos ("~45 min"). "faltam ~2156 min" (encontro de amanhã) é ilegível e a IA
    repassaria o número cru ao cliente. Recebe o valor absoluto por dentro: o sinal (faltam /
    já passou) é do template."""
    m = abs(minutos)
    if m > 120:
        return f"~{round(m / 60)}h"
    return f"~{m} min"


def _duracao_de_pacote(horas: Any) -> str:
    """Horas de um pacote da tabela -> como a persona FALA a duração: `0.5` → "30min", `1` → "1h",
    `1.5` → "1h30".

    Irmão do `_duracao_humana` (que é de MINUTOS, para o relógio do encontro) e distinto dele de
    propósito: aqui a entrada é a coluna `duracoes.horas`, e o número não leva "~".

    Existe desde que a tabela passou a ter duração fracionária (30min da Catarina, 11/08/2026):
    os templates concatenavam "h" na variável crua e o pacote de meia hora sairia como "(0.5h)" —
    número que a IA repassa ao cliente ("0,5h") em vez do "30min" que ele disse."""
    valor = Decimal(str(horas))
    minutos = int(valor * 60)
    inteiras, resto = divmod(minutos, 60)
    if inteiras == 0:
        return f"{resto}min"
    return f"{inteiras}h" if resto == 0 else f"{inteiras}h{resto:02d}"


_env.filters["brl"] = brl
_env.filters["idioma_humano"] = _idioma_humano
_env.filters["brt"] = _brt
_env.filters["duracao_humana"] = _duracao_humana
_env.filters["duracao_de_pacote"] = _duracao_de_pacote


@dataclass(frozen=True)
class IdentidadeModelo:
    """Variáveis por-modelo do BP3 (identidade óbvia + operacional).

    Declarado para o M2 (BP3); ainda não consumido no M0.
    """

    nome: str
    idade: int
    idiomas: list[str]
    localizacao_operacional: str | None
    tipos_aceitos: list[str]
    # O endereço operacional (ponto de encontro) NÃO vive mais aqui (gate estrutural, análise
    # prod 22/07): ele entra no contexto dinâmico via <local_de_encontro>, gated por estado
    # (prepare_context._resolver_variaveis), pra IA não ter o endereço antes de Qualificado.


@lru_cache(maxsize=8)
def render_persona(
    desconto_degrau_pct: float | None = None, desconto_teto_pct: float | None = None
) -> str:
    """BP1 geral (persona + regras) — sem variáveis por-modelo, idêntico para todas.

    `desconto_degrau_pct`/`desconto_teto_pct` interpolam o bloco <desconto> de `regras.md.j2`
    (ADR-0031: escalada de 2 rodadas — degrau na 1ª contraproposta, teto na 2ª e última): seguem
    GERAL porque são settings globais, não por-modelo. None → lê de settings.
    """
    s = get_settings()
    degrau = s.desconto_degrau_pct if desconto_degrau_pct is None else desconto_degrau_pct
    teto = s.desconto_teto_pct if desconto_teto_pct is None else desconto_teto_pct
    persona = _env.get_template("persona.md").render()
    regras = _env.get_template("regras.md.j2").render(
        desconto_degrau_pct=degrau,
        desconto_teto_pct=teto,
        pix_valor=brl(s.pix_deslocamento_valor),
    )
    return f"{persona}\n{regras}"


def render_prefixo_geral(
    desconto_degrau_pct: float | None = None, desconto_teto_pct: float | None = None
) -> str:
    """BP_GERAL — persona+regras num único bloco system byte-idêntico p/ todas.

    É o prefixo geral global: byte-idêntico entre todas as modelos, ele e o BP_MODELO formam o
    prefixo que o DeepSeek cacheia automaticamente no provider (a disciplina de byte-identidade é
    o que mantém o cache quente).

    Caller único: `prepare_context.py`. Testes que precisam reproduzir o conteúdo do bloco geral
    devem chamar esta função (não montar a string fora — risco de byte-drift).
    """
    return render_persona(desconto_degrau_pct, desconto_teto_pct)


def render_contexto_dinamico(**variaveis: Any) -> str:
    """Contexto dinâmico do turno (02 §5) — texto volátil, NÃO cacheável.

    Renderizado a cada turno e concatenado no último HumanMessage pelo prepare_context;
    nunca vira SystemMessage nem leva cache_control (fica fora do prefixo, "stable first,
    volatile last"). As variáveis são resolvidas por queries no prepare_context.
    """
    return _env.get_template("contexto_dinamico.md.j2").render(**variaveis)


def render_bloco_da_modelo(**variaveis: Any) -> str:
    """Bloco ESTÁTICO por-modelo — 3ª SystemMessage do prefixo, CACHEÁVEL.

    O que aqui entra é função só do CADASTRO dela (as tags `<sem_periodo_longo>`, `<sem_menage>`,
    `<sem_video_chamada>`, `<sem_fetiches>` e o `<periodo_de_trabalho>`), nunca do turno: mesmo
    atendimento, turno a turno, o texto sai byte-idêntico. Renderizava na cauda volátil junto do
    contexto dinâmico e por isso era re-enviado como cache-MISS a cada turno — 66% do custo de
    miss por turno era este conteúdo estático (diagnóstico por traces, 11/08). Aqui ele passa a
    viver no prefixo `[BP_GERAL][BP_MODELO][bloco da modelo]`, que o DeepSeek cacheia
    automaticamente.

    Recebe o MESMO dicionário do `render_contexto_dinamico` (`ContextoDoTurno.como_variaveis()`),
    pelo mesmo motivo do `<ja_registrado>` e do `<foco_do_turno>`: um rename de campo quebra o
    contrato em `tests/unit/test_contrato_variaveis_contexto.py`, não em silêncio no prompt.

    INVARIANTE: só entra aqui o que NÃO varia com o turno. `<cliente>` e `<local_de_encontro>`
    ficam de fora por construção — o segundo é liberado por degrau de estado (ADR-0026), ou seja,
    volátil por design; movê-lo congelaria o degrau no primeiro turno da conversa.
    """
    return _env.get_template("bloco_da_modelo.md.j2").render(**variaveis).strip()


def render_ja_registrado(**variaveis: Any) -> str:
    """Bloco `<ja_registrado>` do turno (spec extracao-janela-dedicada) — texto volátil.

    Estado que o sistema JÁ tem gravado, rotulado como estado do sistema (nunca como fala do
    cliente) e com a instrução de delta. Renderizado no prepare_context a partir do MESMO
    dicionário de `render_contexto_dinamico` — é o que garante que o que a IA lê e o que o
    extrator lê não divergem. Não entra no que o chat recebe: viaja pelo State até a janela
    dedicada da extração.
    """
    return _env.get_template("ja_registrado.md.j2").render(**variaveis)


def render_foco_do_turno(**variaveis: Any) -> str:
    """Bloco `<foco_do_turno>` (re-ancoragem por turno, rodada 3) — texto volátil, NÃO cacheável.

    O que o burst ATUAL do cliente pede, detectado deterministicamente (`nos/_foco_do_turno.py`)
    e devolvido ao modelo como DADO em posição de recência: as perguntas dele citadas, o endereço
    literal quando ele pediu localização e o degrau libera, a rota do preço e a linha da tabela em
    discussão. Vai entre o contexto dinâmico e a fala do cliente no último HumanMessage — a fala
    continua por último (incidente 29/07). Renderiza VAZIO quando o turno não pede nada: conversa
    sem pergunta nem pedido não paga token nenhum. Mesmo dicionário do contexto dinâmico
    (`ContextoDoTurno.como_variaveis()`), pelo mesmo motivo do `<ja_registrado>`: um rename de
    campo quebra o contrato em `test_foco_do_turno.py`, não em silêncio.
    """
    return _env.get_template("foco_do_turno.md.j2").render(**variaveis).strip()


def render_ancora_extracao(agora: datetime | None) -> str:
    """Âncora temporal da janela dedicada da extração (spec extracao-janela-dedicada).

    O MÍNIMO que as descrições dos campos exigem para resolver tempo relativo ("agora", "daqui
    1h", "amanhã"): elas apontam nominalmente para `<agenda hoje="..." agora="HH:MM">`, então a
    âncora reusa a MESMA tag do contexto dinâmico — o resto do bloco `<agenda>` (bloqueios,
    janelas livres, horário mínimo) é conduta de venda e fica fora do que o extrator lê.

    `agora` é o `agora_turno` do State (BRT naive, resolvido no prepare_context); None (turno sem
    relógio resolvido) → sem âncora.
    """
    if agora is None:
        return ""
    return _env.get_template("ancora_extracao.md.j2").render(
        data_atual=agora.date(), hora_atual=agora.strftime("%H:%M")
    )


def render_reminder(
    fase: str | None, nome: str | None = None, fase_humana: str | None = None
) -> str:
    """Reminder anti-drift (03 §10) — texto volátil, NÃO cacheável.

    Reinjeta o núcleo da voz perto do fim da janela em conversas longas, em primeira pessoa
    (sem meta-vocabulário tipo "a persona"/"IA"). O prepare_context o prepende ao último
    HumanMessage, dentro de <lembrete_silencioso> (coberto por <instrucoes_meta> em
    regras.md.j2), na cauda volátil — fora do prefixo cacheável.

    `nome` (da modelo, vindo do BP_MODELO) reancora a IDENTIDADE no fim da janela longa, como
    continuidade de self ("você, {nome} — mulher real, no seu WhatsApp"), sem nunca citar
    "IA"/"robô" — mencionar a negação primaria o tópico (white-bear) e poderia AUMENTAR o
    disclosure-leak. Por-modelo/volátil → fica na cauda, nunca no prefixo BP_GERAL byte-idêntico.
    None → o template omite a âncora (comportamento histórico).

    `fase` (enum cru) segue guardando o `{% if fase %}` do template; `fase_humana` é o texto que ele
    imprime (contrato F32 — só exibição). O chamador (prepare_context) humaniza; None → cai no
    `fase` cru pela sua vez, mantendo o bloco íntegro se o mapa não cobrir o estado.
    """
    return _env.get_template("reminder.md.j2").render(
        fase=fase, nome=nome, fase_humana=fase_humana or fase
    )


def render_aup_saida() -> str:
    """Constituição do output-guard de AUP (ADR 0016 / Etapa 2). Markdown puro, sem variável.

    Prompt PRÓPRIO do judge de saída: NÃO interpola dado por-modelo e NÃO entra em
    BP_GERAL/BP_MODELO/BP_JANELA — logo não afeta o cache hit-rate do chat principal.
    """
    return _env.get_template("aup_saida.md").render()


def render_judge_pos_envio() -> str:
    """Rubrica do judge PÓS-ENVIO (produção assistida, semana 1). Markdown puro, sem variável.

    Prompt PRÓPRIO do judge de telemetria (workers/judge_pos_envio.py): NÃO interpola dado
    por-modelo e NÃO entra em BP_GERAL/BP_MODELO — não afeta o cache hit-rate do chat principal.
    """
    return _env.get_template("judge_pos_envio.md").render()


def render_identidade(m: IdentidadeModelo) -> str:
    """BP3 por-modelo — identidade óbvia + tipos_aceitos (programas concatenados à parte, §3.3)."""
    return _env.get_template("identidade.md.j2").render(
        nome=m.nome,
        idade=m.idade,
        idiomas=m.idiomas,
        localizacao_operacional=m.localizacao_operacional,
        tipos_aceitos=m.tipos_aceitos,
    )


def render_programas(programas: list[dict[str, Any]]) -> str:
    """BP3 por-modelo — tabela nome/duração/preço (03 §3.3).

    Cada linha é uma combinação (programa/duração) da modelo. O schema real (pós-migrations
    0009/0010) tem duração como entidade própria (`duracoes`): `duracao_nome` vem do JOIN, não
    de `programas.duracao_horas` (coluna removida; a query do §3.3 está desatualizada). A lista
    deve chegar já ordenada de forma determinística (pré-req do cache — agente/CLAUDE.md)."""
    return _env.get_template("programas.md.j2").render(programas=programas)


def _linhas_de_uma_hora(programas: list[dict[str, Any]]) -> dict[str, LinhaDeTabela]:
    """A linha de 1 HORA de cada programa, por NOME — a base do extra de fetiche (ADR-0038).

    Nome (e não `programa_id`) porque é o que o render tem em mãos e o que identifica o pacote na
    tabela impressa. `preco_minimo` vai None de propósito: o `<fetiches>` é BP_MODELO, estático,
    sempre no patamar CHEIO — o mínimo só muda valor em degrau/piso, que dependem da negociação
    do turno e por isso não podem entrar no prefixo cacheável.
    """
    return {
        p["nome"]: (Decimal(str(p["preco"])), None)
        for p in programas
        if p.get("duracao_horas") is not None
        and Decimal(str(p["duracao_horas"])) == DURACAO_MINIMA_FETICHE_PAGO
    }


def _grupos_de_extra(
    fetiches: list[dict[str, Any]], programas: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Agrupa os fetiches PAGOS de uma SEÇÃO pelo extra que cada um cobra, com a conta pronta.

    Chave do grupo = o preço cadastrado (None = extra derivado da linha de 1h). Fetiches que
    cobram o mesmo extra saem numa linha só de nomes com UMA tabela; com preços cadastrados
    diferentes, cada valor ganha a sua. Ordem = a do cadastro (dict preserva inserção), pré-req
    do cache do BP_MODELO.

    `extra` do grupo é o valor único do extra — sob o ADR-0038 ele é UM número na maioria dos
    cadastros (o extra é a 1h do programa e não muda com a duração). Fica None só quando a modelo
    tem programas com 1h de preços diferentes (Normal 400 e Completo 600): aí o extra varia de
    linha pra linha e o template volta a imprimir a coluna "Extra". `fonte` diz de onde o número
    veio (`cadastro` ou `uma_hora`), que é o que a frase de cabeçalho precisa nomear.

    Serve às DUAS seções (atos e composição) com a MESMA conta desde o ADR-0039: a 2ª pessoa
    custa o que qualquer outro extra custa, então não há mais um `por_pessoa` que mude a
    aritmética — as seções continuam separadas na saída porque são coisas diferentes de VENDER,
    não porque custam diferente.

    Linha OMITIDA quando `extra_de_fetiche` devolve None: pacote < 1h (decisão de 11/08/2026 — a
    IA nunca pode LER "Normal (30 minutos) | R$650") e programa sem linha de 1h cadastrada
    (fail-closed do ADR-0038 — sem a 1h não há extra a cotar naquele programa; desde o ADR-0039
    isso vale também para a composição, que antes dispensava a 1h). Grupo que fica sem nenhuma
    linha continua na lista; quem decide se a seção renderiza é o `tem_linhas_*` de
    `render_fetiches` (senão sairia cabeçalho de tabela sem corpo).
    """
    uma_hora = _linhas_de_uma_hora(programas)
    grupos: dict[Any, dict[str, Any]] = {}
    for f in fetiches:
        cadastrado = preco_cadastrado_de_fetiche(f.get("preco"))
        grupo = grupos.setdefault(cadastrado, {"nomes": [], "extra": None, "linhas": []})
        grupo["nomes"].append(f["nome"])
    for cadastrado, grupo in grupos.items():
        for p in programas:
            preco = Decimal(str(p["preco"]))
            extra = extra_de_fetiche(
                uma_hora.get(p["nome"]),
                p.get("duracao_horas"),
                preco_cadastrado=cadastrado,
            )
            if extra is None:  # pacote < 1h, ou programa sem linha de 1h: não tem linha
                continue
            # Totais pré-computados, INCLUSIVE o de dois fetiches: a conta chega pronta no dado —
            # o modelo copia, não soma (800+800 já saiu como "1200" em replay 22/07). É por isso
            # que a coluna "+2 fetiches" existe em vez de uma frase mandando somar duas vezes.
            grupo["linhas"].append(
                {
                    "pacote": f"{p['nome']} ({p['duracao_nome']})",
                    "duracao_nome": p["duracao_nome"],
                    "horas": Decimal(str(p["duracao_horas"])),
                    "extra": extra,
                    "total": preco + extra,
                    "total_2": preco + extra * 2,
                }
            )
        extras = {ln["extra"] for ln in grupo["linhas"]}
        grupo["extra"] = extras.pop() if len(extras) == 1 else None
        grupo["fonte"] = "cadastro" if cadastrado is not None else "uma_hora"
    return [{**g, "nomes": ", ".join(g["nomes"])} for g in grupos.values()]


def _nota_de_pacote_curto(
    curtos: list[dict[str, Any]],
    grupos: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Dado da instrução de conduta do pacote curto — None quando ela não deve renderizar.

    A regra "menos de 1h não tem fetiche pago" (11/08/2026) tira a linha da tabela, mas sozinha
    ela deixaria a IA sem fala: o cliente NA meia hora pede um ato pago e o bloco não tem número
    nenhum pra ele. A conduta é upsell — ela faz o ato, só não naquela duração — e mora aqui, no
    `<fetiches>`, e não em `regras.md.j2`: o BP_GERAL é byte-idêntico entre modelos e a maioria
    não tem pacote curto; instrução por-modelo vive no bloco por-modelo.

    Só existe com pacote curto E alguma linha paga impressa — sem os dois não há nem regra a
    explicar nem número a cotar. O exemplo aponta a MENOR linha que o primeiro grupo pago
    imprimiu ("a partir de..."), lida da própria linha: é o mesmo número que a tabela logo acima
    mostrou, nunca um número novo (a IA não pode ler valor que não está na tabela dela).
    """
    if not curtos or not grupos or not grupos[0]["linhas"]:
        return None
    menor = min(grupos[0]["linhas"], key=lambda ln: ln["horas"])
    return {
        "curtos": ", ".join(f"{p['nome']} ({p['duracao_nome']})" for p in curtos),
        "duracao": menor["duracao_nome"],
        "total": menor["total"],
        "fetiche": grupos[0]["nomes"].split(", ")[0],
    }


def render_fetiches(fetiches: list[dict[str, Any]], programas: list[dict[str, Any]]) -> str:
    """BP3 por-modelo — cardápio de fetiches que a modelo FAZ (ADR 0030 / 0035 / 0038).

    Cada item é um fetiche vinculado, com `preco` (None = incluso; preenchido = pago) e a flag
    `cobra_por_pessoa` (COMPOSIÇÃO — quem acompanha quem no encontro; desde 11/08/2026 há um item
    por composição no catálogo, não mais o par ambíguo "Casal"/"Menage"). Incluso vs. pago
    continua sendo `preco` NULL vs. NOT NULL;
    o VALOR do extra pago tem dois regimes:
    - **preço cadastrado** (fonte de verdade, decisão de 11/08/2026): o extra é o número do
      painel, fixo em qualquer pacote — `preco_cadastrado_de_fetiche` separa o número real do
      sentinel truthy que o painel grava só para dizer "pago" (`_PRECO_PAGO_SENTINEL`).
    - **derivado** (ADR-0038, o cadastro de quase todo o prod): o extra é o preço da linha de 1
      HORA do MESMO programa — também fixo em relação à duração do pacote, o que é justamente o
      que permitiu trocar a coluna "Extra" por um número nomeado no cabeçalho.
    Só programa PRESENCIAL entra: a vídeo chamada (ADR-0021) não carrega fetiche pago.
    `cobra_por_pessoa` (composição) mantém a SEÇÃO própria, mas desde o ADR-0039 não tem mais
    ARITMÉTICA própria: a 2ª pessoa custa o mesmo extra dos atos (o pacote não dobra, e o preço
    cadastrado dela já é o total). A seção sobrevive porque a fala é outra — a coluna é "Total com
    a 2ª pessoa", não "+2 fetiches" — e porque é ela que o `<sem_menage>` e o `composicao_em_pauta`
    leem.
    A ausência de um fetiche da lista significa que ela NÃO faz — a IA recusa de forma aberta, sem
    lista de negativos no prompt. As listas chegam ordenadas de forma determinística (pré-req do
    cache — agente/CLAUDE.md): o bloco sai na mesma ordem sempre, sem depender do turno/conversa."""
    # `cobra_por_pessoa` vence o preco NULL: composição "inclusa" não existe (CONTEXT.md,
    # verbete Composição — cadastro assim é cadastro a corrigir); cai na seção "Por pessoa" com o extra
    # derivado do `extra_de_fetiche` (a linha de 1h do programa), nunca nos Inclusos.
    inclusos = [f for f in fetiches if not f.get("preco") and not f.get("cobra_por_pessoa")]
    por_pessoa = [f for f in fetiches if f.get("cobra_por_pessoa")]
    atos = [f for f in fetiches if f.get("preco") and not f.get("cobra_por_pessoa")]
    pagos = atos + por_pessoa
    # Fetiche pago só existe em programa PRESENCIAL: a vídeo chamada (único serviço remoto,
    # ADR-0021) sai de TODAS as seções de extra, inclusive da nota de pacote curto. Exclusão
    # ortogonal à da duração — a chamada de 60min da Catarina (R$600) tem `horas = 1` e passaria
    # no `aceita_fetiche_pago`, virando "Vídeo chamada (1h) | R$1.000": fetiche pago numa chamada
    # de vídeo, que não existe como produto. As linhas curtas dela também não viram a conduta de
    # upsell ("a partir de 1 hora" apontaria a chamada de 1h).
    presenciais = [p for p in programas if not e_video_chamada(p.get("nome", ""))]
    curtos = [p for p in presenciais if not aceita_fetiche_pago(p.get("duracao_horas"))]
    grupos_ato = _grupos_de_extra(atos, presenciais)
    grupos_por_pessoa = _grupos_de_extra(por_pessoa, presenciais)
    # Flag POR SEÇÃO, e não "a modelo tem pacote de 1h+": uma seção pode existir no cadastro e
    # ficar sem NENHUMA linha, e cabeçalho de tabela sem uma linha embaixo é pior que o aviso de
    # que não dá pra cotar. Desde o ADR-0039 as duas perdem linha pelos MESMOS dois motivos
    # (pacote < 1h e programa sem linha de 1h), já filtrados em `_grupos_de_extra` — antes o
    # por-pessoa sobrevivia sem a 1h, porque dobrava o pacote.
    return _env.get_template("fetiches.md.j2").render(
        inclusos=inclusos,
        grupos_ato=grupos_ato,
        grupos_por_pessoa=grupos_por_pessoa,
        tem_pagos=bool(pagos),
        tem_linhas_ato=any(g["linhas"] for g in grupos_ato),
        tem_linhas_por_pessoa=any(g["linhas"] for g in grupos_por_pessoa),
        pacote_curto=_nota_de_pacote_curto(curtos, grupos_ato + grupos_por_pessoa),
    )


def render_cardapio_fechado() -> str:
    """Declaração closed-world do cardápio (rodada 3 do eval de substituição). Markdown puro.

    O contrato "ausência = não faz" sempre existiu como docstring de `render_fetiches` — ou seja,
    só o dev lia. Aqui ele vira texto que o MODELO lê, colado no dado a que se refere (fecha a
    lista, em vez de uma proibição por lacuna — o anti-padrão que a família `<sem_*>` da cauda
    conteve caso a caso). Estático e byte-idêntico entre modelos: não quebra o cache do BP_MODELO.
    """
    return _env.get_template("cardapio_fechado.md").render()


def render_bp3(
    identidade: IdentidadeModelo,
    programas: list[dict[str, Any]],
    fetiches: list[dict[str, Any]],
) -> str:
    """BP3 completo por-modelo: identidade + programas + fetiches + fechamento do cardápio
    (03 §2.3). O `<cardapio_fechado>` sai por último, DEPOIS das listas que ele fecha."""
    return (
        f"{render_identidade(identidade)}\n{render_programas(programas)}\n"
        f"{render_fetiches(fetiches, programas)}\n{render_cardapio_fechado()}"
    )
