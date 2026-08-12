"""Reexport de `barra.core.texto.normalizar` -- a implementacao DESCEU para `core/` (11/08/2026).

O modulo continua existindo com este nome porque os sete importadores do agente (classificador,
disciplina, persona, output_guard, prepare_context, rollback_watch e os testes) o citam por ele, e
porque a normalizacao entrou no projeto como defesa DO AGENTE (ver a docstring de `core/texto.py`,
que carrega a motivacao original). O que mudou e so a camada: `dominio/` e `core/` tambem precisam
do mesmo dobramento (`core/catalogo.e_video_chamada`) e nao podem importar `barra.agente`.

Codigo novo deve importar de `barra.core.texto`.
"""

from barra.core.texto import normalizar

__all__ = ["normalizar"]
