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
import { RAMPA_DIVERGENTE_CSS } from "@/lib/cores/divergente"
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
    label: "Métrica",
    tooltip: "Pin colorido pela intensidade: dourado (pouco) ao vermelho (mais quente).",
  },
  {
    id: "desfecho",
    label: "Desfecho",
    tooltip: "Verde: fechou · Vermelho: perdeu · Âmbar: em andamento.",
  },
  {
    id: "perfil",
    label: "Perfil físico",
    tooltip:
      "Cor pelo perfil declarado do cliente. Quem não tem perfil declarado: cinza.",
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
      aria-label="Colorir os pontos por"
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
      "Um ponto por cliente. No modo 'Métrica' o tamanho do ponto cresce com o valor; nos outros modos, é pin colorido.",
  },
  {
    id: "hexbin",
    label: "Favos",
    tooltip:
      "Agrupa clientes próximos em favos hexagonais. Mais escuro = mais movimento na região. Clique num favo para ver o total.",
  },
  {
    id: "calor",
    label: "Calor",
    tooltip:
      "Mapa de calor contínuo. Mostra de relance onde a região está mais quente; não tem clique.",
  },
] as const

/** Seletor de camada (MAPA-6/MAPA-7). Default = "bolhas" (preserva a Fase 1).
 *  `pontosCount` é usado pela guarda de honestidade do MAPA-7: abaixo do limiar
 *  o botão Calor fica desabilitado com tooltip explicativo (KDE com pouco dado
 *  hiperestima densidade nas pontas).
 *
 *  MAPA-14: `bloqueada` desabilita todos os botões diferentes do ativo (no modo
 *  Comparar a camada é fixada em Hexbin — Bolhas/Calor não fazem sentido para
 *  delta espacial). */
export function SeletorCamada({
  camada,
  pontosCount,
  onCamadaChange,
  bloqueada,
}: {
  camada: MapaCamada
  pontosCount: number
  onCamadaChange: (c: MapaCamada) => void
  bloqueada?: boolean
}) {
  const calorOk = calorHabilitado(pontosCount)
  return (
    <div
      role="radiogroup"
      aria-label="Tipo de visualização do mapa"
      aria-disabled={bloqueada || undefined}
      className="inline-flex rounded-lg border border-border bg-card p-0.5"
    >
      {OPCOES_CAMADA.map((opcao) => {
        const ativo = opcao.id === camada
        const calorDesab = opcao.id === "calor" && !calorOk
        // MAPA-14: bloqueada impede troca — apenas o ativo fica clicável (NO-OP).
        const compararDesab = bloqueada === true && !ativo
        const desabilitado = calorDesab || compararDesab
        const title = compararDesab
          ? "Comparar fixa a visualização em Favos. Desligue Comparar para escolher outra."
          : calorDesab
            ? `Poucos clientes para um Calor confiável (mínimo ${LIMIAR_CALOR_MIN_PONTOS}; agora ${pontosCount}). Use Pontos ou Favos.`
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
      aria-label="O que medir no mapa"
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
  rampa = RAMPA_SEQ,
}: {
  metrica: MapaMetrica
  pontos: MapaClientePonto[]
  /** Stops CSS da rampa, do menor (esquerda) ao maior (direita) valor. Default
   *  `RAMPA_SEQ` (Calor). No modo Pontos+Métrica (Task 12) o pai passa
   *  `RAMPA_INTENSIDADE_CSS` (→ vermelho no topo) para casar com a cor do pin; os
   *  Favos (hexbin) passam `RAMPA_FAVO_CSS` (dourado pálido → âmbar). Senão a
   *  legenda mente sobre a cor exibida. */
  rampa?: readonly string[]
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
      title="Contar clientes só faz sentido em Favos ou Calor. Em Pontos, todos ficam do mesmo tamanho."
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
          background: `linear-gradient(to right, ${rampa.join(", ")})`,
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
  { id: "todos", label: "Todos", tooltip: "Mostrar todos os clientes." },
  {
    id: "Fechado",
    label: "Fechado",
    tooltip: "Só clientes cujo último atendimento fechou.",
  },
  {
    id: "Perdido",
    label: "Perdido",
    tooltip: "Só clientes cujo último atendimento foi perdido.",
  },
  {
    id: "andamento",
    label: "Em andamento",
    tooltip: "Só clientes com atendimento ainda em aberto.",
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
    "A lente 'Demanda não atendida' está ditando esses filtros. Desligue para mudar."
  return (
    <div
      role="radiogroup"
      aria-label="Filtrar por desfecho do último atendimento"
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
        aria-label="Filtrar por motivo da perda"
        title={
          bloqueada
            ? "A lente 'Demanda não atendida' está ditando esses filtros. Desligue para mudar."
            : desabilitado
              ? "Disponível só quando o desfecho for 'Perdido'."
              : "Por que o último atendimento foi perdido. Pode escolher vários."
        }
        className={cn(
          "flex h-9 min-w-[8.5rem] items-center justify-between gap-2 rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
          desabilitado && "cursor-not-allowed opacity-50 hover:border-input",
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
    ? "Mostrando só onde você está perdendo demanda (sem cobrir ou ocupado). Clique para desligar."
    : "Veja onde você está perdendo demanda. Só clientes perdidos por indisponibilidade ou fora da área."
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
        Clientes perdidos por indisponibilidade ou fora da área. Áreas onde você
        está deixando dinheiro na mesa.
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
      : `${valorMin === null ? "qualquer" : formatBRL(valorMin)} a ${valorMax === null ? "qualquer" : formatBRL(valorMax)}`

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label="Filtrar por R$ já gasto pelo cliente"
        title="Total que cada cliente já gastou (em todas as modelos). Quem fica fora da faixa não aparece no mapa."
        className="flex h-9 min-w-[8.5rem] items-center justify-between gap-2 rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <span className="flex items-center gap-2 truncate">
          <span className="text-[11px] font-medium text-text-muted">R$ gasto:</span>
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
            <span className="text-[12px] font-medium text-text-muted">Mínimo (R$)</span>
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
              placeholder="sem limite"
              className={cn(
                "h-8 w-24 rounded-md border border-input bg-input px-2 text-right text-sm tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring",
                invalido && "border-state-lost",
              )}
            />
          </label>
          <label className="flex items-center justify-between gap-2 text-sm text-text-primary">
            <span className="text-[12px] font-medium text-text-muted">Máximo (R$)</span>
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
              placeholder="sem limite"
              className={cn(
                "h-8 w-24 rounded-md border border-input bg-input px-2 text-right text-sm tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring",
                invalido && "border-state-lost",
              )}
            />
          </label>
          {invalido && (
            <span className="text-[11px] text-state-lost">
              Mínimo maior que máximo. Ajuste para aplicar.
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
  { id: "todos", label: "Todos", tooltip: "Mostrar clientes de qualquer época." },
  {
    id: "ativos",
    label: `Ativos (últimos ${RECENCIA_CUTOFF_DIAS} dias)`,
    tooltip: `Clientes com atendimento nos últimos ${RECENCIA_CUTOFF_DIAS} dias.`,
  },
  {
    id: "dormentes",
    label: `Dormentes (mais de ${RECENCIA_CUTOFF_DIAS} dias)`,
    tooltip: `Clientes sem atendimento há mais de ${RECENCIA_CUTOFF_DIAS} dias.`,
  },
] as const

export function SeletorRecencia({
  recencia,
  onRecenciaChange,
  bloqueada,
}: {
  recencia: FiltroRecencia
  onRecenciaChange: (r: FiltroRecencia) => void
  /** MAPA-14: no modo Comparar a recência não faz sentido (ranges absolutos
   *  substituem a noção de cutoff relativo) — backend já ignora o param. */
  bloqueada?: boolean
}) {
  const tooltipBloqueada =
    "Comparar usa os próprios períodos (A e B). Recência fica desligada."
  return (
    <div
      role="radiogroup"
      aria-label="Filtrar por última visita"
      aria-disabled={bloqueada || undefined}
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
            aria-disabled={bloqueada || undefined}
            disabled={bloqueada}
            title={bloqueada ? tooltipBloqueada : opcao.tooltip}
            onClick={() => onRecenciaChange(opcao.id)}
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

/** Filtro "Comparar dois períodos" (MAPA-14, lift de campanha). Toggle + dois
 *  pares de `<input type="date">`. Sobrescreve `periodo`/`recencia` no fetch
 *  (UI também desabilita o seletor de recência durante o modo). Validação inline:
 *  ranges com `fim < inicio` ficam `aria-invalid` e não disparam fetch (defesa
 *  em profundidade — backend também valida com 422). Ranges podem ou não se
 *  sobrepor; Fernando pode comparar "Q1 inteiro" com "março". */
export interface CompararRecortes {
  comparar: boolean
  aInicio: string | null
  aFim: string | null
  bInicio: string | null
  bFim: string | null
}

function rangeInvalido(inicio: string | null, fim: string | null): boolean {
  return inicio !== null && fim !== null && fim < inicio
}

function rangePronto(inicio: string | null, fim: string | null): boolean {
  return inicio !== null && fim !== null && fim >= inicio
}

// ── Comparações rápidas (presets) ────────────────────────────────────────────
// A maioria esmagadora das comparações de campanha é "período atual × período
// anterior de mesmo tamanho". Os presets resolvem isso em um clique e produzem
// exatamente os mesmos 4 limites ISO que a entrada manual — nada novo chega ao
// fetch. Convenção: A = base (mais antigo) · B = comparado (mais recente) ·
// favo = B − A. Datas calculadas em horário local (Fernando opera em BRT).

type LimitesComparar = Pick<CompararRecortes, "aInicio" | "aFim" | "bInicio" | "bFim">

function isoLocal(d: Date): string {
  const y = d.getFullYear()
  const mes = String(d.getMonth() + 1).padStart(2, "0")
  const dia = String(d.getDate()).padStart(2, "0")
  return `${y}-${mes}-${dia}`
}

function somarDias(base: Date, n: number): Date {
  const r = new Date(base)
  r.setDate(r.getDate() + n)
  return r
}

/** B = últimos `n` dias (até hoje) · A = os `n` dias imediatamente anteriores. */
function janelaUltimosDias(n: number): LimitesComparar {
  const hoje = new Date()
  return {
    bFim: isoLocal(hoje),
    bInicio: isoLocal(somarDias(hoje, -(n - 1))),
    aFim: isoLocal(somarDias(hoje, -n)),
    aInicio: isoLocal(somarDias(hoje, -(2 * n - 1))),
  }
}

/** B = mês atual (dia 1 até hoje) · A = mês anterior inteiro. */
function janelaMesVsAnterior(): LimitesComparar {
  const hoje = new Date()
  const inicioMesAtual = new Date(hoje.getFullYear(), hoje.getMonth(), 1)
  const fimMesAnterior = somarDias(inicioMesAtual, -1)
  const inicioMesAnterior = new Date(
    fimMesAnterior.getFullYear(),
    fimMesAnterior.getMonth(),
    1,
  )
  return {
    aInicio: isoLocal(inicioMesAnterior),
    aFim: isoLocal(fimMesAnterior),
    bInicio: isoLocal(inicioMesAtual),
    bFim: isoLocal(hoje),
  }
}

type PresetCompararId = "7d" | "30d" | "mes"

const PRESETS_COMPARAR: readonly {
  id: PresetCompararId
  label: string
  descricao: string
  calcular: () => LimitesComparar
}[] = [
  {
    id: "7d",
    label: "Últimos 7 dias",
    descricao: "vs 7 dias anteriores",
    calcular: () => janelaUltimosDias(7),
  },
  {
    id: "30d",
    label: "Últimos 30 dias",
    descricao: "vs 30 dias anteriores",
    calcular: () => janelaUltimosDias(30),
  },
  {
    id: "mes",
    label: "Este mês",
    descricao: "vs mês passado",
    calcular: janelaMesVsAnterior,
  },
] as const

/** Qual preset (se algum) corresponde exatamente aos 4 limites atuais — usado
 *  para destacar o chip ativo e resumir o trigger. Recalcula a partir de hoje,
 *  então é coerente com o que os botões aplicariam agora. */
function presetCorrespondente(valor: CompararRecortes): PresetCompararId | null {
  for (const p of PRESETS_COMPARAR) {
    const r = p.calcular()
    if (
      valor.aInicio === r.aInicio &&
      valor.aFim === r.aFim &&
      valor.bInicio === r.bInicio &&
      valor.bFim === r.bFim
    ) {
      return p.id
    }
  }
  return null
}

export function FiltroCompararPeriodos({
  valor,
  onChange,
}: {
  valor: CompararRecortes
  onChange: (next: CompararRecortes) => void
}) {
  const [open, setOpen] = useState(false)
  const [mostrarCustom, setMostrarCustom] = useState(false)
  const invalidoA = rangeInvalido(valor.aInicio, valor.aFim)
  const invalidoB = rangeInvalido(valor.bInicio, valor.bFim)
  const prontoA = rangePronto(valor.aInicio, valor.aFim)
  const prontoB = rangePronto(valor.bInicio, valor.bFim)
  const ativo = valor.comparar
  const presetId = presetCorrespondente(valor)
  // Datas que não batem com nenhum preset = entrada manual; revela a seção
  // "personalizado" sozinha (derivado, sem effect) para o usuário ver o que
  // está aplicado ao reabrir o popover.
  const ehCustom = (prontoA || prontoB) && presetId === null
  const custom = mostrarCustom || ehCustom

  const aplicarPreset = (limites: LimitesComparar) => {
    onChange({ comparar: true, ...limites })
    setMostrarCustom(false)
  }

  const toggleAtivo = () => {
    // Ligar já aplica uma comparação útil (1 clique → mapa preenchido): preserva
    // datas anteriores se já havia um range válido, senão usa o 1º preset.
    // Desligar não mexe nas datas (volta intacto ao religar).
    if (!ativo) {
      if (prontoA && prontoB) {
        onChange({ ...valor, comparar: true })
      } else {
        aplicarPreset(PRESETS_COMPARAR[0].calcular())
      }
      setOpen(true)
    } else {
      onChange({ ...valor, comparar: false })
      setOpen(false)
    }
  }

  const resumoTrigger = presetId
    ? PRESETS_COMPARAR.find((p) => p.id === presetId)!.label
    : prontoA && prontoB
      ? `A ${curtaData(valor.aInicio!)}–${curtaData(valor.aFim!)} · B ${curtaData(valor.bInicio!)}–${curtaData(valor.bFim!)}`
      : null

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <div
        role="group"
        aria-label="Comparar dois períodos"
        className={cn(
          "inline-flex items-center gap-0 overflow-hidden rounded-lg border bg-card",
          ativo ? "border-gold-500" : "border-border",
        )}
      >
        <button
          type="button"
          role="switch"
          aria-checked={ativo}
          aria-label="Comparar dois períodos"
          title={
            ativo
              ? "Comparando. Os favos mostram quanto subiu ou caiu de A para B. Clique para desligar."
              : "Compare dois períodos. Veja onde a demanda subiu ou caiu (ex.: antes e depois de uma campanha)."
          }
          onClick={toggleAtivo}
          className={cn(
            "inline-flex items-center gap-1.5 px-2.5 py-1 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            ativo
              ? "bg-gold-500/15 text-text-primary"
              : "text-text-muted hover:text-text-secondary",
          )}
        >
          <span
            aria-hidden
            className="h-2 w-2 rounded-full border border-gold-500"
            style={{ background: ativo ? "var(--gold-500)" : "transparent" }}
          />
          Comparar
        </button>
        <PopoverTrigger
          aria-label="Editar datas dos períodos"
          disabled={!ativo}
          aria-disabled={!ativo || undefined}
          title={
            ativo
              ? "Editar as datas dos períodos A e B."
              : "Ligue Comparar para escolher as datas."
          }
          className={cn(
            "flex h-7 items-center justify-between gap-1 border-l border-border px-2 text-[11px] tabular-nums text-text-muted outline-none transition-colors hover:bg-accent focus-visible:bg-accent",
            !ativo && "cursor-not-allowed opacity-50 hover:bg-card",
          )}
        >
          {resumoTrigger ? (
            <span className="truncate">{resumoTrigger}</span>
          ) : (
            <span className="text-text-muted">escolher período</span>
          )}
          <ChevronDown size={12} strokeWidth={1.5} className="shrink-0 text-text-muted" />
        </PopoverTrigger>
      </div>
      <PopoverContent align="end" className="w-[300px] p-3">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
              Comparações rápidas
            </span>
            <div className="flex flex-col gap-1">
              {PRESETS_COMPARAR.map((p) => {
                const selecionado = presetId === p.id
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => aplicarPreset(p.calcular())}
                    aria-pressed={selecionado}
                    className={cn(
                      "flex items-center justify-between gap-2 rounded-md border px-2.5 py-2 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                      selecionado
                        ? "border-gold-500 bg-gold-500/10"
                        : "border-border bg-card hover:bg-accent",
                    )}
                  >
                    <span className="flex flex-col leading-tight">
                      <span className="text-sm font-medium text-text-primary">
                        {p.label}
                      </span>
                      <span className="text-[11px] text-text-muted">{p.descricao}</span>
                    </span>
                    {selecionado && (
                      <Check
                        size={15}
                        strokeWidth={2}
                        className="shrink-0 text-gold-500"
                      />
                    )}
                  </button>
                )
              })}
            </div>
          </div>
          <div className="flex flex-col gap-2 border-t border-border pt-2.5">
            <button
              type="button"
              onClick={() => setMostrarCustom((v) => !v)}
              aria-expanded={custom}
              className="flex items-center justify-between gap-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted outline-none transition-colors hover:text-text-secondary focus-visible:text-text-secondary"
            >
              Datas personalizadas
              <ChevronDown
                size={14}
                strokeWidth={1.5}
                className={cn("shrink-0 transition-transform", custom && "rotate-180")}
              />
            </button>
            {custom && (
              <div className="flex flex-col gap-3">
                <LinhaRangeData
                  rotulo="Período base (A)"
                  destaque={false}
                  inicio={valor.aInicio}
                  fim={valor.aFim}
                  invalido={invalidoA}
                  msgErro="A: a data final está antes da inicial. Ajuste para aplicar."
                  onInicio={(v) => onChange({ ...valor, aInicio: v })}
                  onFim={(v) => onChange({ ...valor, aFim: v })}
                />
                <LinhaRangeData
                  rotulo="Período a comparar (B)"
                  destaque
                  inicio={valor.bInicio}
                  fim={valor.bFim}
                  invalido={invalidoB}
                  msgErro="B: a data final está antes da inicial. Ajuste para aplicar."
                  onInicio={(v) => onChange({ ...valor, bInicio: v })}
                  onFim={(v) => onChange({ ...valor, bFim: v })}
                />
              </div>
            )}
          </div>
          <p className="text-[11px] leading-snug text-text-muted">
            O mapa entra em Favos coloridos pela variação de B em relação a A. Período e
            Recência ficam desligados enquanto o Comparar está ativo.
          </p>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function curtaData(iso: string): string {
  // YYYY-MM-DD → DD/MM (mostrado no trigger compacto, para 4 datas caberem).
  // Em formatos inesperados, devolve a string crua — input nativo já garante o
  // shape, mas a defesa em profundidade evita NaN/exception na UI.
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  return m ? `${m[3]}/${m[2]}` : iso
}

/** Uma linha de range (início → fim) da seção "Datas personalizadas". Extraída
 *  porque A e B são idênticas exceto pelo rótulo, cor do ponto e callbacks —
 *  inline seria 2× o mesmo bloco de inputs nativos. `destaque` pinta o ponto de
 *  dourado (B, o período "novo/comparado"); A fica neutro. */
function LinhaRangeData({
  rotulo,
  destaque,
  inicio,
  fim,
  invalido,
  msgErro,
  onInicio,
  onFim,
}: {
  rotulo: string
  destaque: boolean
  inicio: string | null
  fim: string | null
  invalido: boolean
  msgErro: string
  onInicio: (v: string | null) => void
  onFim: (v: string | null) => void
}) {
  const classeInput = cn(
    "h-8 flex-1 rounded-md border border-input bg-input px-2 text-sm tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring",
    invalido && "border-state-lost",
  )
  return (
    <div className="flex flex-col gap-1">
      <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
        <span
          aria-hidden
          className={cn(
            "h-2 w-2 rounded-full",
            destaque ? "bg-gold-500" : "border border-border bg-text-muted/40",
          )}
        />
        {rotulo}
      </span>
      <div className="flex items-center gap-2">
        <input
          aria-label={`${rotulo}, data inicial`}
          type="date"
          value={inicio ?? ""}
          aria-invalid={invalido || undefined}
          onChange={(e) => onInicio(e.target.value === "" ? null : e.target.value)}
          className={classeInput}
        />
        <span className="text-text-muted">a</span>
        <input
          aria-label={`${rotulo}, data final`}
          type="date"
          value={fim ?? ""}
          aria-invalid={invalido || undefined}
          onChange={(e) => onFim(e.target.value === "" ? null : e.target.value)}
          className={classeInput}
        />
      </div>
      {invalido && <span className="text-[11px] text-state-lost">{msgErro}</span>}
    </div>
  )
}

/** Legenda divergente do modo Comparar (MAPA-14). Mostra a rampa BrBG invertida
 *  com rótulos "caiu / neutro / subiu" para o delta da métrica corrente. Mesma
 *  estética das outras legendas (LegendaEscala/LegendaDesfecho/LegendaPerfil). */
export function LegendaDelta({ metrica }: { metrica: MapaMetrica }) {
  const rotuloMetrica =
    metrica === "valor"
      ? "R$ fechado"
      : metrica === "atendimentos"
        ? "Atendimentos"
        : "Clientes"
  return (
    <div
      aria-label={`Legenda de variação: ${rotuloMetrica}`}
      className="w-[220px] rounded-md border border-border bg-card/95 p-2 shadow-sm backdrop-blur"
    >
      <div className="mb-1 text-[11px] font-medium text-text-secondary">
        Variação de {rotuloMetrica} (B menos A)
      </div>
      <div
        aria-hidden
        className="h-2 w-full rounded-sm"
        style={{
          background: `linear-gradient(to right, ${RAMPA_DIVERGENTE_CSS.join(", ")})`,
        }}
      />
      <div className="mt-1 flex items-center justify-between text-[11px] text-text-muted">
        <span>caiu</span>
        <span>sem mudança</span>
        <span>subiu</span>
      </div>
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
