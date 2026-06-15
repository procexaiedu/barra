// Reconstrucao do chat por conversa a partir dos turnos (respostas da IA) do
// trafego real/e2e. Puro/testavel. Cada resposta da IA em `mensagens` ja e uma
// bolha individual (o coordenador grava 1 linha por chunk), entao nao ha chunking
// aqui: cada turno = uma bolha avaliavel. A msg do cliente de cada turno e a
// ultima ANTES daquela resposta; deduplicamos por timestamp p/ nao repetir a
// bolha quando a IA respondeu em varias mensagens seguidas.

import type { TurnoObservabilidade } from "@/tipos/observabilidade"

export type ItemChat =
  | { tipo: "cliente"; texto: string; ts: string }
  | { tipo: "atendimento"; numeroCurto: number }
  | { tipo: "ia"; turno: TurnoObservabilidade }

export interface ConversaAvaliacao {
  conversaId: string
  modeloNome: string
  clienteLabel: string
  itens: ItemChat[]
  total: number // respostas da IA
  avaliadas: number
}

/** Agrupa os turnos por conversa (preserva a ordem de chegada — backend manda o
 *  turno mais recente primeiro, entao a conversa mais recente vem no topo) e monta
 *  a timeline interleaved (cliente -> IA), com divisoria quando o atendimento muda. */
export function agruparConversas(turnos: TurnoObservabilidade[]): ConversaAvaliacao[] {
  const ordem: string[] = []
  const mapa = new Map<string, TurnoObservabilidade[]>()
  for (const t of turnos) {
    let bucket = mapa.get(t.conversa_id)
    if (!bucket) {
      bucket = []
      mapa.set(t.conversa_id, bucket)
      ordem.push(t.conversa_id)
    }
    bucket.push(t)
  }

  return ordem.map((id) => {
    // dentro da conversa, do mais antigo ao mais novo (ISO ordena lexicograficamente)
    const grupo = [...mapa.get(id)!].sort((a, b) =>
      a.resposta_ia.created_at.localeCompare(b.resposta_ia.created_at),
    )
    const itens: ItemChat[] = []
    let ultimoClienteTs: string | null = null
    let ultimoAtendimento: string | null = null
    for (const t of grupo) {
      if (t.atendimento_id !== ultimoAtendimento && t.numero_curto != null) {
        itens.push({ tipo: "atendimento", numeroCurto: t.numero_curto })
      }
      ultimoAtendimento = t.atendimento_id
      if (t.mensagem_cliente && t.mensagem_cliente.created_at !== ultimoClienteTs) {
        itens.push({
          tipo: "cliente",
          texto: t.mensagem_cliente.conteudo,
          ts: t.mensagem_cliente.created_at,
        })
        ultimoClienteTs = t.mensagem_cliente.created_at
      }
      itens.push({ tipo: "ia", turno: t })
    }
    const primeiro = grupo[0]
    return {
      conversaId: id,
      modeloNome: primeiro.modelo_nome,
      clienteLabel: primeiro.cliente_nome ?? primeiro.cliente_telefone,
      itens,
      total: grupo.length,
      avaliadas: grupo.filter((t) => t.avaliacao !== null).length,
    }
  })
}
