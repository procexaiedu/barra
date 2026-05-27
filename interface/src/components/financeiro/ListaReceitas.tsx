"use client"

import { Fragment, useEffect, useRef } from "react"
import { ChevronRight, AlertTriangle } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import { formatBRL, formatData, formatHorario } from "@/lib/formatters"
import type {
  FormaPagamentoReceita,
  ReceitaLinha,
  ReceitasListaResponse,
} from "@/tipos/financeiro"

interface ListaReceitasProps {
  lista: ReceitasListaResponse | null
  loading: boolean
  selectedId: string | null
  onSelect: (linha: ReceitaLinha | null) => void
}

interface GrupoDia {
  dia: string // YYYY-MM-DD em BRT (chave estável)
  rotulo: string // "13 de mai. de 2026"
  items: ReceitaLinha[]
  bruto: number
  repasse: number
}

// Extrai a data BRT (YYYY-MM-DD) de um ISO timestamp. Usa `sv-SE` porque
// produz o mesmo formato ISO independente do locale do navegador.
function diaBRT(iso: string) {
  return new Date(iso).toLocaleDateString("sv-SE", {
    timeZone: "America/Sao_Paulo",
  })
}

function agruparPorDia(items: ReceitaLinha[]): GrupoDia[] {
  const grupos: GrupoDia[] = []
  let atual: GrupoDia | null = null
  for (const r of items) {
    const dia = diaBRT(r.fechado_em)
    if (!atual || atual.dia !== dia) {
      atual = {
        dia,
        rotulo: formatData(r.fechado_em),
        items: [],
        bruto: 0,
        repasse: 0,
      }
      grupos.push(atual)
    }
    atual.items.push(r)
    atual.bruto += r.valor_bruto
    atual.repasse += r.valor_repasse_calculado
  }
  return grupos
}

export function ListaReceitas({
  lista,
  loading,
  selectedId,
  onSelect,
}: ListaReceitasProps) {
  const selectedRowRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (selectedRowRef.current) {
      selectedRowRef.current.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      })
    }
  }, [selectedId])

  // React Compiler memoiza automaticamente — não usamos useMemo aqui porque
  // o Compiler infere dependências mais coerentes (vê `lista` como um todo).
  const items = lista?.items ?? []
  const grupos = items.length ? agruparPorDia(items) : []
  const maxBruto = items.length
    ? Math.max(...items.map((r) => r.valor_bruto), 1)
    : 1
  const totais = items.reduce(
    (acc, r) => ({
      bruto: acc.bruto + r.valor_bruto,
      repasse: acc.repasse + r.valor_repasse_calculado,
      n: acc.n + 1,
    }),
    { bruto: 0, repasse: 0, n: 0 },
  )

  if (loading && !lista) return <Skeleton className="h-64" />
  if (!lista || lista.items.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-text-muted">
        Nenhuma receita no período.
      </div>
    )
  }

  return (
    <div
      role="listbox"
      aria-label="Receitas agrupadas por dia"
      aria-multiselectable="false"
      className="overflow-hidden rounded-lg border border-border bg-card"
    >
      {grupos.map((g) => (
        <Fragment key={g.dia}>
          <DiaBanner grupo={g} />
          <div role="group" aria-label={`Receitas de ${g.rotulo}`}>
            {g.items.map((r) => {
              const selected = r.atendimento_id === selectedId
              return (
                <LinhaReceita
                  key={r.atendimento_id}
                  linha={r}
                  selected={selected}
                  refEl={selected ? selectedRowRef : undefined}
                  maxBruto={maxBruto}
                  onClick={() => onSelect(selected ? null : r)}
                />
              )
            })}
          </div>
        </Fragment>
      ))}
      <FooterTotal
        n={totais.n}
        bruto={totais.bruto}
        repasse={totais.repasse}
        truncado={Boolean(lista.next_cursor)}
      />
    </div>
  )
}

function DiaBanner({ grupo }: { grupo: GrupoDia }) {
  const plural = grupo.items.length === 1 ? "fechamento" : "fechamentos"
  return (
    <div
      role="separator"
      aria-label={`${grupo.rotulo} — ${grupo.items.length} ${plural}`}
      className="flex items-center justify-between gap-4 border-b border-border bg-muted/40 px-4 py-2"
    >
      <div className="flex items-baseline gap-3">
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-text-brand">
          {grupo.rotulo}
        </span>
        <span className="text-[11px] text-text-muted">
          {grupo.items.length} {plural}
        </span>
      </div>
      <div className="flex items-baseline gap-3 text-[11px] tabular-nums">
        <span className="font-medium text-text-primary">
          {formatBRL(grupo.bruto)}
        </span>
        <span className="text-text-muted">
          {formatBRL(grupo.repasse)} repasse
        </span>
      </div>
    </div>
  )
}

function LinhaReceita({
  linha,
  selected,
  refEl,
  maxBruto,
  onClick,
}: {
  linha: ReceitaLinha
  selected: boolean
  refEl?: React.RefObject<HTMLDivElement | null>
  maxBruto: number
  onClick: () => void
}) {
  const semSnapshot = linha.percentual_repasse_snapshot === null
  const magnitude = Math.min(1, linha.valor_bruto / maxBruto)
  const hora = formatHorario(linha.fechado_em)

  return (
    <div
      ref={refEl}
      role="option"
      aria-selected={selected}
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onClick()
        }
      }}
      className={`group grid cursor-pointer grid-cols-[3.5rem_minmax(0,1fr)_8rem_minmax(8rem,9rem)] items-center gap-x-4 border-b border-border/60 px-4 py-2.5 transition-colors last:border-b-0 ${
        selected
          ? "bg-[color:var(--gold-500)]/10"
          : "hover:bg-muted/30"
      }`}
    >
      {/* col 1: hora + chevron quando selecionado, # logo abaixo */}
      <div className="flex flex-col gap-0.5">
        <div className="flex items-center gap-1">
          <ChevronRight
            aria-hidden="true"
            className={`size-3 transition-opacity ${
              selected ? "opacity-100 text-text-brand" : "opacity-0"
            }`}
          />
          <span className="font-mono text-[11px] tabular-nums text-text-primary">
            {hora}
          </span>
        </div>
        <span className="pl-4 font-mono text-[10px] text-text-muted">
          #{linha.numero_curto}
        </span>
      </div>

      {/* col 2: cliente (primário) e modelo·forma·% (secundário) */}
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-text-primary">
          {linha.cliente_nome}
        </p>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-text-muted">
          <span className="truncate">{linha.modelo_nome}</span>
          <FormaChip forma={linha.forma_pagamento} />
          <RepasseBadge
            percentual={linha.percentual_repasse_snapshot}
            semSnapshot={semSnapshot}
          />
        </div>
      </div>

      {/* col 3: magnitude bar */}
      <div className="hidden sm:block">
        <MagnitudeBar pct={magnitude} />
      </div>

      {/* col 4: valor bruto + repasse */}
      <div className="flex flex-col items-end gap-0.5">
        <span className="text-sm font-medium tabular-nums text-text-primary">
          {formatBRL(linha.valor_bruto)}
        </span>
        <span className="text-[11px] tabular-nums text-text-muted">
          {semSnapshot ? "— repasse" : `${formatBRL(linha.valor_repasse_calculado)} rep.`}
        </span>
      </div>
    </div>
  )
}

function MagnitudeBar({ pct }: { pct: number }) {
  // 2px de altura, dourado sólido. Sem track de fundo: o bar é apenas o sinal.
  // A largura é proporcional ao bruto vs o maior bruto da página visível —
  // isso transforma a coluna num "termômetro" relativo do recorte atual.
  const width = `${Math.max(pct * 100, 2)}%`
  return (
    <div
      aria-hidden="true"
      className="relative h-[3px] w-full overflow-hidden rounded-full bg-border-subtle/40"
    >
      <div
        className="absolute inset-y-0 left-0 rounded-full bg-[color:var(--gold-500)]"
        style={{ width }}
      />
    </div>
  )
}

const FORMA_STYLE: Record<
  FormaPagamentoReceita,
  { bg: string; text: string; label: string }
> = {
  pix: {
    bg: "bg-[color:var(--success-500)]/12",
    text: "text-success-500",
    label: "pix",
  },
  dinheiro: {
    bg: "bg-[color:var(--info-500)]/12",
    text: "text-info-500",
    label: "dinheiro",
  },
  cartao: {
    bg: "bg-[color:var(--chart-4)]/14",
    text: "text-[color:var(--chart-4)]",
    label: "cartão",
  },
  outro: {
    bg: "bg-muted",
    text: "text-text-muted",
    label: "outro",
  },
}

function FormaChip({ forma }: { forma: FormaPagamentoReceita | null }) {
  if (!forma) {
    return <span className="text-text-disabled">—</span>
  }
  const style = FORMA_STYLE[forma]
  return (
    <span
      className={`inline-flex items-center rounded-full px-1.5 py-px text-[10px] font-medium uppercase tracking-wider ${style.bg} ${style.text}`}
    >
      {style.label}
    </span>
  )
}

function RepasseBadge({
  percentual,
  semSnapshot,
}: {
  percentual: number | null
  semSnapshot: boolean
}) {
  if (semSnapshot) {
    return (
      <span className="inline-flex items-center gap-0.5 text-warn-500">
        <AlertTriangle className="size-3" aria-hidden="true" />
        <span>sem %</span>
      </span>
    )
  }
  return (
    <span className="tabular-nums text-text-muted">
      {percentual?.toFixed(0)}%
    </span>
  )
}

function FooterTotal({
  n,
  bruto,
  repasse,
  truncado,
}: {
  n: number
  bruto: number
  repasse: number
  truncado: boolean
}) {
  const plural = n === 1 ? "linha" : "linhas"
  return (
    <div className="border-t border-border bg-muted/30">
      <div className="flex items-center justify-between gap-4 px-4 py-2.5">
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-text-muted">
          Total · {n} {plural}
        </span>
        <div className="flex items-baseline gap-3 text-xs tabular-nums">
          <span className="font-semibold text-text-primary">
            {formatBRL(bruto)}
          </span>
          <span className="text-text-muted">
            {formatBRL(repasse)} repasse
          </span>
        </div>
      </div>
      {truncado && (
        <div className="border-t border-border/60 bg-muted/20 px-4 py-1.5 text-center text-[11px] text-text-muted">
          Mais resultados disponíveis — refine o período ou modelo para ver tudo.
        </div>
      )}
    </div>
  )
}
