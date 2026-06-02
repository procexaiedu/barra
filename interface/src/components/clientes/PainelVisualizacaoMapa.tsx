"use client"

import {
  SeletorCamada,
  SeletorMetrica,
  SeletorModoCor,
  type ModoCor,
} from "@/components/clientes/MapaControles"
import type { MapaCamada, MapaMetrica } from "@/lib/mapaMetrica"

/** Painel de controles de visualização do Mapa (Camada/Métrica/Cor). Vive como
 *  overlay sobre o mapa (top-right) — coloca Camada/Métrica/Cor perto dos pontos
 *  que elas pintam, longe dos filtros (que reduzem o conjunto). Mesmo trato
 *  visual das legendas (border + bg-card/95 + backdrop) para se integrar ao chrome
 *  do mapa sem competir com ele. */
export function PainelVisualizacaoMapa({
  camada,
  pontosCount,
  metrica,
  modoCor,
  comparar,
  onCamadaChange,
  onMetricaChange,
  onModoCorChange,
}: {
  camada: MapaCamada
  pontosCount: number
  metrica: MapaMetrica
  modoCor: ModoCor
  /** MAPA-14: quando true, força Hexbin e esconde Cor (delta é cor por design). */
  comparar?: boolean
  onCamadaChange: (c: MapaCamada) => void
  onMetricaChange: (m: MapaMetrica) => void
  onModoCorChange: (m: ModoCor) => void
}) {
  return (
    <div
      aria-label="Como mostrar o mapa"
      className="flex w-fit max-w-[280px] flex-col gap-2 rounded-md border border-border bg-card/95 p-2 shadow-sm backdrop-blur"
    >
      <Linha label="Visualização">
        <SeletorCamada
          camada={camada}
          pontosCount={pontosCount}
          onCamadaChange={onCamadaChange}
          bloqueada={comparar}
        />
      </Linha>
      <Linha label="Medir por">
        <SeletorMetrica metrica={metrica} onMetricaChange={onMetricaChange} />
      </Linha>
      {camada === "bolhas" && !comparar && (
        <Linha label="Colorir por">
          <SeletorModoCor modo={modoCor} onModoChange={onModoCorChange} />
        </Linha>
      )}
    </div>
  )
}

function Linha({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
        {label}
      </span>
      {children}
    </div>
  )
}
