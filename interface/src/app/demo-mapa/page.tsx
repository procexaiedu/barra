"use client"

import { useState } from "react"
import { LegendaEscala, SeletorMetrica } from "@/components/clientes/MapaControles"
import type { MapaMetrica } from "@/lib/mapaMetrica"
import type { MapaClientePonto } from "@/tipos/clientes"

// Rota TEMPORÁRIA só para verificação visual do MAPA-1 (seletor + legenda).
// Mock de pontos com valores distintos para evidenciar min/max — sem Google
// Maps, sem auth, sem dados reais. Espelha o padrão de /demo-disp.
const PONTOS_MOCK: MapaClientePonto[] = [
  {
    cliente_id: "c1",
    nome: "Cliente A",
    latitude: -22.97,
    longitude: -43.18,
    bairro: "Barra",
    endereco_formatado: "Av. das Américas, 500",
    total_atendimentos: 8,
    valor_total: 12_400,
  },
  {
    cliente_id: "c2",
    nome: "Cliente B",
    latitude: -23.55,
    longitude: -46.63,
    bairro: "Jardins",
    endereco_formatado: "Rua Oscar Freire, 200",
    total_atendimentos: 3,
    valor_total: 4_200,
  },
  {
    cliente_id: "c3",
    nome: "Cliente C",
    latitude: -19.92,
    longitude: -43.94,
    bairro: "Lourdes",
    endereco_formatado: "Av. do Contorno, 9000",
    total_atendimentos: 1,
    valor_total: 850,
  },
  {
    cliente_id: "c4",
    nome: "Cliente D",
    latitude: -25.43,
    longitude: -49.27,
    bairro: "Batel",
    endereco_formatado: "Av. do Batel, 1500",
    total_atendimentos: 5,
    valor_total: 7_300,
  },
]

export default function Page() {
  const [metrica, setMetrica] = useState<MapaMetrica>("valor")
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl text-text-primary">MAPA-1 — demo</h1>
        <p className="text-[13px] text-text-muted">
          Verificação visual do seletor de métrica + legenda. Mock de {PONTOS_MOCK.length}
          {" "}pontos.
        </p>
      </header>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] text-text-muted">
          {PONTOS_MOCK.length} cliente{PONTOS_MOCK.length === 1 ? "" : "s"} no mapa
        </span>
        <SeletorMetrica metrica={metrica} onMetricaChange={setMetrica} />
      </div>

      <div className="relative h-64 overflow-hidden rounded-lg border border-border bg-surface-hover">
        <span className="absolute inset-0 grid place-items-center text-[13px] text-text-muted">
          (área do mapa — vazia neste demo)
        </span>
        <div className="absolute bottom-3 left-3">
          <LegendaEscala metrica={metrica} pontos={PONTOS_MOCK} />
        </div>
      </div>

      <ul className="grid grid-cols-2 gap-2 text-[12px] text-text-muted">
        {PONTOS_MOCK.map((p) => (
          <li key={p.cliente_id} className="rounded-md border border-border bg-card px-2 py-1">
            <span className="text-text-primary">{p.nome}</span> · {p.total_atendimentos} at. · R$ {p.valor_total.toLocaleString("pt-BR")}
          </li>
        ))}
      </ul>
    </div>
  )
}
