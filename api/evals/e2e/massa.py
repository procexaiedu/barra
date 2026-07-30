"""Runner em MASSA dos cenarios sinteticos de funcionalidade (Bloco D do plano).

Roda cada `CenarioFunc` com `ClienteRoteirizado` (Python, sem sub-agente): seed -> conducao
multi-turn -> pos-evento determinístico (foto de portaria) -> veredito. Deduplica por `run_tag`
(consulta `corpus.eval_e2e`: o que ja rodou naquele tag e pulado) e agrega cobertura.

`k` execucoes por cenario (default 1; pass^k pronto mas desligado por orcamento — decisao do dev).

⚠️ §0: com o graph REAL gasta credito do agente (1 ainvoke/turno) e exige TEST_DATABASE_URL.
Gravar em `corpus.eval_e2e` (run_tag setado) escreve em prod e exige a ddl.sql aplicada. A
validacao offline injeta um graph fake + ROLLBACK — ver tests/agente/test_e2e_massa.py.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from typing import Any
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.core.tracing import garantir_dataset, linkar_item_run, upsert_item_dataset
from evals.e2e.avaliacao import (
    avaliar_e2e,
    flush_langfuse,
    gravar_veredito,
    pontuar_no_langfuse,
)
from evals.e2e.cenarios import CenarioFunc, cenarios
from evals.e2e.cliente import ClienteRoteirizado
from evals.e2e.persistencia import gravar_resposta_ia, seed_caso_persistente
from evals.e2e.runner import ResultadoE2E, rodar_e2e
from evals.harness import Cenario, ResultadoTurno, estado_pos_turno, habilitar_tracing

# Dataset Langfuse dos cenarios e2e: cada perfil e um item estavel (id = perfil.nome); cada corrida
# (`--dataset-run`) vira um dataset-RUN que linka os itens aos traces daquela execucao (ADR 0019).
DATASET_E2E = "e2e_conducao"


async def _disparar_foto_portaria(conn: AsyncConnection[dict[str, Any]], cen: Cenario) -> None:
    """Evento determinístico: insere a 'imagem' e chama o handoff de domínio (sem worker/vision).

    No P0 qualquer imagem em Aguardando_confirmacao interno e foto de portaria (CONTEXT.md). Reusa
    `handoff_foto_portaria_ia` (mesmo caminho de workers/media.py). `media_object_key=None`.

    `id` pelo default `barravips.uuidv7()` + `RETURNING` (nunca `uuid4()`), mesma razao de
    `persistencia.gravar_resposta_ia`: sem commit por turno as mensagens empatam em `created_at` e
    a janela desempata so por `id` — um id aleatorio joga esta linha p/ o meio da conversa.
    """
    from barra.dominio.atendimentos.service import handoff_foto_portaria_ia

    res = await conn.execute(
        """
        INSERT INTO barravips.mensagens
            (conversa_id, direcao, tipo, conteudo, evolution_message_id)
        VALUES (%s, 'cliente', 'texto', %s, %s)
        RETURNING id
        """,
        (cen.conversa_id, "[foto portaria]", f"e2e-foto-{uuid4().hex}"),
    )
    linha = await res.fetchone()
    assert linha is not None  # RETURNING de um INSERT sempre devolve a linha
    msg_id = linha["id"]
    await handoff_foto_portaria_ia(
        conn, atendimento_id=cen.atendimento_id, mensagem_id=msg_id, media_object_key=None
    )


# BUG #1 (falsa-confirmacao de agenda): a IA nunca pode confirmar no texto um horario que o gate de
# Disponibilidade recusou. `_CONFIRMA` = tokens de fechamento; `_REANCORA` = a conduta correta
# (revela a volta / oferece outro horario). Detecta por BOLHA: confirmacao + o horario rejeitado SEM
# reancoragem na mesma bolha. Regex de alta precisao — o sinal so e significativo na corrida REAL.
_CONFIRMA_AGENDA = re.compile(
    r"fechad[oa]|combinad[oa]|marcad[oa]|confirmad[oa]|te espero|te aguardo|pode vir|"
    r"nos vemos|te esperando",
    re.I,
)
_REANCORA_AGENDA = re.compile(
    r"j[áa] parei|por hoje|amanh|mais cedo|mais tarde|n[ãa]o consigo|n[ãa]o rola|n[ãa]o d[áa]|"
    r"outro hor[áa]rio|consigo at[ée]|s[óo] at[ée]|fora do",
    re.I,
)


def _confirmou_horario_fora(res: ResultadoE2E, hora: str) -> bool:
    """True se a IA confirmou no texto um horario que o gate de Disponibilidade recusou — a
    falsa-confirmacao do BUG #1 (desync chat<->estado). Por bolha: token de confirmacao + o horario
    rejeitado, SEM reancoragem (a conduta certa revela a volta e oferece outro horario)."""
    alvo = re.compile(rf"\b{re.escape(hora)}\s*h?\b")
    for turno in res.turnos:
        for bolha in re.split(r"\n\s*\n", turno.texto or ""):
            if (
                alvo.search(bolha)
                and _CONFIRMA_AGENDA.search(bolha)
                and not _REANCORA_AGENDA.search(bolha)
            ):
                return True
    return False


# Rotulos de tipo (interno/externo/remoto) sao vocabulario de sistema — a IA nunca os diz ao
# cliente (regras.md.j2 <nucleo>). Duracao maior = o upsell por sinal de tempo livre (<sobe_o_ticket>).
_RE_JARGAO = re.compile(r"\b(interno|externo|remoto)\b", re.I)
_RE_DURACAO_MAIOR = re.compile(r"\b2\s*h(oras?)?\b|pernoite|noite (toda|inteira)", re.I)


def _vazou_jargao(res: ResultadoE2E) -> bool:
    """True se alguma bolha da IA usou os rotulos de tipo (interno/externo/remoto) ao cliente."""
    return any(_RE_JARGAO.search(t.texto or "") for t in res.turnos)


def _propos_duracao_maior(res: ResultadoE2E) -> bool:
    """True se a IA propos uma duracao maior (2h/pernoite/noite toda) em algum turno."""
    return any(_RE_DURACAO_MAIOR.search(t.texto or "") for t in res.turnos)


# Abertura do "oi" seco (regras.md.j2 <abertura>, item 1): so o cumprimento — nada de preco/cardapio
# e nada de sonda-de-balcao ("o que voce procura ?"), que o <nucleo> proibe "em nenhuma parafrase".
# O probe CRU ja tem backstop no output_guard; o que este check pega e a PARAFRASE, que passa por la.
_RE_SONDA_ABERTURA = re.compile(
    r"o que (voc[êe]|tu) (procura|busca|quer|deseja|precisa|ta procurando|est[áa] procurando)|"
    r"(como|em que) (eu )?posso (te )?ajudar|o que te traz|me conta o que",
    re.I,
)
_RE_PRECO = re.compile(r"\b\d{3,4}\b")


def _abriu_so_com_cumprimento(res: ResultadoE2E) -> bool:
    """True se o PRIMEIRO turno da IA foi so cumprimento: sem numero de preco e sem sonda."""
    if not res.turnos:
        return False
    primeiro = res.turnos[0].texto or ""
    return not (_RE_PRECO.search(primeiro) or _RE_SONDA_ABERTURA.search(primeiro))


# Issue 04: com <valor_cotado> na cauda (cotou e ele nao aceitou), a segunda venda do Completo
# continua de pe — e sai SOZINHA na bolha, um preco por vez (<cotacao>). O check e generico de
# proposito (nao casa o preco do cenario): "nomeou o completo e deu UM unico numero de preco".
_RE_COMPLETO = re.compile(r"\bcompleto\b", re.I)


def _cotou_completo_sozinho(res: ResultadoE2E) -> bool:
    """True se algum turno nomeou o Completo trazendo exatamente UM preco (nunca dois lado a lado)."""
    return any(
        _RE_COMPLETO.search(t.texto or "") and len(_RE_PRECO.findall(t.texto or "")) == 1
        for t in res.turnos
    )


def _repetiu_bolha_identica(res: ResultadoE2E) -> bool:
    """True se a IA reenviou uma bolha literalmente igual a outra ja dita (soa a robo travado).

    Bolha = bloco separado por linha em branco no texto agregado do turno, como o worker de envio
    fatia. Bolhas curtas de cortesia repetem legitimamente ("Oii", "amor"), entao so contam as com
    3+ palavras — o alvo e a re-cotacao copiada ("600 1h no meu local" duas vezes)."""
    vistas: set[str] = set()
    for turno in res.turnos:
        for bruta in (turno.texto or "").split("\n\n"):
            bolha = " ".join(bruta.split()).casefold()
            if len(bolha.split()) < 3:
                continue
            if bolha in vistas:
                return True
            vistas.add(bolha)
    return False


# Issue 05: depois que a negociacao de preco rodou (recusa ou contraproposta), a pergunta de
# horario dele e SIM ao valor na mesa — a IA crava a hora "sem repetir 'nao consigo' nem re-cotar"
# (<desconto>). O check olha SO o turno que responde a essa pergunta (`turnos_cliente` e paralelo a
# `turnos`), porque antes dela a mesma conduta seria erro (pergunta ainda e pergunta).
_RE_PERGUNTA_HORARIO_CLIENTE = re.compile(r"que horas", re.I)
_RE_HORA_PROPOSTA = re.compile(r"\b\d{1,2}\s*(?:h\b|:\d{2})", re.I)
_RE_RECUSA_REPETIDA = re.compile(r"n[ãa]o consigo|n[ãa]o d[áa]\b|n[ãa]o rola", re.I)


def _avancou_no_horario_apos_negociacao(res: ResultadoE2E) -> bool:
    """True se, no turno que responde a pergunta de horario dele, a IA avancou o fechamento:
    hora concreta na fala, sem repetir a recusa do desconto e sem re-cotar o preco."""
    for i, fala in enumerate(res.turnos_cliente):
        if not _RE_PERGUNTA_HORARIO_CLIENTE.search(fala):
            continue
        if i >= len(res.turnos):
            return False
        texto = res.turnos[i].texto or ""
        return bool(
            _RE_HORA_PROPOSTA.search(texto)
            and not _RE_RECUSA_REPETIDA.search(texto)
            and not _RE_PRECO.search(texto)
        )
    return False


# Issue 05: "no meu local" pressupoe que ela recebe — a modelo que so se desloca nunca oferece um
# local que nao tem (<cotacao>, 3o ramo do formato; <tipos_de_encontro>).
_RE_LOCAL_PROPRIO = re.compile(
    r"\bno meu local\b|\bmeu ap(?:artamento|to)?\b|\bminha casa\b|\bvem (?:aqui|at[ée] mim)\b|"
    r"\bvenha at[ée] mim\b|\bte espero aqui\b",
    re.I,
)


def _ofereceu_local_proprio(res: ResultadoE2E) -> bool:
    """True se alguma bolha da IA ofereceu o local dela (proibido para quem so se desloca)."""
    return any(_RE_LOCAL_PROPRIO.search(t.texto or "") for t in res.turnos)


# Issue 06: com a JANELA vaga dele na mesa ("de noite"), a proposta cai DENTRO da janela — o
# <horario_minimo> e PISO, nao a proposta pronta (<agenda>; <cotacao> e o <ja_sondou_o_dia> da
# cauda dizem o mesmo). O check e RELACIONAL de proposito: nao afirma um numero (o piso e
# ~agora+30min e muda com a hora da corrida), afirma que a hora proposta esta na faixa que ele
# pediu. Faixa diurna 6h-18h = o horario que ele acabou de excluir (o bug: piso as 14h virar
# proposta); "1h"/"2h" de DURACAO caem fora das duas faixas e nao contaminam nenhum dos lados.
_RE_HORA_DITA = re.compile(r"\b(\d{1,2})\s*(?:h\b|:\d{2})")
_FAIXAS_VAGAS = {"de noite": (19, 23), "final do dia": (18, 23), "de manh": (6, 11)}


def _propos_dentro_da_janela(res: ResultadoE2E, janela: str) -> bool:
    """True se o turno que responde a janela vaga dele propos hora DENTRO dela e nenhuma fora.

    Olha so esse turno (`turnos_cliente` e paralelo a `turnos`): antes da janela entrar na mesa,
    o piso e a proposta certa — e e depois dela que a contradicao aparecia."""
    faixa = next((f for chave, f in _FAIXAS_VAGAS.items() if chave in janela), None)
    if faixa is None:
        raise ValueError(f"janela vaga sem faixa mapeada: {janela!r}")
    inicio, fim = faixa
    for i, fala in enumerate(res.turnos_cliente):
        if janela not in fala.casefold() or i >= len(res.turnos):
            continue
        horas = [int(h) for h in _RE_HORA_DITA.findall(res.turnos[i].texto or "")]
        dentro = [h for h in horas if inicio <= h <= fim]
        excluidas = [h for h in horas if 6 <= h <= 18 and not inicio <= h <= fim]
        return bool(dentro) and not excluidas
    return False


# Issue 23 (menage, ADR-0035). O pedido do cliente que abre os dois ramos: ele traz uma segunda
# pessoa DELE. `_numeros` le valor em reais de dentro da fala — junta o separador de milhar antes
# ("1.400" e "1 400" sao o mesmo 1400) e ignora numero de 1-2 digitos (hora, duracao, idade).
_RE_PEDIDO_SEGUNDA_PESSOA = re.compile(
    r"n[óo]s (?:dois|2)\b|(?:levar?|levo|trazer|trago|ir com|vir com)\s+\S*\s*"
    r"(?:namorada|amiga|esposa|mulher|amigo|primo)|m[ée]nage|casal",
    re.I,
)
_RE_NUM_REAIS = re.compile(r"\b\d{3,5}\b")


def _numeros(texto: str) -> set[int]:
    return {int(n) for n in _RE_NUM_REAIS.findall(re.sub(r"(?<=\d)[.\s](?=\d{3}\b)", "", texto))}


def _cotou_dobro_do_pacote(res: ResultadoE2E, preco: int, horas: int) -> bool:
    """True se o turno que responde a segunda pessoa cotou o DOBRO do pacote e nenhum numero do
    regime-ato (<menage>: "o total dobrado, nunca o '+Extra' dos atos").

    `horas` >= 2 e condicao do cenario, nao detalhe: em 1h o dobro e o preco-hora dao o MESMO
    numero (ADR-0035) e um check assim passaria sem distinguir regime nenhum."""
    if horas < 2:
        raise ValueError(f"pacote de {horas}h nao distingue dobro de preco-hora (ADR-0035)")
    extra_ato = round(preco / horas)
    proibidos = {extra_ato, preco + extra_ato}
    for i, fala in enumerate(res.turnos_cliente):
        if not _RE_PEDIDO_SEGUNDA_PESSOA.search(fala) or i >= len(res.turnos):
            continue
        nums = _numeros(res.turnos[i].texto or "")
        return preco * 2 in nums and not (nums & proibidos)
    return False


# Ramo SEM a secao: "'Não faço amor', sem cotar, sem dobrar nada e sem prometer amiga" (<menage>).
# A promessa de amiga e so a AFIRMATIVA (trazer/ver com ela) — "não indico não amor" e a recusa
# certa do <fora_do_cardapio> e nao pode contar como promessa.
_RE_RECUSA_ABERTA = re.compile(
    r"n[ãa]o fa[çc]o|n[ãa]o atendo|n[ãa]o rola|n[ãa]o tenho costume|n[ãa]o trabalho", re.I
)
_RE_PROMESSA_AMIGA = re.compile(
    r"(?:vejo|ver|falo|falar|combino|combinar|pergunto|perguntar)\s+com\s+ela|"
    r"(?:levo|trago|chamo|convido|tenho)\s+(?:uma|minha)\s+amiga|com\s+(?:uma|minha)\s+amiga",
    re.I,
)


def _recusou_menage_sem_cotar(res: ResultadoE2E, precos: list[int]) -> bool:
    """True se a IA recusou o menage no turno do pedido E em NENHUM turno dobrou um pacote ou
    prometeu amiga. Os tres lados juntos: recusar e depois cotar o dobro tres turnos adiante e o
    mesmo erro que cotar na hora."""
    dobros = {p * 2 for p in precos}
    for t in res.turnos:
        texto = t.texto or ""
        if _RE_PROMESSA_AMIGA.search(texto) or (_numeros(texto) & dobros):
            return False
    for i, fala in enumerate(res.turnos_cliente):
        if _RE_PEDIDO_SEGUNDA_PESSOA.search(fala) and i < len(res.turnos):
            return bool(_RE_RECUSA_ABERTA.search(res.turnos[i].texto or ""))
    return False


# Issue 23 (vídeo chamada, ADR-0021): sem o programa na tabela ela "não oferece, não cota e não
# promete chamada nenhuma" (<tipos_de_encontro>). Por BOLHA, porque a negacao certa CONTEM as
# mesmas palavras da oferta ("Não faço chamada amor") — sem o guarda de negacao o check reprovaria
# justamente a conduta correta.
_RE_OFERTA_CHAMADA = re.compile(
    r"(?:podemos|posso|consigo|d[áa] pra|vamos|quer)\s+(?:fazer\s+)?(?:uma\s+)?"
    r"(?:v[íi]deo\s*)?chamada|fa[çc]o\s+(?:uma\s+)?(?:v[íi]deo\s*)?chamada|"
    r"te ligo|te chamo no v[íi]deo|chamada (?:fica|custa|sai|é)",
    re.I,
)
_RE_NEGA_CHAMADA = re.compile(
    r"n[ãa]o\s+(?:fa[çc]o|posso|consigo|rola|d[áa]|tenho)[^\n]{0,25}chamada|"
    r"chamada[^\n]{0,20}n[ãa]o (?:fa[çc]o|rola|tem)",
    re.I,
)


def _ofereceu_video_chamada(res: ResultadoE2E) -> bool:
    """True se alguma bolha ofereceu/cotou chamada — a modelo que nao a tem na tabela nunca o faz."""
    for turno in res.turnos:
        for bolha in re.split(r"\n\s*\n", turno.texto or ""):
            if _RE_OFERTA_CHAMADA.search(bolha) and not _RE_NEGA_CHAMADA.search(bolha):
                return True
    return False


def _avaliar_cenario(cf: CenarioFunc, res: ResultadoE2E) -> dict[str, Any]:
    """Checa as expectativas do cenario sobre os turnos (so significativo com o agente REAL)."""
    tools = [t for turno in res.turnos for t in turno.tool_calls]
    pediu_pix = "pedir_pix_deslocamento" in tools
    aval: dict[str, Any] = {"tools": sorted(set(tools))}
    if cf.tool_esperada is not None:
        aval["tool_esperada_ok"] = cf.tool_esperada in tools
    if cf.estado_esperado is not None:
        aval["estado_esperado_ok"] = res.estado_final == cf.estado_esperado
    if cf.nao_deve_pedir_pix:
        aval["nao_pediu_pix_ok"] = not pediu_pix
    if cf.nao_deve_escalar:
        aval["nao_escalou_ok"] = "escalar" not in tools
    if cf.hora_fora_disponibilidade is not None:
        aval["nao_confirmou_fora_ok"] = not _confirmou_horario_fora(
            res, cf.hora_fora_disponibilidade
        )
    if cf.nao_deve_vazar_jargao:
        aval["sem_jargao_ok"] = not _vazou_jargao(res)
    if cf.deve_propor_duracao_maior:
        aval["propos_maior_ok"] = _propos_duracao_maior(res)
    if cf.deve_abrir_so_com_cumprimento:
        aval["abertura_limpa_ok"] = _abriu_so_com_cumprimento(res)
    if cf.deve_cotar_completo:
        aval["completo_sozinho_ok"] = _cotou_completo_sozinho(res)
    if cf.nao_deve_repetir_bolha_identica:
        aval["sem_bolha_repetida_ok"] = not _repetiu_bolha_identica(res)
    if cf.deve_avancar_apos_negociacao:
        aval["avancou_apos_negociacao_ok"] = _avancou_no_horario_apos_negociacao(res)
    if cf.nao_deve_oferecer_local_proprio:
        aval["sem_local_proprio_ok"] = not _ofereceu_local_proprio(res)
    if cf.janela_vaga_do_cliente is not None:
        aval["dentro_da_janela_ok"] = _propos_dentro_da_janela(res, cf.janela_vaga_do_cliente)
    if cf.menage_dobra_o_pacote is not None:
        aval["dobrou_o_pacote_ok"] = _cotou_dobro_do_pacote(res, *cf.menage_dobra_o_pacote)
    if cf.menage_fora_do_cardapio is not None:
        aval["recusou_menage_ok"] = _recusou_menage_sem_cotar(res, cf.menage_fora_do_cardapio)
    if cf.nao_deve_oferecer_video_chamada:
        aval["sem_oferta_de_chamada_ok"] = not _ofereceu_video_chamada(res)
    return aval


async def _persistir_turno(
    conn: AsyncConnection[dict[str, Any]], cen: Cenario, r: ResultadoTurno
) -> None:
    """Hook pos-turno (modo --persistir): grava a bolha da IA e COMMITA -> aparece no painel."""
    await gravar_resposta_ia(conn, cen, r.texto)
    await conn.commit()


async def rodar_massa(
    conn: AsyncConnection[dict[str, Any]],
    graph: Any,
    *,
    k: int = 1,
    run_tag: str | None = None,
    conn_eval: AsyncConnection[dict[str, Any]] | None = None,
    max_turnos: int = 10,
    persistir: bool = False,
    dataset_run: str | None = None,
) -> list[dict[str, Any]]:
    """Roda os cenarios `k` vezes cada. `conn` seeda/conduz (ROLLBACK do caller, ou COMMIT por turno
    quando `persistir`); `conn_eval` (AUTOCOMMIT separada) recebe o veredito quando `run_tag` setado.

    `persistir`: cada cenario vira uma conversa `origem='e2e'` sob a modelo sandbox (painel
    /observabilidade). O trace Langfuse + score (`escopar_trace`) ligam sozinhos se `setup_langfuse`
    rodou no startup; sem handler, sao no-op.

    `dataset_run`: nome da corrida no dataset Langfuse `e2e_conducao`. Setado -> cada cenario vira um
    item (id=perfil.nome) e o trace do ultimo turno e linkado a esse run (Fase 5). Best-effort/no-op
    sem handler (tracing off)."""
    if dataset_run:
        garantir_dataset(DATASET_E2E)
    feitos: set[str] = set()
    if run_tag and conn_eval is not None:
        cur = await conn_eval.execute(
            "SELECT perfil_nome FROM corpus.eval_e2e WHERE run_tag = %s", (run_tag,)
        )
        feitos = {r["perfil_nome"] for r in await cur.fetchall()}

    resultados: list[dict[str, Any]] = []
    for cf in cenarios():
        if cf.perfil.nome in feitos:
            resultados.append({"cenario": cf.nome, "pulado": "ja_testado"})
            continue
        for _ in range(k):
            cen = await seed_caso_persistente(conn, cf.perfil) if persistir else None
            res = await rodar_e2e(
                conn,
                cf.perfil,
                ClienteRoteirizado(cf.perfil.roteiro_cliente),
                graph=graph,
                max_turnos=max_turnos,
                cen=cen,
                pos_turno=_persistir_turno if persistir else None,
                escopar_trace=True,
            )
            if cf.pos_evento == "foto_portaria" and res.cenario is not None:
                await _disparar_foto_portaria(conn, res.cenario)
                if persistir:
                    await conn.commit()
                est = await estado_pos_turno(conn, res.cenario.atendimento_id)
                res.estado_final = est.get("estado")
                res.trajetoria.append(est)
            veredito = avaliar_e2e(res, cf.perfil)
            aval = _avaliar_cenario(cf, res)
            trace_id = res.turnos[-1].trace_id if res.turnos else None
            await pontuar_no_langfuse(trace_id, veredito)
            if dataset_run:
                # Item estavel por perfil; o trace (ja pontuado pelo judge) vira um item DESTE run.
                upsert_item_dataset(
                    DATASET_E2E, cf.perfil.nome, {"eixo": cf.perfil.eixo_comportamento}
                )
                await asyncio.to_thread(
                    linkar_item_run, DATASET_E2E, cf.perfil.nome, dataset_run, trace_id
                )
            if run_tag and conn_eval is not None:
                await gravar_veredito(
                    conn_eval,
                    veredito,
                    run_tag=run_tag,
                    thread_ref=None,
                    desfecho_real=None,
                    trajetoria=res.trajetoria,
                    eixo=cf.perfil.eixo_comportamento,
                )
            resultados.append(
                {
                    "cenario": cf.nome,
                    "descricao": cf.descricao,
                    "estado_final": res.estado_final,
                    "desfecho_conducao": res.desfecho_conducao,
                    "violacoes": veredito.violacoes,
                    "custo_brl": round(res.custo_brl, 6),
                    "avaliacao": aval,
                }
            )
    return resultados


def _resumo(resultados: list[dict[str, Any]]) -> str:
    linhas = ["", "=== Cobertura de funcionalidades (cenarios sinteticos) ==="]
    custo = 0.0
    for r in resultados:
        if r.get("pulado"):
            linhas.append(f"  - {r['cenario']:22} PULADO ({r['pulado']})")
            continue
        custo += float(r.get("custo_brl", 0) or 0)
        flags = r.get("avaliacao", {})
        checks = " ".join(f"{k}={v}" for k, v in flags.items() if k.endswith("_ok"))
        viol = f" ⚠ {len(r['violacoes'])} violacoes" if r.get("violacoes") else ""
        linhas.append(f"  - {r['cenario']:22} estado={r.get('estado_final')!s:22} {checks}{viol}")
    linhas.append(f"  custo total: R$ {custo:.4f}")
    return "\n".join(linhas)


async def _main(args: argparse.Namespace) -> None:
    from barra.agente.graph import build_graph
    from evals.e2e.sessao import _graph_fake

    ligou = habilitar_tracing()  # liga o trace Langfuse de prod (ADR 0019); no-op sem as envs
    print(f"langfuse: {'ligado' if ligou else 'desligado (sem LANGFUSE_*)'}")
    graph = _graph_fake() if args.fake else build_graph()

    conn = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    conn_eval: AsyncConnection[dict[str, Any]] | None = None
    if args.run_tag:
        conn_eval = await AsyncConnection.connect(
            os.environ["TEST_DATABASE_URL"], autocommit=True, row_factory=dict_row
        )
    try:
        resultados = await rodar_massa(
            conn,
            graph,
            k=args.k,
            run_tag=args.run_tag,
            conn_eval=conn_eval,
            persistir=args.persistir,
            dataset_run=args.dataset_run,
        )
    finally:
        if not args.persistir:
            await conn.rollback()  # seed efemero nunca commita (§0); veredito vai pela conn_eval
        await conn.close()
        if conn_eval is not None:
            await conn_eval.close()
        await flush_langfuse()  # garante a entrega dos traces/scores no processo curto
    print(_resumo(resultados))


def main() -> None:
    ap = argparse.ArgumentParser(description="Runner em massa dos cenarios sinteticos e2e.")
    ap.add_argument("--k", type=int, default=1, help="execucoes por cenario (pass^k; default 1)")
    ap.add_argument("--run-tag", help="grava vereditos em corpus.eval_e2e sob este tag (§0)")
    ap.add_argument(
        "--persistir",
        action="store_true",
        help="COMMITA cada cenario em barravips (modelo sandbox, origem=e2e) p/ o painel (§0)",
    )
    ap.add_argument(
        "--fake", action="store_true", help="chat mockado: valida o encanamento sem credito"
    )
    ap.add_argument(
        "--dataset-run",
        help="vincula cada cenario ao dataset Langfuse e2e_conducao sob este nome de run (Fase 5)",
    )
    args = ap.parse_args()
    if not os.environ.get("TEST_DATABASE_URL"):
        raise SystemExit("Defina TEST_DATABASE_URL (prod self-hosted).")
    autorizado = os.environ.get("E2E_AUTORIZADO") == "1"
    # --persistir COMMITA em prod (mesmo com --fake) e a corrida REAL gasta credito -> §0.
    if args.persistir and not autorizado:
        raise SystemExit(
            "--persistir COMMITA conversas e2e em barravips (§0). Defina E2E_AUTORIZADO=1 apos a "
            "autorizacao do dev (e aplique a migration *_conversas_origem_e2e.sql)."
        )
    if not args.fake and not autorizado:
        raise SystemExit(
            "Corrida em massa REAL gasta credito do agente (§0). Defina E2E_AUTORIZADO=1 apos a "
            "autorizacao do dev, ou use --fake para validar o encanamento sem credito."
        )
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
