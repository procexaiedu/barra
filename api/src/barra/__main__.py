"""`python -m barra` — sobe a API em dev com o event loop correto no Windows.

`psycopg` async é incompatível com o ProactorEventLoop (default do Windows) e
pendura em qualquer conexão → timeout/500 em todo endpoint que toca o banco. Para
usar o SelectorEventLoop, duas coisas são necessárias:

1. Setar `WindowsSelectorEventLoopPolicy` ANTES de o loop nascer. Subir via
   `uvicorn barra.main:app` (CLI) não basta: o uvicorn cria o loop antes de
   importar `barra.main`, então a policy de lá roda tarde demais. Aqui ela é
   setada no topo do `__main__`.
2. Passar `loop="none"` ao uvicorn. No uvicorn 0.36+ o `loop="auto"` devolve um
   `get_loop_factory()` que força o ProactorEventLoop via
   `asyncio.run(..., loop_factory=...)`, ignorando a policy. Com `"none"` o
   uvicorn não passa factory e o `asyncio.run` respeita a policy Selector.

No Windows o `reload` fica desligado: o uvicorn faz spawn de um filho que recria o
loop fora deste `__main__`, recaindo no Proactor. Em Linux/macOS nada disso se
aplica (reload e uvloop seguem ligados).
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Import após setar a policy, de propósito (uvicorn cria o loop no run()).
import uvicorn


def main() -> None:
    win = sys.platform == "win32"
    uvicorn.run(
        "barra.main:app",
        host="0.0.0.0",  # noqa: S104 — dev local; mesmo bind do Makefile anterior.
        port=8000,
        loop="none" if win else "auto",
        reload=not win,
    )


if __name__ == "__main__":
    main()
