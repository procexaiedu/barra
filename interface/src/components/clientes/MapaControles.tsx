"use client"

import { Check, ChevronDown } from "lucide-react"
import { useState } from "react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
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
import { MOTIVO_PERDA_LABEL, MOTIVOS_PERDA } from "@/lib/motivoPerda"
import { PERFIS_FISICOS, PERFIL_FISICO_LABEL } from "@/lib/perfilFisico"
import type {
  EstadoAtendimento,
  MapaClientePonto,
  MotivoPerda,
  PerfilFisico,
} from "@/tipos/clientes"

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

/** Cor de "oportunidade" da lente "Demanda não atendida" (MAPA-9). Magenta/violeta
 *  saturado fora das paletas em uso (COR_FECHADO/PERDIDO/EM_ANDAMENTO/COR_PERFIL.*)
 *  para o halo não colidir com nenhum modo de cor. Hex literal aqui pelo mesmo motivo
 *  do MAPA-3 (PinElement/SVG inline não resolvem CSS vars). */
export const COR_OPORTUNIDADE = "#9B5DE5"

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

/** Filtro de desfecho (MAPA-8). Reduz os pontos do mapa — distinto do "modo de cor
 *  por desfecho" (cosmético). Default "todos" preserva o comportamento atual. */
export type FiltroDesfecho = "todos" | "Fechado" | "Perdido" | "andamento"

const OPCOES_DESFECHO: readonly { id: FiltroDesfecho; label: string; tooltip: string }[] = [
  { id: "todos", label: "Todos", tooltip: "Sem filtro de desfecho." },
  {
    id: "Fechado",
    label: "Fechado",
    tooltip: "Só pontos cujo externo mais recente foi fechado.",
  },
  {
    id: "Perdido",
    label: "Perdido",
    tooltip: "Só pontos cujo externo mais recente foi perdido.",
  },
  {
    id: "andamento",
    label: "Em andamento",
    tooltip: "Só pontos cujo externo mais recente ainda não terminou.",
  },
] as const

export function SeletorDesfecho({
  desfecho,
  onDesfechoChange,
  bloqueada,
}: {
  desfecho: FiltroDesfecho
  onDesfechoChange: (d: FiltroDesfecho) => void
  /** MAPA-9: a lente "Demanda não atendida" sobrescreve estes filtros; quando ON,
   *  o seletor fica desabilitado (mas o estado prévio é preservado no pai). */
  bloqueada?: boolean
}) {
  const tooltipBloqueada =
    "Lente 'Demanda não atendida' sobrescreve estes filtros — desligue-a para editá-los."
  return (
    <div
      role="radiogroup"
      aria-label="Filtro por desfecho"
      aria-disabled={bloqueada || undefined}
      className="inline-flex rounded-lg border border-border bg-card p-0.5"
    >
      {OPCOES_DESFECHO.map((opcao) => {
        const ativo = opcao.id === desfecho
        return (
          <button
            key={opcao.id}
            type="button"
            role="radio"
            aria-checked={ativo}
            aria-disabled={bloqueada || undefined}
            disabled={bloqueada}
            title={bloqueada ? tooltipBloqueada : opcao.tooltip}
            onClick={() => onDesfechoChange(opcao.id)}
            className={cn(
              "rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              ativo
                ? "bg-accent text-text-primary"
                : "text-text-muted hover:text-text-secondary",
              bloqueada && "cursor-not-allowed opacity-50 hover:text-text-muted",
            )}
          >
            {opcao.label}
          </button>
        )
      })}
    </div>
  )
}

/** Filtro multi-select de motivos de perda (MAPA-8). Só faz sentido quando o
 *  desfecho selecionado é "Perdido"; fora disso o trigger fica desabilitado com
 *  tooltip — o estado `motivosPerda` é zerado no pai ao trocar de desfecho para
 *  evitar querystring órfã, então `desabilitado` aqui é defesa em profundidade. */
export function FiltroMotivoPerda({
  motivosPerda,
  desfecho,
  onMotivosPerdaChange,
  bloqueada,
}: {
  motivosPerda: MotivoPerda[]
  desfecho: FiltroDesfecho
  onMotivosPerdaChange: (m: MotivoPerda[]) => void
  /** MAPA-9: a lente "Demanda não atendida" sobrescreve este filtro; quando ON,
   *  o dropdown fica desabilitado independentemente de `desfecho`. */
  bloqueada?: boolean
}) {
  const [open, setOpen] = useState(false)
  const desabilitado = bloqueada || desfecho !== "Perdido"
  const selecionados = new Set(motivosPerda)

  const toggle = (m: MotivoPerda) => {
    const prox = new Set(selecionados)
    if (prox.has(m)) prox.delete(m)
    else prox.add(m)
    // Reordena pela canônica para serialização de URL estável.
    onMotivosPerdaChange(MOTIVOS_PERDA.filter((slug) => prox.has(slug)))
  }

  const rotulo =
    motivosPerda.length === 0
      ? "Todos"
      : motivosPerda.length === 1
        ? MOTIVO_PERDA_LABEL[motivosPerda[0]]
        : `${motivosPerda.length} motivos`

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        disabled={desabilitado}
        aria-disabled={desabilitado || undefined}
        aria-label="Filtrar por motivo de perda"
        title={
          bloqueada
            ? "Lente 'Demanda não atendida' sobrescreve estes filtros — desligue-a para editá-los."
            : desabilitado
              ? "Disponível quando o desfecho é Perdido."
              : "Motivo do atendimento que ancora o ponto. Combina por OR."
        }
        className={cn(
          "flex h-9 min-w-[8.5rem] items-center justify-between gap-2 rounded-md border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          desabilitado && "cursor-not-allowed opacity-50 hover:bg-input",
        )}
      >
        <span className="flex items-center gap-2 truncate">
          <span className="text-[11px] font-medium text-text-muted">Motivo:</span>
          <span
            className={cn(
              "truncate",
              motivosPerda.length === 0 && "text-text-muted",
            )}
          >
            {rotulo}
          </span>
          {motivosPerda.length > 1 && (
            <span className="shrink-0 rounded-full bg-gold-500/15 px-1.5 text-[10px] font-semibold text-gold-500 tabular-nums">
              {motivosPerda.length}
            </span>
          )}
        </span>
        <ChevronDown size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
      </PopoverTrigger>
      <PopoverContent align="end" className="min-w-[200px] p-2">
        <ul className="max-h-60 overflow-y-auto">
          <li>
            <button
              type="button"
              onClick={() => onMotivosPerdaChange([])}
              className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm outline-none transition-colors hover:bg-accent focus-visible:bg-accent"
            >
              <span
                className={cn(
                  motivosPerda.length === 0
                    ? "font-medium text-gold-500"
                    : "text-text-primary",
                )}
              >
                Todos
              </span>
              {motivosPerda.length === 0 && (
                <Check size={14} strokeWidth={2} className="text-gold-500" />
              )}
            </button>
          </li>
          {MOTIVOS_PERDA.map((m) => {
            const ativo = selecionados.has(m)
            return (
              <li key={m}>
                <button
                  type="button"
                  onClick={() => toggle(m)}
                  aria-pressed={ativo}
                  className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm text-text-primary outline-none transition-colors hover:bg-accent focus-visible:bg-accent"
                >
                  <span className="truncate">{MOTIVO_PERDA_LABEL[m]}</span>
                  {ativo && (
                    <Check size={14} strokeWidth={2} className="shrink-0 text-gold-500" />
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      </PopoverContent>
    </Popover>
  )
}

/** Toggle da lente "Demanda não atendida" (MAPA-9). Ortogonal a `SeletorCamada` —
 *  pode estar ON com qualquer camada. Quando ON, sobrescreve os filtros de desfecho
 *  e motivo do MAPA-8 no fetch (sem mutar o estado prévio no pai). */
export function ToggleLenteDemanda({
  ativa,
  onAtivaChange,
}: {
  ativa: boolean
  onAtivaChange: (v: boolean) => void
}) {
  const tooltip = ativa
    ? "Mostrando só clientes Perdidos por indisponibilidade ou fora da área. Clique para desligar."
    : "Mostrar só Perdidos por indisponibilidade ou fora da área — onde você deixa dinheiro na mesa por não cobrir."
  return (
    <button
      type="button"
      role="switch"
      aria-checked={ativa}
      aria-label="Lente Demanda não atendida"
      title={tooltip}
      onClick={() => onAtivaChange(!ativa)}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        ativa
          ? "border-transparent text-text-primary"
          : "border-border bg-card text-text-muted hover:text-text-secondary",
      )}
      style={
        ativa
          ? { background: `${COR_OPORTUNIDADE}26`, borderColor: COR_OPORTUNIDADE }
          : undefined
      }
    >
      <span
        aria-hidden
        className="h-2 w-2 rounded-full border"
        style={{
          background: ativa ? COR_OPORTUNIDADE : "transparent",
          borderColor: COR_OPORTUNIDADE,
        }}
      />
      Demanda não atendida
    </button>
  )
}

/** Legenda da lente "Demanda não atendida" (MAPA-9) — uma linha explicando o subset.
 *  Mesmo card-style das outras legendas; usada lado a lado com LegendaEscala/Desfecho/Perfil. */
export function LegendaDemandaNaoAtendida() {
  return (
    <div
      aria-label="Legenda Demanda não atendida"
      className="w-[260px] rounded-md border border-border bg-card/95 p-2 shadow-sm backdrop-blur"
    >
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-text-secondary">
        <span
          aria-hidden
          className="h-2.5 w-2.5 rounded-full border"
          style={{ borderColor: COR_OPORTUNIDADE, background: `${COR_OPORTUNIDADE}40` }}
        />
        Demanda não atendida
      </div>
      <p className="text-[11px] leading-snug text-text-muted">
        Perdidos por indisponibilidade ou fora da área — onde você deixa dinheiro na
        mesa por não cobrir.
      </p>
    </div>
  )
}

// MAPA-11: cutoff fixo (não vira param de URL nem env var). Exportado para a UI
// (tooltips/rótulos) e potencial reuso em testes — a regra equivalente vive no
// backend como literal SQL `INTERVAL '90 days'`.
export const RECENCIA_CUTOFF_DIAS = 90

/** Filtro de faixa de R$ fechado por cliente (MAPA-11). Incide em `ag.valor_total`
 *  (cross-modelo). Ortogonal ao MAPA-8 e à lente MAPA-9: sempre aplicado, controles
 *  sempre habilitados. UI sinaliza min > max com `aria-invalid` e não chama
 *  `onChange` até bater — defesa em profundidade, o backend também aceita range
 *  degenerado (devolve zero pontos). Dois `<input type="number">` em Popover seguindo
 *  o pattern do FiltroMotivoPerda (slider dual-handle não existe no projeto). */
export function FiltroValorRange({
  valorMin,
  valorMax,
  onChange,
}: {
  valorMin: number | null
  valorMax: number | null
  onChange: (range: { valorMin: number | null; valorMax: number | null }) => void
}) {
  const [open, setOpen] = useState(false)
  // Buffers locais: o usuário digita aqui livremente; só commitamos no `onChange`
  // quando o valor é válido (min <= max). Strings vazias mantêm `null` no estado pai.
  const [minStr, setMinStr] = useState<string>(valorMin === null ? "" : String(valorMin))
  const [maxStr, setMaxStr] = useState<string>(valorMax === null ? "" : String(valorMax))

  const minNum = minStr === "" ? null : Number(minStr)
  const maxNum = maxStr === "" ? null : Number(maxStr)
  const invalido =
    minNum !== null && maxNum !== null && minNum > maxNum && !Number.isNaN(minNum) && !Number.isNaN(maxNum)

  const commit = (next: { min: number | null; max: number | null }) => {
    // Bloqueio do submit em range degenerado: a UI marca os inputs como inválidos
    // e não propaga até bater. Backend aceita igual (devolve zero pontos), mas
    // evitamos uma querystring sem sentido.
    if (
      next.min !== null &&
      next.max !== null &&
      next.min > next.max &&
      !Number.isNaN(next.min) &&
      !Number.isNaN(next.max)
    ) {
      return
    }
    onChange({
      valorMin: next.min !== null && !Number.isNaN(next.min) ? next.min : null,
      valorMax: next.max !== null && !Number.isNaN(next.max) ? next.max : null,
    })
  }

  const rotulo =
    valorMin === null && valorMax === null
      ? "Todos"
      : `${valorMin === null ? "—" : formatBRL(valorMin)} – ${valorMax === null ? "—" : formatBRL(valorMax)}`

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label="Filtrar por faixa de R$ fechado por cliente"
        title="Soma do R$ fechado do cliente (todas as modelos). Cliente cujo total cai fora do intervalo não vira ponto."
        className="flex h-9 min-w-[8.5rem] items-center justify-between gap-2 rounded-md border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <span className="flex items-center gap-2 truncate">
          <span className="text-[11px] font-medium text-text-muted">Valor:</span>
          <span
            className={cn(
              "truncate",
              valorMin === null && valorMax === null && "text-text-muted",
            )}
          >
            {rotulo}
          </span>
        </span>
        <ChevronDown size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
      </PopoverTrigger>
      <PopoverContent align="end" className="min-w-[240px] p-3">
        <div className="flex flex-col gap-2">
          <label className="flex items-center justify-between gap-2 text-sm text-text-primary">
            <span className="text-[12px] font-medium text-text-muted">Mín (R$)</span>
            <input
              type="number"
              min={0}
              step={50}
              value={minStr}
              aria-invalid={invalido || undefined}
              onChange={(e) => {
                setMinStr(e.target.value)
                commit({
                  min: e.target.value === "" ? null : Number(e.target.value),
                  max: maxNum,
                })
              }}
              placeholder="—"
              className={cn(
                "h-8 w-24 rounded-md border border-input bg-input px-2 text-right text-sm tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring",
                invalido && "border-state-lost",
              )}
            />
          </label>
          <label className="flex items-center justify-between gap-2 text-sm text-text-primary">
            <span className="text-[12px] font-medium text-text-muted">Máx (R$)</span>
            <input
              type="number"
              min={0}
              step={50}
              value={maxStr}
              aria-invalid={invalido || undefined}
              onChange={(e) => {
                setMaxStr(e.target.value)
                commit({
                  min: minNum,
                  max: e.target.value === "" ? null : Number(e.target.value),
                })
              }}
              placeholder="—"
              className={cn(
                "h-8 w-24 rounded-md border border-input bg-input px-2 text-right text-sm tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring",
                invalido && "border-state-lost",
              )}
            />
          </label>
          {invalido && (
            <span className="text-[11px] text-state-lost">
              Mín maior que Máx — ajuste para aplicar.
            </span>
          )}
          <button
            type="button"
            onClick={() => {
              setMinStr("")
              setMaxStr("")
              onChange({ valorMin: null, valorMax: null })
            }}
            className="mt-1 self-end rounded-md px-2 py-1 text-[12px] font-medium text-text-muted outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
          >
            Limpar
          </button>
        </div>
      </PopoverContent>
    </Popover>
  )
}

/** Filtro de recência sobre o externo que ancora o ponto (MAPA-11). Cutoff fixo
 *  em `RECENCIA_CUTOFF_DIAS` (90d). Mutuamente exclusivo: "Todos" não filtra. */
export type FiltroRecencia = "todos" | "ativos" | "dormentes"

const OPCOES_RECENCIA: readonly { id: FiltroRecencia; label: string; tooltip: string }[] = [
  { id: "todos", label: "Todos", tooltip: "Sem filtro de recência." },
  {
    id: "ativos",
    label: `Ativos (≤${RECENCIA_CUTOFF_DIAS}d)`,
    tooltip: `Externo mais recente do cliente nos últimos ${RECENCIA_CUTOFF_DIAS} dias.`,
  },
  {
    id: "dormentes",
    label: `Dormentes (>${RECENCIA_CUTOFF_DIAS}d)`,
    tooltip: `Externo mais recente do cliente há mais de ${RECENCIA_CUTOFF_DIAS} dias.`,
  },
] as const

export function SeletorRecencia({
  recencia,
  onRecenciaChange,
}: {
  recencia: FiltroRecencia
  onRecenciaChange: (r: FiltroRecencia) => void
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Filtro por recência"
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
            title={opcao.tooltip}
            onClick={() => onRecenciaChange(opcao.id)}
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
