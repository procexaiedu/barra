from decimal import Decimal
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
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

    # Cotacao USD->BRL p/ a metrica AGENTE_CUSTO_TURNO_BRL (03 §4.2; meta <=0.12 BRL/turno).
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
        default=10, ge=0, le=23,
        description="Hora local de início da operação; reengajamento não dispara fora dela.",
    )
    operacao_hora_fim: int = Field(
        default=2, ge=0, le=23,
        description="Hora local de fim da operação (pode ser < início, ex.: 10-2h cruza a meia-noite).",
    )
    lembrete_valor_ativo: bool = Field(
        default=True,
        description="Liga o Lembrete de fechamento: cobra o valor_final da modelo no grupo após o fim previsto do atendimento (ADR-0009). Mensagem interna no grupo de 2 pessoas, baixo risco -> default on.",
    )
    lembrete_valor_tolerancia_min: int = Field(
        default=15, ge=0,
        description="Minutos após bloqueios.fim antes do 1º lembrete de valor (o atendimento pode esticar).",
    )
    lembrete_valor_intervalo_min: int = Field(
        default=30, ge=1,
        description="Minutos entre reenvios do lembrete de valor (e antes de escalar após o máximo de toques).",
    )
    lembrete_valor_max_toques: int = Field(
        default=3, ge=1,
        description="Máximo de cards de lembrete de valor antes de escalar para Fernando via handoff.",
    )
    pix_deslocamento_valor: Decimal = Field(
        default=Decimal("100.00"),
        description="Valor esperado do Pix de deslocamento, em BRL (06 §2.2/§0 item 6). Comparação é `valor >= esperado`: underpay → em_revisao; valor maior é aceito como validado.",
    )

    langchain_tracing_v2: bool = True
    langchain_api_key: str | None = None
    langchain_project: str = "barra-vips-dev"

    evolution_base_url: str = ""
    evolution_api_key: str = ""
    evolution_webhook_token: str = ""
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
        description="Quando definido, webhook só processa mensagens deste JID. Usado na Fase 1.5.",
    )

    sentry_dsn: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
