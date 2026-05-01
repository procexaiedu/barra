"""Autenticacao Supabase Auth para rotas /v1."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg import AsyncConnection

from barra.core.errors import NaoAutenticado, SemPermissao
from barra.settings import Settings

try:
    import jwt
except ModuleNotFoundError:  # pragma: no cover - ambiente sem dependencias sincronizadas
    jwt = None  # type: ignore[assignment]

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class UsuarioAtual:
    id: UUID
    email: str | None
    papel: str
    ativo: bool


async def validar_jwt_supabase(token: str, settings: Settings) -> dict[str, Any]:
    if settings.ambiente == "teste" and token.startswith("test:"):
        _, user_id, papel, ativo = token.split(":", 3)
        return {"sub": user_id, "email": "fernando@example.com", "papel": papel, "ativo": ativo}

    if not settings.supabase_jwt_secret:
        if settings.ambiente == "producao":
            raise NaoAutenticado("SUPABASE_JWT_SECRET nao configurado.")
        if jwt is None:
            raise NaoAutenticado("PyJWT nao instalado para decodificar token.")
        try:
            return jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
        except Exception as exc:
            raise NaoAutenticado("Token invalido.") from exc

    try:
        if jwt is None:
            raise NaoAutenticado("PyJWT nao instalado para validar token.")
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_aud": False},
        )
    except Exception as exc:
        raise NaoAutenticado("Token invalido.") from exc


async def usuario_por_token(
    credentials: HTTPAuthorizationCredentials | None,
    settings: Settings,
    conn: AsyncConnection[Any] | None,
) -> UsuarioAtual:
    if credentials is None:
        raise NaoAutenticado()

    payload = await validar_jwt_supabase(credentials.credentials, settings)
    sub = payload.get("sub")
    if not sub:
        raise NaoAutenticado("Token sem subject.")
    user_id = UUID(str(sub))

    if settings.ambiente == "teste" and payload.get("papel"):
        user = UsuarioAtual(
            id=user_id,
            email=payload.get("email"),
            papel=str(payload["papel"]),
            ativo=str(payload.get("ativo", "true")).lower() == "true",
        )
    else:
        if conn is None:
            raise NaoAutenticado("Banco indisponivel para autenticar usuario.")
        row = await conn.execute(
            """
            SELECT id, email, papel::text AS papel, ativo
              FROM barravips.usuarios
             WHERE id = %s
            """,
            (user_id,),
        )
        data = await row.fetchone()
        if data is None:
            raise SemPermissao()
        user = UsuarioAtual(
            id=data["id"],
            email=data["email"],
            papel=data["papel"],
            ativo=data["ativo"],
        )

    if not user.ativo:
        raise SemPermissao("Usuario inativo.")
    if user.papel != "fernando":
        raise SemPermissao()
    return user


async def usuario_atual(request: Request) -> UsuarioAtual:
    settings: Settings = request.app.state.settings
    credentials = await bearer(request)
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        return await usuario_por_token(credentials, settings, None)
    async with pool.connection() as conn:
        return await usuario_por_token(credentials, settings, conn)
