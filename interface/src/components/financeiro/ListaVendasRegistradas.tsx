"use client"

import { Fragment } from "react"
import { AlertTriangle, Ban, Banknote, KeyRound, Loader2, ShoppingBag } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { formatBRL, formatData } from "@/lib/formatters"
import type {
  DivergenciaDoFechamento,
  EstadoDeConciliacaoVenda,
  VendaRegistradaLinha,
  VendasRegistradasListaResponse,
} from "@/tipos/financeiro"

/**
 * Vendas registradas (ADR-0043) — a segunda fonte de receita, anunciada nos Grupos
 * financeiros das modelos. Lista auditável e somente leitura: a venda se corrige NO
 * GRUPO, respondendo o recibo do Agente financeiro. Um botão de editar aqui criaria
 * uma segunda autoridade sobre o mesmo número, sem rastro no grupo que a anunciou.
 *
 * Duas flags, deliberadamente separadas porque são de coisas diferentes:
 * — chave Pix desconhecida é da VENDA (que Pix a fechou);
 * — divergência de fechamento é da MODELO (a conferência vendido × comprovado), e
 *   por isso vive num bloco próprio acima da lista, fora do recorte de período.
 */

interface Props {
  lista: VendasRegistradasListaResponse | null
  loading: boolean
  incluirAnuladas: boolean
  onIncluirAnuladas: (v: boolean) => void
  onCarregarMais?: () => void
  carregandoMais?: boolean
}

interface GrupoDia {
  dia: string
  rotulo: string
  items: VendaRegistradaLinha[]
  total: number
}

const CONCILIACAO: Record<
  EstadoDeConciliacaoVenda,
  { label: string; bg: string; text: string }
> = {
  conciliada: {
    label: "conciliada",
    bg: "bg-[color:var(--success-500)]/12",
    text: "text-success-500",
  },
  em_especie: {
    label: "em espécie",
    bg: "bg-[color:var(--info-500)]/12",
    text: "text-info-500",
  },
  aguardando_comprovante: {
    label: "falta comprovante",
    bg: "bg-[color:var(--warn-500)]/12",
    text: "text-warn-500",
  },
  aguardando_forma: {
    label: "falta a forma",
    bg: "bg-[color:var(--warn-500)]/12",
    text: "text-warn-500",
  },
  anulada: { label: "anulada", bg: "bg-muted", text: "text-text-muted" },
}

const DIVERGENCIA_TEXTO: Record<DivergenciaDoFechamento["tipo"], string> = {
  comprovante_sem_par: "comprovante que não fechou venda nenhuma",
  credito_da_modelo: "sobra de comprovante sem venda pra fechar",
  pix_sem_venda_em_pix: "Pix que nenhuma venda em pix explica",
  venda_comprovada_a_menor: "venda dada como paga com Pix menor que ela",
}

function agruparPorDia(items: VendaRegistradaLinha[]): GrupoDia[] {
  const grupos: GrupoDia[] = []
  let atual: GrupoDia | null = null
  for (const v of items) {
    if (!atual || atual.dia !== v.data) {
      atual = { dia: v.data, rotulo: formatData(v.data), items: [], total: 0 }
      grupos.push(atual)
    }
    atual.items.push(v)
    // Venda anulada não soma: ela está na lista como rastro, não como dinheiro.
    if (!v.anulada_em) atual.total += v.valor
  }
  return grupos
}

export function ListaVendasRegistradas({
  lista,
  loading,
  incluirAnuladas,
  onIncluirAnuladas,
  onCarregarMais,
  carregandoMais = false,
}: Props) {
  const items = lista?.items ?? []
  const grupos = items.length ? agruparPorDia(items) : []
  const total = items.reduce((acc, v) => acc + (v.anulada_em ? 0 : v.valor), 0)
  const vivas = items.filter((v) => !v.anulada_em).length

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-text-muted">
          Vendas anunciadas nos Grupos financeiros. Só leitura — a correção é no grupo.
        </p>
        <label className="flex cursor-pointer items-center gap-2 text-[12px] text-text-secondary">
          <input
            type="checkbox"
            checked={incluirAnuladas}
            onChange={(e) => onIncluirAnuladas(e.target.checked)}
            className="size-3.5 accent-[color:var(--gold-500)]"
          />
          Mostrar anuladas
        </label>
      </div>

      {lista && lista.divergencias.length > 0 && (
        <BlocoDivergencias divergencias={lista.divergencias} />
      )}

      {loading && !lista ? (
        <Esqueleto />
      ) : items.length === 0 ? (
        <Vazio />
      ) : (
        <div
          role="table"
          aria-label="Vendas registradas agrupadas por dia"
          className="overflow-hidden rounded-lg bg-card ring-1 ring-border-subtle shadow-elev-1 rise-in"
        >
          {grupos.map((g) => (
            <Fragment key={g.dia}>
              <DiaBanner grupo={g} />
              {g.items.map((v) => (
                <Linha key={v.id} venda={v} />
              ))}
            </Fragment>
          ))}
          <Rodape
            n={vivas}
            total={total}
            truncado={Boolean(lista?.next_cursor)}
            onCarregarMais={onCarregarMais}
            carregandoMais={carregandoMais}
          />
        </div>
      )}
    </div>
  )
}

function BlocoDivergencias({ divergencias }: { divergencias: DivergenciaDoFechamento[] }) {
  return (
    <div
      role="status"
      className="rounded-lg border border-warn-500/40 bg-[color:var(--warn-500)]/8 px-4 py-3"
    >
      <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-warn-500">
        <AlertTriangle className="size-3.5" aria-hidden />
        Divergências de fechamento
      </p>
      <p className="mt-1 text-[12px] text-text-muted">
        Dinheiro que a conferência da modelo não explica. Não trava nada: no grupo virou
        pergunta, aqui é sinal. Saldo corrente — independe do período filtrado.
      </p>
      <ul className="mt-2 flex flex-col gap-1">
        {divergencias.map((d) => (
          <li
            key={`${d.modelo_id}-${d.tipo}-${d.valor}`}
            className="flex flex-wrap items-baseline gap-x-2 text-[13px] text-text-primary"
          >
            <span className="font-medium">{d.modelo_nome}</span>
            <span className="font-mono tabular-nums text-warn-500">{formatBRL(d.valor)}</span>
            <span className="text-text-muted">{DIVERGENCIA_TEXTO[d.tipo]}</span>
            {d.data && (
              <span className="font-mono text-[11px] text-text-muted">{formatData(d.data)}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function DiaBanner({ grupo }: { grupo: GrupoDia }) {
  const plural = grupo.items.length === 1 ? "venda" : "vendas"
  return (
    <div
      role="separator"
      aria-label={`${grupo.rotulo} — ${grupo.items.length} ${plural}`}
      className="flex items-center justify-between gap-4 border-b border-border bg-muted/40 px-4 py-2"
    >
      <span className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-text-primary">
        <span className="h-2.5 w-0.5 rounded-full bg-gold-500" aria-hidden />
        {grupo.rotulo}
        <span className="font-normal normal-case tracking-normal text-text-muted">
          {grupo.items.length} {plural}
        </span>
      </span>
      <span className="font-mono text-[11px] font-medium tabular-nums text-text-primary">
        {formatBRL(grupo.total)}
      </span>
    </div>
  )
}

function Linha({ venda }: { venda: VendaRegistradaLinha }) {
  const estado = CONCILIACAO[venda.conciliacao]
  const anulada = Boolean(venda.anulada_em)
  return (
    <div
      role="row"
      className={`grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 border-b border-border/60 px-4 py-2.5 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_minmax(9rem,10rem)_8rem] ${
        anulada ? "opacity-60" : ""
      }`}
    >
      <div className="min-w-0">
        <p
          className={`truncate text-sm font-medium text-text-primary ${
            anulada ? "line-through" : ""
          }`}
        >
          {venda.cliente_nome ?? "cliente não dito"}
        </p>
        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
          <span className="truncate">{venda.modelo_nome}</span>
          {venda.duracao_minutos != null && <span>{venda.duracao_minutos} min</span>}
          {venda.local_atendimento && <span className="truncate">{venda.local_atendimento}</span>}
          {anulada && (
            <span className="inline-flex items-center gap-0.5">
              <Ban className="size-3" aria-hidden />
              apagada no grupo
            </span>
          )}
        </div>
      </div>

      <div className="hidden items-center gap-1.5 sm:flex">
        <span
          className={`inline-flex items-center rounded-full px-1.5 py-px text-[10px] font-medium uppercase tracking-wider ${estado.bg} ${estado.text}`}
        >
          {estado.label}
        </span>
        {venda.forma_pagamento === "dinheiro" && (
          <Banknote className="size-3.5 text-info-500" aria-label="em espécie com a modelo" />
        )}
        {venda.chave_pix_desconhecida && <ChaveDesconhecida chave={venda.chave_pix_destino} />}
      </div>

      <span className="text-right font-mono text-sm font-medium tabular-nums text-text-primary">
        {formatBRL(venda.valor)}
      </span>
    </div>
  )
}

function ChaveDesconhecida({ chave }: { chave: string | null }) {
  return (
    <Tooltip>
      <TooltipTrigger type="button" tabIndex={-1} aria-label="Chave Pix fora da lista da casa">
        <KeyRound className="size-3.5 text-warn-500" aria-hidden />
      </TooltipTrigger>
      <TooltipContent className="border border-border bg-card text-text-primary">
        <div className="flex flex-col gap-0.5">
          <span className="text-[10.5px] font-semibold uppercase tracking-wide text-warn-500">
            Chave fora da lista da casa
          </span>
          {/* A chave vai a vista: quem confere precisa comparar com a tela do banco. */}
          <span className="font-mono text-[11px]">{chave ?? "destino não lido"}</span>
        </div>
      </TooltipContent>
    </Tooltip>
  )
}

function Esqueleto() {
  return (
    <div
      aria-busy="true"
      className="overflow-hidden rounded-lg bg-card ring-1 ring-border-subtle shadow-elev-1"
    >
      <Skeleton className="h-9 w-full rounded-none" />
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 border-b border-border/60 px-4 py-2.5 last:border-b-0"
        >
          <Skeleton className="h-4 w-40 rounded-md" />
          <Skeleton className="ml-auto h-4 w-20 rounded-md" />
        </div>
      ))}
    </div>
  )
}

function Vazio() {
  return (
    <Card>
      <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
        <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
          <ShoppingBag size={22} strokeWidth={1.75} className="text-text-muted" />
        </div>
        <div>
          <p className="text-sm font-medium text-text-primary">
            Nenhuma venda registrada no período.
          </p>
          <p className="mt-1 text-[13px] text-text-muted">
            As vendas aparecem aqui conforme os Grupos financeiros as anunciam.
          </p>
        </div>
      </div>
    </Card>
  )
}

function Rodape({
  n,
  total,
  truncado,
  onCarregarMais,
  carregandoMais,
}: {
  n: number
  total: number
  truncado: boolean
  onCarregarMais?: () => void
  carregandoMais?: boolean
}) {
  const plural = n === 1 ? "venda" : "vendas"
  return (
    <div className="border-t border-border bg-muted/30">
      <div className="flex items-center justify-between gap-4 px-4 py-2.5">
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-text-muted">
          {truncado ? `Mostrando ${n} ${plural}` : `Total · ${n} ${plural}`}
        </span>
        <span className="font-mono text-xs font-semibold tabular-nums text-text-brand">
          {formatBRL(total)}
        </span>
      </div>
      {truncado && onCarregarMais && (
        <div className="border-t border-border/60 bg-muted/20 px-4 py-2 text-center">
          <button
            type="button"
            onClick={onCarregarMais}
            disabled={carregandoMais}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-[11px] font-medium text-text-secondary transition-colors hover:bg-muted hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
          >
            {carregandoMais ? (
              <>
                <Loader2 className="size-3 animate-spin" />
                Carregando…
              </>
            ) : (
              "Carregar mais"
            )}
          </button>
        </div>
      )}
    </div>
  )
}
