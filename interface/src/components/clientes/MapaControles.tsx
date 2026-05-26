"use client"

import { cn } from "@/lib/utils"
import { formatBRL } from "@/lib/formatters"
import {
  OPCOES_METRICA,
  RAMPA_SEQ,
  limitesMetrica,
  type MapaMetrica,
} from "@/lib/mapaMetrica"
import { PERFIS_FISICOS, PERFIL_FISICO_LABEL } from "@/lib/perfilFisico"
import type { MapaClientePonto, PerfilFisico } from "@/tipos/clientes"

/** Modo de cor dos pontos (MAPA-10). Ortogonal ao seletor de métrica (que controla
 *  tamanho/intensidade). "perfil" usa a parte DECLARADA do perfil físico (ADR 0006);
 *  pintura de perfil calculado é proibida — é cross-modelo e fura o isolamento por par. */
export type MapaModoCor = "padrao" | "perfil"

/** Paleta categórica para os perfis físicos. Reusa os tokens --chart-* já existentes
 *  no globals.css (light + dark) para acompanhar o tema, em vez de definir hex novos. */
export const COR_PERFIL: Record<PerfilFisico, string> = {
  loira: "var(--chart-1)",
  morena: "var(--chart-5)",
  ruiva: "var(--chart-7)",
  negra: "var(--chart-4)",
  asiatica: "var(--chart-6)",
  outra: "var(--chart-2)",
}

/** Cor neutra para cliente sem perfil declarado (perfis: []). */
export const COR_PERFIL_SEM_DECLARACAO = "var(--text-muted)"

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

const OPCOES_MODO_COR: { id: MapaModoCor; label: string; tooltip: string }[] = [
  {
    id: "padrao",
    label: "Padrão",
    tooltip: "Pin padrão sem cor categórica.",
  },
  {
    id: "perfil",
    label: "Por perfil físico",
    tooltip:
      "Cor pelo perfil físico declarado do cliente (ADR 0006). Clientes com mais de um perfil pegam o primeiro.",
  },
]

export function SeletorModoCor({
  modo,
  onModoChange,
}: {
  modo: MapaModoCor
  onModoChange: (m: MapaModoCor) => void
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Modo de cor do mapa"
      className="inline-flex rounded-lg border border-border bg-card p-0.5"
    >
      {OPCOES_MODO_COR.map((opcao) => {
        const ativo = opcao.id === modo
        return (
          <button
            key={opcao.id}
            type="button"
            role="radio"
            aria-checked={ativo}
            title={opcao.tooltip}
            onClick={() => onModoChange(opcao.id)}
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

/** Legenda da paleta categórica de perfis. Mostra só os perfis presentes nos pontos
 *  atuais (mais "sem declaração" se houver), para não poluir com baldes vazios. */
export function LegendaPerfis({ pontos }: { pontos: MapaClientePonto[] }) {
  // Mantém a ordem canônica de PERFIS_FISICOS (ADR 0006); inclui só os presentes.
  const presentes = new Set<PerfilFisico>()
  let temSemDeclaracao = false
  for (const ponto of pontos) {
    if (ponto.perfis.length === 0) temSemDeclaracao = true
    else for (const perfil of ponto.perfis) presentes.add(perfil)
  }
  const itens = PERFIS_FISICOS.filter((p) => presentes.has(p))

  return (
    <div
      aria-label="Legenda de perfis físicos"
      className="w-[200px] rounded-md border border-border bg-card/95 p-2 shadow-sm backdrop-blur"
    >
      <div className="mb-1.5 text-[11px] font-medium text-text-secondary">
        Perfil físico (declarado)
      </div>
      {itens.length === 0 && !temSemDeclaracao ? (
        <span className="text-[11px] text-text-muted">sem pontos</span>
      ) : (
        <ul className="space-y-1">
          {itens.map((perfil) => (
            <li key={perfil} className="flex items-center gap-2 text-[11px] text-text-secondary">
              <span
                aria-hidden
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: COR_PERFIL[perfil] }}
              />
              {PERFIL_FISICO_LABEL[perfil]}
            </li>
          ))}
          {temSemDeclaracao && (
            <li className="flex items-center gap-2 text-[11px] text-text-muted">
              <span
                aria-hidden
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: COR_PERFIL_SEM_DECLARACAO }}
              />
              Sem declaração
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
