"use client"

import { cn } from "@/lib/utils"
import { formatBRL } from "@/lib/formatters"
import {
  OPCOES_METRICA,
  RAMPA_SEQ,
  limitesMetrica,
  type MapaMetrica,
} from "@/lib/mapaMetrica"
import type { RecenciaMapa } from "@/hooks/useClientesMapa"
import type { MapaClientePonto } from "@/tipos/clientes"

// MAPA-11: teto fixo do slider de R$. Decisão arbitrária deste PR (cobre a faixa P0 de
// programas — pernoite incluso); ajustável depois sem migrar dado.
const VALOR_MAX_PADRAO = 3000
const VALOR_PASSO = 50

// Seletor + legenda do Mapa de clientes (MAPA-1, espinha dorsal). Os dois são
// exportados separados para o pai posicionar cada um (seletor na barra do header,
// legenda sobreposta ao mapa). O estado `metrica` vive no pai.

const NUM_FMT = new Intl.NumberFormat("pt-BR")

export function SeletorMetrica({
  metrica,
  onMetricaChange,
}: {
  metrica: MapaMetrica
  onMetricaChange: (m: MapaMetrica) => void
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Métrica do mapa"
      className="inline-flex rounded-lg border border-border bg-card p-0.5"
    >
      {OPCOES_METRICA.map((opcao) => {
        const ativo = opcao.id === metrica
        return (
          <button
            key={opcao.id}
            type="button"
            role="radio"
            aria-checked={ativo}
            title={opcao.tooltip}
            onClick={() => onMetricaChange(opcao.id)}
            className={cn(
              "rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              ativo
                ? "bg-accent text-text-primary"
                : "text-text-muted hover:text-text-secondary",
            )}
          >
            {opcao.label}
          </button>
        )
      })}
    </div>
  )
}

export function LegendaEscala({
  metrica,
  pontos,
}: {
  metrica: MapaMetrica
  pontos: MapaClientePonto[]
}) {
  const limites = limitesMetrica(pontos, metrica)
  const rotuloMetrica =
    metrica === "valor"
      ? "R$ fechado"
      : metrica === "atendimentos"
        ? "Atendimentos"
        : "Clientes"
  const mutedRampa = metrica === "clientes"
  // Em "clientes" cada ponto vale 1 — min/max não informa; mostra placeholder
  // explicativo (alinhado à nota do roadmap sobre o caso degenerado).
  const conteudoLimites = mutedRampa ? (
    <span
      className="text-[11px] text-text-muted"
      title="Nº de clientes só faz pleno sentido nas camadas de agregação (Hexbin/Calor)."
    >
      1 cliente por ponto
    </span>
  ) : limites ? (
    <div className="flex items-center justify-between text-[11px] tabular-nums text-text-muted">
      <span>{formatarValor(metrica, limites.min)}</span>
      <span>{formatarValor(metrica, limites.max)}</span>
    </div>
  ) : (
    <span className="text-[11px] text-text-muted">sem pontos</span>
  )

  return (
    <div
      aria-label={`Legenda de escala: ${rotuloMetrica}`}
      className="w-[200px] rounded-md border border-border bg-card/95 p-2 shadow-sm backdrop-blur"
    >
      <div className="mb-1 text-[11px] font-medium text-text-secondary">
        {rotuloMetrica}
      </div>
      <div
        aria-hidden
        className={cn(
          "h-2 w-full rounded-sm transition-opacity",
          mutedRampa && "opacity-40",
        )}
        style={{
          background: `linear-gradient(to right, ${RAMPA_SEQ.join(", ")})`,
        }}
      />
      <div className="mt-1">{conteudoLimites}</div>
    </div>
  )
}

function formatarValor(metrica: MapaMetrica, n: number): string {
  if (metrica === "valor") return formatBRL(n)
  return NUM_FMT.format(n)
}

// MAPA-11: faixa de R$ (min/max) sobre o `valor_total` agregado do cliente. Dois <input
// type="range"> empilhados — controle nativo, sem dependência nova. Min/max do slider são
// fixos (0 → VALOR_MAX_PADRAO); não derivam dos pontos para não encolher quando o filtro
// reduz o conjunto (UX de loop).
export function FiltroFaixaValor({
  valorMin,
  valorMax,
  onChange,
}: {
  valorMin: number | null
  valorMax: number | null
  onChange: (valorMin: number | null, valorMax: number | null) => void
}) {
  const minAtual = valorMin ?? 0
  const maxAtual = valorMax ?? VALOR_MAX_PADRAO
  const ativo = valorMin !== null || valorMax !== null
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-[11px] font-medium text-text-muted">
        <span>Faixa de R$</span>
        {ativo && (
          <button
            type="button"
            onClick={() => onChange(null, null)}
            className="text-[10px] uppercase tracking-wide text-text-muted hover:text-text-secondary"
          >
            Limpar
          </button>
        )}
      </div>
      <div className="flex flex-col gap-1">
        <input
          aria-label="Valor mínimo"
          type="range"
          min={0}
          max={VALOR_MAX_PADRAO}
          step={VALOR_PASSO}
          value={minAtual}
          onChange={(e) => {
            const novoMin = Number(e.target.value)
            // Não passa do max atual.
            const novoMax = novoMin > maxAtual ? novoMin : valorMax
            onChange(novoMin === 0 ? null : novoMin, novoMax)
          }}
          className="w-full accent-primary"
        />
        <input
          aria-label="Valor máximo"
          type="range"
          min={0}
          max={VALOR_MAX_PADRAO}
          step={VALOR_PASSO}
          value={maxAtual}
          onChange={(e) => {
            const novoMax = Number(e.target.value)
            const novoMin = novoMax < minAtual ? novoMax : valorMin
            onChange(novoMin, novoMax === VALOR_MAX_PADRAO ? null : novoMax)
          }}
          className="w-full accent-primary"
        />
      </div>
      <div className="flex items-center justify-between text-[11px] tabular-nums text-text-secondary">
        <span>{formatBRL(minAtual)}</span>
        <span>{formatBRL(maxAtual)}{valorMax === null ? "+" : ""}</span>
      </div>
    </div>
  )
}

// MAPA-11: toggle de recência. 3 estados — Ativos (≤ N dias), Dormentes (> N dias), Todos.
// N (limiar) chega como prop só para o tooltip; quem aplica é o backend via `ativo_em_dias`.
const OPCOES_RECENCIA: readonly { id: RecenciaMapa; label: string }[] = [
  { id: "ativo", label: "Ativos" },
  { id: "dormente", label: "Dormentes" },
  { id: "todos", label: "Todos" },
] as const

export function ToggleRecencia({
  recencia,
  ativoEmDias,
  onChange,
}: {
  recencia: RecenciaMapa
  ativoEmDias: number
  onChange: (r: RecenciaMapa) => void
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span
        className="text-[11px] font-medium text-text-muted"
        title={`Ativos: última visita ≤ ${ativoEmDias} dias. Dormentes: > ${ativoEmDias} dias.`}
      >
        Recência
      </span>
      <div
        role="radiogroup"
        aria-label="Recência da última visita"
        className="inline-flex rounded-lg border border-border bg-card p-0.5"
      >
        {OPCOES_RECENCIA.map((opcao) => {
          const ativo = opcao.id === recencia
          return (
            <button
              key={opcao.id}
              type="button"
              role="radio"
              aria-checked={ativo}
              onClick={() => onChange(opcao.id)}
              className={cn(
                "rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                ativo
                  ? "bg-accent text-text-primary"
                  : "text-text-muted hover:text-text-secondary",
              )}
            >
              {opcao.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
