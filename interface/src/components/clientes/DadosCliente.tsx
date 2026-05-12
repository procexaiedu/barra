"use client"

import { Info } from "lucide-react"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { formatBRL, formatData, formatTempoRelativo } from "@/lib/formatters"
import type { AtendimentoHistoricoItem, ClienteDetalhe } from "@/tipos/clientes"

const TIPO_LABEL: Record<"interno" | "externo", string> = {
  interno: "Interno (vai à modelo)",
  externo: "Externo (vai ao cliente)",
}

const FORMA_PAGAMENTO_LABEL: Record<"pix" | "dinheiro" | "outro", string> = {
  pix: "Pix",
  dinheiro: "Dinheiro",
  outro: "Outro",
}

export function DadosCliente({
  cliente,
  historico,
}: {
  cliente: ClienteDetalhe
  historico: AtendimentoHistoricoItem[]
}) {
  const fechados = historico.filter((h) => h.estado === "Fechado")
  const perdidos = historico.filter((h) => h.estado === "Perdido")
  const receita = fechados.reduce((acc, curr) => acc + (Number(curr.valor_final) || 0), 0)
  const ticketMedio = fechados.length > 0 ? receita / fechados.length : 0
  const ultimoFechamentoEm = fechados[0]?.created_at ?? null

  return (
    <div
      aria-label="Dados do cliente"
      className="rounded-lg border border-border bg-card"
    >
      <div className="grid grid-cols-4 divide-x divide-border">
        <Metrica label="Fechados">
          <span className="text-2xl font-semibold text-text-primary">
            {fechados.length > 0 ? fechados.length : "—"}
          </span>
        </Metrica>
        <Metrica label="Perdidos">
          <span className={`text-2xl font-semibold ${perdidos.length > 0 ? "text-state-lost" : "text-text-primary"}`}>
            {perdidos.length > 0 ? perdidos.length : "—"}
          </span>
        </Metrica>
        <Metrica label="Receita Total">
          <span className={`text-lg font-semibold ${receita > 0 ? "text-state-closed" : "text-text-primary"}`}>
            {receita > 0 ? formatBRL(receita) : "—"}
          </span>
        </Metrica>
        <Metrica label="Ticket Médio">
          <span className="text-lg font-semibold text-text-primary">
            {ticketMedio > 0 ? formatBRL(ticketMedio) : "—"}
          </span>
        </Metrica>
      </div>

      <div className="border-t border-border">
        <div className="px-5 pt-3 pb-1">
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            Perfil do cliente
          </span>
        </div>
        <div className="divide-y divide-border">
          <div className="grid grid-cols-3 divide-x divide-border">
            <Metrica label="Último fechamento">
              {ultimoFechamentoEm ? (
                <span className="text-sm text-text-primary">
                  {formatData(ultimoFechamentoEm)}{" "}
                  <span className="text-text-muted">· {formatTempoRelativo(ultimoFechamentoEm)}</span>
                </span>
              ) : (
                <span className="text-sm text-text-primary">Nenhum</span>
              )}
            </Metrica>
            <Metrica label="Modelo preferida">
              <span className="text-sm text-text-primary">
                {cliente.modelo_preferida?.nome ?? "—"}
              </span>
            </Metrica>
            <Metrica
              label="Tipo preferido"
              tooltip="Interno: cliente vai à modelo. Externo: modelo vai ao cliente."
            >
              <span className="text-sm text-text-primary">
                {cliente.tipo_atendimento_mais_frequente
                  ? TIPO_LABEL[cliente.tipo_atendimento_mais_frequente]
                  : "—"}
              </span>
            </Metrica>
          </div>
          <div className="grid grid-cols-3 divide-x divide-border">
            <Metrica label="Programa preferido">
              <span className="text-sm text-text-primary">
                {cliente.programa_preferido?.nome ?? "—"}
              </span>
            </Metrica>
            <Metrica label="Duração preferida">
              <span className="text-sm text-text-primary">
                {cliente.duracao_preferida?.nome ?? "—"}
              </span>
            </Metrica>
            <Metrica label="Pagamento preferido">
              <span className="text-sm text-text-primary">
                {cliente.forma_pagamento_preferida
                  ? FORMA_PAGAMENTO_LABEL[cliente.forma_pagamento_preferida]
                  : "—"}
              </span>
            </Metrica>
          </div>
        </div>
      </div>
    </div>
  )
}

function Metrica({
  label,
  tooltip,
  children,
}: {
  label: string
  tooltip?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5 px-5 py-4">
      <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        {label}
        {tooltip ? (
          <Tooltip>
            <TooltipTrigger
              type="button"
              aria-label={`Sobre ${label}`}
              className="inline-flex items-center text-text-muted/60 transition-colors hover:text-text-primary focus-visible:text-text-primary focus-visible:outline-none"
            >
              <Info size={12} strokeWidth={1.75} aria-hidden />
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-[260px] text-left leading-snug normal-case tracking-normal">
              {tooltip}
            </TooltipContent>
          </Tooltip>
        ) : null}
      </span>
      {children}
    </div>
  )
}
