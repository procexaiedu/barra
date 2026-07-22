"""Harness FIEL: roda o agente pelo MESMO ponto de entrada de producao.

`evals/harness.py::rodar_turno` chama `graph.ainvoke` direto e pula tudo que envolve o turno na
prod: o lock por conversa, o gate de pendencia, o drain/coalescing, o tratamento de refusal/
truncation e o `enviar_turno` (humanizacao, output-guard final e a GRAVACAO da resposta da IA no
banco — sem ela o multi-turno vira amnesia, ver memoria replay_agente_amnesia). Resultado: o teste
respondia diferente do WhatsApp.

Este harness exercita o caminho do WhatsApp ponta a ponta:

    set pending  ->  coordenador.processar_turno  (lock real, drain, gates, graph.ainvoke, despacho)
                 ->  envio.enviar_turno            (output-guard final, grava a resposta IA, "envia")

Fidelidade:
  - DB real (TEST_DATABASE_URL), pool de UMA conexao — ROLLBACK e responsabilidade do caller.
  - Redis real-em-memoria via `fakeredis`: SET NX/TTL, scripts Lua (release do lock) e sets sao os
    do servidor Redis, nao um fake caseiro — o coalescing/lock/dedupe rodam de verdade.
  - graph real (`build_graph`) e settings reais (`get_settings`) — MESMO codigo do worker.
  - Relogio do turno injetavel via `agora` (clock injection -> ContextAgente.agora_utc): agenda e
    bordas (meia-noite, antecedencia) ficam deterministicas.

Unicos desvios deliberados (nao da pra "ser igual" sem eles): o Evolution e capturado por um spy
(nao manda WhatsApp) e os `asyncio.sleep` da humanizacao sao neutralizados (o teste valida conteudo
e mecanica, nao a cadencia de digitacao). Custo: roda o graph real -> bate no LLM (DeepSeek) e cai
no gate de credito (§0); para testar so a mecanica, injete um `graph` fake.

Flags & temperatura: o harness le `get_settings()` real (mesmo objeto que o worker), entao NAO
falsifica as flags que moldam a conduta — ele as herda. A `chat_temperature=1.3` (recomendacao
DeepSeek) e MANTIDA de proposito: a fidelidade e por veredito de judge, nao por igualdade textual;
forcar temp=0 ja seria divergir de prod. As flags efetivas do run saem em `ResultadoFiel.flags`
(via `flags_relevantes`) para que uma divergencia .env x prod fique VISIVEL — risco real: o `.env`
local pode ter, p.ex., `REENGAJAMENTO_ATIVO=false` enquanto o default/prod e True.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from fakeredis.aioredis import FakeRedis
from psycopg import AsyncConnection

from barra.agente.graph import build_graph
from barra.settings import get_settings
from barra.webhook.debounce import chave_pending
from barra.workers.coordenador import processar_turno
from barra.workers.envio import enviar_turno
from evals.harness import Cenario, PoolDeUmaConexao, _inserir_mensagem, estado_pos_turno


class EvolutionSpy:
    """Captura o que sairia no WhatsApp em vez de enviar. `enviar_texto`/`enviar_midia` devolvem um
    `evolution_message_id` sintetico — o `enviar_turno` o usa no INSERT da resposta da IA."""

    def __init__(self) -> None:
        self.textos: list[str] = []
        self.midias: list[dict[str, Any]] = []
        self.lidas: list[list[str]] = []
        self.presencas: list[str] = []

    def _mid(self) -> str:
        # UNICO entre instancias: rodar_turno_fiel cria um spy POR TURNO, e um contador que
        # reinicia ("spy-mid-1" de novo) colidia no ON CONFLICT (evolution_message_id) DO NOTHING
        # do enviar_turno — as primeiras bolhas de cada turno seguinte sumiam da janela e o agente
        # rodava com amnesia parcial das proprias falas (achado do replay prod dia-1, 22/07).
        return f"spy-mid-{uuid4().hex}"

    async def marcar_lida(self, **kwargs: Any) -> None:
        self.lidas.append(kwargs.get("message_ids") or [])

    async def set_presence(self, **kwargs: Any) -> None:
        self.presencas.append(str(kwargs.get("presence", "")))

    async def enviar_texto(self, **kwargs: Any) -> str:
        self.textos.append(str(kwargs.get("texto", "")))
        return self._mid()

    async def enviar_midia(self, **kwargs: Any) -> str:
        self.midias.append(dict(kwargs))
        return self._mid()


class FakeArqRedis(FakeRedis):  # type: ignore[misc]
    """fakeredis (lock/pending/sets/get fieis ao ARQ) + `enqueue_job` com dedupe NX por `_job_id`,
    capturando os jobs em `jobs` para o harness drenar (roda `enviar_turno` inline, como o worker)."""

    def __init__(self, *a: Any, **k: Any) -> None:
        super().__init__(*a, **k)
        self.jobs: list[tuple[str, dict[str, Any]]] = []
        self._job_ids: set[str] = set()

    async def enqueue_job(self, name: str, *_a: Any, **kwargs: Any) -> Any:
        job_id = kwargs.get("_job_id")
        if job_id is not None and job_id in self._job_ids:
            return None  # coalesced/rodando — indistinguivel p/ o caller (igual ao ARQ)
        if job_id is not None:
            self._job_ids.add(job_id)
        self.jobs.append((name, kwargs))
        return object()


class _MinioStub:
    """So tocado quando o turno envia midia de saida; devolve uma URL sintetica."""

    def presigned_get_object(self, *_a: Any, **_k: Any) -> str:
        return "https://example.invalid/midia-stub"


def _montar_ctx(
    conn: AsyncConnection[dict[str, Any]],
    *,
    graph: Any,
    evolution: EvolutionSpy,
    redis: FakeArqRedis,
    agora: datetime | None,
) -> dict[str, Any]:
    """Monta o `ctx` do ARQ que `processar_turno`/`enviar_turno` esperam (workers/settings.py)."""
    return {
        "redis": redis,
        "db_pool": PoolDeUmaConexao(conn),
        "graph": graph,
        "settings": get_settings(),
        "evolution": evolution,
        "minio": _MinioStub(),
        "job_id": f"turno:{uuid4()}",
        "score": 1,
        "agora_override": agora,
    }


@dataclass
class BolhaCliente:
    """Uma bolha de entrada do cliente. Texto puro: `BolhaCliente("oi")` (ou so a str). Midia
    carrega o `conteudo` que o agente VE — caption da imagem / transcricao do audio, ja resolvidos
    pelo caption/STT antes do turno em prod — e a `media_object_key`. `conteudo=""` numa imagem ->
    o agente ve o placeholder `[imagem]` (cego no P0); num audio -> `[áudio que não consegui ouvir]`.

    FRONTEIRA (handoff Fase 4): isto cobre midia que em prod entra na JANELA e o LLM le via
    `traduzir_mensagens` (imagem com caption em Triagem/Qualificado, audio transcrito). NAO cobre o
    Pix nem a Foto de portaria: essas imagens sao roteadas por `workers/media.py::rotear_imagem`
    ANTES/A PARTE do turno de texto (em Aguardando_confirmacao interno qualquer imagem vira Foto de
    portaria, sem vision) — inserir uma imagem e chamar `processar_turno` NAO reproduz esse desvio.
    Cobrir o roteamento de imagem e follow-up."""

    conteudo: str
    tipo: str = "texto"
    media_object_key: str | None = None


def flags_relevantes(settings: Any) -> dict[str, Any]:
    """As settings que moldam a conduta/encanamento do turno e que, se divergirem entre o `.env`
    local e prod, fazem o harness mentir. Expostas no `ResultadoFiel` para a divergencia ser
    detectavel; em prod os defaults sao 1.3 / True / True / False (ver `barra.settings`)."""
    return {
        "chat_temperature": settings.chat_temperature,
        "extracao_no_modelo_barato": settings.extracao_no_modelo_barato,
        "reengajamento_ativo": settings.reengajamento_ativo,
        "experimento_braco_ativo": settings.experimento_braco_ativo,
    }


@dataclass
class ResultadoFiel:
    """O que saiu do turno pelo caminho real: as bolhas enviadas ao cliente + o estado pos-turno."""

    textos: list[str]
    midias: list[dict[str, Any]]
    estado: str | None
    pix_status: str | None
    ia_pausada: bool
    presencas: list[str]
    n_jobs_envio: int
    flags: dict[str, Any]

    @property
    def resposta(self) -> str:
        """As bolhas concatenadas — conveniencia p/ asserts de conteudo."""
        return "\n".join(self.textos)


async def _noop(*_a: Any, **_k: Any) -> None:
    return None


async def rodar_turno_fiel(
    conn: AsyncConnection[dict[str, Any]],
    cen: Cenario,
    turno_cliente: str | BolhaCliente | list[str | BolhaCliente],
    *,
    graph: Any | None = None,
    agora: datetime | None = None,
    aguardar_transcricao: bool = False,
) -> ResultadoFiel:
    """Insere a(s) mensagem(ns) do cliente, dispara `processar_turno` e drena o `enviar_turno`.

    `turno_cliente` str/`BolhaCliente` = uma bolha; list = varias bolhas na MESMA janela (coalescing
    real do debounce: o webhook grava cada bolha e marca o pending, e UM turno le a janela inteira).
    Uma str vira texto puro; `BolhaCliente` carrega midia (imagem com caption / audio transcrito,
    ver a sua fronteira). `graph` reusavel entre turnos (passe `build_graph()` uma vez); None ->
    constroi um. Com o graph real, bate no LLM (custa credito, §0); injete um fake p/ testar so a
    mecanica. `agora` fixa o relogio do turno (clock injection). `conn` e a MESMA do seed (transacao;
    ROLLBACK no caller).
    """
    entrada = [turno_cliente] if isinstance(turno_cliente, str | BolhaCliente) else turno_cliente
    bolhas = [BolhaCliente(b) if isinstance(b, str) else b for b in entrada]
    msg_id = ""
    for bolha in bolhas:
        msg_id = f"test-evo-{uuid4().hex}"
        await _inserir_mensagem(
            conn,
            conversa_id=cen.conversa_id,
            direcao="cliente",
            texto=bolha.conteudo,
            tipo=bolha.tipo,
            media_object_key=bolha.media_object_key,
        )

    redis = FakeArqRedis()
    # O webhook marca a pendencia (ultima msg) antes de enfileirar o turno (webhook/despacho.py):
    # varias bolhas coalescem numa janela so -> um pending -> um turno le todas. Reproduz isso.
    await redis.set(chave_pending(str(cen.conversa_id)), msg_id, ex=120)
    evolution = EvolutionSpy()
    ctx = _montar_ctx(
        conn, graph=graph or build_graph(), evolution=evolution, redis=redis, agora=agora
    )

    # Neutraliza os delays de humanizacao do `enviar_turno` (o teste valida conteudo/mecanica, nao a
    # cadencia). O heartbeat do lock usa `asyncio.wait_for`, nao `sleep` — segue funcionando.
    n_envio = 0
    with patch("asyncio.sleep", _noop):
        await processar_turno(
            ctx,
            conversa_id=str(cen.conversa_id),
            aguardar_transcricao=aguardar_transcricao,
        )
        # Drena os jobs `enviar_turno` enfileirados (o worker rodando o job de entrega).
        for name, kwargs in list(redis.jobs):
            if name != "enviar_turno":
                continue
            n_envio += 1
            # Kwargs de infra do ARQ (_job_id, _defer_by...) nao sao parametros do enviar_turno.
            payload = {k: v for k, v in kwargs.items() if not k.startswith("_")}
            await enviar_turno(ctx, **payload)

    estado = await estado_pos_turno(conn, cen.atendimento_id)
    return ResultadoFiel(
        textos=evolution.textos,
        midias=evolution.midias,
        estado=estado.get("estado"),
        pix_status=estado.get("pix_status"),
        ia_pausada=bool(estado.get("ia_pausada")),
        presencas=evolution.presencas,
        n_jobs_envio=n_envio,
        flags=flags_relevantes(ctx["settings"]),
    )
