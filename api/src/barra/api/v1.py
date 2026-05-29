from fastapi import APIRouter, Depends

from barra.api.deps import get_user
from barra.dominio.agenda.routes import router as agenda_router
from barra.dominio.atendimentos.routes import router as atendimentos_router
from barra.dominio.clientes.routes import router as clientes_router
from barra.dominio.conversas.routes import router as crm_router
from barra.dominio.dashboard.routes import router as dashboard_router
from barra.dominio.eventos.routes import router as eventos_router
from barra.dominio.financeiro.routes import router as financeiro_router
from barra.dominio.modelos.programas_routes import duracoes_router
from barra.dominio.modelos.programas_routes import router as programas_router
from barra.dominio.modelos.routes import router as modelos_router
from barra.dominio.painel.routes import router as painel_router
from barra.dominio.pix.routes import router as pix_router
from barra.dominio.tarefas.routes import router as tarefas_router

router = APIRouter(dependencies=[Depends(get_user)])
router.include_router(atendimentos_router, prefix="/atendimentos", tags=["atendimentos"])
router.include_router(agenda_router, prefix="/agenda", tags=["agenda"])
router.include_router(crm_router, prefix="/crm", tags=["crm"])
router.include_router(clientes_router, prefix="/crm", tags=["crm"])
router.include_router(modelos_router, prefix="/modelos", tags=["modelos"])
router.include_router(programas_router, prefix="/programas", tags=["programas"])
router.include_router(duracoes_router, prefix="/duracoes", tags=["programas"])
router.include_router(pix_router, prefix="/pix", tags=["pix"])
router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
router.include_router(eventos_router, prefix="/eventos", tags=["eventos"])
router.include_router(painel_router, prefix="/painel", tags=["painel"])
router.include_router(financeiro_router, prefix="/financeiro", tags=["financeiro"])
router.include_router(tarefas_router, prefix="/tarefas", tags=["tarefas"])


@router.get("/saude", include_in_schema=False)
async def saude() -> dict[str, str]:
    return {"status": "ok"}
