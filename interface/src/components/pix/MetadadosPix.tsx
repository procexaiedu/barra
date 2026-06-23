"use client"

import type { ReactNode } from "react"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { formatBRL, formatDataHora } from "@/lib/formatters"
import type { PixDetalhe } from "@/tipos/pix"
import { tipoChaveLabel } from "./utils"

export function MetadadosPix({ pix }: { pix: PixDetalhe }) {
  const valor = pix.valor_extraido !== null ? formatBRL(pix.valor_extraido) : null
  const horario = pix.horario_transacao ? formatDataHora(pix.horario_transacao) : null
  const remetente = pix.titular_extraido
  const documento = pix.documento_extraido
  const chave = pix.chave_extraida
  const tipoChave = pix.tipo_chave
  const hash = pix.hash_duplicidade

  return (
    <section
      aria-label="Dados do comprovante"
      className="rounded-lg bg-card p-3 shadow-elev-1 ring-1 ring-border-subtle"
    >
      <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
        <span className="h-3 w-0.5 rounded-full bg-gold-500" aria-hidden />
        Dados do comprovante
      </h3>
      <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-[180px_1fr]">
        <Linha label="Valor">
          {valor ? (
            <span className="font-mono tabular-nums text-text-primary">{valor}</span>
          ) : (
            <NaoExtraido />
          )}
        </Linha>
        <Linha label="Data e hora">
          {horario ?? <NaoExtraido />}
        </Linha>
        <Linha label="Remetente">
          {remetente ? (
            <span className="flex flex-wrap items-baseline gap-2">
              <span className="text-text-primary">{remetente}</span>
              {documento && (
                <span className="font-mono text-xs text-text-muted">{documento}</span>
              )}
            </span>
          ) : (
            <NaoExtraido />
          )}
        </Linha>
        <Linha label="Chave de destino">
          {chave ? (
            <span className="flex flex-wrap items-baseline gap-2">
              <span className="min-w-0 break-all font-mono text-[13px] text-text-primary">{chave}</span>
              {tipoChave && (
                <span className="text-xs text-text-muted">{tipoChaveLabel[tipoChave]}</span>
              )}
            </span>
          ) : (
            <NaoExtraido />
          )}
        </Linha>
        {hash && (
          <Linha label="Identificador">
            <Tooltip>
              <TooltipTrigger render={<span className="font-mono text-xs text-text-muted" />}>
                {hash.length > 12 ? `${hash.slice(0, 12)}…` : hash}
              </TooltipTrigger>
              <TooltipContent>
                <span className="font-mono text-xs">{hash}</span>
              </TooltipContent>
            </Tooltip>
          </Linha>
        )}
      </dl>
    </section>
  )
}

function Linha({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-[13px] text-text-muted">{label}</dt>
      <dd className="min-w-0 text-sm text-text-primary">{children}</dd>
    </>
  )
}

function NaoExtraido() {
  return <span className="text-text-muted">Não identificado</span>
}
