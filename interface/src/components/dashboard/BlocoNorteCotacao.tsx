"use client"

import { Target } from "lucide-react"
import type { NorteCotacao } from "@/tipos/dashboard"
import { TileKpi } from "./TileKpi"
import { formatPercent } from "./utils"
import { formatBRL } from "@/lib/formatters"
import { emitirContrato } from "@/lib/verify/contract"

interface Props {
  norte: NorteCotacao
}

const NUM_FMT = new Intl.NumberFormat("pt-BR")

// Métrica de norte: das threads que receberam cotação (coorte por cotacao_enviada_em),
// quanto fechou e quanto rende por thread cotada. Denominador = cotadas (mais estrito que
// a taxa de conversão por decididos). O contrato publica os números crus para a spec.
export function BlocoNorteCotacao({ norte }: Props) {
  const { cotadas, fechadas, em_aberto, conversao_cotada_para_fechado_pct, receita_bruta_brl } =
    norte
  const r_por_thread = norte.r_por_thread_cotada_brl

  return (
    <section
      {...emitirContrato("norte", {
        cotadas,
        fechadas,
        em_aberto,
        conversao_cotada_para_fechado_pct,
        receita_bruta_brl,
        r_por_thread_cotada_brl: r_por_thread,
      })}
      aria-label="Norte: conversão de threads cotadas e receita por thread"
      className="flex flex-col gap-3"
    >
      <header className="flex items-center justify-between">
        <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
          <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
          Norte — cotada → fechado
        </h2>
        <span className="text-xs font-medium text-text-muted">
          <span className="font-mono tabular-nums">{NUM_FMT.format(cotadas)}</span>{" "}
          {cotadas === 1 ? "thread cotada" : "threads cotadas"} no período
        </span>
      </header>

      {cotadas === 0 ? (
        <div className="rounded-lg bg-card p-6 text-center shadow-elev-1 ring-1 ring-border-subtle">
          <p className="text-sm font-medium text-text-primary">
            Nenhuma thread recebeu cotação no período selecionado.
          </p>
          <p className="mt-1 text-[13px] text-text-muted">Ajuste o período no topo da página.</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <TileKpi
              label="Conversão cotada → fechado"
              icone={Target}
              iconeClassName="text-gold-500"
              tooltip="Das threads que receberam cotação no período, a fração que já fechou. Coorte ancorada na cotação; threads ainda em aberto sub-contam a conversão até decidirem."
              valor={
                conversao_cotada_para_fechado_pct === null ? (
                  <span className="text-text-muted">—</span>
                ) : (
                  formatPercent(conversao_cotada_para_fechado_pct)
                )
              }
              valorClassName="text-aurum"
              linhaAuxiliar={
                <span>
                  {`${NUM_FMT.format(fechadas)} fechada${fechadas === 1 ? "" : "s"} / ${NUM_FMT.format(cotadas)} cotada${cotadas === 1 ? "" : "s"}`}
                  {em_aberto > 0 ? ` · ${NUM_FMT.format(em_aberto)} em aberto` : ""}
                </span>
              }
              nReferencia={cotadas}
            />
            <TileKpi
              label="Receita por thread cotada"
              tooltip="Receita bruta dos Fechado dividida pelo total de threads cotadas — o valor esperado por lead que recebeu preço. Só Fechado entra na receita."
              valor={
                r_por_thread === null ? (
                  <span className="text-text-muted">—</span>
                ) : (
                  formatBRL(r_por_thread)
                )
              }
              linhaAuxiliar={
                <span>{`${formatBRL(receita_bruta_brl)} bruto em ${NUM_FMT.format(fechadas)} fechada${fechadas === 1 ? "" : "s"}`}</span>
              }
              nReferencia={cotadas}
            />
          </div>
          {em_aberto > 0 ? (
            <p className="text-xs text-text-muted">
              {NUM_FMT.format(em_aberto)} {em_aberto === 1 ? "thread ainda" : "threads ainda"} em
              aberto — a conversão sobe conforme decidem.
            </p>
          ) : null}
        </>
      )}
    </section>
  )
}
