"""Montagem dos SystemMessages do prefixo (docs/agente/03 §1, §4).

`build_system_messages` monta o prefixo `system` como SystemMessages de string pura — o formato
que roda em prod sob DeepSeek V4 Flash direto, que cacheia o prefixo AUTOMATICAMENTE (sem
`cache_control`). A factory do chat (`criar_chat_deepseek`) vive em `core/llm.py` — aqui é só a
montagem.

Invariante (agente/CLAUDE.md): BP_GERAL (persona+regras) é GERAL — byte-idêntico entre todas
as modelos. Função pura: mesma entrada → mesma saída sem I/O.
"""

from langchain_core.messages import SystemMessage


def build_system_messages(
    *,
    geral_md: str,
    modelo_md: str | None = None,
    cadastro_md: str | None = None,
) -> list[SystemMessage]:
    """Blocos `system` (strings puras), na ordem de render (§1, §4).

    `geral_md` (persona+regras fundidos pelo caller) é GERAL — byte-idêntico entre todas as
    modelos. Quando `modelo_md` é passado, emite um 2º bloco por-modelo (identidade + programas).
    A ordem é estável e CRÍTICA: geral antes do por-modelo, senão o prefixo deixa de ser global
    (§1, §4.3).

    `cadastro_md` (`render_bloco_da_modelo`) é o 3º bloco, também por-modelo: as condutas que o
    CADASTRO dela decide e o turno não muda (`<sem_menage>`, `<sem_video_chamada>`,
    `<sem_fetiches>`, `<sem_periodo_longo>`, `<periodo_de_trabalho>`). Vinha na cauda volátil e
    pagava cache-MISS todo turno. Entra DEPOIS do BP_MODELO de propósito: o prefixo
    `[geral][por-modelo]` que já está quente no provider não muda um byte com esta adição.

    Strings puras: é o formato que RODA em prod sob DeepSeek (OpenAI-compatível, espera `content`
    string), cujo cache de prefixo é automático no provider — sem marcador `cache_control`.

    **Fusão BP_GERAL**: persona+regras entram num bloco system único — antes eram 2 separados
    (BP1+BP2), mas tinham conteúdo/cadência idênticos.

    Função pura: recebe markdown já renderizado, sem I/O nem `render_persona`/DB — mesma entrada
    produz saída byte-idêntica (invariante de prefixo, agente/CLAUDE.md).
    """
    mensagens = [SystemMessage(content=geral_md)]
    if modelo_md is not None:
        mensagens.append(SystemMessage(content=modelo_md))
    if cadastro_md:
        mensagens.append(SystemMessage(content=cadastro_md))
    return mensagens
