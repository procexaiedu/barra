"use client"

/* FIXTURE DE VERIFICAÇÃO agent-native — não faz parte do produto.
   Monta o KanbanBoard real com atendimentos mock para que o contrato (data-verificacao)
   seja publicado sem auth nem backend. O middleware libera /verificacao. */

import { KanbanBoard } from "@/components/atendimentos/KanbanBoard"
import type { AtendimentoListaItem, EstadoAtendimento } from "@/tipos/atendimentos"

let seq = 0
function item(estado: EstadoAtendimento, nome: string): AtendimentoListaItem {
  seq += 1
  return {
    id: `fix-${seq}`,
    numero_curto: seq,
    cliente: { id: `c-${seq}`, nome, telefone: "5521999990000" },
    modelo: { id: "m-1", nome: "Lúcia" },
    estado,
    tipo_atendimento: "externo",
    urgencia: "agendado",
    ia_pausada: false,
    ia_pausada_motivo: null,
    responsavel_atual: "IA",
    motivo_escalada: null,
    proxima_acao_esperada: null,
    valor_acordado: 800,
    valor_final: estado === "Fechado" ? 1000 : null,
    updated_at: "2026-05-28T18:00:00Z",
    programa_principal_nome: "1 hora",
  }
}

// 6 ativos (Qualificando/Aguardando/Em atendimento) + 3 encerrados (Fechado/Perdido) = 9.
const ITEMS: AtendimentoListaItem[] = [
  item("Novo", "Ana"),
  item("Triagem", "Bia"),
  item("Qualificado", "Cris"),
  item("Aguardando_confirmacao", "Dora"),
  item("Confirmado", "Eva"),
  item("Em_execucao", "Fabi"),
]
const ENCERRADOS: AtendimentoListaItem[] = [
  item("Fechado", "Gabi"),
  item("Fechado", "Hana"),
  item("Perdido", "Iza"),
]

const NOOP = () => {}
const ASYNC_NOOP = async () => {}

export default function VerificacaoKanban() {
  return (
    <div className="min-h-screen bg-background p-6 text-foreground">
      <h1 className="mb-3 text-sm font-medium text-text-secondary">
        FIXTURE — Kanban de atendimentos
      </h1>
      <KanbanBoard
        items={ITEMS}
        itemsEncerrados={ENCERRADOS}
        mostrarEncerrados
        onToggleEncerrados={NOOP}
        onCardClick={NOOP}
        onMoverEstado={ASYNC_NOOP}
        onSolicitarTerminal={NOOP}
      />
    </div>
  )
}
