import { seletorContrato } from "../contract"
import type { Spec } from "../spec"

// Estado que o KanbanBoard publica: contagem por coluna (as 5) + total. Cada
// atendimento mapeia para exatamente uma coluna, então a soma por coluna fecha o total.
export interface EstadoKanban {
  total: number
  porColuna: Record<string, number>
}

export const specKanban: Spec<EstadoKanban> = {
  id: "kanban",
  url: "/verificacao/kanban",
  selector: seletorContrato("kanban"),
  invariantes: [
    {
      id: "colunas-somam-total",
      descricao: "soma das contagens por coluna = total de atendimentos",
      checar: (e) => Object.values(e.porColuna).reduce((s, n) => s + n, 0) === e.total,
    },
    {
      id: "contagens-nao-negativas",
      descricao: "nenhuma coluna tem contagem negativa",
      checar: (e) => Object.values(e.porColuna).every((n) => n >= 0),
    },
  ],
}
