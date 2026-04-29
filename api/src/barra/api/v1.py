from fastapi import APIRouter

from barra.dominio.conversas.routes import router as conversas_router

router = APIRouter()
router.include_router(conversas_router, prefix="/conversas", tags=["conversas"])
# router.include_router(atendimentos_router, prefix="/atendimentos", tags=["atendimentos"])
# router.include_router(agenda_router, prefix="/agenda", tags=["agenda"])
# router.include_router(pix_router, prefix="/pix", tags=["pix"])
# ... outros contextos conforme forem implementados.


@router.get("/saude")
async def saude() -> dict[str, str]:
    return {"status": "ok"}
