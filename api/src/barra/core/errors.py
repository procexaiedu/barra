"""Envelope de erro HTTP e excecoes previsiveis do dominio."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErroDominio(Exception):
    """Base para erros previsiveis do dominio."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class NaoAutenticado(ErroDominio):
    def __init__(self, message: str = "Autenticacao obrigatoria.") -> None:
        super().__init__("NAO_AUTENTICADO", message, status_code=status.HTTP_401_UNAUTHORIZED)


class SemPermissao(ErroDominio):
    def __init__(self, message: str = "Usuario sem permissao.") -> None:
        super().__init__("SEM_PERMISSAO", message, status_code=status.HTTP_403_FORBIDDEN)


class NaoEncontrado(ErroDominio):
    def __init__(self, recurso: str = "Recurso") -> None:
        super().__init__(
            "RECURSO_NAO_ENCONTRADO",
            f"{recurso} nao encontrado.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ConflitoEstado(ErroDominio):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            "CONFLITO_ESTADO",
            message,
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class EntradaInvalida(ErroDominio):
    def __init__(
        self,
        code: str = "ENTRADA_INVALIDA",
        message: str = "Entrada invalida.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code,
            message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
        )


class JidNaoPermitido(ErroDominio):
    def __init__(self) -> None:
        super().__init__("JID_NAO_PERMITIDO", "JID nao permitido.", status_code=403)


def erro_response(status_code: int, code: str, message: str, details: object = None) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=body)


def instalar_handlers(app: FastAPI) -> None:
    @app.exception_handler(ErroDominio)
    async def dominio_handler(_: Request, exc: ErroDominio) -> JSONResponse:
        return erro_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validacao_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return erro_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDACAO_INVALIDA",
            "Entrada invalida.",
            {"errors": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "ERRO_HTTP"
        if exc.status_code == 401:
            code = "NAO_AUTENTICADO"
        elif exc.status_code == 403:
            code = "SEM_PERMISSAO"
        elif exc.status_code == 404:
            code = "RECURSO_NAO_ENCONTRADO"
        return erro_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def inesperado_handler(_: Request, __: Exception) -> JSONResponse:
        return erro_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "ERRO_INTERNO",
            "Erro inesperado.",
        )
