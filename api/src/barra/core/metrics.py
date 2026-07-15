"""Metricas Prometheus minimas."""

from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram
    from prometheus_client import generate_latest as _prometheus_generate_latest
except ModuleNotFoundError:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"

    class _Metric:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def labels(self, *_: object) -> "_Metric":
            return self

        def inc(self, *_: object) -> None:
            return None

        def observe(self, *_: object) -> None:
            return None

        def set(self, *_: object) -> None:
            return None

    Counter = Gauge = Histogram = _Metric  # type: ignore[misc,assignment]

    def _generate_latest() -> bytes:
        return b""
else:

    def _generate_latest() -> bytes:
        return _prometheus_generate_latest()


# Observabilidade da observabilidade (piloto de producao assistida): 1 = handler Langfuse ligado,
# 0 = tracing off (chave ausente/auth falhou — provavel Env do stack zerado por redeploy git).
# Alertavel no dashboard; o grito duro no boot e o `langfuse_obrigatorio` (settings).
TRACING_LANGFUSE_LIGADO = Gauge(
    "barra_tracing_langfuse_ligado",
    "Tracing Langfuse ativo neste processo (1=handler ligado, 0=off)",
)

HTTP_REQUESTS = Counter(
    "barra_http_requests_total", "Total de requests", ["route", "method", "status"]
)
HTTP_DURATION = Histogram(
    "barra_http_request_duration_seconds", "Duracao por rota", ["route", "method"]
)
JOBS = Counter("barra_jobs_total", "Jobs executados", ["tipo", "resultado"])
COMANDOS_GRUPO = Counter("barra_comandos_grupo_total", "Comandos do grupo", ["resultado"])
PIX = Counter("barra_pix_total", "Decisoes Pix", ["resultado"])
ENVIOS_EVOLUTION = Counter("barra_envios_evolution_total", "Envios Evolution", ["resultado"])
WEBHOOK_ERRORS = Counter("barra_webhook_errors_total", "Erros de webhook", ["tipo"])
TIMEOUTS = Counter("barra_timeouts_total", "Timeouts aplicados", ["tipo"])
LEMBRETE_VALOR = Counter(
    "barra_lembrete_valor_total",
    "Lembrete de fechamento (ADR-0009): cobranca do valor_final",
    ["acao"],  # enviado | reenviado | escalado | falha
)
REENGAJAMENTO = Counter(
    "barra_reengajamento_total",
    "Reengajamento proativo do cliente apos a cotacao (07 §4.5)",
    ["resultado"],  # enviado | flag_off | sem_alvo
)
FLUXO_DRIFT = Counter(
    "barra_fluxo_drift_total",
    "Sensor de deriva de fluxo conversacional (contabilidade da corrida; JSD vai pro Langfuse)",
    ["origem", "resultado"],  # resultado: ok | flag_off | sem_dado
)

# Metricas do agente LangGraph (ver docs/agente/08-evals.md)
AGENTE_TURNO_DURACAO = Histogram(
    "agente_turno_duracao_seconds",
    "Duracao por turno (p50/p95/p99); split por tipo_turno p/ nao misturar texto e audio-Whisper (E5)",
    ["modelo", "tipo_turno"],
)
AGENTE_TURNO_RESULTADO = Counter(
    "agente_turno_resultado_total",
    "Resultado do turno: ok|escalado|exaustao|ia_pausada_skip|lock_busy|transcricao_timeout",
    ["resultado"],
)
# E3 (grilling 2026-05-23): dashboard de tendencia, NAO gate de qualidade.
# bucket=defesa (ataque ativo, desejavel; spike -> alerta) | capacidade (cego a
# alucinacao-sem-escalada, por isso nao gateia o cutover). mapa motivo->bucket vive
# em codigo (deterministico) e o enum de motivo aceito por `escalar` e restrito.
AGENTE_ESCALADA = Counter(
    "agente_escalada_total",
    "Escaladas por bucket/motivo (ver docs/agente/08-evals.md 3.2)",
    ["bucket", "motivo"],
)
AGENTE_TOOL_ERRO_RECUPERAVEL = Counter(
    "agente_tool_erro_recuperavel_total",
    "Tools do agente que retornaram um 'ERRO:' recuperavel ao LLM (instrui a IA a reagir, "
    "nao falha de turno). tool=nome da ferramenta, motivo=categoria curta e estavel.",
    ["tool", "motivo"],
)
AGENTE_TURNO_TOKENS = Counter(
    "agente_turno_tokens_total",
    "Tokens por turno por tipo: input|output|cache_read|cache_write. Rotulado por "
    "modelo p/ hit/write-rate por serie e tripwire de invalidador silencioso (03 §4.2)",
    ["modelo", "tipo"],
)
# EVAL-11: observada ONLINE no worker (coordenador._amostrar_eval_online) -- amostra ~5% dos
# turnos 'ok' e grava 1.0/0.0 da rubrica DETERMINISTICA de non_disclosure (suite=online_non_disclosure).
# Sinal de TENDENCIA scraped por Prometheus; nao e gate (o runner offline foi removido). O nome
# `pass_rate` num Histogram = distribuicao de 0/1 amostrais; o rate vivo e a media movel no Grafana.
AGENTE_EVAL_PASS_RATE = Histogram(
    "agente_eval_pass_rate",
    "Rubrica binaria amostrada online por suite (EVAL-11): 1.0=passou, 0.0=falhou",
    ["suite"],
)
AGENTE_CUSTO_TURNO_BRL = Histogram(
    "agente_custo_turno_brl",
    "Custo estimado por turno em BRL (Sonnet 4.6 com cache; meta = settings.custo_alvo_brl)",
    ["modelo"],
)
# CUSTO-02: custo das outras chamadas de IA por atendimento, espelhando AGENTE_CUSTO_TURNO_BRL.
# Tarifas em agente/_custo.py (PENDENTES de confirmacao do operador). Label `modelo` = nome do
# modelo de vision do OpenRouter (nao o modelo_id da agencia), mesmo criterio do chat.
AGENTE_CUSTO_VISION_BRL = Histogram(
    "agente_custo_vision_brl",
    "Custo estimado por chamada de vision (Pix) em BRL (CUSTO-02; tarifa em _custo.py)",
    ["modelo"],
)
AGENTE_CUSTO_STT_BRL = Histogram(
    "agente_custo_stt_brl",
    "Custo estimado por transcricao STT (Whisper) em BRL (CUSTO-02; tarifa por-minuto em _custo.py)",
    ["modelo"],
)
TURNO_TRUNCADO = Counter(
    "agente_turno_truncado_total",
    "Turnos com stop_reason=max_tokens (08 §3; valida a premissa de max_tokens~1024 nao "
    "truncar). No P0 so observa, nao escala (09 §4.2 / 03 §6.3); spike = revisar teto / mid-tool_use",
)
PERSONA_DRIFT_REMINDER = Counter(
    "agente_persona_reminder_injetado_total",
    "Reminder anti-drift injetado no ultimo HumanMessage (>=8 turnos da IA; 03 §10). Regra "
    "proativa -> proxy de volume de conversas longas, nao de drift detectado",
)
LOCK_OCUPADO = Counter(
    "agente_lock_ocupado_total",
    "lock:conv estava ocupado quando processar_turno tentou adquirir (re-defer; 07 §3)",
)
ROTEAR_IMAGEM_DECISAO = Counter(
    "agente_rotear_imagem_decisao_total",
    "Decisao de roteamento de imagem sob lock:conv (06 §2.1): "
    "pix|foto_portaria|foto_portaria_ressurreicao|fora_fluxo_legenda|silencio|lock_busy",
    ["decisao"],
)
# 10 §9: deteccao heuristica de disclosure/jailbreak no intercept_disclosure (M3g).
DISCLOSURE_DETECTADO = Counter(
    "agente_disclosure_attempt_total",
    "Tentativas de disclosure detectadas",
    ["resultado"],  # negado | escalado | passou_silenciosamente
)
JAILBREAK_DETECTADO = Counter(
    "agente_jailbreak_attempt_total",
    "Tentativas de jailbreak detectadas",
)
# SEC-JB-02: reincidencia de seguranca por telefone (cliente) em janela de 24h. Conta tentativas
# de disclosure/jailbreak e escala a Fernando ao cruzar o limiar, SEM bloquear o cliente.
REINCIDENCIA_SEGURANCA = Counter(
    "agente_reincidencia_seguranca_total",
    "Eventos de reincidencia de disclosure/jailbreak por telefone (SEC-JB-02), por acao",
    ["acao"],  # contabilizada | escalada
)
# AGENTE-OG (ADR 0016): output-guard de saida antes da bolha. Etapa 1 = scan deterministico de
# vazamento (persona/system/auto-referencia de IA/dado de outra modelo); Etapa 2 = LLM-judge de
# AUP vinculante. Bloqueio -> handoff p/ Fernando (bucket=defesa) e a bolha nao e enviada.
OUTPUT_LEAK_DETECTADO = Counter(
    "agente_output_leak_total",
    "Vazamentos barrados pela Etapa 1 do output-guard (10 §; ADR 0016), por motivo",
    [
        "motivo"
    ],  # ia_self | system | outro_cliente | raciocinio (legenda; texto e saneado no Estagio 0)
)
AUP_SAIDA_BLOQUEADO = Counter(
    "agente_aup_saida_bloqueado_total",
    "Bolhas barradas pela Etapa 2 (LLM-judge de AUP) do output-guard, por resultado",
    ["resultado"],  # violou | judge_falhou (default seguro: bloqueia+escala)
)
# Estagio 0 do output-guard: vazamento de RACIOCINIO (meta-fala) saneado antes do envio. Acao =
# SANEAR (stripar a bolha de raciocinio, manter a fala real), nao barrar -> metrica propria, fora do
# leak-rate. `acao`: saneado (sobrou fala real) | mudo (turno 100%-leak, nada despachado).
OUTPUT_RACIOCINIO_SANEADO = Counter(
    "agente_output_raciocinio_saneado_total",
    "Turnos com vazamento de raciocinio saneado pelo Estagio 0 do output-guard, por acao",
    ["acao"],  # saneado | mudo
)
# Gate pre-envio com regeneracao one-shot (producao assistida): turno sujo (leak no texto /
# repeticao / 100%-raciocinio) re-gera a resposta 1x antes de cair no handoff/mudo.
OUTPUT_REGEN = Counter(
    "agente_output_regen_total",
    "Regeneracoes one-shot do output-guard, por gatilho e resultado",
    [
        "gatilho",
        "resultado",
    ],  # gatilho: leak|repeticao|mudo; resultado: limpou|persistiu|indisponivel
)
# Detector deterministico de repeticao (rastro de papagaio): bolha quase identica a uma bolha
# recente da propria IA. `acao`: dropada (bolha repetida removida, sobrou fala) | mudo (nada sobrou).
OUTPUT_REPETICAO_DETECTADA = Counter(
    "agente_output_repeticao_total",
    "Bolhas repetidas barradas pelo detector de repeticao do output-guard, por acao",
    ["acao"],  # dropada | mudo
)
# Marcador de reply [quote]/[quote: trecho] residual removido pela rede final antes do envio: o
# chunking deveria te-lo extraido no inicio da bolha, entao cada scrub aqui e regressao de
# prompt/chunking (marker malformado ou fora de posicao que denunciaria a IA se saisse ao cliente).
QUOTE_MARCADOR_VAZADO = Counter(
    "agente_quote_marcador_vazado_total",
    "Marcadores [quote] residuais removidos pela rede de saida (scrub anti-vazamento)",
)
# Judge assincrono POS-ENVIO (producao assistida, semana 1): 100% dos turnos enviados, telemetria.
# `resultado`: ok (julgou, sem rastro) | rastro (incidente NAO-CONTIDO) | indisponivel (judge
# falhou/recusou/parse) | pulado (ja julgado, dedupe) | nao_enviado (turno sem marcador de envio:
# barrado pela rede final, cancelado ou ainda em transito -- nao e julgado).
JUDGE_POS_ENVIO = Counter(
    "agente_judge_pos_envio_total",
    "Turnos julgados pelo judge pos-envio, por resultado",
    ["resultado"],  # ok | rastro | indisponivel | pulado | nao_enviado
)
# Gatilhos objetivos de rollback do piloto (workers/rollback_watch.py): 1 = disparado na ultima
# corrida do cron (janela 7d), 0 = ok. Gauge de proposito: reflete o estado corrente, nao acumula.
ROLLBACK_GATILHO = Gauge(
    "barra_rollback_gatilho",
    "Gatilho de rollback do piloto disparado na janela de 7d (1=disparado)",
    ["gatilho"],  # nao_contidos | acusacoes | taxa_gate
)
# Digest semanal pro Fernando (workers/digest_semanal.py), por resultado do envio.
DIGEST_SEMANAL = Counter(
    "barra_digest_semanal_total",
    "Cards de digest semanal enviados no grupo de Coordenacao, por resultado",
    ["resultado"],  # enviado | falha | pulado
)
# 05 §2: sentenca unica > 600 chars sai inteira no chunk; sinal de prompt que ignorou o
# \n\n instruido (regressao de prompt), NAO erro de envio.
CHUNK_OVERSIZE = Counter(
    "agente_chunk_oversize_total",
    "Chunks com sentenca unica acima de MAX_CHARS (05 §2)",
)
QUOTE_RESOLUCAO = Counter(
    "agente_quote_resolucao_total",
    # ok = trecho casou uma inbound; miss = trecho nao casou (caiu na ultima); ultima = `[quote]`
    # puro (uso normal, nao e erro). Taxa de falha do trecho = miss / (ok + miss), NAO miss / total.
    "Resolucao do alvo de quote (`[quote: trecho]`): ok|miss|ultima",
    ["resultado"],
)
# 05 §9: humanizacao de envio (job enviar_turno).
ENVIO_DEFER_HUMANO = Histogram(
    "agente_envio_defer_humano_segundos",
    "Defer 'humano' aplicado ao enqueue do enviar_turno (05 §4.1); 0 = flag off/critico/ja-gasto",
    buckets=(0, 5, 15, 30, 45, 60, 75, 90, 120, float("inf")),
)
ENVIO_DURACAO = Histogram(
    "agente_envio_turno_duracao_seconds",
    "Duracao do job enviar_turno inteiro (chunks + midias) (05 §9)",
)
ENVIO_RESULTADO = Counter(
    "agente_envio_resultado_total",
    "Resultado do envio do turno (05 §9): "
    "ok|cancelado|dedupe_skip|falha_evolution|exaustao_critico|bloqueado_leak|bloqueado_placeholder",
    ["resultado"],
)
ENVIO_RETRIES = Counter(
    "agente_envio_retries_total",
    "Execucoes do job enviar_turno que sao retry do ARQ (ctx job_try>1) (05 §9)",
)
# SEC-PII-02: rede final do enviar_turno redigiu por eco PII do cliente (CPF/RG/telefone) que a
# bolha ia repetir. Endereco/CEP de proposito fora (saida legitima de atendimento externo).
ENVIO_PII_REDIGIDA = Counter(
    "agente_envio_pii_redigida_total",
    "Tokens de PII do cliente redigidos por eco na bolha de saida (SEC-PII-02), por tipo",
    ["tipo"],  # cpf | rg | telefone
)
# 06 §7: pipeline de validacao do Pix de deslocamento. timestamp foi dropado no MVP
# (skew BRT vs UTC marca falso ~100% dos comprovantes) entao nao ha label timestamp.
PIX_VALIDACAO_DURACAO = Histogram(
    "agente_pix_validacao_duracao_seconds",
    "Duracao do job validar_pix (download MinIO + vision OpenRouter + persistencia) (06 §7)",
)
PIX_VALIDACAO_DECISAO = Counter(
    "agente_pix_validacao_decisao_total",
    "Decisao do pipeline Pix; o fluxo nunca trava (01 §6.1) e ambas avancam o atendimento",
    ["decisao"],  # validado | em_revisao
)
PIX_DIVERGENCIA = Counter(
    "agente_pix_divergencia_total",
    "Motivo que levou um comprovante a em_revisao (06 §7; sem timestamp por §0 item 11)",
    ["motivo"],  # plausibilidade | legibilidade | valor | chave | titular | midia | vision
)
# 06 §1.3: pipeline de transcricao Whisper.
TRANSCRICAO_DURACAO = Histogram(
    "agente_transcricao_duracao_seconds",
    "Duracao do job transcrever_audio (download MinIO + Whisper + UPDATE) (06 §1.3)",
)
TRANSCRICAO_RESULTADO = Counter(
    "agente_transcricao_resultado_total",
    "Resultado da transcricao (06 §1.3/§1.5): ok|erro_provider|timeout|sem_audio",
    ["resultado"],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        HTTP_REQUESTS.labels(path, request.method, str(response.status_code)).inc()
        HTTP_DURATION.labels(path, request.method).observe(perf_counter() - start)
        return response


def prometheus_response() -> Response:
    return Response(_generate_latest(), media_type=CONTENT_TYPE_LATEST)
