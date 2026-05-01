from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    minio_bucket_media: str = "media"
    minio_use_ssl: bool = False

    llm_chat_provider: Literal["openrouter", "anthropic"] = "openrouter"
    llm_vision_provider: Literal["openrouter"] = "openrouter"
    llm_audio_provider: Literal["openrouter"] = "openrouter"
    openrouter_api_key: str | None = None
    openrouter_model_chat: str | None = None
    openrouter_model_vision_pix: str | None = None
    openrouter_model_audio_transcribe: str | None = None
    anthropic_api_key: str | None = None
    anthropic_modelo_principal: str = "claude-sonnet-4-6"
    anthropic_modelo_rapido: str = "claude-haiku-4-5-20251001"
    anthropic_model_chat: str | None = None

    langchain_tracing_v2: bool = True
    langchain_api_key: str | None = None
    langchain_project: str = "barra-vips-dev"

    evolution_base_url: str = ""
    evolution_api_key: str = ""
    evolution_instancia: str = "barra"
    evolution_webhook_token: str = ""
    evolution_grupo_coordenacao_jid: str | None = None
    evolution_fernando_jids: list[str] = Field(default_factory=list)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    jid_permitido: str | None = Field(
        default=None,
        description="Quando definido, webhook só processa mensagens deste JID. Usado na Fase 1.5.",
    )

    sentry_dsn: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
