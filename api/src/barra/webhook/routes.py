from fastapi import APIRouter

router = APIRouter()


@router.post("/evolution")
async def evolution_webhook() -> dict[str, str]:
    # 1. validar token (header) -> webhook.filtro
    # 2. filtrar JID permitido -> webhook.filtro
    # 3. debounce multi-device + 60s -> webhook.debounce
    # 4. despachar para agente.graph -> webhook.despacho
    return {"status": "received"}
