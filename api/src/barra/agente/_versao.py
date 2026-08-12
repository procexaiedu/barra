"""Impressao digital da ARVORE DE PROMPTS — o "de que versao da conduta este turno saiu".

O agente nao muda por deploy de codigo: muda por edicao de `agente/prompts/`. Sem um carimbo por
turno, um trace de ontem e um de hoje sao indistinguiveis no Langfuse mesmo tendo rodado prompts
diferentes — e a pergunta que mais se faz olhando trace ("isso ja e a rodada nova?") vira
arqueologia de git. `versao_prompts()` responde com um hash curto que viaja como tag do trace
(`prompts:<hash>`, ver `core.tracing.metadata_trace_turno`).

Nao substitui `release` (sha do codigo, que o SDK do Langfuse le de `LANGFUSE_RELEASE` no Env):
sao eixos diferentes — codigo e conduta versionam em ritmos diferentes neste projeto.
"""

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

_DIR_PROMPTS = Path(__file__).parent / "prompts"


@lru_cache(maxsize=1)
def versao_prompts() -> str:
    """Hash curto (12 hex) do conteudo de TODOS os arquivos de `agente/prompts/`.

    Deterministico (ordena por nome, le bytes crus) e cacheado por processo: o worker recarrega no
    restart, que e exatamente quando um prompt editado passa a valer. Cobre `.md` e `.md.j2` — o
    template conta como conduta, mesmo que o texto final dependa dos dados da modelo.

    NAO cobre o que o prompt final tambem contem: os dados da modelo (banco) e os blocos montados em
    `persona.py`. Duas modelos com prompts diferentes tem o mesmo hash — o eixo aqui e a ARVORE, e o
    eixo por-modelo ja e a tag `modelo_id`.

    Diretorio ausente (instalacao exotica/teste) -> "desconhecida": o carimbo e observabilidade e
    nunca pode derrubar o turno.
    """
    if not _DIR_PROMPTS.is_dir():
        return "desconhecida"
    h = hashlib.sha256()
    for arquivo in sorted(_DIR_PROMPTS.iterdir()):
        if not arquivo.is_file():
            continue
        h.update(arquivo.name.encode())
        h.update(arquivo.read_bytes())
    return h.hexdigest()[:12]


def regime_do_turno(settings: Any) -> dict[str, str]:
    """Carimbo do CONFIG que produziu o turno, para viajar como tag/metadata do trace.

    Tres eixos, os que mudam a conduta sem mudar o codigo: o modelo, o modo de raciocinio
    (`deepseek_thinking_chat`, "low" em prod desde 11/08/2026) e o hash da arvore de prompts. Junto,
    respondem no painel a pergunta que hoje so o git responde: "esta fala saiu de qual versao da
    conduta?" — e sao o que separa os braços de um A/B no mesmo projeto Langfuse.

    `getattr` com default vazio e chave vazia descartada: os fakes de Settings dos testes definem so
    o que usam, e um carimbo de telemetria nunca pode ser motivo de o turno quebrar.
    """
    campos = {
        "modelo_llm": str(getattr(settings, "deepseek_model_chat", "") or ""),
        "thinking": str(getattr(settings, "deepseek_thinking_chat", "") or ""),
        "prompts": versao_prompts(),
    }
    return {k: v for k, v in campos.items() if v}
