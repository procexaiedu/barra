from uuid import UUID

from fastapi import APIRouter

router = APIRouter()


@router.get("/{conversa_id}")
async def obter_conversa(conversa_id: UUID) -> dict[str, str]:
    return {"conversa_id": str(conversa_id), "status": "stub"}


@router.post("/{conversa_id}/devolver-para-ia")
async def devolver_para_ia(conversa_id: UUID) -> dict[str, str]:
    # Decisão grilling 29/04 §5: opção D — IA absorve backlog, não envia proativo.
    return {"conversa_id": str(conversa_id), "ia_pausada": "false"}
