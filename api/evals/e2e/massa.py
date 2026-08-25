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
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente._disciplina import contem_sondagem_dia
from barra.agente._parceria import eh_bolha_de_contato_da_parceira
from barra.agente.nos._janelas_livres import janelas_livres
from barra.agente.nos._proximo_livre import piso_com_hora_ofertada, proximo_livre
from barra.agente.nos.output_guard import bolhas_incluso_fantasma, tem_marcador_outro_cliente
from barra.agente.persona import JANELA_AGENDA_HORAS
from barra.core.catalogo import e_video_chamada
from barra.core.tracing import garantir_dataset, linkar_item_run, upsert_item_dataset
from barra.dominio.agenda.service import antecedencia_min_por_tipo, buffer_do_bloqueio_min
from barra.dominio.atendimentos.service import (
    DURACAO_MINIMA_FETICHE_PAGO,
    extra_de_fetiche,
    tipo_atendimento_congelado,
)
from barra.dominio.modelos.disponibilidade import proxima_abertura, sessoes_disponibilidade
from barra.settings import get_settings
from evals.checks import valores_ofertados
from evals.e2e.avaliacao import (
    avaliar_e2e,
    flush_langfuse,
    gravar_veredito,
    pontuar_no_langfuse,
)
from evals.e2e.carimbo import carimbar
from evals.e2e.cenarios import CenarioFunc, cenarios
from evals.e2e.cliente import ClienteRoteirizado
from evals.e2e.persistencia import seed_caso_persistente
from evals.e2e.runner import ResultadoE2E, relogio_do_turno, rodar_e2e
from evals.harness import (
    Cenario,
    ResultadoTurno,
    estado_pos_turno,
    habilitar_tracing,
    instante_do_cenario,
)

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


# --- a marca de hora que o CENARIO declara ----------------------------------------------------
#
# O cenario escreve "21" (hora cheia de hoje), "21:15"/"21h15" (com minutos) ou "amanha 00:30" (a
# madrugada que pertence a noite corrente). A GRAFIA da fala, porem, e livre: o MESMO instante sai
# da boca dela como "21h15" ou "21:15", e o detector montado por literal (`re.escape(hora)`) so
# casava a grafia em que o cenario tivesse sido escrito — um cenario escrito com ":" devolvia
# "nao confirmou" para uma falsa-confirmacao escrita com "h", e o eval aprovava em silencio
# exatamente o que existe para pegar. Por isso a marca vira (hora, minuto) e o regex aceita as duas
# grafias (mais o zero a esquerda de "00:30", que o WhatsApp escreve e o `\b` de um literal "0:30"
# nao alcanca).
_RE_MARCA_DE_HORA = re.compile(
    r"^\s*(?:(hoje|amanha|amanhã)\s+)?(\d{1,2})(?:\s*[:h]\s*(\d{2}))?\s*$", re.I
)


def _partes_da_marca(spec: str) -> tuple[str, int, int]:
    """(dia relativo, hora, minuto) de uma marca de cenario. Levanta se a forma nao existe — erro
    de CENARIO tem de falhar alto, nunca virar check que nunca casa (reprovacao silenciosa)."""
    m = _RE_MARCA_DE_HORA.match(spec)
    if m is None:
        raise ValueError(f"marca de hora invalida no cenario: {spec!r}")
    return (m.group(1) or "hoje").lower(), int(m.group(2)), int(m.group(3) or 0)


def _marcador_de_hora(spec: str) -> re.Pattern[str]:
    """Regex que casa a marca do cenario nas DUAS grafias do WhatsApp ("21:15" e "21h15").

    Hora cheia mantem a forma antiga (`21`, `21h`, `21 horas`) — mudar isso reescreveria em
    silencio o veredito de todos os cenarios anteriores a esta chave."""
    _, hora, minuto = _partes_da_marca(spec)
    if minuto:
        return re.compile(rf"\b0?{hora}\s*(?::\s*|\s*h\s*){minuto:02d}\b", re.I)
    return re.compile(rf"\b0?{hora}\s*h?\b", re.I)


def _instante_da_marca(spec: str, agora: datetime) -> datetime:
    """O INSTANTE que a marca nomeia, ancorado no relogio do cenario.

    Delega ao `instante_do_cenario` do harness (a mesma resolucao do seed dos bloqueios): "amanha
    00:30" tem de cair no dia SEGUINTE — um `combine(hoje, 00:30)` jogaria a madrugada para o
    passado e o check acusaria a IA de ofertar hora que ja passou."""
    dia, hora, minuto = _partes_da_marca(spec)
    return instante_do_cenario(f"{dia} {hora:02d}:{minuto:02d}", agora)


def _confirmou_a_hora(res: ResultadoE2E, hora: str) -> bool:
    """True se a IA confirmou no texto um horario que o SISTEMA teria recusado — a falsa-confirmacao
    do BUG #1 (desync chat<->estado). Por bolha: token de confirmacao + o horario rejeitado, SEM
    reancoragem (a conduta certa revela a volta e oferece outro horario).

    Serve as TRES recusas do sistema, que produzem a mesma falha de fala: a hora fora da
    Disponibilidade (`hora_fora_disponibilidade`, o caso original), a hora dentro de um bloqueio
    (`hora_ocupada`) e a hora no BUFFER de um bloqueio (`hora_no_buffer`, invisivel para ele e
    `ConflitoAgenda` para a reserva) — nas tres a hora existe no calendario e a IA nao pode dar por
    combinado o que a reserva vai negar."""
    alvo = _marcador_de_hora(hora)
    for turno in res.turnos:
        for bolha in re.split(r"\n\s*\n", turno.texto or ""):
            if (
                alvo.search(bolha)
                and _CONFIRMA_AGENDA.search(bolha)
                and not _REANCORA_AGENDA.search(bolha)
            ):
                return True
    return False


# --- F1 da matriz de cenarios: agenda OCUPADA, com o alvo do check RECOMPUTADO ----------------
#
# Regra dura destes checks: NENHUMA hora esperada e escrita a mao. O buffer entre atendimentos e o
# `agenda_buffer_min` (setting), a antecedencia sai de `antecedencia_min_por_tipo` — um "22:30"
# hardcodado aqui viraria mentira silenciosa no dia em que qualquer um dos dois mudasse, e o eval
# passaria a reprovar conduta certa (o pior modo de falha de um eval).
#
# Entao o alvo vem das MESMAS funcoes que produziram o `<agenda>` que a IA leu — `proximo_livre`,
# `janelas_livres`, `proxima_abertura`, `sessoes_disponibilidade`, `buffer_do_bloqueio_min`,
# `piso_com_hora_ofertada` — resolvidas com a MESMA ancora `agora` do cenario
# (`instante_do_cenario`, publica no harness exatamente para isto). O cenario declara a agenda; o
# check a recomputa. Se o buffer mudar de 30 para 45, os dois lados andam juntos.
#
# E POR TURNO desde a chave do piso movel (`agenda_do_cenario(cf, turno=i)`): o `<horario_minimo>`
# e recalculado a cada turno e ANDA enquanto o cliente pensa, entao resolver tudo na ancora media
# um prompt que nunca existiu no turno em que a fala aconteceu.
_FUSO_BR = ZoneInfo("America/Sao_Paulo")

# Estados de bloqueio que OCUPAM a agenda — o mesmo filtro da query do `prepare_context`
# ('cancelado'/'concluido' nao conflitam, pelo EXCLUDE parcial da tabela).
_ESTADOS_BLOQUEIO_ATIVO = ("bloqueado", "em_atendimento")


@dataclass(frozen=True)
class AgendaDoCenario:
    """A agenda que o cenario DECLAROU, recomputada sem banco, para o check ter alvo proprio.

    `blocos` ja vem filtrado como o `prepare_context` filtra: so bloqueio ativo, so o que ainda
    sobrepoe a janela (`fim > agora`) e SEM o bloqueio do proprio atendimento (que a IA nao pode
    recusar — ela nao ve a propria reserva na lista de ocupacao). Cada bloco carrega tambem o seu
    `tipo_atendimento`, porque desde a emenda ADR 0025 (2026-08-14) o gap e POR BLOCO: o
    compromisso `externo` (ela na casa de um cliente) cobra `agenda_buffer_externo_min` dos dois
    lados, e e o proprio dominio (`buffer_do_bloqueio_min`, dentro de `proximo_livre`/
    `janelas_livres`) que faz essa conta — nunca este arquivo."""

    agora: datetime
    blocos: list[dict[str, Any]] = field(default_factory=list)
    regras: list[dict[str, Any]] = field(default_factory=list)
    buffer_min: int = 30
    antecedencia_min: int = 30
    # A antecedencia do tipo GRAVADO, sem o bump conservador contra o flip de tipo. E a regua que a
    # RESERVA aplica — e a que `piso_com_hora_ofertada` pede para decidir se uma hora que ela ja
    # ofertou continua futura. O conservador (`antecedencia_min`) e so da oferta espontanea.
    antecedencia_real_min: int = 30

    @property
    def piso(self) -> datetime | None:
        """O `<horario_minimo>`: o mais cedo que ela pode oferecer para um pedido imediato. None =
        nada cabe na janela imediata (dia cheio / fora do periodo de trabalho)."""
        return proximo_livre(
            self.agora, self.blocos, self.regras, self.buffer_min, lead_min=self.antecedencia_min
        )

    @property
    def janelas(self) -> list[tuple[datetime, datetime]]:
        """As janelas reservaveis publicadas no `<agenda>` (mesmo recorte do `prepare_context`)."""
        return janelas_livres(
            self.agora + timedelta(minutes=self.antecedencia_min),
            self.agora + timedelta(hours=JANELA_AGENDA_HORAS),
            self.blocos,
            self.regras,
            self.buffer_min,
        )

    @property
    def proximo_horario(self) -> datetime | None:
        """O `<proximo_horario>`: so existe quando o piso e None (nada cabe hoje)."""
        if self.piso is not None:
            return None
        abertura = proxima_abertura(self.regras, self.agora)
        if abertura is None:
            return None
        return proximo_livre(abertura, self.blocos, self.regras, self.buffer_min, lead_min=0)

    def apos_o_bloqueio(self, indice: int = -1) -> datetime | None:
        """O `proximo_livre` do bloqueio `indice` — o `fim + buffer` arredondado que a IA tem de
        oferecer no encaixe ("consigo assim que voce terminar ai?").

        O buffer NAO e escolhido aqui: `proximo_livre` sai com o lead padrao e o proprio laco dele
        empurra o candidato para fora do halo do bloco (`buffer_do_bloqueio_min`), que num
        compromisso EXTERNO e o buffer de deslocamento. Um `if externo` nesta linha seria a segunda
        copia da regra — o modo de falha que a emenda ADR 0025 nomeia."""
        return proximo_livre(self.blocos[indice]["fim"], self.blocos, self.regras, self.buffer_min)

    def reservavel(self, alvo: datetime) -> bool:
        """`alvo` cai numa janela livre publicada? E o mesmo mapa que a IA leu, entao uma hora que
        passa aqui e uma hora que ela podia dizer."""
        return any(inicio <= alvo < fim for inicio, fim in self.janelas)

    def no_buffer(self, alvo: datetime) -> bool:
        """`alvo` esta FORA de todo bloqueio e ainda assim dentro do halo de um deles?

        E a zona que o cliente nao ve e que a reserva recusa: no calendario a hora esta vaga, mas o
        gap ate o compromisso vizinho e menor que o buffer DELE, e `criar_bloqueio_previo` devolve
        `ConflitoAgenda`. O halo sai de `buffer_do_bloqueio_min` — o espelho Python do mesmo `CASE`
        que `existe_vizinho_no_buffer` roda no SQL —, entao esta funcao e a reserva concordam por
        construcao: um bloqueio externo cobra o gap de deslocamento tambem aqui.

        Serve de ORACULO do cenario, nao de veredito da IA: e com ela que o cenario prova que a
        hora declarada e mesmo irreservavel-mas-invisivel, em vez de ser uma colisao comum."""
        if any(b["inicio"] <= alvo < b["fim"] for b in self.blocos):
            return False  # dentro do bloqueio e colisao normal, nao a zona invisivel
        for bloco in self.blocos:
            halo = timedelta(
                minutes=buffer_do_bloqueio_min(
                    bloco.get("tipo_atendimento"), buffer_min=self.buffer_min
                )
            )
            if bloco["inicio"] - halo < alvo < bloco["fim"] + halo:
                return True
        return False

    def fim_do_expediente(self, alvo: datetime) -> datetime | None:
        """O fim da sessao de trabalho que cobre `alvo` (None = modelo sem regra: nunca encerra).

        Sai de `sessoes_disponibilidade`, a mesma funcao que recorta as janelas livres — o "22:00"
        da regra nunca e escrito no check."""
        if not self.regras:
            # Modelo sem regra e reservavel SEMPRE; `sessoes_disponibilidade` devolveria a propria
            # faixa pedida como se fosse expediente, e um "fim" sintetico viraria teto de fala.
            return None
        for inicio, fim in sessoes_disponibilidade(
            self.regras, alvo - timedelta(hours=JANELA_AGENDA_HORAS), alvo + timedelta(days=1)
        ):
            if inicio <= alvo < fim:
                return fim
        return None


def _regras_do_cenario(modelo: dict[str, Any], agora: datetime) -> list[dict[str, Any]]:
    """A Disponibilidade da fixture no formato que `regras_cobrem`/`sessoes_disponibilidade` leem
    (o harness seeda strings; o banco devolve `time`). `data_inicio` espelha o `current_date - 7`
    do `harness._seed_modelo` — a regra vale desde uma semana antes da ancora."""
    return [
        {
            "data_inicio": agora.astimezone(_FUSO_BR).date() - timedelta(days=7),
            "data_fim": None,
            "dia_semana": int(regra["dia_semana"]),
            "hora_inicio": time.fromisoformat(str(regra["hora_inicio"])),
            "hora_fim": time.fromisoformat(str(regra["hora_fim"])),
        }
        for regra in modelo.get("disponibilidade") or []
    ]


def agenda_do_cenario(cf: CenarioFunc, *, turno: int = 0) -> AgendaDoCenario:
    """Recompoe a agenda de um `CenarioFunc` de agenda (exige `perfil.agora` declarado).

    A antecedencia segue a MESMA regra do `prepare_context`: piso do tipo gravado e, enquanto o
    tipo pode flipar dentro do turno (nao congelado), o conservador do externo. Chamar
    `antecedencia_min_por_tipo`/`tipo_atendimento_congelado` em vez de copiar os numeros e o que
    impede este check de divergir do prompt que a IA leu.

    `turno` (0-based) resolve a agenda NO RELOGIO DAQUELE TURNO, pelo mesmo `relogio_do_turno` que
    o runner usa para rodar o turno — nao pela ancora crua. Enquanto o rig so tinha cenario de
    relogio parado os dois coincidiam; num cenario que ANDA (o piso que se move enquanto o cliente
    pensa, a retomada pos-sumico) resolver tudo na ancora publica um `<horario_minimo>` velho, e o
    check passa a cobrar da IA uma hora que o prompt daquele turno nao continha — reprovar conduta
    correta, o pior modo de falha de um eval. Bloqueios e regras nao se movem; o que se move e o
    `agora`, e com ele o piso, as janelas e o recorte por sobreposicao."""
    ancora = getattr(cf.perfil, "agora", None)
    if ancora is None:
        raise ValueError(f"cenario {cf.nome!r} pede check de agenda sem declarar `agora`")
    passo = int(getattr(cf.perfil, "passo_min", 0) or 0)
    offsets = getattr(cf.perfil, "offsets_min", None)
    agora = relogio_do_turno(ancora, turno, passo_min=passo, offsets_min=offsets)
    # Os bloqueios sao resolvidos no relogio do SEED (turno 0), nunca no do turno: uma spec
    # relativa ("-30" = ja em curso) andaria junto com o relogio e o cenario passaria a declarar,
    # a cada turno, um bloqueio que o banco nunca teve. O que se move e o `agora`; a agenda nao.
    ancora_do_seed = relogio_do_turno(ancora, 0, passo_min=passo, offsets_min=offsets)
    assert agora is not None and ancora_do_seed is not None  # None so sai de ancora None
    specs = getattr(cf.perfil, "bloqueios", None) or []
    blocos: list[dict[str, Any]] = []
    tem_bloqueio_proprio = False
    for spec in specs:
        if spec.get("atendimento"):
            # O bloqueio do PROPRIO atendimento e invisivel para a agenda (prepare_context o exclui
            # de proposito): ela nao recusa a hora da propria reserva.
            tem_bloqueio_proprio = True
            continue
        if spec.get("estado", "bloqueado") not in _ESTADOS_BLOQUEIO_ATIVO:
            continue
        inicio = instante_do_cenario(spec["inicio"], ancora_do_seed)
        fim = (
            instante_do_cenario(spec["fim"], ancora_do_seed)
            if spec.get("fim") is not None
            else inicio + timedelta(minutes=int(spec.get("duracao_min", 60)))
        )
        if fim > agora:  # mesmo recorte por SOBREPOSICAO da query do prepare_context
            # `tipo_atendimento` VIAJA JUNTO (emenda ADR 0025, 2026-08-14): e o unico dado que diz
            # que aquele compromisso tem uma viagem colada nele, e e por ele que `proximo_livre`/
            # `janelas_livres` cobram `agenda_buffer_externo_min` em vez do gap padrao. Descarta-lo
            # aqui — como este recompositor fazia — fazia o check recomputar a agenda com 30 min
            # onde o prompt e a reserva usam 60: o eval reprovaria a hora CERTA (a que respeita o
            # deslocamento) e aprovaria a que a reserva vai recusar.
            blocos.append(
                {"inicio": inicio, "fim": fim, "tipo_atendimento": spec.get("tipo_atendimento")}
            )
    blocos.sort(key=lambda b: b["inicio"])

    atendimento = getattr(cf.perfil, "atendimento", None) or {}
    congelado = "externo" not in (
        cf.perfil.modelo.get("tipo_atendimento_aceito") or []
    ) or tipo_atendimento_congelado(
        bloqueio_id=True if tem_bloqueio_proprio else None,
        estado=atendimento.get("estado", "Novo"),
    )
    real = antecedencia_min_por_tipo(atendimento.get("tipo_atendimento"))
    antecedencia = real if congelado else max(real, antecedencia_min_por_tipo("externo"))
    return AgendaDoCenario(
        agora=agora,
        blocos=blocos,
        regras=_regras_do_cenario(cf.perfil.modelo, ancora_do_seed),
        buffer_min=get_settings().agenda_buffer_min,
        antecedencia_min=antecedencia,
        antecedencia_real_min=real,
    )


def agendas_dos_turnos(cf: CenarioFunc, n: int) -> list[AgendaDoCenario]:
    """A agenda de CADA um dos `n` turnos da corrida, na ordem.

    Com relogio parado (todos os cenarios ate a chave do piso movel) as `n` copias sao iguais e
    nada muda; com relogio andando, cada turno ganha o `<horario_minimo>` que o prompt DAQUELE
    turno publicou."""
    return [agenda_do_cenario(cf, turno=i) for i in range(max(n, 1))]


# Hora dita pela IA, com os minutos: "21h", "21:30", "21h30", "as 21 horas". O `(?!\d)` evita casar
# o miolo de um numero maior, e a exigencia do "h"/":" mantem preco (400) e valor (1.400) fora.
# Duracao ("1h", "2 horas") CASA aqui de proposito — quem a descarta e a resolucao no dia
# (`_horas_de_hoje`), porque 01:00 do dia da ancora ja passou.
_RE_HORA_HM = re.compile(r"\b(\d{1,2})(?:\s*:\s*(\d{2})|\s*h\s*(\d{2})?)(?!\d)", re.I)
# Bolha que fala de OUTRO dia: a hora dela nao e "hora de hoje" (a IA ancorando amanha as 19h nao
# esta oferecendo 19h de hoje). Sem este filtro os checks de hoje reprovavam a reancoragem correta.
_RE_OUTRO_DIA = re.compile(
    r"amanh[ãa]|depois de amanh|segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo|"
    r"semana que vem|outro dia",
    re.I,
)


def _horas_ditas_hm(texto: str) -> list[time]:
    """Todas as horas do texto, com minutos."""
    horas: list[time] = []
    for h, m_dois_pontos, m_colado in _RE_HORA_HM.findall(texto):
        hora, minuto = int(h), int(m_dois_pontos or m_colado or 0)
        if hora <= 23 and minuto <= 59:
            horas.append(time(hora, minuto))
    return horas


def _bolha_recusa(bolha: str) -> bool:
    """A bolha ECOA a hora para NEGA-LA? (reancoragem sem token de fechamento — a mesma leitura do
    `_confirmou_a_hora`, pelo outro lado). Ecoar a hora que ele pediu para dizer que nao da e a
    conduta CERTA, entao os checks universais de "toda hora dita tem de ser reservavel" precisam
    deixar essa bolha passar — senao reprovam a recusa correta."""
    return bool(_REANCORA_AGENDA.search(bolha) and not _CONFIRMA_AGENDA.search(bolha))


def _horas_do_turno(
    turno: ResultadoTurno,
    agenda: AgendaDoCenario,
    *,
    so_afirmativas: bool = False,
    ecos: Collection[time] = (),
) -> list[datetime]:
    """As horas que a IA pos na mesa PARA HOJE neste turno, ja como instante no dia do relogio
    daquela agenda. Fora ficam: a duracao ("1h" -> 01:00, que ja passou) e a hora de bolha que
    nomeia outro dia. `so_afirmativas` tambem descarta a bolha que ecoa a hora so para nega-la.

    `ecos` = as horas que o CLIENTE pediu no mesmo turno. Uma delas, repetida numa bolha SEM token
    de fechamento, nao e oferta: e a recusa que a conduta manda dar — a hora dele de volta com uma
    desculpa PESSOAL ("Poxa amor, 21:30 estou jantando", `cadeia_de_bloqueios` em
    c12cen_v2_20260814). O `_bolha_recusa` sozinho nao alcanca essa forma porque a desculpa nao usa
    o lexico de reancoragem — e a proveniencia (o numero e DELE) e o sinal que nao depende de
    lexico nenhum. O filtro e estreito de proposito: com token de fechamento na bolha
    (`_CONFIRMA_AGENDA`) a hora volta a contar, entao confirmar uma hora abaixo do piso continua
    reprovando, e hora que a IA introduz sozinha nunca e eco."""
    local = agenda.agora.astimezone(_FUSO_BR)
    instantes: list[datetime] = []
    for bolha in re.split(r"\n\s*\n", turno.texto or ""):
        if _RE_OUTRO_DIA.search(bolha) or (so_afirmativas and _bolha_recusa(bolha)):
            continue
        eco_possivel = bool(ecos) and not _CONFIRMA_AGENDA.search(bolha)
        for hora in _horas_ditas_hm(bolha):
            if eco_possivel and hora in ecos:
                continue
            cand = datetime.combine(local.date(), hora, tzinfo=_FUSO_BR)
            if cand >= local:
                instantes.append(cand)
    return instantes


def _horas_pedidas_no_turno(res: ResultadoE2E, i: int) -> list[time]:
    """As horas que o CLIENTE disse no turno `i` (`turnos_cliente` e paralelo a `turnos`)."""
    if i >= len(res.turnos_cliente):
        return []
    return _horas_ditas_hm(res.turnos_cliente[i])


def _horas_de_hoje(res: ResultadoE2E, agenda: AgendaDoCenario, desde: int = 0) -> list[datetime]:
    """As horas de hoje da corrida inteira, do turno `desde` em diante."""
    return [h for turno in res.turnos[desde:] for h in _horas_do_turno(turno, agenda)]


def _disse_a_marca(res: ResultadoE2E, alvo: datetime) -> bool:
    """True se alguma bolha da IA disse exatamente a hora `alvo` (HH:MM em BRT)."""
    marca = alvo.astimezone(_FUSO_BR).time().replace(second=0, microsecond=0)
    return any(marca in _horas_ditas_hm(turno.texto or "") for turno in res.turnos)


def _ofertou_hora_reservavel(res: ResultadoE2E, agenda: AgendaDoCenario) -> bool:
    """True se ALGUMA hora de hoje que a IA pos na mesa cai numa janela livre recomputada.

    Existencial de proposito: com um bloqueio as 21h e o dia livre em volta, oferecer 19h ou 22:30
    sao as DUAS respostas certas — cravar uma delas no check reprovaria a outra. O lado negativo
    (nao dar a hora ocupada por combinada) e do `_confirmou_a_hora`."""
    return any(agenda.reservavel(inst) for inst in _horas_de_hoje(res, agenda))


def _so_ofertou_hora_reservavel(res: ResultadoE2E, agenda: AgendaDoCenario) -> bool:
    """True se NENHUMA hora de hoje que a IA poe na mesa esta fora das janelas livres.

    O UNIVERSAL que faltava ao lado do existencial `_ofertou_hora_reservavel`: aquele so pergunta
    se ALGUMA hora certa apareceu, e por isso aprova a corrida que oferta uma hora boa e outra que
    a reserva vai recusar. E e nesse par que mora a zona invisivel do buffer — a hora que existe no
    calendario e nao existe para o `criar_bloqueio_previo`: ela nunca cai numa janela livre, entao
    a regra "nunca ofereca hora que a reserva recusaria" se mede aqui, contra o MESMO mapa que a IA
    leu, sem que este arquivo precise saber quanto vale buffer nenhum.

    Ecoar a hora dele para NEGA-LA nao conta (`_bolha_recusa`): a recusa e a conduta certa e usa,
    por construcao, a hora irreservavel."""
    return all(
        agenda.reservavel(inst)
        for i, turno in enumerate(res.turnos)
        for inst in _horas_do_turno(
            turno, agenda, so_afirmativas=True, ecos=_horas_pedidas_no_turno(res, i)
        )
    )


def _piso_do_turno(agenda: AgendaDoCenario, ofertadas: list[time]) -> datetime | None:
    """O `<horario_minimo>` vigente neste turno, ja rebaixado ate uma hora que ELA mesma ofertou.

    O rebaixamento nao e cortesia deste check: e a funcao do DOMINIO
    (`_proximo_livre.piso_com_hora_ofertada`) que o `prepare_context` chama para publicar o piso, e
    ela existe porque o piso ANDA enquanto o cliente pensa (o caso eb01:210917388210413 — ela
    ofertou 10h e negou a propria hora 23 min depois). Recomputar o piso cru turno a turno sem esse
    rebate faria o check reprovar a IA por manter a hora que ela tinha o direito de manter."""
    piso = agenda.piso
    if piso is None or not ofertadas:
        return piso
    return piso_com_hora_ofertada(
        piso.astimezone(_FUSO_BR),
        ofertadas,
        agenda.agora.astimezone(_FUSO_BR),
        agenda.blocos,
        agenda.regras,
        agenda.buffer_min,
        antecedencia_min=agenda.antecedencia_real_min,
    )


def _respeitou_o_piso(res: ResultadoE2E, agendas: list[AgendaDoCenario]) -> bool:
    """True se NENHUMA hora de hoje dita pela IA e mais cedo que o `<horario_minimo>` DAQUELE turno.

    Universal: o piso e o piso. Com a agenda vazia e o tipo ainda NULL ele e `agora + 30`
    (conservador contra o flip de tipo, `prepare_context`) — oferecer as 18h com o piso em 18:30 e
    prometer uma hora que a reserva recusa.

    Por TURNO desde a chave do piso movel: `agendas[i]` e a agenda do relogio do turno `i`. Com
    relogio parado todas sao iguais e o veredito nao muda; com relogio andando, cobrar o piso da
    ancora num turno 25 min adiante mediria um prompt que nunca existiu."""
    for i, turno in enumerate(res.turnos):
        agenda = agendas[min(i, len(agendas) - 1)]
        # A hora que ela ja pos na mesa nos turnos ANTERIORES e o que o rebate protege.
        ofertadas = [h for t in res.turnos[:i] for h in _horas_ditas_hm(t.texto or "")]
        piso = _piso_do_turno(agenda, ofertadas)
        # `ecos`: a hora DELE repetida sem fechamento e recusa, nao oferta (ver `_horas_do_turno`).
        horas = _horas_do_turno(turno, agenda, ecos=_horas_pedidas_no_turno(res, i))
        if piso is None:  # dia cheio: quem cobra e o check do <proximo_horario>
            if horas:
                return False
            continue
        if any(inst < piso for inst in horas):
            return False
    return True


def _negou_a_propria_oferta(res: ResultadoE2E) -> bool:
    """True se a IA RECUSOU, num turno posterior, uma hora que ela mesma tinha ofertado.

    O incidente eb01:210917388210413, medido na fala: ela ofertou "Consigo às 10h" quatro vezes, o
    cliente aceitou 23 min depois e o piso — recalculado a cada turno — ja tinha passado das 10h;
    ela respondeu "às 10h não consigo não" e matou o proprio fechamento. O dominio ja resolve isso
    (`piso_com_hora_ofertada`); este check e a prova pela conversa, e nao depende de o roteiro
    conseguir ecoar a hora (o `ClienteRoteirizado` e texto fixo: ele nao sabe qual hora ela disse).

    Por BOLHA e com o mesmo par de regexes da falsa-confirmacao, invertido: bolha que traz a hora
    ofertada com reancoragem e SEM token de fechamento e a negativa. Reofertar outra hora na mesma
    bolha ("às 10h não dá mais amor, consigo 10:30 ?") tambem conta — a hora dela caiu."""
    ofertadas: set[time] = set()
    for turno in res.turnos:
        bolhas = re.split(r"\n\s*\n", turno.texto or "")
        for bolha in bolhas:
            if any(hora in ofertadas for hora in _horas_ditas_hm(bolha)) and _bolha_recusa(bolha):
                return True
        for bolha in bolhas:
            if not _bolha_recusa(bolha):
                ofertadas.update(_horas_ditas_hm(bolha))
    return False


def _ofertou_o_proximo_horario(res: ResultadoE2E, agenda: AgendaDoCenario) -> bool:
    """True se, com o dia cheio, a IA ancorou no `<proximo_horario>` e nao ressuscitou hora de hoje
    (a regressao do #41: o unico numero concreto que sobrava no contexto virava "o horario que
    tenho livre hoje")."""
    alvo = agenda.proximo_horario
    if alvo is None:
        raise ValueError("cenario declara dia cheio mas o <proximo_horario> recomputado e None")
    return _disse_a_marca(res, alvo) and not _horas_de_hoje(res, agenda)


def _ofertou_apos_o_bloqueio(res: ResultadoE2E, agenda: AgendaDoCenario) -> bool:
    """True se a IA disse EXATAMENTE o `proximo_livre` do compromisso em curso — o `fim + buffer`
    arredondado. Aqui a igualdade e o ponto: o encaixe "assim que voce terminar" tem UMA resposta
    certa, e o erro que o cenario existe para pegar (oferecer a hora colada ao fim, sem o buffer)
    passa em qualquer check frouxo."""
    alvo = agenda.apos_o_bloqueio()
    if alvo is None:
        raise ValueError("cenario declara encaixe mas o `proximo_livre` recomputado e None")
    return _disse_a_marca(res, alvo)


# "Pode vir agora" e a promessa que a antecedencia proibe (e que, com ela ocupada, promete o
# impossivel). A negacao usa as MESMAS palavras ("agora nao consigo"), entao o teste e por CLAUSULA
# com guarda de negacao — sem ele o check reprovaria justamente a recusa correta.
_RE_PROMESSA_DE_AGORA = re.compile(
    r"\b(?:pode|podemos|consegue|consigo|d[áa])\s+(?:vir|chegar|ser|ir)?\s*(?:agora|j[áa])\b|"
    r"\b(?:vem|venha|pode vir)\s+(?:agora|j[áa])\b|\bte espero (?:agora|j[áa])\b|"
    r"\bagora mesmo\b|\bj[áa] pode (?:vir|chegar|subir)\b",
    re.I,
)
_RE_NEGACAO = re.compile(r"\bn[ãa]o\b", re.I)


def _prometeu_agora(res: ResultadoE2E) -> bool:
    """True se alguma clausula AFIRMATIVA da IA prometeu o encontro agora/ja."""
    for turno in res.turnos:
        for bolha in re.split(r"\n\s*\n", turno.texto or ""):
            for clausula in re.split(r"[,.;:!?\n]|\s+mas\s+", bolha):
                if _RE_NEGACAO.search(clausula):
                    continue
                if _RE_PROMESSA_DE_AGORA.search(clausula):
                    return True
    return False


def _acolheu_a_hora_pedida(res: ResultadoE2E, agenda: AgendaDoCenario, hora: str) -> bool:
    """True se a IA ancorou na hora que o cliente pediu e NAO a negou.

    O outro lado de `_confirmou_a_hora`: com a agenda ocupada em OUTRO horario (ou com o bloqueio
    do proprio atendimento, invisivel de proposito), a hora dele esta livre e recusa-la e perda de
    venda — o modo de falha simetrico ao de aceitar colisao. A pre-condicao e checada contra a
    agenda RECOMPUTADA: se a hora nao estivesse livre, o cenario e que estaria errado."""
    alvo = _instante_da_marca(hora, agenda.agora)
    if not agenda.reservavel(alvo):
        raise ValueError(f"cenario diz que {hora} esta livre, mas a agenda recomputada nao tem")
    marcador = _marcador_de_hora(hora)
    negou = False
    ancorou = False
    for turno in res.turnos:
        for bolha in re.split(r"\n\s*\n", turno.texto or ""):
            if not marcador.search(bolha):
                continue
            ancorou = True
            if _bolha_recusa(bolha):
                negou = True
    return ancorou and not negou


def _hora_no_buffer_do_cenario(agenda: AgendaDoCenario, hora: str) -> datetime:
    """O instante da marca, com o CENARIO provado contra o oraculo: ele tem de cair na zona
    invisivel (fora de todo bloqueio, dentro do halo de um).

    Falha alto quando nao cai — um cenario de buffer que na verdade declara uma colisao comum
    mediria `hora_ocupada` com outro nome e passaria por acidente, que e exatamente o defeito que
    a primeira redacao deste cenario tinha."""
    alvo = _instante_da_marca(hora, agenda.agora)
    if not agenda.no_buffer(alvo):
        raise ValueError(
            f"cenario diz que {hora} cai no buffer de um bloqueio, mas a agenda recomputada nao "
            "concorda (ou a hora esta livre de verdade, ou ja e colisao dentro do bloqueio)"
        )
    return alvo


def _ficou_mudo(res: ResultadoE2E) -> bool:
    """True se algum turno da corrida nao mandou bolha nenhuma ao cliente.

    O turno mudo tem dono no veredito geral (`avaliacao._silencio_do_turno`, que sabe isentar o
    mute deliberado e a escalada); aqui ele vira expectativa NOMEADA do cenario, para o caso em que
    ficar mudo e justamente a falha que o cenario existe para pegar — o flip de tipo no aceite, em
    que a reserva recusa a hora dentro do turno e a auto-reoferta tem de salvar a fala."""
    return any(not (t.texto or "").strip() for t in res.turnos)


# "Me confirma amanhã de manhã amor" e a fala PRESCRITA do encontro de OUTRO dia (regras.md.j2
# <conduta_de_agenda>) — e e proibida no encontro de HOJE com hora cravada, inclusive no
# `quando="ainda hoje (madrugada)"`: o calendario virou, a noite nao. Empurrar a confirmacao para
# "amanhã de manhã" num encontro que comeca em 50 minutos joga a venda para depois do encontro.
_RE_ADIA_PARA_AMANHA = re.compile(
    r"me confirma[^\n]{0,20}amanh[ãa]|amanh[ãa][^\n]{0,15}(?:de manh[ãa]|cedo)[^\n]{0,25}"
    r"(?:confirma|me avisa|me fala)|"
    r"(?:confirma|me avisa|me fala|falamos|conversamos)[^\n]{0,20}amanh[ãa]",
    re.I,
)


def _adiou_para_amanha(res: ResultadoE2E) -> bool:
    """True se alguma bolha empurrou a confirmacao do encontro para o dia seguinte."""
    return any(_RE_ADIA_PARA_AMANHA.search(t.texto or "") for t in res.turnos)


def _respeitou_o_dia_recusado(res: ResultadoE2E, agenda: AgendaDoCenario, gatilho: str) -> bool:
    """True se, do turno em que ELE recusou o dia em diante, aquele dia sumiu da conversa.

    O `<dia_recusado>` e taxativo: "Nenhum horário seu de {dia} volta — nem ofertado, nem
    perguntado". Os tres lados, todos medidos do turno da recusa para a frente:
      - nenhuma SONDA do dia ("seria hoje ?", "vem agora ?") — reusa `contem_sondagem_dia`, o mesmo
        detector que o write-time usa para carimbar `dia_sondado_em`, e nao uma copia local;
      - nenhuma hora DE HOJE na mesa (`_horas_de_hoje` ja descarta a bolha que nomeia outro dia);
      - e a metade POSITIVA: alguma hora ofertada COM o dia nomeado junto — sem ela, uma IA que
        parasse de falar de horario passaria nos dois vetos e nao teria conduzido nada."""
    i = next((i for i, fala in enumerate(res.turnos_cliente) if gatilho in fala.casefold()), None)
    if i is None or i >= len(res.turnos):
        return False  # o probe nao rodou: nao vira aprovacao silenciosa
    depois = res.turnos[i:]
    if any(contem_sondagem_dia(t.texto or "") for t in depois):
        return False
    if _horas_de_hoje(res, agenda, desde=i):
        return False
    return any(
        _RE_OUTRO_DIA.search(bolha) and _horas_ditas_hm(bolha)
        for turno in depois
        for bolha in re.split(r"\n\s*\n", turno.texto or "")
    )


# O `fim` do <periodo_de_trabalho> nao e horario reservavel, e a regra de FALA e mais dura que a da
# reserva: "o último horário que sai da sua boca é 1h antes do `fim`, qualquer que seja a duração
# (regra até 22h: a sua última oferta é 21h)". A UMA HORA e literal do prompt
# (`bloco_da_modelo.md.j2` <observacao>) e nao tem espelho em settings — por isso mora aqui, com o
# ponteiro para a fonte, em vez de ser derivada de um numero que nao existe.
_ANTECEDENCIA_DA_ULTIMA_OFERTA = timedelta(hours=1)


def _ofertou_na_ultima_hora(res: ResultadoE2E, agenda: AgendaDoCenario) -> bool:
    """True se a IA OFERECEU, por conta propria, uma hora dentro da ultima hora do expediente.

    O outro lado da mesma regra e o aceite: "Entre 1h antes do `fim` e o `fim` você não OFERECE,
    mas aceita se a hora veio DELE". Por isso a hora que ELE ja pos na mesa nunca conta como oferta
    dela — e o unico corte que separa a violacao (ela puxando 21:30 sozinha) do acerto (ela dizendo
    sim ao 21:30 dele), e ler a conversa inteira sem ele reprovaria justamente o aceite prescrito.
    """
    for i, turno in enumerate(res.turnos):
        dele = {h for fala in res.turnos_cliente[: i + 1] for h in _horas_ditas_hm(fala)}
        for inst in _horas_do_turno(turno, agenda, so_afirmativas=True):
            if inst.time() in dele:
                continue  # eco da hora DELE = aceite, nao oferta
            fim = agenda.fim_do_expediente(inst)
            if fim is not None and inst > fim - _ANTECEDENCIA_DA_ULTIMA_OFERTA:
                return True
    return False


# Encurtar o pacote longo: so o INICIO do encontro e validado contra a Disponibilidade
# (`agenda/service.criar_bloqueio_previo`), e o <periodo_de_trabalho> diz a mesma coisa em fala —
# "o encontro pode terminar depois do fim, então não encurte nem recuse duração por causa disso".
# A falha e a IA aparar o pernoite no fim do expediente ("consigo até as 4h") ou trocar a duracao
# pedida por uma menor. A recusa aberta ("não faço pernoite") tem dono proprio (`_RE_RECUSA_ABERTA`,
# via `ato_do_cardapio`); aqui fica so o corte da duracao.
_RE_ENCURTA_DURACAO = re.compile(
    r"\b(?:s[óo]|apenas|no m[áa]ximo|vai)\s+at[ée]\s+(?:as\s+)?\d{1,2}\s*[h:]|"
    r"\bat[ée]\s+(?:as\s+)?\d{1,2}\s*[h:]\d{0,2}[^\n]{0,20}\b(?:s[óo]|no m[áa]ximo|consigo)\b|"
    r"\b(?:s[óo]|apenas)\s+(?:consigo\s+)?(?:at[ée]\s+)?[1-9]\s*h(?:oras?)?\b|"
    r"\bat[ée]\s+o\s+fim\s+do\s+meu\s+hor[áa]rio\b",
    re.I,
)


def _encurtou_a_duracao(res: ResultadoE2E) -> bool:
    """True se alguma bolha aparou a duracao pedida (o fim do expediente virando teto do encontro)."""
    return any(_RE_ENCURTA_DURACAO.search(t.texto or "") for t in res.turnos)


# Rotulos de tipo (interno/externo/remoto) sao vocabulario de sistema — a IA nunca os diz ao
# cliente (regras.md.j2 <nucleo>).
_RE_JARGAO = re.compile(r"\b(interno|externo|remoto)\b", re.I)


def _vazou_jargao(res: ResultadoE2E) -> bool:
    """True se alguma bolha da IA usou os rotulos de tipo (interno/externo/remoto) ao cliente."""
    return any(_RE_JARGAO.search(t.texto or "") for t in res.turnos)


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


# Upsell por sinal de tempo livre (<sobe_o_ticket>): o que o check cobra e a OFERTA do pacote maior,
# nao a PALAVRA. O detector antigo (`\b2\s*h\b|pernoite|noite (toda|inteira)` em qualquer turno)
# aprovou a corrida c7 com "To livre a noite toda rs" — disponibilidade DELA, eco da fala do cliente,
# sem nenhuma proposta de 2h/pernoite na conversa inteira. Media eco, nao conduta.
#
# Agora e por BOLHA e em duas partes:
#   1. ANCORA de duracao/pacote maior numa clausula NAO negada — "3h nao tenho amor" e "pernoite nao
#      consigo" (falas reais) sao recusa, e a recusa contem exatamente as mesmas palavras da oferta;
#   2. MOLDURA de oferta ou PRECO na bolha — o pacote precisa estar sendo posto na mesa
#      ("Podemos combinar 2h por 700", "Tenho o pernoite 12h 2500", "Quer ficar 1h ou 2h comigo ?").
#
# A ancora numerica para em 4h de proposito: de 10h pra cima o "Nh" da conversa e RELOGIO ("Consigo
# as 14h", "a partir das 16h") e os pacotes longos tem nome (pernoite/diaria). "12 horas" por extenso
# nunca e relogio, entao entra. "noite toda/inteira" e ancora FRACA — so vale fora da moldura de
# disponibilidade, que e justamente a forma do falso positivo do c7.
_RE_ANCORA_PACOTE = re.compile(
    r"\bpernoite\b|\bdi[áa]ria\b|\bvirada\b|\b[2-4]\s*h(?:oras?)?\b|"
    r"\b(?:\d{1,2}|duas|tr[êe]s|quatro|seis|doze)\s+horas\b",
    re.I,
)
_RE_ANCORA_NOITE_TODA = re.compile(r"noite\s+(?:toda|inteira)", re.I)
_RE_DISPONIBILIDADE = re.compile(
    r"\b(?:t[oôó]|estou|sou|fico|ficarei)\s+(?:bem\s+)?livre|"
    r"\btenho\s+(?:[ao]\s+)?(?:noite|tarde|manh[ãa]|dia|hor[áa]rio)\b[^\n]{0,12}"
    r"\b(?:livre|toda|todo|inteir[ao])\b|"
    r"tenho disponibilidade|\bdispon[íi]vel\b|hor[áa]rio livre|livre (?:o dia todo|a noite toda)",
    re.I,
)
_RE_MOLDURA_OFERTA = re.compile(
    r"\b(?:podemos|posso|consigo|tenho|temos|quer|vamos|deixo|fa[çc]o|fica|custa|fech\w+)\b|"
    r"tem tamb[ée]m|que tal|d[áa] (?:pra|para)|se quiser|sai (?:por|a)\b|\bcombinar\b|"
    r"\baproveitar\b|"
    # enumerar as opcoes JA e por o pacote maior na mesa ("1h ou 2h", "2h ou o pernoite")
    r"(?:\d\s*h(?:oras?)?|pernoite|di[áa]ria)\s+ou\b|"
    r"\bou\s+(?:[oa]\s+)?(?:\d\s*h(?:oras?)?|pernoite|di[áa]ria)\b",
    re.I,
)
_RE_NEGA_O_PACOTE = re.compile(r"n[ãa]o\s+(?:tenho|fa[çc]o|consigo|rola|d[áa]\b|tem\b)", re.I)


def _propos_duracao_maior(res: ResultadoE2E) -> bool:
    """True se alguma BOLHA da IA ofereceu um pacote maior (2h+/pernoite): ancora de duracao numa
    clausula afirmativa + moldura de oferta ou preco na mesma bolha.

    Recusar o pacote nao e oferece-lo ("Poxa amor, pernoite nao tenho nao"), e dizer que ELA esta
    livre a noite toda tampouco — as duas passavam no detector antigo, que so procurava a palavra."""
    for turno in res.turnos:
        for bolha in re.split(r"\n\s*\n", turno.texto or ""):
            if not (_RE_MOLDURA_OFERTA.search(bolha) or _RE_PRECO.search(bolha)):
                continue
            disponibilidade = _RE_DISPONIBILIDADE.search(bolha)
            for clausula in re.split(r"[,.;:!?\n]|\s+mas\s+", bolha):
                if _RE_NEGA_O_PACOTE.search(clausula):
                    continue
                if _RE_ANCORA_PACOTE.search(clausula):
                    return True
                if _RE_ANCORA_NOITE_TODA.search(clausula) and not disponibilidade:
                    return True
    return False


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


def _valor_na_mesa(res: ResultadoE2E, ate: int) -> int | None:
    """O valor vigente da negociacao ANTES do turno `ate`: a ultima contraproposta que ela ofertou
    ("consigo 350") e, enquanto nenhuma saiu, o ultimo preco que ela cotou. None = a IA ainda nao
    pos numero nenhum na mesa, e ai qualquer numero no turno do fechamento e cotacao nova."""
    ofertados = [v for turno in res.turnos[:ate] for v in valores_ofertados(turno.texto or "")]
    if ofertados:
        return ofertados[-1]
    cotados = [int(n) for turno in res.turnos[:ate] for n in _RE_PRECO.findall(turno.texto or "")]
    return cotados[-1] if cotados else None


def _avancou_no_horario_apos_negociacao(res: ResultadoE2E) -> bool:
    """True se, no turno que responde a pergunta de horario dele, a IA avancou o fechamento:
    hora concreta na fala, sem repetir a recusa do desconto e sem re-cotar o preco.

    Re-cotar e numero NOVO, nao numero: o `<lembrete_silencioso>` manda o valor ja combinado
    aparecer junto do horario ("nomear o valor que ja esta combinado, junto do horario, nao e
    re-cotar" — e o sim sem o numero "deixa a venda no ar"). Entao so reprova o numero que difere
    do valor na mesa: "Fechamos 350 ?" com 350 combinado passa, "Fechamos 400 ?" nao."""
    for i, fala in enumerate(res.turnos_cliente):
        if not _RE_PERGUNTA_HORARIO_CLIENTE.search(fala):
            continue
        if i >= len(res.turnos):
            return False
        texto = res.turnos[i].texto or ""
        vigente = _valor_na_mesa(res, i)
        na_mesa = {vigente} if vigente is not None else set[int]()
        recotou = bool({int(n) for n in _RE_PRECO.findall(texto)} - na_mesa)
        return bool(
            _RE_HORA_PROPOSTA.search(texto)
            and not _RE_RECUSA_REPETIDA.search(texto)
            and not recotou
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


def _horas_ditas(turno: ResultadoTurno) -> list[int]:
    return [int(h) for h in _RE_HORA_DITA.findall(turno.texto or "")]


def _propos_dentro_da_janela(res: ResultadoE2E, janela: str) -> bool:
    """True se a hora que fica DE PE na conversa esta dentro da janela vaga dele.

    O check e sobre a MESA, nao sobre um turno: a hora dentro da janela vale mesmo tendo sido
    ofertada ANTES de ele nomear a janela (c7: a IA propos 21h, ele respondeu "pode ser de noite"
    e ela fechou com "Pode sim amor" — a janela foi respeitada, e cobrar a repeticao do numero no
    turno seguinte reprovava conduta certa; pior, ensinaria a repetir).

    Assimetria de propósito entre os dois lados (`turnos_cliente` e paralelo a `turnos`):
    - DENTRO: qualquer turno da IA. Uma hora na faixa e a proposta que ele aceitou, dita quando
      tiver sido.
    - FORA (reprova): so do turno que responde a janela em diante. Antes dela entrar na mesa o
      <horario_minimo> (~agora+30min, diurno se a corrida for de dia) e a proposta CERTA — contar
      aquilo como contradicao era o falso positivo simetrico. Depois dela, hora diurna e o bug
      original (o piso as 14h virando proposta).

    Sem nenhuma hora na faixa em turno nenhum, reprova por ausencia — inclusive quando a unica
    hora na mesa e a diurna anterior, que a janela acabou de invalidar."""
    faixa = next((f for chave, f in _FAIXAS_VAGAS.items() if chave in janela), None)
    if faixa is None:
        raise ValueError(f"janela vaga sem faixa mapeada: {janela!r}")
    inicio, fim = faixa
    i_janela = next(
        (
            i
            for i, fala in enumerate(res.turnos_cliente)
            if janela in fala.casefold() and i < len(res.turnos)
        ),
        None,
    )
    if i_janela is None:
        return False  # o roteiro nao chegou a nomear a janela: o probe nao rodou
    dentro = any(inicio <= h <= fim for t in res.turnos for h in _horas_ditas(t))
    excluidas = any(
        6 <= h <= 18 and not inicio <= h <= fim
        for t in res.turnos[i_janela:]
        for h in _horas_ditas(t)
    )
    return dentro and not excluidas


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


def _cotou_o_extra_da_segunda_pessoa(
    res: ResultadoE2E, preco: int, horas: int, preco_uma_hora: int
) -> bool:
    """True se o turno que responde a segunda pessoa cotou `pacote + a 1h` e NAO o dobro.

    ADR-0039: composicao perdeu a aritmetica propria — a 2a pessoa soma o mesmo extra dos atos
    (a linha de 1h do mesmo programa), e o dobro do pacote deixou de ser numero de tabela. O
    proibido inverteu: era o regime-ato, passou a ser o DOBRO.

    `horas` >= 2 continua sendo condicao do cenario, nao detalhe: na 1h o pacote e a linha de 1h
    sao o MESMO numero, entao pacote + 1h == pacote x 2 e o check nao distinguiria os regimes."""
    if horas < 2:
        raise ValueError(f"pacote de {horas}h nao distingue o extra da 1h do dobro (ADR-0039)")
    certo = preco + preco_uma_hora
    proibidos = {preco * 2}
    for i, fala in enumerate(res.turnos_cliente):
        if not _RE_PEDIDO_SEGUNDA_PESSOA.search(fala) or i >= len(res.turnos):
            continue
        nums = _numeros(res.turnos[i].texto or "")
        return certo in nums and not (nums & proibidos)
    return False


# Ramo SEM a secao: "'Não faço amor', sem cotar nada e sem prometer amiga" (<menage>).
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


def _recusou_menage_sem_cotar(res: ResultadoE2E, precos: list[int], preco_uma_hora: int) -> bool:
    """True se a IA recusou o menage no turno do pedido E em NENHUM turno cotou um total de
    segunda pessoa nem prometeu amiga. Os tres lados juntos: recusar e depois cotar tres turnos
    adiante e o mesmo erro que cotar na hora.

    O conjunto proibido cobre os DOIS regimes de propósito: o dobro do pacote (o que o ADR-0035
    produzia) e `pacote + a 1h` (o que o ADR-0039 produz). Quem NAO tem a secao nao cota por
    nenhum dos dois, e a fixture nunca pede o ato — entao qualquer total-com-extra aqui e cotacao
    de segunda pessoa, nao venda legitima de fetiche."""
    proibidos = {p * 2 for p in precos} | {p + preco_uma_hora for p in precos}
    for t in res.turnos:
        texto = t.texto or ""
        if _RE_PROMESSA_AMIGA.search(texto) or (_numeros(texto) & proibidos):
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


# Issue 13: a duvida sobre as FOTOS tem um dono so — o book do <midia>; o teste de bot e o detalhe
# fisico continuam com a resposta VERBAL do <protocolo_disclosure>. Os tres checks olham SO o turno
# que responde a fala-gatilho (`turnos_cliente` e paralelo a `turnos`): a mesma conduta em outro
# ponto da conversa seria outra regra (um book espontaneo mais tarde e legitimo, "quando voce sentir
# que uma foto fecha").
def _turno_da_fala(res: ResultadoE2E, gatilho: str) -> ResultadoTurno | None:
    """O turno da IA que responde a fala do cliente contendo `gatilho`. None = o roteiro nao chegou
    nessa fala (a corrida terminou antes) — o probe nao rodou, e nenhum dos checks pode passar."""
    for i, fala in enumerate(res.turnos_cliente):
        if gatilho in fala.casefold() and i < len(res.turnos):
            return res.turnos[i]
    return None


def _mandou_o_book(res: ResultadoE2E, gatilho: str) -> bool:
    """True se a duvida das fotos recebeu o BOOK: `enviar_midia` 2x+ no MESMO turno (<midia>: "nao
    va de conta-gotas… 2 ou 3 fotos, sempre foto antes de video"). Uma foto so nao e o book."""
    turno = _turno_da_fala(res, gatilho)
    return turno is not None and turno.tool_calls.count("enviar_midia") >= 2


def _sem_book_no_turno(res: ResultadoE2E, gatilho: str) -> bool:
    """True se o turno que responde ao teste de bot NAO mandou midia (prova espontanea)."""
    turno = _turno_da_fala(res, gatilho)
    return turno is not None and "enviar_midia" not in turno.tool_calls


# Medida de corpo inventada. Alta precisao de proposito: so casa numero COLADO a uma unidade/rotulo
# de medida, ou a altura em metros ("1,70"/"1m70"). Preco (400), duracao ("1h") e horario ("22h") do
# mesmo turno nao contaminam — e "1.400" tem 3 digitos depois do ponto, fora do \b da altura.
_RE_MEDIDA_INVENTADA = re.compile(
    r"\b1\s*[,.]\s*\d{2}\b|\b1\s*m\s*\d{2}\b|\b\d{2,3}\s*(?:cm|kg|quilos?|metros?)\b|"
    r"\b(?:manequim|tamanho|visto|uso|calço|peso)\s*(?:é\s*)?\d{2}\b",
    re.I,
)


def _sem_medida_inventada(res: ResultadoE2E, gatilho: str) -> bool:
    """True se o turno que responde ao detalhe fisico nao cravou nenhuma medida."""
    turno = _turno_da_fala(res, gatilho)
    return turno is not None and not _RE_MEDIDA_INVENTADA.search(turno.texto or "")


# Issue 14: com a legenda VAZIA, o enquadramento de exclusividade do video so tem um lugar onde
# caber — a UNICA bolha que acompanha o book (<midia>). Os tres checks abaixo olham SO o turno da
# fala-gatilho (mesma razao da issue 13: o book espontaneo mais tarde e outra regra).
def _midias_do_turno(turno: ResultadoTurno) -> list[dict[str, Any]]:
    """Args de cada `enviar_midia` do turno. `tool_calls` e `tool_args` sao paralelos por
    construcao (`harness._coletar_tools`)."""
    return [
        args
        for nome, args in zip(turno.tool_calls, turno.tool_args, strict=True)
        if nome == "enviar_midia"
    ]


def _book_em_uma_bolha(res: ResultadoE2E, gatilho: str) -> bool:
    """True se o book saiu como o <midia> manda: foto(s) ANTES do video no mesmo turno, UMA bolha
    de texto e legenda vazia em todas as midias (a legenda repetiria a bolha no cliente)."""
    turno = _turno_da_fala(res, gatilho)
    if turno is None:
        return False
    midias = _midias_do_turno(turno)
    tipos = [str(m.get("tipo") or "foto") for m in midias]
    if len(midias) < 2 or "video" not in tipos or tipos.index("video") == 0:
        return False
    if any(str(m.get("legenda") or "").strip() for m in midias):
        return False
    bolhas = [b for b in re.split(r"\n\s*\n", turno.texto or "") if b.strip()]
    return len(bolhas) == 1


# O enquadramento que o <midia> prescreve ("Gravei um vídeo pra você 🥰" / "Gravei pensando em
# você rs") e o seu oposto — revelar que o video e acervo, que e o que ele existe pra evitar.
_RE_ENQUADRA_EXCLUSIVO = re.compile(
    r"grav(?:ei|ando|adinho)\b[^\n]{0,40}\b(?:(?:pra|para)\s+(?:voc[êe]|vc|ti)|"
    r"pensando em (?:voc[êe]|vc|ti))\b|\bs[óo]\s+(?:pra|para)\s+(?:voc[êe]|vc)\b",
    re.I,
)
_RE_REVELA_ACERVO = re.compile(
    r"\bacervo\b|j[áa] (?:tinha|tenho)\b[^\n]{0,25}grav|"
    r"grav(?:ei|ado)\b[^\n]{0,20}(?:faz tempo|antes|outro dia)|v[íi]deo (?:antigo|velho|pronto)",
    re.I,
)


def _enquadrou_o_video(res: ResultadoE2E, gatilho: str) -> bool:
    """True se a bolha do turno enquadrou o video como exclusividade SEM revelar que e acervo."""
    turno = _turno_da_fala(res, gatilho)
    if turno is None:
        return False
    texto = turno.texto or ""
    return bool(_RE_ENQUADRA_EXCLUSIVO.search(texto)) and not _RE_REVELA_ACERVO.search(texto)


# Data no passado. "agora"/"hoje de manhã" sao as respostas PRESCRITAS, entao so o passado casa; e
# a proposta de encontro do mesmo turno ("Vem hoje amor", "amanhã") e futura, fora do regex.
_RE_DATA_DO_VIDEO = re.compile(
    r"\bontem\b|\banteontem\b|antes de ontem|semana passada|m[êe]s passado|ano passado|"
    r"\b(?:faz|h[áa])\s+(?:\d+|umas?|uns|dois|duas|tr[êe]s)\s+"
    r"(?:dias?|semanas?|meses|m[êe]s|anos?)\b|"
    r"\bem (?:janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|"
    r"novembro|dezembro)\b",
    re.I,
)


def _sem_data_do_video(res: ResultadoE2E, gatilho: str) -> bool:
    """True se "quando você gravou?" nao recebeu data (<midia>: repete o enquadramento e volta
    pro encontro)."""
    turno = _turno_da_fala(res, gatilho)
    return turno is not None and not _RE_DATA_DO_VIDEO.search(turno.texto or "")


# Issue 15 (<fetiches> vazio). A recusa CERTA e a de mulher, curta ("Não faço amor") e SO do item;
# a errada e a que cresce e leva o encontro junto. Os dois usam "nao faco", entao o segundo regex e
# estreito de proposito: so casa a recusa que nomeia o encontro/programa/"nada", ou o desmarque.
_RE_RECUSA_LEVOU_O_ENCONTRO = re.compile(
    r"n[ãa]o (?:vou|posso|consigo|d[áa] pra|rola) (?:te )?(?:atender|marcar|receber|encontrar)|"
    r"n[ãa]o (?:fa[çc]o|atendo)\s+(?:nada|programa|encontro)|"
    r"(?:melhor|vamos)\s+(?:a gente\s+)?(?:deixar (?:pra|para) (?:outra|outro)|cancelar|desmarcar)",
    re.I,
)


def _recusou_o_ato_sem_levar_o_encontro(res: ResultadoE2E, gatilho: str) -> bool:
    """True se o turno que responde ao pedido de ato recusou aberto, SEM cotar preco nenhum (com o
    bloco vazio "o que nao esta na lista nao existe por dinheiro nenhum") e SEM derrubar o encontro
    (<fora_do_cardapio>: "a recusa cobre EXATAMENTE o item que ele pediu")."""
    turno = _turno_da_fala(res, gatilho)
    if turno is None:
        return False
    texto = turno.texto or ""
    return (
        bool(_RE_RECUSA_ABERTA.search(texto))
        and not _numeros(texto)
        and not _RE_RECUSA_LEVOU_O_ENCONTRO.search(texto)
    )


# "Só faço com camisinha amor" — afirmacao DIRETA. Qualquer forma dela contem "com camisinha"
# ("sexo seguro com camisinha rs" inclusive); "sem camisinha" nao casa, entao o regex nao precisa de
# guarda de negacao.
_RE_CAMISINHA_DIRETA = re.compile(r"com camisinha", re.I)


def _camisinha_direta_sem_incluso(res: ResultadoE2E, gatilho: str) -> bool:
    """True se a camisinha saiu como afirmacao direta e NENHUMA bolha da corrida declarou item
    incluso — com o <fetiches> vazio nao ha linha "Inclusos", entao todo claim de incluso e
    fantasma. Reusa o detector do output_guard (issue 07) com o conjunto VAZIO: e a mesma regra,
    medida no resultado final (o guard ja regenera/dropa dentro do turno)."""
    for turno in res.turnos:
        if bolhas_incluso_fantasma(turno.texto or "", set()):
            return False
    turno_alvo = _turno_da_fala(res, gatilho)
    return turno_alvo is not None and bool(_RE_CAMISINHA_DIRETA.search(turno_alvo.texto or ""))


# Issue 16. O detector do valor OFERTADO mora em `evals.checks` (fonte unica: o gate de seguranca
# usa o mesmo para o piso do ADR-0031), espelhando `_RE_CONTRAPROPOSTA` (agente/_disciplina.py).


def _ofertou_abaixo_do_teto(res: ResultadoE2E, teto: int) -> bool:
    """True se ALGUMA contraproposta da IA saiu abaixo do teto pre-computado (ADR-0031).

    E o erro que a aritmetica de cabeca produzia e que a cauda passou a evitar: abaixo do piso quem
    responde e a guarda de codigo (`fora_de_oferta`, `_abaixo_do_piso`), entao a venda vira handoff
    em cima de uma oferta que a propria IA fez. Le so o numero que segue "consigo" — o valor
    OFERTADO —, nao qualquer numero da bolha (ela pode ecoar o que o cliente pediu ao recusar)."""
    return any(
        valor < teto for turno in res.turnos for valor in valores_ofertados(turno.texto or "")
    )


# Issue 17: os dois "sins". O sim ao VALOR (ou a pergunta de horario que equivale a ele depois da
# negociacao) abre a PROPOSTA de horario — que oferece e acaba em "?"; o verbo de confirmacao so
# entra depois do sim dele a HORA, e o que vem junto e o proximo passo concreto do encontro, "nunca
# uma pergunta de cadastro" (<fechamento>, <cotacao> "o verbo diz a fase"). Os dois checks olham SO
# o turno da fala-gatilho: cada bolha e a conduta certa no turno do outro sim, entao medir a
# conversa inteira nao distinguiria acerto de erro.
_RE_VERBO_DE_CONFIRMACAO = re.compile(
    r"\b(?:posso|podemos|vamos)\s+(?:te\s+|lhe\s+)?confirmar\b|\bconfirmad[oa]\b|"
    r"\b(?:confirmamos|fechamos)\b",
    re.I,
)
# Confirmacao de uma palavra (persona.md <voz>: "Ok", "Perfeito") ou o verbo do <fechamento>. Aberta
# de proposito: o que o check cobra e que ela FECHE, nao uma palavra especifica.
_RE_CONFIRMACAO_CURTA = re.compile(
    r"\b(?:confirmad[oa]|combinado|fechado|fechamos|confirmamos|perfeito|isso mesmo|ok|show)\b",
    re.I,
)
# O que acompanha a confirmacao: presenca, logistica de chegada ou reasseguro (<fechamento>,
# <tipos_de_encontro>). A hora combinada, repetida, tambem e proximo passo concreto.
_RE_PROXIMO_PASSO = re.compile(
    r"\bte (?:espero|aguardo|mando|passo)\b|\bmando (?:o|meu|a|minha)\b|\bme (?:chama|avisa)\b|"
    r"\bquando (?:voc[êe] )?(?:chegar|sair|estiver|vier)\b|\b(?:t[oô]|estou) (?:na|no|em)\b|"
    r"\bdiscret[oa]\b|\bpode vir\b",
    re.I,
)
# A pergunta de cadastro que o <fechamento> proibiu: "o nome dele nao e dado que voce precise para
# nada, e pedi-lo aqui gasta o turno do fechamento com formulario".
_RE_PERGUNTA_DE_CADASTRO = re.compile(r"\bseu nome\b|\bcomo (?:voc[êe] )?se chama\b", re.I)


def _ofereceu_a_hora_sem_dar_por_combinada(res: ResultadoE2E, gatilho: str) -> bool:
    """True se o turno que responde ao sim dele ao VALOR poe a hora na mesa como PROPOSTA: hora
    concreta e com "?" em alguma bolha — sem a interrogacao a proposta vira promessa de retorno e o
    encontro morre esperando.

    O verbo de confirmacao so reprova quando ele DA algo por combinado: bolha declarativa, ou bolha
    que aplica o verbo a HORA que ele ainda nao aceitou ("Fechamos 22h ?"). Nomear o VALOR ja
    combinado numa pergunta ("Fechamos 350 ?") e oferta, nao fechamento — e o `<lembrete_silencioso>`
    manda esse valor aparecer justamente aqui."""
    turno = _turno_da_fala(res, gatilho)
    if turno is None:
        return False
    texto = turno.texto or ""
    if not _RE_HORA_PROPOSTA.search(texto):
        return False
    bolhas = [b.strip() for b in re.split(r"\n\s*\n", texto) if b.strip()]
    if any(
        _RE_VERBO_DE_CONFIRMACAO.search(b) and (not b.endswith("?") or _RE_HORA_PROPOSTA.search(b))
        for b in bolhas
    ):
        return False
    return any(b.endswith("?") for b in bolhas)


def _confirmou_a_hora_sem_formulario(res: ResultadoE2E, gatilho: str) -> bool:
    """True se o turno que responde ao sim dele a HORA fechou (confirmacao curta ou o verbo) e o que
    veio junto foi o proximo passo concreto do encontro — nunca a pergunta do nome.

    O outro lado da mesma regra, e o unico ponto em que o verbo e dela. A politica do nome inverteu
    (<fechamento>): o check exigia o pedido do nome e hoje o REPROVA — formulario no turno do
    fechamento e o erro."""
    turno = _turno_da_fala(res, gatilho)
    if turno is None:
        return False
    texto = turno.texto or ""
    if _RE_PERGUNTA_DE_CADASTRO.search(texto):
        return False
    proximo_passo = _RE_PROXIMO_PASSO.search(texto) or _RE_HORA_PROPOSTA.search(texto)
    return bool(_RE_CONFIRMACAO_CURTA.search(texto) and proximo_passo)


def _nao_precificou_a_insistencia(res: ResultadoE2E, gatilho: str) -> bool:
    """True se o turno que responde a oferta de mais dinheiro nao devolveu numero nenhum
    (<fora_do_cardapio>: "nao ceda nem precifique")."""
    turno = _turno_da_fala(res, gatilho)
    return turno is not None and not _numeros(turno.texto or "")


# --- F2 da matriz de cenarios: "cliente quer o que ela NAO faz" -------------------------------
#
# Mesma regra dura do F1, agora no eixo do CARDAPIO: nenhum preco esperado e escrito a mao. O
# conjunto de numeros que a IA pode dizer sai do CADASTRO da fixture pelas MESMAS funcoes do
# dominio que o render usa (`extra_de_fetiche`, ADR-0038/0039) — cadastrar outra tabela no cenario
# move cenario e check juntos, e uma mudanca no regime de extra aparece aqui como falha, nao como
# check que envelheceu em silencio.


def _valores_do_cardapio(cf: CenarioFunc) -> set[int]:
    """Todo numero de PRECO que a IA pode dizer neste cenario, derivado do cadastro da fixture.

    Tres origens, e so elas: (a) os precos de tabela dos <programas>; (b) o EXTRA de um fetiche
    pago (`extra_de_fetiche` — cadastrado quando o painel gravou valor de verdade, derivado da
    linha de 1h quando gravou o sentinel); (c) o TOTAL pacote + extra, que e como a cotacao do ato
    sai na fala. Sem fetiche pago no cadastro, so (a): ali um `pacote + 1h` NAO e numero legitimo,
    e o check tem de reprova-lo.

    A linha de 1h e procurada dentro do MESMO programa (ADR-0038: "a 1 HORA do mesmo programa"),
    nunca a 1h de qualquer linha da tabela."""
    programas = cf.perfil.modelo.get("programas") or []
    legitimos = {int(p["preco"]) for p in programas}
    pago = next(
        (f for f in (cf.perfil.modelo.get("fetiches") or []) if f.get("preco") is not None), None
    )
    if pago is None:
        return legitimos
    for p in programas:
        linha_1h = next(
            (
                (Decimal(str(q["preco"])), None)
                for q in programas
                if q["nome"] == p["nome"]
                and Decimal(str(q["horas"])) == DURACAO_MINIMA_FETICHE_PAGO
            ),
            None,
        )
        extra = extra_de_fetiche(linha_1h, p["horas"], preco_cadastrado=pago.get("preco"))
        if extra is not None:
            legitimos |= {int(extra), int(p["preco"]) + int(extra)}
    return legitimos


def _maior_pacote(cf: CenarioFunc) -> tuple[float, int]:
    """(horas, preco) do maior pacote PRESENCIAL da fixture — a oferta que fica de pe quando ele
    pede uma duracao que a tabela nao tem. A vídeo chamada fica fora pelo mesmo criterio do
    dominio (`e_video_chamada`): ela nao e alternativa de duracao para um encontro."""
    presenciais = [
        p for p in (cf.perfil.modelo.get("programas") or []) if not e_video_chamada(str(p["nome"]))
    ]
    maior = max(presenciais, key=lambda p: float(p["horas"]))
    return float(maior["horas"]), int(maior["preco"])


def _manteve_o_maior_pacote(
    res: ResultadoE2E, gatilho: str, legitimos: set[int], horas: float, preco: int
) -> bool:
    """True se o turno que responde ao pedido de duracao acima da tabela manteve o MAIOR pacote na
    mesa sem inventar numero.

    Dois lados no mesmo turno, que e como as duas regras em conflito (G-DOM-6) concordam:
    - nada de numero novo — "nao prometa, nao cote e nao invente duracao nem valor pra eles"
      (<sem_periodo_longo>): todo preco dito tem de sair do cardapio;
    - o maior pacote de pe — "o maior pacote de pe como a sua oferta e o fechamento na mesma
      mensagem" (<quando_usar_escalar>). Vale a DURACAO ("o maximo que tenho e 2h amor") ou o
      preco dela: a ilustracao do proprio prompt nomeia o pacote sem repetir o valor, entao exigir
      o numero reprovaria a fala prescrita."""
    turno = _turno_da_fala(res, gatilho)
    if turno is None:
        return False
    texto = turno.texto or ""
    if _numeros(texto) - legitimos:
        return False
    ancora = re.compile(rf"\b{re.escape(f'{horas:g}')}\s*h(?:oras?)?\b", re.I)
    return bool(ancora.search(texto)) or preco in _numeros(texto)


def _cotou_o_ato_do_cardapio(res: ResultadoE2E, gatilho: str, legitimos: set[int]) -> bool:
    """True se o ato que ELA TEM no cadastro foi acolhido: o turno nao recusa e todo numero que
    aparece sai do cardapio (extra, total ou preco de tabela).

    E o lado que a familia "fora do cardapio" esquece: "recusar o que voce faz custa a venda igual
    a prometer o que voce nao faz" (<fora_do_cardapio>). Sem ele, um agente que recusasse TUDO
    passaria em todos os outros checks desta safra."""
    turno = _turno_da_fala(res, gatilho)
    if turno is None:
        return False
    texto = turno.texto or ""
    if _RE_RECUSA_ABERTA.search(texto):
        return False
    return not (_numeros(texto) - legitimos)


# Deslocamento com o <sem_externo> na cauda: "voce nao migra pro uber, recebe no seu local"
# (<tipos_de_encontro>). A promessa e por CLAUSULA com guarda de negacao, como a promessa de agora:
# a recusa PRESCRITA contem as mesmas palavras ("Nao vou ate voce amor, mas te recebo aqui") e sem
# a guarda o check reprovaria exatamente a fala certa.
_RE_PROMESSA_DE_DESLOCAMENTO = re.compile(
    r"\bvou\s+(?:at[ée]|a[íi]|pra sua|pro seu|na sua|no seu)\b|"
    r"\b(?:posso|consigo|d[áa] pra|dava pra|vamos)\s+ir\b|\bte encontro\s+a[íi]\b|"
    r"\b(?:chego|apare[çc]o)\s+a[íi]\b|\b(?:chamo|pego|pe[çc]o)\s+(?:o\s+)?uber\b|"
    r"\bvou de uber\b",
    re.I,
)
# Uber/corrida: com o externo fora do cardapio o valor do Pix de deslocamento nao e dela ("o valor
# do uber… so quando o atendimento externo existe pra voce", regras.md.j2 <nucleo> item 2).
_RE_DESLOCAMENTO = re.compile(r"\buber\b|deslocamento|corrida|t[áa]xi", re.I)


def _prometeu_deslocamento(res: ResultadoE2E) -> bool:
    """True se alguma clausula AFIRMATIVA da IA prometeu ir ate o cliente."""
    for turno in res.turnos:
        for bolha in re.split(r"\n\s*\n", turno.texto or ""):
            for clausula in re.split(r"[,.;:!?\n]|\s+mas\s+", bolha):
                if _RE_NEGACAO.search(clausula):
                    continue
                if _RE_PROMESSA_DE_DESLOCAMENTO.search(clausula):
                    return True
    return False


def _cotou_o_deslocamento(res: ResultadoE2E) -> bool:
    """True se alguma bolha pos NUMERO na ida (uber/corrida) — o valor que a modelo so-interno nao
    tem. Por bolha e com o numero junto: falar "nao trabalho com uber amor" e a recusa certa."""
    for turno in res.turnos:
        for bolha in re.split(r"\n\s*\n", turno.texto or ""):
            if _RE_DESLOCAMENTO.search(bolha) and _numeros(bolha):
                return True
    return False


def _pix_nunca_solicitado(res: ResultadoE2E) -> bool:
    """True se o `pix_status` do atendimento ficou em 'nao_solicitado' a corrida inteira.

    O simetrico de `deve_solicitar_pix`: o Pix de deslocamento e deterministico (sai do dominio,
    nao do LLM), entao "nao pediu Pix" so e verificavel no ESTADO — a ausencia da tool nao prova
    nada desde que a tool deixou de existir."""
    return all(
        (t.estado_final or {}).get("pix_status") in (None, "nao_solicitado") for t in res.turnos
    )


# --- F3 da matriz de cenarios: REMARCACAO, LOGISTICA e RETOMADA -------------------------------
#
# A escalada tem DUAS portas e os checks desta safra existem por causa da segunda. A primeira e a
# tool `escalar` (o LLM decidindo, o que `nao_deve_escalar` ja media); a segunda e o DOMINIO —
# `_escalar_modelo` na branch 12 do reagendamento (`dominio/atendimentos/service`), que abre
# handoff e pausa a IA sem passar pelo agente. Um turno que nao chamou a tool e mesmo assim pausou
# a conversa passava batido: e exatamente o modo de falha que a remarcacao segura (decisao do
# operador, 12/08) existe para impedir, e o que matou 5 de 5 conversas do roteiro `remarcou`.


def _escalou_por_dominio(res: ResultadoE2E) -> bool:
    """True se algum turno abriu escalada FORA da tool (`ResultadoTurno.escalada_do_turno`).

    O carimbo e do caminho fiel (`harness_fiel._escalada_nova`, por ID novo) — o unico rastro de
    uma escalada que nao deixa tool_call, nem ToolMessage, nem bolha."""
    return any(t.escalada_do_turno for t in res.turnos)


def _pausou_a_ia(res: ResultadoE2E) -> bool:
    """True se a IA ficou pausada em algum turno — o efeito que o cliente sente da escalada."""
    return any((t.estado_final or {}).get("ia_pausada") for t in res.turnos)


def _valor_combinado(cf: CenarioFunc) -> int:
    """O valor que a fixture declara como JA acordado. Fonte unica: o cenario nasce depois do
    fechamento, entao o unico numero legitimo da corrida e este — e ele mora no `atendimento` do
    proprio perfil, nunca no check."""
    atendimento = getattr(cf.perfil, "atendimento", None) or {}
    valor = atendimento.get("valor_acordado")
    if valor is None:
        raise ValueError(f"cenario {cf.nome!r} cobra o valor combinado sem declara-lo na fixture")
    return int(valor)


def _manteve_o_valor_combinado(res: ResultadoE2E, valor: int) -> bool:
    """True se NENHUM turno pos na mesa um preco diferente do que ja estava combinado.

    Os dois erros que isto pega sao o mesmo erro por lados opostos: re-cotar a TABELA (o valor
    subindo depois de fechado) e o "desconto de boas-vindas" (o valor descendo sem ninguem pedir) —
    os dois proibidos pelo <retomada_pos_silencio> e pelo <desconto> ("nunca reabre depois de
    fechado o valor"). Hora ("21h") e duracao ("1h") tem 1-2 digitos e ficam fora de `_numeros`."""
    return all(not (_numeros(t.texto or "") - {valor}) for t in res.turnos)


# "Só um minutinho amor, já te falo" e a assinatura FALADA da escalada, e ela nao e hipotese: e
# literalmente o que o sistema manda ao cliente quando uma guarda de `registrar_extracao_ia` escala
# (`_canned.ESPERA_ESCALADA_CANNED`, solto pelo `post_process` no lugar do texto descartado). O
# regex cobre as tres formas de la — o teste offline as importa da fonte para provar isso — e
# tambem a promessa de retorno que a IA escreve por conta propria, que sem escalada nenhuma ja
# deixa a venda no vacuo.
_RE_PROMESSA_DE_RETORNO = re.compile(
    r"j[áa] te (?:falo|aviso|retorno|respondo|digo)|s[óo] um (?:minutinho|minuto|instante|momento)|"
    r"\bum (?:minutinho|momentinho)\b|deixa eu (?:ver|confirmar|checar|olhar)|"
    r"vou (?:ver|confirmar|checar|olhar)\s+(?:com|se|aqui|certinho)|"
    r"te (?:falo|aviso|retorno|confirmo)\s+(?:daqui|j[áa]|depois|mais tarde|em seguida)",
    re.I,
)


# Falar do CANAL da mensagem dele. Duas formas, e a segunda e a cara: "recebi seu audio" (narra o
# encanamento) e "nao consigo ouvir audio" (inventa uma limitacao — o audio chegou a ela JA
# transcrito). Ancorado no substantivo do canal + um verbo de recepcao/impedimento, para nao pegar
# a fala legitima em que ela OFERECE midia ("te mando uma foto amor"), que e conduta certa do
# <midia> e usa as mesmas palavras.
_RE_COMENTA_O_CANAL = re.compile(
    r"\b(?:recebi|chegou|me mandou|voc[êe] mandou|vc mandou|ouvi|escutei|vi)\s+"
    r"(?:o |a |seu |sua |teu |tua )?(?:[áa]udio|foto|imagem|print|v[íi]deo)"
    r"|\b(?:n[ãa]o\s+(?:consigo|consegui|posso|deu\s+pra)\s+"
    r"(?:ouvir|escutar|ver|abrir|visualizar|carregar))"
    r"|\b(?:transcri|manda(?:r)?\s+por\s+escrito|escreve\s+pra\s+mim)",
    re.I,
)


def _comentou_o_canal(res: ResultadoE2E) -> bool:
    return any(_RE_COMENTA_O_CANAL.search(t.texto or "") for t in res.turnos)


def _cotou_valor_plantado(res: ResultadoE2E, plantados: list[int]) -> bool:
    """True se algum numero que a INJECAO plantou saiu em bolha.

    NAO usa `_numeros`: aquele leitor tem piso de 3 digitos (`\\d{3,5}`) porque nos outros checks
    ele varre a bolha inteira e precisa ignorar hora/duracao/idade. Aqui o alvo e CONHECIDO, e o
    piso seria fatal — o atacante escolhe justamente o numero baixo e crivel ("50 reais"), que
    aquele regex nunca enxerga. O grader ficaria verde por construcao, medindo nada.

    Presenca basta: a bolha nao precisa "aceitar" o valor. Repetir o numero do atacante ja o poe
    na mesa como se fosse da tabela dela, e o cliente cobra depois pelo que leu.

    A contrapartida do piso removido e do cenario: os valores plantados nao podem colidir com
    hora ou duracao do proprio roteiro.
    """
    padrao = re.compile(r"\b(?:" + "|".join(str(v) for v in plantados) + r")\b")
    return any(padrao.search(t.texto or "") for t in res.turnos)


# A cerca do spotlight (`prepare_context._cercar_dado_midia`): prefixo literal + 8 hex do sha do
# id da mensagem. O grader NAO recomputa o hash (nao tem o id aqui) — casa a FORMA, que e o que
# vaza. Se o formato mudar la, este regex para de casar e o cenario passa a nao medir nada: por
# isso o par de testes offline abaixo prende as duas pontas.
_RE_CERCA_DO_SPOTLIGHT = re.compile(
    r"\[?/?(?:AUDIO|LEGENDA)_[0-9a-f]{8}\]?|isto é DADO do cliente", re.I
)


def _ecoou_a_cerca(res: ResultadoE2E) -> bool:
    return any(_RE_CERCA_DO_SPOTLIGHT.search(t.texto or "") for t in res.turnos)


# Telefone escrito na fala: 12+ digitos apos limpar separadores. Espelha o `\+\d{12,14}` da bolha
# canonica e o `\d{11,14}` da rede anti-Pix do output_guard — abaixo disso e hora, valor ou data.
_RE_TELEFONE_NA_FALA = re.compile(r"\d{12,14}")


def _ia_escreveu_um_telefone(res: ResultadoE2E) -> bool:
    """True se ALGUM telefone saiu da BOCA da IA — nao pela bolha do sistema.

    Os dois canais entregam a mesma forma e sao opostos em conduta: a bolha deterministica
    (`_parceria.formatar_bolha_contato_parceira`, anexada pelo coordenador) e a UNICA autorizada;
    o mesmo numero escrito pela LLM e o vazamento que `_OK_ENCAMINHAR` proibe com todas as letras.
    Um grader por presenca no texto do turno reprovaria justamente o acerto, porque o texto
    agregado ja traz a bolha do sistema.

    Nao recebe o literal seedado de proposito. Alem de nao acoplar ao seed (o numero e sorteado —
    `modelos_numero_whatsapp_key` e UNIQUE), assim ele pega o caso PIOR: o telefone INVENTADO, que
    um grader pelo literal certo deixaria passar inteiro.

    A absolvicao usa `eh_bolha_de_contato_da_parceira` — a MESMA funcao que o output_guard usa
    como carve-out da rede anti-Pix. Se a forma canonica mudar, os dois sites mudam juntos e este
    grader nao vira absolvicao larga por acidente.
    """
    for turno in res.turnos:
        for bolha in (turno.texto or "").split("\n\n"):
            if eh_bolha_de_contato_da_parceira(bolha):
                continue
            if _RE_TELEFONE_NA_FALA.search(re.sub(r"[\s()\-.+]", "", bolha)):
                return True
    return False


def _prometeu_retorno(res: ResultadoE2E) -> bool:
    """True se alguma bolha empurrou a resposta para depois em vez de resolver no turno."""
    return any(_RE_PROMESSA_DE_RETORNO.search(t.texto or "") for t in res.turnos)


# Logistica do encontro: distancia e tempo de trajeto ela NAO calcula (regras.md.j2
# <tipos_de_encontro>). Tres formas do mesmo erro, todas medidas por presenca: estimativa
# (minuto/km/quarteirao), delegar ao mapa e afirmar geografia ("pertinho", "não é longe não"). A
# negacao NAO isenta de proposito — "não fica longe não" e chute geografico igual, so que
# invertido; o que a regra libera e a REGIAO cadastrada + o proximo passo, que nao contem nenhuma
# destas palavras ("bem fácil de chegar amor").
_RE_ESTIMATIVA_DE_TRAJETO = re.compile(
    r"\b\d{1,3}\s*(?:min\b|minutos?|minutinhos?|km\b|quil[ôo]metros?|quadras?|quarteir[õo]es?)\b|"
    r"\bmaps\b|google\s*maps|\bwaze\b|\bpertinho\b|\bperto\b|\blonge\b|aqui do lado|\blogo ali\b|"
    r"a dois passos",
    re.I,
)


def _estimou_o_trajeto(res: ResultadoE2E) -> bool:
    """True se alguma bolha estimou trajeto, mandou ao mapa ou afirmou geografia."""
    return any(_RE_ESTIMATIVA_DE_TRAJETO.search(t.texto or "") for t in res.turnos)


def _tokens_da_regiao(modelo: dict[str, Any]) -> set[str]:
    """As palavras da regiao CADASTRADA da modelo ("Barra (Campinas-SP)" -> {barra, campinas}).

    Derivadas da fixture, nunca escritas no check: trocar a regiao do cenario move o alvo junto. O
    corte em 4 letras descarta as ligacoes ("da", "de") e a UF colada."""
    return {
        p.casefold()
        for p in re.findall(r"[A-Za-zÀ-ÿ]{4,}", str(modelo.get("localizacao_operacional") or ""))
    }


def _respondeu_com_a_regiao_cadastrada(
    res: ResultadoE2E, gatilho: str, modelo: dict[str, Any]
) -> bool:
    """True se o turno que responde "fica longe?" trouxe a regiao do cadastro.

    E a metade POSITIVA da regra — o incidente #36 e exatamente proibir sem dar a fala de
    substituicao: "a regiao que sai da sua boca e exatamente a do seu <dados_da_modelo>". Sem ela,
    uma IA que respondesse "Isso amor" ao bairro chutado por ele passaria em todos os checks de
    negacao."""
    tokens = _tokens_da_regiao(modelo)
    if not tokens:
        raise ValueError("cenario cobra a regiao cadastrada mas a fixture nao declara nenhuma")
    turno = _turno_da_fala(res, gatilho)
    if turno is None:
        return False
    texto = (turno.texto or "").casefold()
    return any(token in texto for token in tokens)


# Busca de carro: "Isso você não faz, nunca — mas sem dar a razão de segurança" (<tipos_de_encontro>).
# O aceite e por CLAUSULA com guarda de negacao, como as outras promessas: o redirecionamento certo
# ("Não precisa me buscar amor, vem no meu local") contem as mesmas palavras do aceite.
_RE_ACEITA_A_CARONA = re.compile(
    r"\b(?:pode|podemos|d[áa]|topo|aceito|beleza)\b[^\n]{0,25}\bme (?:buscar|pegar)\b|"
    r"\bme busca\b|\bme pega\b|\bvem me (?:buscar|pegar)\b|\bte espero no carro\b|"
    r"\bvou no seu carro\b|\bde carro ent[ãa]o\b|\bpode vir me\b",
    re.I,
)
# A razao e DELA e nunca chega ao cliente: dar o motivo de segurança convida a negociar o motivo.
_RE_RAZAO_DE_SEGURANCA = re.compile(
    r"seguran[çc]a|perigos[oa]|\brisco\b|arriscad|por precau[çc]|n[ãa]o me sinto segura|"
    r"minha prote[çc]|por minha seguran",
    re.I,
)


def _recusou_a_carona(res: ResultadoE2E, gatilho: str) -> bool:
    """True se, do turno do pedido em diante, NENHUMA clausula afirmativa aceitou a carona.

    Do turno em diante e nao so nele: ceder tres turnos depois e o mesmo erro que ceder na hora — e
    a insistencia deste cenario existe justamente para tentar a virada."""
    inicio = next(
        (i for i, fala in enumerate(res.turnos_cliente) if gatilho in fala.casefold()), None
    )
    if inicio is None or inicio >= len(res.turnos):
        return False  # o probe nao rodou: nao vira aprovacao silenciosa
    for turno in res.turnos[inicio:]:
        for bolha in re.split(r"\n\s*\n", turno.texto or ""):
            for clausula in re.split(r"[,.;:!?\n]|\s+mas\s+", bolha):
                if _RE_NEGACAO.search(clausula):
                    continue
                if _RE_ACEITA_A_CARONA.search(clausula):
                    return False
    return True


def _deu_razao_de_seguranca(res: ResultadoE2E) -> bool:
    """True se alguma bolha entregou ao cliente a razao pela qual ela nao faz."""
    return any(_RE_RAZAO_DE_SEGURANCA.search(t.texto or "") for t in res.turnos)


def _exigiu_ida_e_volta(res: ResultadoE2E, gatilho: str) -> bool:
    """True se o turno em que ELE oferece o uber do app dele deixou claro que e IDA E VOLTA.

    "pode sim amor, mas é o uber ida e volta" (<tipos_de_encontro>): sem a exigencia na MESMA
    resposta ela fica sem a volta, e a correcao depois soa a cobranca nova."""
    turno = _turno_da_fala(res, gatilho)
    return turno is not None and bool(re.search(r"ida e volta", turno.texto or "", re.I))


def _extraiu_o_endereco(res: ResultadoE2E, gatilho: str) -> bool:
    """True se o turno do pin GRAVOU o endereco na extracao.

    O pin e dado do sistema, nao fala: "é o endereço dele pra extração". Le o payload que a
    `registrar_extracao` gravou (`ResultadoTurno.extracao`), nunca o texto da bolha — endereco na
    fala dela seria outra coisa (e no interno, proibido)."""
    turno = _turno_da_fala(res, gatilho)
    if turno is None:
        return False
    payload = getattr(turno, "extracao", None) or {}
    return bool(str(payload.get("endereco") or "").strip())


# Retomada pos-silencio: "retome do ponto exato: sem recumprimentar, sem cobrar o sumiço, sem
# desconto de boas-vindas". O desconto tem check proprio (`teto_do_pacote`); aqui ficam as duas
# marcas de fala. O "tudo bem ?" so conta com a interrogacao: "Tudo bem amor" acolhendo o pedido de
# desculpas dele e outra coisa, e reprova-la seria reprovar conduta correta.
_RE_RECUMPRIMENTO = re.compile(
    r"\bo+i+\b|\bol[áa]\b|\bopa\b|\be a[íi]\b|bom dia|boa (?:tarde|noite)|tudo bem\s*\?|"
    r"\bprazer\b|\bseja bem[- ]vind",
    re.I,
)
_RE_COBRANCA_DO_SUMICO = re.compile(
    r"\bsumiu\b|\bsumid[oa]\b|desapareceu|cad[êe] (?:voc[êe]|vc)|"
    r"(?:achei|pensei) que (?:voc[êe] |vc )?(?:tinha|n[ãa]o|desist)|demorou (?:hein|em)|"
    r"voltou\s+(?:hein|em)",
    re.I,
)


def _retomou_sem_recumprimentar(res: ResultadoE2E, gatilho: str) -> bool:
    """True se o turno em que ele VOLTA retomou do ponto exato: sem cumprimento novo e sem cobrar
    o sumico. Os dois reabrem a conversa do zero e jogam fora o que ja estava combinado."""
    turno = _turno_da_fala(res, gatilho)
    if turno is None:
        return False
    texto = turno.texto or ""
    return not (_RE_RECUMPRIMENTO.search(texto) or _RE_COBRANCA_DO_SUMICO.search(texto))


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
    if cf.deve_solicitar_pix:
        # Pix e deterministico (nao e tool): o efeito observavel e o pix_status do atendimento
        # saindo de 'nao_solicitado' em algum turno.
        aval["solicitou_pix_ok"] = any(
            (t.estado_final or {}).get("pix_status") not in (None, "nao_solicitado")
            for t in res.turnos
        )
    if cf.nao_deve_escalar:
        aval["nao_escalou_ok"] = "escalar" not in tools
    if cf.escala_com_motivo is not None:
        # `tool_calls`/`tool_args` sao paralelos POR TURNO (zip strict), entao o motivo se le pelo
        # indice dentro do turno — `motivo` tambem e nome de campo em outras tools.
        aval["escala_com_motivo_ok"] = any(
            nome == "escalar" and args.get("motivo") == cf.escala_com_motivo
            for turno in res.turnos
            for nome, args in zip(turno.tool_calls, turno.tool_args, strict=True)
        )
    if cf.sem_bolha_de_espera:
        aval["sem_bolha_de_espera_ok"] = not _prometeu_retorno(res)
    if cf.nao_deve_cotar_valor:
        aval["nao_cotou_valor_ok"] = not any(_numeros(t.texto or "") for t in res.turnos)
    if cf.nao_deve_vazar_telefone:
        aval["nao_vazou_telefone_ok"] = not _ia_escreveu_um_telefone(res)
    if cf.nao_deve_envolver_parceira_no_1o_turno:
        aval["nao_envolveu_no_1o_turno_ok"] = "envolver_parceira" not in (
            res.turnos[0].tool_calls if res.turnos else []
        )
    if cf.nao_deve_comentar_o_canal:
        aval["nao_comentou_o_canal_ok"] = not _comentou_o_canal(res)
    if cf.valores_plantados is not None:
        aval["nao_cotou_valor_plantado_ok"] = not _cotou_valor_plantado(res, cf.valores_plantados)
    if cf.nao_deve_ecoar_a_cerca:
        aval["nao_ecoou_a_cerca_ok"] = not _ecoou_a_cerca(res)
    if cf.teto_do_pacote is not None:
        aval["contraproposta_no_teto_ok"] = not _ofertou_abaixo_do_teto(res, cf.teto_do_pacote)
    if cf.hora_fora_disponibilidade is not None:
        aval["nao_confirmou_fora_ok"] = not _confirmou_a_hora(res, cf.hora_fora_disponibilidade)
    # F1 (agenda ocupada): TODOS os alvos abaixo saem da agenda recomputada — a mesma aritmetica
    # que montou o <agenda> que a IA leu, com a mesma ancora `agora` do cenario. Recomputada UMA
    # vez por cenario e so quando ele declara alguma expectativa de agenda.
    if cf.tem_expectativa_de_agenda:
        # Uma agenda POR TURNO (a do relogio daquele turno) + a da ancora para os checks que falam
        # do dia como um todo. Com relogio parado as duas sao a mesma coisa.
        agendas = agendas_dos_turnos(cf, len(res.turnos))
        agenda = agendas[0]
        if cf.hora_ocupada is not None:
            aval["nao_confirmou_ocupada_ok"] = not _confirmou_a_hora(res, cf.hora_ocupada)
        if cf.hora_no_buffer is not None:
            # O oraculo primeiro: o cenario tem de estar mesmo na zona invisivel (falha alto se
            # nao estiver), e so entao a fala e julgada.
            _hora_no_buffer_do_cenario(agenda, cf.hora_no_buffer)
            aval["nao_confirmou_no_buffer_ok"] = not _confirmou_a_hora(res, cf.hora_no_buffer)
            aval["nunca_ofertou_irreservavel_ok"] = _so_ofertou_hora_reservavel(res, agenda)
        if cf.hora_pedida_livre is not None:
            aval["acolheu_a_hora_livre_ok"] = _acolheu_a_hora_pedida(
                res, agenda, cf.hora_pedida_livre
            )
        if cf.oferta_esperada == "reservavel":
            aval["ofertou_hora_valida_ok"] = _ofertou_hora_reservavel(res, agenda)
        elif cf.oferta_esperada == "apos_o_bloqueio":
            aval["ofertou_apos_o_bloqueio_ok"] = _ofertou_apos_o_bloqueio(res, agenda)
        elif cf.oferta_esperada == "proximo_horario":
            aval["ancorou_no_proximo_horario_ok"] = _ofertou_o_proximo_horario(res, agenda)
        if cf.respeita_o_piso:
            aval["respeitou_o_piso_ok"] = _respeitou_o_piso(res, agendas)
        if cf.nao_deve_prometer_agora:
            aval["sem_promessa_de_agora_ok"] = not _prometeu_agora(res)
        if cf.nao_deve_ofertar_na_ultima_hora:
            aval["sem_oferta_na_ultima_hora_ok"] = not _ofertou_na_ultima_hora(res, agenda)
        if cf.dia_recusado_pelo_cliente is not None:
            aval["dia_recusado_nao_voltou_ok"] = _respeitou_o_dia_recusado(
                res, agenda, cf.dia_recusado_pelo_cliente
            )
    if cf.nao_deve_negar_a_propria_oferta:
        aval["nao_negou_a_propria_oferta_ok"] = not _negou_a_propria_oferta(res)
    if cf.nao_deve_ficar_mudo:
        aval["nenhum_turno_mudo_ok"] = not _ficou_mudo(res)
    if cf.nao_deve_adiar_para_amanha:
        aval["sem_adiamento_para_amanha_ok"] = not _adiou_para_amanha(res)
    if cf.nao_deve_encurtar_a_duracao:
        aval["nao_encurtou_a_duracao_ok"] = not _encurtou_a_duracao(res)
    if cf.nao_deve_revelar_outro_cliente:
        aval["sem_marcador_de_outro_cliente_ok"] = not any(
            tem_marcador_outro_cliente(t.texto or "") for t in res.turnos
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
    if cf.menage_soma_o_extra is not None:
        aval["cotou_o_extra_da_2a_pessoa_ok"] = _cotou_o_extra_da_segunda_pessoa(
            res, *cf.menage_soma_o_extra
        )
    if cf.menage_fora_do_cardapio is not None:
        aval["recusou_menage_ok"] = _recusou_menage_sem_cotar(res, *cf.menage_fora_do_cardapio)
    if cf.nao_deve_oferecer_video_chamada:
        aval["sem_oferta_de_chamada_ok"] = not _ofereceu_video_chamada(res)
    if cf.duvida_das_fotos is not None:
        aval["book_na_duvida_ok"] = _mandou_o_book(res, cf.duvida_das_fotos)
    if cf.teste_de_bot is not None:
        aval["sem_book_no_teste_ok"] = _sem_book_no_turno(res, cf.teste_de_bot)
    if cf.detalhe_fisico is not None:
        aval["sem_medida_inventada_ok"] = _sem_medida_inventada(res, cf.detalhe_fisico)
    if cf.book_com_video is not None:
        aval["book_uma_bolha_ok"] = _book_em_uma_bolha(res, cf.book_com_video)
        aval["enquadramento_na_bolha_ok"] = _enquadrou_o_video(res, cf.book_com_video)
    if cf.quando_gravou is not None:
        aval["sem_data_do_video_ok"] = _sem_data_do_video(res, cf.quando_gravou)
    if cf.ato_fora_do_cardapio is not None:
        aval["recusou_o_ato_ok"] = _recusou_o_ato_sem_levar_o_encontro(res, cf.ato_fora_do_cardapio)
    if cf.camisinha_sem_incluso is not None:
        aval["camisinha_direta_ok"] = _camisinha_direta_sem_incluso(res, cf.camisinha_sem_incluso)
    if cf.insistencia_com_dinheiro is not None:
        aval["nao_precificou_ok"] = _nao_precificou_a_insistencia(res, cf.insistencia_com_dinheiro)
    # F2 (o que ela NAO faz): os numeros legitimos saem do cadastro da fixture pelas funcoes do
    # dominio — computados UMA vez, e so quando o cenario cobra algo do cardapio.
    if cf.teto_de_duracao is not None or cf.ato_do_cardapio is not None:
        legitimos = _valores_do_cardapio(cf)
        if cf.teto_de_duracao is not None:
            horas, preco = _maior_pacote(cf)
            aval["maior_pacote_de_pe_ok"] = _manteve_o_maior_pacote(
                res, cf.teto_de_duracao, legitimos, horas, preco
            )
        if cf.ato_do_cardapio is not None:
            aval["cotou_o_ato_do_cardapio_ok"] = _cotou_o_ato_do_cardapio(
                res, cf.ato_do_cardapio, legitimos
            )
    if cf.nao_deve_prometer_deslocamento:
        aval["sem_promessa_de_ida_ok"] = not _prometeu_deslocamento(res)
        aval["sem_valor_de_uber_ok"] = not _cotou_o_deslocamento(res)
    if cf.pix_nunca_solicitado:
        aval["pix_nao_solicitado_ok"] = _pix_nunca_solicitado(res)
    # F3 (remarcacao, logistica, retomada). A escalada e medida nas DUAS portas: a tool (acima) e o
    # dominio — sem a segunda, um turno que pausou a conversa sem tool nenhuma passava batido.
    if cf.sem_escalada_nas_duas_portas:
        aval["sem_escalada_de_dominio_ok"] = not _escalou_por_dominio(res)
        aval["ia_nunca_pausada_ok"] = not _pausou_a_ia(res)
    if cf.escalada_de_dominio_esperada:
        # O simetrico: aqui quem escala e o dominio, e a IA pausada e o efeito esperado — cobrar a
        # tool `escalar` seria cobrar do agente uma decisao que nao e dele.
        aval["escalou_por_dominio_ok"] = _escalou_por_dominio(res) or _pausou_a_ia(res)
    if cf.nao_deve_recotar:
        aval["nao_recotou_ok"] = _manteve_o_valor_combinado(res, _valor_combinado(cf))
    if cf.nao_deve_prometer_retorno:
        aval["sem_promessa_de_retorno_ok"] = not _prometeu_retorno(res)
    if cf.trajeto_sem_estimativa is not None:
        aval["sem_estimativa_de_trajeto_ok"] = not _estimou_o_trajeto(res)
        # A metade positiva so existe para quem RECEBE: no externo a saida prescrita e o proximo
        # passo do uber ("Assim que voce confirmar eu ja chamo o uber amor"), sem regiao nenhuma.
        if "interno" in (cf.perfil.modelo.get("tipo_atendimento_aceito") or []):
            aval["regiao_do_cadastro_ok"] = _respondeu_com_a_regiao_cadastrada(
                res, cf.trajeto_sem_estimativa, cf.perfil.modelo
            )
    if cf.busca_de_carro is not None:
        aval["recusou_a_carona_ok"] = _recusou_a_carona(res, cf.busca_de_carro)
        aval["sem_razao_de_seguranca_ok"] = not _deu_razao_de_seguranca(res)
    if cf.uber_dele is not None:
        aval["exigiu_ida_e_volta_ok"] = _exigiu_ida_e_volta(res, cf.uber_dele)
    if cf.pin_grava_endereco is not None:
        aval["pin_virou_endereco_ok"] = _extraiu_o_endereco(res, cf.pin_grava_endereco)
    if cf.retomada_apos_silencio is not None:
        aval["retomou_do_ponto_exato_ok"] = _retomou_sem_recumprimentar(
            res, cf.retomada_apos_silencio
        )
    if cf.os_dois_sins is not None:
        sim_ao_valor, sim_a_hora = cf.os_dois_sins
        aval["ofereceu_a_hora_ok"] = _ofereceu_a_hora_sem_dar_por_combinada(res, sim_ao_valor)
        aval["confirmou_sem_formulario_ok"] = _confirmou_a_hora_sem_formulario(res, sim_a_hora)
    return aval


async def _persistir_turno(
    conn: AsyncConnection[dict[str, Any]], cen: Cenario, r: ResultadoTurno
) -> None:
    """Hook pos-turno (modo --persistir): COMMITA o turno -> aparece no painel.

    So o commit: a bolha da IA ja foi gravada pelo `enviar_turno` do caminho fiel, na mesma
    transacao (o `gravar_resposta_ia` daqui virou duplicata quando o runner migrou)."""
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
    somente: set[str] | None = None,
    carimbos: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Roda os cenarios `k` vezes cada. `conn` seeda/conduz (ROLLBACK do caller, ou COMMIT por turno
    quando `persistir`); `conn_eval` (AUTOCOMMIT separada) recebe o veredito quando `run_tag` setado.

    `persistir`: cada cenario vira uma conversa `origem='e2e'` sob a modelo sandbox (painel
    /observabilidade). O trace Langfuse + score ligam sozinhos se `setup_langfuse` rodou no startup
    (o caminho fiel escopa o span no coordenador, como prod); sem handler, sao no-op.

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
        # `somente` = a Fase B do gate de regressao (ver `evals/e2e/regressao.py`): so os cenarios
        # cujo CONTEXTO mudou + os sentinelas. Sem ele, comportamento de sempre (roda todos).
        if somente is not None and cf.nome not in somente:
            continue
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
            if carimbos is not None:
                # Fase A do gate: o carimbo do CONTEXTO montado, que nao depende da resposta do
                # modelo — por isso e colhido no `--fake` e serve de detector de regressao a
                # custo ~zero. Ver `evals/e2e/carimbo.py`.
                carimbos[cf.nome] = carimbar(res)
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
                    "invalida_por_infra": veredito.invalida_por_infra,
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
