"""Parceria entre modelos: a fonte ÚNICA de "quem é a parceira desta modelo" (ADR-0042).

Dois fluxos partem da MESMA pessoa e divergem em tudo:

- **Encaminhamento** (fluxo A) — o cliente quer um ATO que a modelo do canal não faz. Ela nega em
  personagem, e se ele topar passa nome + telefone + fotos da parceira. Dali em diante o
  envolvimento acaba: preço, local e horário são com a parceira, e a IA **não cota valor nenhum**.
- **Dupla** (fluxo B) — o cliente quer DUAS MULHERES. A modelo do canal conduz e fecha ela mesma,
  cota as duas pela tabela DELA (regime de composição, ADR-0039) e **nunca** passa o telefone.

O que decide qual é o `fluxo_da_parceira` (`agente/_parceria.py`), determinístico. O que este
módulo faz é só carregar a AUTORIZAÇÃO do par — a whitelist que o dono do produto pediu, que aqui é
a própria linha da tabela: sem linha ativa, nenhum dos dois fluxos existe (closed-world, a mesma
disciplina do cardápio).

`Parceria` NÃO carrega telefone, e isso é a decisão de segurança do desenho: o telefone da parceira
nunca entra no prompt. Ele é lido fresh, no momento de montar a bolha determinística, pelo
`workers/coordenador.py` — exatamente o trilho da chave Pix (`_formatar_bolha_pix`), que também
mantém a string crítica fora do LLM.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

__all__ = ["Parceria", "carregar_parceria", "contato_da_parceira"]


@dataclass(frozen=True, slots=True)
class Parceria:
    """A parceira autorizada de uma modelo, do ponto de vista do turno.

    `encaminhamento_atos` são CHAVES DE FAMÍLIA de `agente/nos/_foco_do_turno.py:_FAMILIAS_FETICHE`
    (ex.: `("anal",)`) — o mesmo vocabulário que o detector determinístico do burst produz. É o que
    permite ao discriminante ser uma pergunta sobre a FAMÍLIA mencionada em vez de uma inferência.

    Sem telefone de propósito (ver docstring do módulo).
    """

    parceira_id: str
    nome: str
    idade: int | None
    encaminhamento_ativo: bool
    encaminhamento_atos: tuple[str, ...]
    dupla_ativa: bool


async def carregar_parceria(conn: AsyncConnection[Any], modelo_id: str | UUID) -> Parceria | None:
    """A parceira ATIVA da modelo, ou None (o caso de quase todo o cadastro).

    Uma linha por modelo, garantida pelo índice parcial `modelo_parcerias_uma_ativa_por_modelo`; o
    `LIMIT 1` é cinto-suspensório. O SELECT nunca traz `numero_whatsapp` — o telefone não pode
    encostar no caminho do prompt.
    """
    res = await conn.execute(
        """
        SELECT p.parceira_id, p.encaminhamento_ativo, p.encaminhamento_atos, p.dupla_ativa,
               m.nome, m.idade
          FROM barravips.modelo_parcerias p
          JOIN barravips.modelos m ON m.id = p.parceira_id
         WHERE p.modelo_id = %s AND p.ativo
         LIMIT 1
        """,
        (modelo_id,),
    )
    row = await res.fetchone()
    if not row or not row.get("nome"):
        return None
    return Parceria(
        parceira_id=str(row["parceira_id"]),
        nome=row["nome"],
        idade=row.get("idade"),
        encaminhamento_ativo=bool(row["encaminhamento_ativo"]),
        encaminhamento_atos=tuple(row.get("encaminhamento_atos") or ()),
        dupla_ativa=bool(row["dupla_ativa"]),
    )


async def contato_da_parceira(
    conn: AsyncConnection[Any], modelo_id: str | UUID
) -> tuple[str, str] | None:
    """`(nome, telefone)` da parceira ativa — o ÚNICO ponto que lê o telefone.

    Chamado só pelo `workers/coordenador.py`, depois do turno, para montar a bolha determinística
    (mesmo trilho da chave Pix). Devolve None quando não há parceira ativa ou ela não tem número.
    """
    res = await conn.execute(
        """
        SELECT m.nome, m.numero_whatsapp
          FROM barravips.modelo_parcerias p
          JOIN barravips.modelos m ON m.id = p.parceira_id
         WHERE p.modelo_id = %s AND p.ativo
         LIMIT 1
        """,
        (modelo_id,),
    )
    row = await res.fetchone()
    if not row or not row.get("nome") or not row.get("numero_whatsapp"):
        return None
    return str(row["nome"]), str(row["numero_whatsapp"])
