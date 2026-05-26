"use client"

import { useState } from "react"
import Link from "next/link"
import { ArrowUpRight, X, AlertTriangle } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import {
  formatBRL,
  formatData,
  formatDataHora,
  formatTempoRelativo,
} from "@/lib/formatters"
import type {
  ContextoModeloDia,
  ReceitaContextoResponse,
  ReceitaLinha,
} from "@/tipos/financeiro"

interface InspectorReceitaProps {
  linha: ReceitaLinha | null
  contexto: ReceitaContextoResponse | null
  loading: boolean
  error: string | null
  onClose: () => void
}

export function InspectorReceita({
  linha,
  contexto,
  loading,
  error,
  onClose,
}: InspectorReceitaProps) {
  if (!linha) return null

  return (
    <aside
      aria-label="Detalhes da receita"
      className="flex h-full w-[380px] shrink-0 flex-col border-l border-l-success-500/40 bg-card"
    >
      <header className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-xs text-text-muted">
              #{linha.numero_curto}
            </span>
            <h2 className="truncate text-sm font-semibold text-text-primary">
              {linha.cliente_nome}
            </h2>
          </div>
          <p className="mt-0.5 text-xs text-text-muted">
            {formatDataHora(linha.fechado_em)} · {linha.forma_pagamento ?? "—"}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Fechar inspector"
          className="rounded-md p-1 text-text-muted transition-colors hover:bg-muted hover:text-text-primary"
        >
          <X className="size-4" />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="m-4 rounded-md border border-danger-500/40 bg-danger-500/5 p-3 text-xs text-danger-500">
            {error}
          </div>
        )}

        <BlocoFinanceiro linha={linha} />
        <Separador />
        <BlocoModelo contexto={contexto} loading={loading} />
        <Separador />
        <BlocoCliente contexto={contexto} loading={loading} />
      </div>

      <footer className="border-t border-border p-3">
        <Link
          href={`/atendimentos?id=${linha.atendimento_id}`}
          className="flex w-full items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          Abrir atendimento
          <ArrowUpRight className="size-4" />
        </Link>
      </footer>
    </aside>
  )
}

function Separador() {
  return <div aria-hidden="true" className="h-px bg-border" />
}

function BlocoLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
      {children}
    </p>
  )
}

function BlocoFinanceiro({ linha }: { linha: ReceitaLinha }) {
  const semSnapshot = linha.percentual_repasse_snapshot === null
  return (
    <section className="px-4 py-3">
      <BlocoLabel>Financeiro</BlocoLabel>
      <dl className="space-y-1.5 text-sm">
        <Row rotulo="Bruto" valor={formatBRL(linha.valor_bruto)} destaque />
        <Row
          rotulo="Repasse %"
          valor={
            semSnapshot ? (
              <span className="inline-flex items-center gap-1 text-warn-500">
                <AlertTriangle className="size-3" /> não definido
              </span>
            ) : (
              `${linha.percentual_repasse_snapshot?.toFixed(0)}%`
            )
          }
        />
        <Row
          rotulo="Repasse calc."
          valor={semSnapshot ? "—" : formatBRL(linha.valor_repasse_calculado)}
        />
      </dl>
    </section>
  )
}

function BlocoModelo({
  contexto,
  loading,
}: {
  contexto: ReceitaContextoResponse | null
  loading: boolean
}) {
  return (
    <section className="px-4 py-3">
      <BlocoLabel>Modelo · no período</BlocoLabel>
      {loading || !contexto ? (
        <ModeloSkeleton />
      ) : (
        <>
          <p className="text-sm font-medium text-text-primary">
            {contexto.modelo.nome}
          </p>
          <Sparkline serie={contexto.modelo.serie_30d} />
          <p className="mt-1 text-[11px] text-text-muted">últimos 30 dias</p>
          <dl className="mt-3 space-y-1 text-sm">
            <Row
              rotulo="Fechamentos"
              valor={contexto.modelo.fechamentos_periodo.toString()}
            />
            <Row
              rotulo="Bruto"
              valor={formatBRL(contexto.modelo.valor_bruto_periodo)}
            />
            <Row
              rotulo="Repasse calc."
              valor={formatBRL(contexto.modelo.valor_repasse_periodo)}
            />
          </dl>
        </>
      )}
    </section>
  )
}

function BlocoCliente({
  contexto,
  loading,
}: {
  contexto: ReceitaContextoResponse | null
  loading: boolean
}) {
  return (
    <section className="px-4 py-3">
      <BlocoLabel>Cliente · cross-modelo</BlocoLabel>
      {loading || !contexto ? (
        <ClienteSkeleton />
      ) : (
        <>
          <p className="text-sm font-medium text-text-primary">
            {contexto.cliente.nome}
          </p>
          <dl className="mt-2 space-y-1 text-sm">
            <Row
              rotulo="Fechados"
              valor={`${contexto.cliente.total_fechados} de ${contexto.cliente.total_atendimentos}`}
            />
            <Row
              rotulo="Valor acumulado"
              valor={formatBRL(contexto.cliente.valor_total_brl)}
              destaque
            />
            <Row
              rotulo="Modelos distintas"
              valor={contexto.cliente.modelos_distintas.toString()}
            />
            <Row
              rotulo="Última atividade"
              valor={
                contexto.cliente.ultima_atividade_iso
                  ? `${formatData(contexto.cliente.ultima_atividade_iso)} (${formatTempoRelativo(contexto.cliente.ultima_atividade_iso)})`
                  : "—"
              }
            />
          </dl>
        </>
      )}
    </section>
  )
}

function Row({
  rotulo,
  valor,
  destaque = false,
}: {
  rotulo: string
  valor: React.ReactNode
  destaque?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs text-text-muted">{rotulo}</dt>
      <dd
        className={`tabular-nums ${destaque ? "text-text-primary font-medium" : "text-text-primary"}`}
      >
        {valor}
      </dd>
    </div>
  )
}

/**
 * Sparkline 30d em mini-barras 1D — sem biblioteca de chart.
 *
 * Usa rampa sequencial dourada (--seq-1..5 do DESIGN.md). Cada barra é altura
 * proporcional ao bruto do dia. Hover mostra dia + valor em tooltip flutuante,
 * mantido por estado (substitui o `title` HTML nativo — lento e sem estilo).
 */
function Sparkline({ serie }: { serie: ContextoModeloDia[] }) {
  const [hovered, setHovered] = useState<number | null>(null)
  const max = Math.max(...serie.map((d) => d.bruto), 1)
  const total = serie.length

  const ativo = hovered !== null ? serie[hovered] : null
  // Ancora o tooltip no centro da barra; nas bordas alinha pelo lado pra não
  // sair do container do inspector.
  const ancora =
    hovered === null || total === 0
      ? null
      : hovered <= 2
        ? { left: "0%", transform: "translateX(0)" }
        : hovered >= total - 3
          ? { right: "0%", transform: "translateX(0)" }
          : {
              left: `${((hovered + 0.5) / total) * 100}%`,
              transform: "translateX(-50%)",
            }

  return (
    <div
      className="relative mt-2"
      onMouseLeave={() => setHovered(null)}
    >
      {ativo && ancora && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute bottom-full z-10 mb-1.5 whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-[11px] shadow-[0_8px_24px_rgba(0,0,0,0.6)]"
          style={ancora}
        >
          <div className="text-text-muted">{formatData(ativo.dia)}</div>
          <div className="font-medium tabular-nums text-text-primary">
            {ativo.bruto > 0 ? formatBRL(ativo.bruto) : "sem receita"}
          </div>
        </div>
      )}
      <div
        className="flex h-10 items-end gap-px"
        role="img"
        aria-label={`Receita diária dos últimos ${total} dias`}
      >
        {serie.map((d, i) => {
          const ratio = d.bruto / max
          const alturaPct = Math.max(ratio * 100, d.bruto > 0 ? 8 : 4)
          const tonalidade =
            d.bruto === 0
              ? "var(--seq-5)"
              : ratio > 0.75
                ? "var(--seq-1)"
                : ratio > 0.5
                  ? "var(--seq-2)"
                  : ratio > 0.25
                    ? "var(--seq-3)"
                    : "var(--seq-4)"
          const ativaEssa = hovered === i
          return (
            <div
              key={d.dia}
              onMouseEnter={() => setHovered(i)}
              className="flex-1 cursor-default transition-opacity"
              style={{
                height: `${alturaPct}%`,
                backgroundColor: tonalidade,
                borderRadius: "1px",
                opacity: hovered === null || ativaEssa ? 1 : 0.55,
              }}
            />
          )
        })}
      </div>
    </div>
  )
}

function ModeloSkeleton() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-3 w-20" />
      <div className="space-y-1.5 pt-2">
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-full" />
      </div>
    </div>
  )
}

function ClienteSkeleton() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-4 w-40" />
      <div className="space-y-1.5 pt-2">
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-full" />
      </div>
    </div>
  )
}
