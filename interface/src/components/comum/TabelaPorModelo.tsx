import { formatBRL } from "@/lib/formatters"

/** Shape mínimo de uma linha de faturamento por modelo (compatível com os
 * recortes de Atendimentos e Clientes). */
export interface LinhaPorModelo {
  modelo_id: string
  modelo_nome: string
  fechados: number
  faturamento_bruto_brl: number
  ticket_medio_brl: number | null
}

/** Tabela de faturamento por modelo (fechados / faturamento / ticket), usada nos
 * detalhes dos resumos de Atendimentos e Clientes. */
export function TabelaPorModelo({ items }: { items: LinhaPorModelo[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
            <th className="py-1 pr-2 text-left">Modelo</th>
            <th className="w-20 px-2 py-1 text-right">Fech.</th>
            <th className="w-28 px-2 py-1 text-right">Faturamento</th>
            <th className="w-24 py-1 pl-2 text-right">Ticket</th>
          </tr>
        </thead>
        <tbody>
          {items.map((m) => (
            <tr key={m.modelo_id} className="border-t border-border-subtle">
              <td className="py-1.5 pr-2 align-middle text-[13px] text-text-primary">{m.modelo_nome}</td>
              <td className="px-2 py-1.5 text-right align-middle font-mono text-xs text-text-primary tabular-nums">
                {m.fechados}
              </td>
              <td className="px-2 py-1.5 text-right align-middle font-mono text-xs text-success-500 tabular-nums">
                {formatBRL(m.faturamento_bruto_brl)}
              </td>
              <td className="py-1.5 pl-2 text-right align-middle font-mono text-xs text-text-muted tabular-nums">
                {m.ticket_medio_brl != null ? formatBRL(m.ticket_medio_brl) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
