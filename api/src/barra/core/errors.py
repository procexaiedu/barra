"""Exceções de domínio."""


class ErroDominio(Exception):
    """Base para erros previsíveis do domínio (não bug)."""


class JidNaoPermitido(ErroDominio):
    """Webhook recebeu mensagem fora do JID configurado (Fase 1.5)."""
