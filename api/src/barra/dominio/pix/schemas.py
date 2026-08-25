"""DTOs da borda HTTP do Pix de deslocamento (o painel de revisao).

O vocabulario da SUSPEITA nao mora aqui — ele e dominio puro e os dois caminhos o consomem
(`dominio/grupo_financeiro/comprovante.py::MotivoDeSuspeita`, ADR-0049 §5, ticket 07). O que este
modulo acrescenta e a traducao dele para a borda: de que rejeicao cada duvida costuma terminar
quando um humano confirma a suspeita.
"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field

from barra.dominio.grupo_financeiro.comprovante import MotivoDeSuspeita

__all__ = [
    "REJEICAO_SUGERIDA",
    "AprovarPixRequest",
    "MotivoDeSuspeita",
    "MotivoRejeicao",
    "ReabrirPixRequest",
    "RecusarPixRequest",
    "RejeitarPixRequest",
]


class RecusarPixRequest(BaseModel):
    motivo: str


MotivoRejeicao = Literal[
    "valor_incorreto",
    "comprovante_ilegivel",
    "conta_destino_errada",
    "comprovante_falso",
    "duplicado",
    "fora_da_janela",
    "outro",
]
"""O VEREDITO humano ao rejeitar um comprovante — o que Fernando concluiu, nao o que a maquina
suspeitou.

`comprovante_falso` entrou no ticket 07 e e a unica adicao: a montagem / print de outro app — o
"Pix zoado" da ata — nao tinha palavra propria, e o operador era obrigado a marcar `outro`. Com
isso a fraude ficava indistinguivel de tudo que nao tem nome, que e o mesmo defeito de vocabulario
que o ADR-0049 conserta na chave. Nao ha enum no banco por tras deste Literal (o motivo viaja no
payload JSONB do evento `pix_status_mudado`), entao acrescentar valor nao pede migration."""


REJEICAO_SUGERIDA: Mapping[MotivoDeSuspeita, MotivoRejeicao] = {
    "imagem_repetida": "duplicado",
    "sem_leitura": "comprovante_ilegivel",
    "imagem_implausivel": "comprovante_falso",
    "imagem_ilegivel": "comprovante_ilegivel",
    "valor_abaixo_do_esperado": "valor_incorreto",
    "destino_desconhecido": "conta_destino_errada",
    "titular_divergente": "conta_destino_errada",
}
"""A ponte entre o que a MAQUINA suspeitou e o veredito que o HUMANO provavelmente vai dar.

Sao dois vocabularios e continuam sendo dois de proposito — um e leitura, o outro e decisao —, mas
sem esta ponte eles nao se cruzam: a estatistica de suspeita e a de rejeicao ficam falando de
coisas diferentes sobre o mesmo comprovante.

Na pratica e o pre-selecionado do dialogo de rejeicao: quem rejeita continua escolhendo, e trocar
e um clique. Existe porque o operador que abriu o comprovante ja leu, na linha de cima, qual foi a
duvida — repetir a escolha a mao e a chance de as duas contagens divergirem por desatencao."""


class RejeitarPixRequest(BaseModel):
    motivo: MotivoRejeicao
    observacao: str | None = Field(default=None, max_length=500)


class AprovarPixRequest(BaseModel):
    pass


class ReabrirPixRequest(BaseModel):
    pass
