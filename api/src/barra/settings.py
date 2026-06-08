import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ambiente: Literal["desenvolvimento", "teste", "producao"] = "desenvolvimento"
    log_level: str = "INFO"

    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str | None = None

    redis_url: str = ""

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket_media: str = "barra-media"
    minio_use_ssl: bool = False

    @field_validator("minio_endpoint", mode="before")
    @classmethod
    def normalizar_minio_endpoint(cls, v: object) -> str:
        """MinIO exige host[:porta] sem esquema e sem path (evita ValueError no client)."""
        if v is None:
            return "localhost:9000"
        s = str(v).strip()
        if not s:
            return "localhost:9000"
        if "://" in s:
            parsed = urlparse(s)
            host = parsed.hostname or ""
            if not host:
                return "localhost:9000"
            if parsed.port:
                return f"{host}:{parsed.port}"
            return host
        if "/" in s:
            s = s.split("/", 1)[0].strip()
        return s

    @model_validator(mode="before")
    @classmethod
    def _carregar_secrets_de_arquivo(cls, data: object) -> object:
        """Padrão *_FILE (Docker/Swarm secret): se `<CAMPO>_FILE` aponta para um arquivo
        existente, seu conteúdo (sem espaços nas pontas) vence o valor inline. Mantém o
        segredo fora do env e do git — em prod a chave vive só no Swarm secret montado em
        /run/secrets/minio_secret_key, lido via MINIO_SECRET_KEY_FILE (DEPLOY-01)."""
        if isinstance(data, dict):
            for campo in ("minio_secret_key",):
                caminho = os.environ.get(f"{campo.upper()}_FILE")
                if caminho and Path(caminho).is_file():
                    data[campo] = Path(caminho).read_text(encoding="utf-8").strip()
        return data

    llm_chat_provider: Literal["openrouter", "anthropic"] = "anthropic"
    llm_vision_provider: Literal["openrouter"] = "openrouter"
    llm_audio_provider: Literal["openrouter"] = "openrouter"
    openrouter_api_key: str | None = None
    openrouter_model_chat: str | None = None
    openrouter_model_vision_pix: str | None = None
    # TODO(M5-final): aposentar (sabatina 2026-05-23 §1.3 — STT migrou para OpenAI direto).
    openrouter_model_audio_transcribe: str | None = None
    anthropic_api_key: str | None = None
    anthropic_modelo_principal: str = "claude-sonnet-4-6"
    anthropic_model_chat: str | None = None
    # Modelo do LLM-judge dos evals (EVAL-02). None -> usa o `anthropic_modelo_principal`, i.e. o
    # MESMO modelo do agente sob teste -> vies de auto-concordancia (self-preference). Apontar p/
    # um modelo diferente (ex. "claude-opus-4-8") mitiga: pesos distintos reduzem o vies. Cross-
    # familia real (GPT/Gemini via OpenRouter) e o alvo final, exige wiring de provider -> P1.
    anthropic_modelo_judge: str | None = None

    # Rotulagem de calibracao no painel (Loop B / EVAL-10): sem RBAC, ambos operadores sao
    # papel='fernando' -> a unica forma de distinguir quem rotula e o email. Mapeia cada email
    # ao rotulador; email nao listado nao abre a tela (403). Setar os tres em prod.
    # 'procex' e um 3o revisor independente (bucket proprio); o golden segue fernando x socia.
    calibracao_email_fernando: str | None = None
    calibracao_email_socia: str | None = None
    calibracao_email_procex: str | None = None

    # STT do agente (06 §1.3): Whisper direto da OpenAI. Sai do OpenRouter porque o hop
    # extra nao compensa num STT critico de baixa latencia sob o orcamento de 8s (sabatina
    # 2026-05-23 §1.3). Default whisper-1 porque a resposta verbose_json inclui .duration
    # nativamente; gpt-4o-mini-transcribe exigiria calculo local de duracao.
    openai_api_key: str | None = None
    openai_model_audio_transcribe: str = "whisper-1"

    # Chat Anthropic (grilling 2026-05-23; docs/agente/03 §6.1): TTL de cache por bloco +
    # parâmetros do ChatAnthropic. cache_ttl_geral (BP1/BP2) não pode ser mais curto que
    # cache_ttl_modelo (BP3) — a Anthropic exige o TTL mais longo antes do mais curto (03 §1/§5).
    cache_ttl_geral: str = "1h"
    cache_ttl_modelo: str = "1h"
    anthropic_thinking: Literal["enabled", "disabled"] = "disabled"
    anthropic_effort: Literal["low", "medium", "high"] = "low"
    anthropic_max_tokens: int = 1024

    # Fonte unica do alvo de custo por turno (CUSTO-06). Antes o numero estava duplicado em
    # comentarios/help de core/metrics.py, agente/nos/llm.py e _custo.py; agora todos apontam
    # para este campo. NAO confundir com `max_custo_brl` das fixtures de eval (budget por-fixture
    # mais estrito, knob diferente, inerte no runner hoje).
    custo_alvo_brl: float = Field(
        default=0.12,
        gt=0.0,
        description="Alvo de custo estimado por turno do agente em BRL (Sonnet 4.6 com cache; 03 §4.2).",
    )

    # Cotacao USD->BRL p/ a metrica AGENTE_CUSTO_TURNO_BRL (03 §4.2; meta em settings.custo_alvo_brl).
    # Reajustar por settings em vez de hardcoded p/ nao requerer deploy a cada flutuacao cambial.
    usd_brl_cotacao: float = Field(
        default=5.50,
        gt=0.0,
        description="Cotacao USD->BRL usada p/ converter o custo estimado do turno (Sonnet 4.6).",
    )

    # Strict mode em tools (doc oficial Anthropic `strict-tool-use`): grammar-constrained
    # decoding + cache de grammar 24h. Master-switch do strict PER-TOOL: quando True, aplica strict
    # SO as tools de `STRICT_TOOLS` (`agente/ferramentas/__init__.py` — hoje {"escalar"}), nao a
    # todas. O default ANTES era False porque o strict GLOBAL estourava "Schema is too complex"
    # (limite somado em todas as tools strict da request); per-tool no `escalar` (1 enum de
    # roteamento + 2 strings, apos `_sanitizar_para_strict` remover min/maxLength) cabe nos limites
    # e foi VALIDADO contra a API real (2026-05-28: 200 OK, sem 400). `registrar_extracao` (~15
    # campos, muitos union types `X | None`) fica FORA de STRICT_TOOLS ate o schema ser enxugado
    # (limite de 16 union types). Setar False mata o strict sem deploy (kill-switch).
    anthropic_strict_tools: bool = Field(
        default=True,
        description="Master-switch do strict PER-TOOL (STRICT_TOOLS em ferramentas/__init__.py). False desliga.",
    )
    preaquecer_cache_no_startup: bool = Field(
        default=True,
        description="Pre-aquece o prefixo global de cache (tools+BP_GERAL) com 1 request no startup do worker, evitando o burst de cache writes a 2x apos deploy de prompt ou gap > TTL (pesquisa §1.7 / 03 §4.5).",
    )
    # Output-guard de saida antes da bolha (AGENTE-OG / ADR 0016).
    output_guard_habilitado: bool = Field(
        default=True,
        description="Liga o no output_guard (scan deterministico + LLM-judge de AUP) antes do despacho da bolha. False desliga o no inteiro (bolha sai como hoje) — kill-switch sem deploy.",
    )
    output_guard_judge_habilitado: bool = Field(
        default=True,
        description="Liga a Etapa 2 (LLM-judge de AUP vinculante) do output_guard. False roda so a Etapa 1 (scan deterministico barato), util se o judge nao-calibrado causar over-refusal. Falha de infra do judge -> default seguro (bloqueia+escala), nunca configuravel p/ passar.",
    )
    # Rede final de saida no enviar_turno (SEC-OUT-01/SEC-PII-02): cobre tambem os caminhos
    # canned/reengajamento que pulam o no output_guard do grafo.
    envio_guard_habilitado: bool = Field(
        default=True,
        description="Liga a rede final no enviar_turno: bloqueia+escala bolha que admite ser IA (auto-referencia) e redige por eco a PII do cliente (CPF/RG/telefone) — nao a chave Pix da modelo, que nao vem do cliente. False = bolha sai como hoje (kill-switch sem deploy).",
    )
    reincidencia_seguranca_habilitada: bool = Field(
        default=True,
        description="Conta tentativas de disclosure/jailbreak por telefone (cliente) em 24h e escala a Fernando ao atingir o limiar, SEM bloquear o cliente (SEC-JB-02/AUP). False desliga a contagem.",
    )
    reincidencia_seguranca_limiar: int = Field(
        default=3,
        ge=1,
        description="Nº de tentativas de disclosure/jailbreak do mesmo telefone em 24h que dispara a escalada de reincidencia (1x por janela).",
    )
    eval_online_sample_rate: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="EVAL-11: fracao dos turnos 'ok' amostrados p/ a rubrica online de non_disclosure (deterministica, sem custo de LLM) observada em agente_eval_pass_rate{suite=online_non_disclosure}. 0 desliga.",
    )

    # Comportamento comercial do agente (grilling 2026-05-23; docs/agente + ADR-0004)
    desconto_max_pct: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Teto do Desconto de fechamento sobre o Preço de tabela do programa (ADR-0004). 0 desliga o desconto (IA escala todo pedido abaixo da tabela).",
    )
    reengajamento_ativo: bool = Field(
        default=False,
        description="Liga a reabertura proativa de cliente que sumiu após a cotação. Default off no início do piloto (docs/agente/07 §4).",
    )
    reengajamento_delay_min: int = Field(
        default=30,
        ge=1,
        description="Minutos de silêncio do cliente após a cotação antes do toque único de reengajamento.",
    )
    operacao_hora_inicio: int = Field(
        default=10,
        ge=0,
        le=23,
        description="Hora local de início da operação; reengajamento não dispara fora dela.",
    )
    operacao_hora_fim: int = Field(
        default=2,
        ge=0,
        le=23,
        description="Hora local de fim da operação (pode ser < início, ex.: 10-2h cruza a meia-noite).",
    )
    lembrete_valor_ativo: bool = Field(
        default=True,
        description="Liga o Lembrete de fechamento: cobra o valor_final da modelo no grupo após o fim previsto do atendimento (ADR-0009). Mensagem interna no grupo de 2 pessoas, baixo risco -> default on.",
    )
    lembrete_valor_tolerancia_min: int = Field(
        default=15,
        ge=0,
        description="Minutos após bloqueios.fim antes do 1º lembrete de valor (o atendimento pode esticar).",
    )
    lembrete_valor_intervalo_min: int = Field(
        default=30,
        ge=1,
        description="Minutos entre reenvios do lembrete de valor (e antes de escalar após o máximo de toques).",
    )
    lembrete_valor_max_toques: int = Field(
        default=3,
        ge=1,
        description="Máximo de cards de lembrete de valor antes de escalar para Fernando via handoff.",
    )
    pix_deslocamento_valor: Decimal = Field(
        default=Decimal("100.00"),
        description="Valor esperado do Pix de deslocamento, em BRL (06 §2.2/§0 item 6). Comparação é `valor >= esperado`: underpay → em_revisao; valor maior é aceito como validado.",
    )
    # Taxa de cartão default (ADR 0013): cobrada por cima do serviço quando forma_pagamento='cartao'.
    # Snapshot por atendimento em atendimentos.taxa_cartao_snapshot; este e so o DEFAULT da UI/fechamento.
    taxa_cartao_padrao_pct: Decimal = Field(
        default=Decimal("10.00"),
        ge=Decimal("0"),
        le=Decimal("100"),
        description="Percentual default da Taxa de cartão (ADR 0013), cobrado por cima do serviço no cartão. Isentável por atendimento; snapshot fica em atendimentos.taxa_cartao_snapshot.",
    )

    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str = "barra-vips-dev"

    evolution_base_url: str = ""
    evolution_api_key: str = ""
    evolution_webhook_token: str = ""
    midia_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        description="Teto de bytes ao baixar mídia da Evolution; download aborta acima disso (defesa DoS).",
    )
    webhook_max_body_bytes: int = Field(
        default=1024 * 1024,
        description="Teto do corpo do POST /webhook/evolution (Content-Length); payload Evolution é pequeno (mídia vem por URL). Acima disso → 413 (defesa DoS de memória).",
    )
    evolution_webhook_callback_url: str | None = Field(
        default=None,
        description="URL pública do nosso /webhook/evolution. Quando definida, é passada à Evolution no POST /instance/create.",
    )
    evolution_grupo_coordenacao_jid: str | None = None
    evolution_fernando_jids: list[str] = Field(default_factory=list)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    cors_origin_regex: str | None = None

    jid_permitido: str | None = Field(
        default=None,
        description=(
            "Flag de TESTE da Fase 1.5: quando definido, o webhook só processa mensagens deste "
            "único JID global. Default None = desligado. NÃO é allowlist por modelo nem defesa de "
            "produção — a borda real é token + instância cadastrada + UNIQUE evolution_instance_id."
        ),
    )

    reset_teste_instances: list[str] = Field(
        default_factory=list,
        description=(
            "Allowlist de evolution_instance_id que aceitam o comando de TESTE `#reset` no grupo "
            "(zera todo o estado transacional da modelo p/ recomeçar um teste E2E do zero). "
            "Default vazio = desligado. Ferramenta de teste — nunca inclua a instância de uma "
            "modelo real em produção."
        ),
    )

    sentry_dsn: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
