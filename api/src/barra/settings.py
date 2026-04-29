from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ambiente: Literal["desenvolvimento", "teste", "producao"] = "desenvolvimento"
    log_level: str = "INFO"

    database_url: str
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    redis_url: str

    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket_media: str = "media"
    minio_use_ssl: bool = False

    anthropic_api_key: str
    anthropic_modelo_principal: str = "claude-sonnet-4-6"
    anthropic_modelo_rapido: str = "claude-haiku-4-5-20251001"

    langchain_tracing_v2: bool = True
    langchain_api_key: str | None = None
    langchain_project: str = "barra-vips-dev"

    evolution_base_url: str
    evolution_api_key: str
    evolution_instancia: str = "barra"
    evolution_webhook_token: str

    jid_permitido: str | None = Field(
        default=None,
        description="Quando definido, webhook só processa mensagens deste JID. Usado na Fase 1.5.",
    )

    sentry_dsn: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
