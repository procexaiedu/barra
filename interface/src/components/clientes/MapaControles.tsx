"use client"

import { cn } from "@/lib/utils"
import { formatBRL } from "@/lib/formatters"
import {
  LIMIAR_CALOR_MIN_PONTOS,
  OPCOES_METRICA,
  RAMPA_SEQ,
  calorHabilitado,
  limitesMetrica,
  type MapaCamada,
  type MapaMetrica,
} from "@/lib/mapaMetrica"
import { PERFIS_FISICOS, PERFIL_FISICO_LABEL } from "@/lib/perfilFisico"
import type { EstadoAtendimento, MapaClientePonto, PerfilFisico } from "@/tipos/clientes"

// Paletas categóricas reusadas pelo marker (PinElement) e pelas legendas. Hex literal
// porque PinElement não resolve CSS vars; valores espelham --state-*/--chart-* do tema.
// Vivem aqui porque é a fonte da verdade compartilhada entre marker e legenda — se
// divergem, a legenda mente.
const COR_FECHADO = "#1FB07A"
const COR_PERDIDO = "#D62828"
const COR_EM_ANDAMENTO = "#F4B81C"
export function corPorDesfecho(estado: EstadoAtendimento): string {
  if (estado === "Fechado") return COR_FECHADO
  if (estado === "Perdido") return COR_PERDIDO
  return COR_EM_ANDAMENTO
}
/** Rótulo agrupado por cor (3 baldes) para a legenda categórica. */
const ROTULO_DESFECHO_LEGENDA: ReadonlyArray<{ label: string; cor: string }> = [
  { label: "Fechado", cor: COR_FECHADO },
  { label: "Perdido", cor: COR_PERDIDO },
  { label: "Em andamento", cor: COR_EM_ANDAMENTO },
] as const

export const COR_PERFIL: Record<PerfilFisico, string> = {
  loira: "#C4A961",
  morena: "#4F8FE1",
  ruiva: "#1FB07A",
  negra: "#B66CD9",
  asiatica: "#E07A5F",
  outra: "#6FCFC9",
}
/** Sem perfil declarado: cinza neutro, distinto das categorias. */
export const COR_PERFIL_SEM = "#7A7A7A"

// Seletor + legenda do Mapa de clientes (MAPA-1, espinha dorsal). Os dois são
// exportados separados para o pai posicionar cada um (seletor na barra do header,
// legenda sobreposta ao mapa). O estado `metrica` vive no pai.

const NUM_FMT = new Intl.NumberFormat("pt-BR")

/** Modo de cor dos pontos (MAPA-3, MAPA-10). Ortogonal à métrica — métrica rege o
 *  tamanho, modo de cor rege a cor. Default "metrica" preserva o comportamento prévio.
 *  "perfil" usa só a parte DECLARADA do cliente (ADR 0006); cliente com >1 perfil
 *  recebe a cor do primeiro do array, demais aparecem no InfoWindow. */
export type ModoCor = "metrica" | "desfecho" | "perfil"

const OPCOES_MODO_COR: readonly { id: ModoCor; label: string; tooltip: string }[] = [
  {
    id: "metrica",
    label: "Por métrica",
    tooltip: "Cor segue a rampa da métrica selecionada.",
  },
  {
    id: "desfecho",
    label: "Por desfecho",
    tooltip: "Verde: Fechado · Vermelho: Perdido · Âmbar: em andamento.",
  },
  {
    id: "perfil",
    label: "Por perfil físico",
    tooltip: "Cor pelo perfil declarado (primeiro do array). Sem declaração: neutro.",
  },
] as const

export function SeletorModoCor({
  modo,
  onModoChange,
}: {
  modo: ModoCor
  onModoChange: (m: ModoCor) => void
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

const OPCOES_CAMADA: readonly { id: MapaCamada; label: string; tooltip: string }[] = [
  {
    id: "bolhas",
    label: "Pontos",
    tooltip:
      "1 marcador por cliente. Em 'Por métrica' o ponto vira bolha sqrt-escalada; em 'Por desfecho/perfil' vira pin colorido.",
  },
  {
    id: "hexbin",
    label: "Hexbin",
    tooltip:
      "Favos somando a métrica selecionada. Cor da rampa --seq-*. Em Hexbin o modo de cor (Métrica/Desfecho/Perfil) é fixo em Métrica.",
  },
  {
    id: "calor",
    label: "Calor",
    tooltip:
      "Heatmap KDE (deck.gl) ponderado pela métrica selecionada. Sem clique (campo contínuo).",
  },
] as const

/** Seletor de camada (MAPA-6/MAPA-7). Default = "bolhas" (preserva a Fase 1).
 *  `pontosCount` é usado pela guarda de honestidade do MAPA-7: abaixo do limiar
 *  o botão Calor fica desabilitado com tooltip explicativo (KDE com pouco dado
 *  hiperestima densidade nas pontas). */
export function SeletorCamada({
  camada,
  pontosCount,
  onCamadaChange,
}: {
  camada: MapaCamada
  pontosCount: number
  onCamadaChange: (c: MapaCamada) => void
}) {
  const calorOk = calorHabilitado(pontosCount)
  return (
    <div
      role="radiogroup"
      aria-label="Camada do mapa"
      className="inline-flex rounded-lg border border-border bg-card p-0.5"
    >
      {OPCOES_CAMADA.map((opcao) => {
        const ativo = opcao.id === camada
        const desabilitado = opcao.id === "calor" && !calorOk
        const title = desabilitado
          ? `Poucos pontos para um calor confiável (mínimo ${LIMIAR_CALOR_MIN_PONTOS}; agora ${pontosCount}). Use Bolhas ou Hexbin.`
          : opcao.tooltip
        return (
          <button
            key={opcao.id}
            type="button"
            role="radio"
            aria-checked={ativo}
            aria-disabled={desabilitado || undefined}
            disabled={desabilitado}
            title={title}
            onClick={() => onCamadaChange(opcao.id)}
            className={cn(
              "rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              ativo
                ? "bg-accent text-text-primary"
                : "text-text-muted hover:text-text-secondary",
              desabilitado && "cursor-not-allowed opacity-50 hover:text-text-muted",
            )}
          >
            {opcao.label}
          </button>
        )
      })}
    </div>
  )
}

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

/** Legenda categórica do modo "Por desfecho" (3 baldes de cor — espelham os pins). */
export function LegendaDesfecho() {
  return (
    <div
      aria-label="Legenda por desfecho"
      className="w-[200px] rounded-md border border-border bg-card/95 p-2 shadow-sm backdrop-blur"
    >
      <div className="mb-1 text-[11px] font-medium text-text-secondary">Desfecho</div>
      <ul className="flex flex-col gap-1 text-[11px] text-text-muted">
        {ROTULO_DESFECHO_LEGENDA.map((item) => (
          <li key={item.label} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="h-2.5 w-2.5 rounded-full border border-border"
              style={{ background: item.cor }}
            />
            <span>{item.label}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Legenda categórica do modo "Por perfil físico" — 6 perfis (ordem canônica ADR 0006)
 *  + "Sem declaração". A cor do pin segue o PRIMEIRO perfil quando o cliente tem >1. */
export function LegendaPerfil() {
  return (
    <div
      aria-label="Legenda por perfil físico"
      className="w-[200px] rounded-md border border-border bg-card/95 p-2 shadow-sm backdrop-blur"
    >
      <div className="mb-1 text-[11px] font-medium text-text-secondary">
        Perfil físico
      </div>
      <ul className="grid grid-cols-2 gap-x-2 gap-y-1 text-[11px] text-text-muted">
        {PERFIS_FISICOS.map((slug) => (
          <li key={slug} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="h-2.5 w-2.5 rounded-full border border-border"
              style={{ background: COR_PERFIL[slug] }}
            />
            <span>{PERFIL_FISICO_LABEL[slug]}</span>
          </li>
        ))}
        <li className="col-span-2 flex items-center gap-1.5">
          <span
            aria-hidden
            className="h-2.5 w-2.5 rounded-full border border-border"
            style={{ background: COR_PERFIL_SEM }}
          />
          <span>Sem declaração</span>
        </li>
      </ul>
    </div>
  )
}
