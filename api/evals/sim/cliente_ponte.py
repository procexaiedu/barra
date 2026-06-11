"""Cliente da PONTE Claude Code: a fala do cliente vem de um agente do Claude Code, nao da API.

Regra da rodada de go-live (10/06): credito Anthropic de API e gasto SOMENTE pelo agente do
Barra. Nos cenarios robo, o lado cliente e respondido por agentes do Claude Code (tokens do
plano): a cada turno, `ClientePonte.decidir` escreve um `*.pedido.json` com o prompt JA
RENDERIZADO por `montar_prompt_cliente` (mesmo guard anti-leakage do `ClienteSimulado` -- so
muda quem responde) e aguarda o `*.resposta.json` correspondente aparecer no diretorio da ponte.

Protocolo (1 par de arquivos por turno do cliente; escrita ATOMICA via tmp + os.replace):

    <conversa_id sanitizado>__t<N>.pedido.json    {"conversa_id", "turno", "mensagens": [...]}
    <conversa_id sanitizado>__t<N>.resposta.json  {"mensagem": "<fala do cliente>"}

Quem responde (agente Claude Code) age EXATAMENTE como o system/user do pedido instruem e grava
so a fala -- tambem atomicamente, senao o leitor pode ver JSON parcial (o loop tolera e retenta).
Sem resposta dentro do timeout -> TimeoutError: a jornada falha e a rodada segue
(`massa._rodar_item` isola por item). `custo_brl_acumulado` e 0.0 por design (tokens do plano).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from .cliente import AcaoCliente, PersonaCliente, montar_prompt_cliente


def _sanitizar(conversa_id: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "-" for c in conversa_id)


def _escrever_pedido(pedido: Path, payload: dict[str, Any]) -> None:
    os.makedirs(pedido.parent, exist_ok=True)
    tmp = pedido.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, pedido)


def _ler_resposta(resposta: Path) -> str | None:
    """Fala do cliente, ou None se ainda nao disponivel (ausente ou escrita em andamento)."""
    if not resposta.exists():
        return None
    try:
        return str(json.loads(resposta.read_text(encoding="utf-8"))["mensagem"])
    except (json.JSONDecodeError, KeyError):
        return None  # parcial/malformado: o proximo ciclo retenta ate o timeout


class ClientePonte:
    """ClienteLike cuja fala vem de fora do processo (agente Claude Code) via arquivos."""

    def __init__(
        self,
        persona: PersonaCliente,
        dir_ponte: Path,
        conversa_id: str,
        *,
        timeout_s: float = 900.0,
        intervalo_s: float = 2.0,
    ) -> None:
        self.persona = persona
        self.dir_ponte = dir_ponte
        self.conversa_id = conversa_id
        self.timeout_s = timeout_s
        self.intervalo_s = intervalo_s
        self.custo_brl_acumulado: float = 0.0  # nunca cresce: a ponte nao toca a API
        self._turno = 0

    async def decidir(
        self, historico_visivel: list[str], *, settings: Any | None = None
    ) -> AcaoCliente:
        mensagens = montar_prompt_cliente(self.persona, historico_visivel)
        self._turno += 1
        base = f"{_sanitizar(self.conversa_id)}__t{self._turno}"
        pedido = self.dir_ponte / f"{base}.pedido.json"
        resposta = self.dir_ponte / f"{base}.resposta.json"

        payload = {"conversa_id": self.conversa_id, "turno": self._turno, "mensagens": mensagens}
        await asyncio.to_thread(_escrever_pedido, pedido, payload)

        limite = time.monotonic() + self.timeout_s
        while True:
            texto = await asyncio.to_thread(_ler_resposta, resposta)
            if texto is not None:
                if not texto.strip():
                    raise ValueError(f"ponte devolveu mensagem vazia em {resposta.name}")
                return AcaoCliente(mensagem=texto.strip())
            if time.monotonic() > limite:
                raise TimeoutError(
                    f"ponte sem resposta para {resposta.name} em {self.timeout_s:.0f}s"
                )
            await asyncio.sleep(self.intervalo_s)
