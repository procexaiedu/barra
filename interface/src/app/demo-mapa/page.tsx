"use client"

/* ROTA TEMPORÁRIA DE VERIFICAÇÃO VISUAL — não faz parte do produto.
   Monta o MapaClientes real com pontos mockados (clusters no Rio, com spread de
   valor_total) para inspecionar os Favos/Hexbin sem auth nem backend. O middleware
   libera /demo-mapa. Remover ao final da verificação. */

import { useState } from "react"
import { MapaClientes } from "@/components/clientes/MapaClientes"
import { FILTROS_MAPA_PADRAO } from "@/hooks/useClientesMapa"
import type { CompararRecortes } from "@/components/clientes/MapaControles"
import type { MapaClientePonto } from "@/tipos/clientes"

// Pontos mockados clusterizados no Rio. valor_total vai de ~300 (célula que deve
// ler PÁLIDA, não preta) a ~7300 (célula âmbar profunda) para exercitar a rampa
// inteira do favo. Pares co-localizados (<3 km) somam num mesmo hexágono.
const P = (
  cliente_id: string,
  latitude: number,
  longitude: number,
  bairro: string,
  valor_total: number,
  total_atendimentos: number,
): MapaClientePonto => ({
  cliente_id,
  nome: `E2E-DEMO ${cliente_id}`,
  latitude,
  longitude,
  bairro,
  endereco_formatado: bairro,
  estado: "Fechado",
  perfis: [],
  total_atendimentos,
  valor_total,
  recorrente: total_atendimentos >= 2,
})

const PONTOS: MapaClientePonto[] = [
  // Recreio — célula de MENOR valor (deve ler dourado pálido)
  P("recreio-1", -23.022, -43.46, "Recreio dos Bandeirantes", 300, 1),
  // Jacarepaguá — baixo/médio
  P("jpa-1", -22.952, -43.372, "Jacarepaguá", 800, 1),
  // Barra (oeste) — médio
  P("barra-o", -23.0, -43.4, "Barra da Tijuca", 1500, 1),
  // Barra (centro) — médio-alto, célula de 2 pontos
  P("barra-c1", -23.001, -43.362, "Barra da Tijuca", 1300, 1),
  P("barra-c2", -23.003, -43.358, "Barra da Tijuca", 1200, 2),
  // Méier — médio
  P("meier-1", -22.902, -43.282, "Méier", 1500, 1),
  // Tijuca — alto
  P("tijuca-1", -22.928, -43.232, "Tijuca", 4000, 3),
  // Botafogo — alto
  P("botafogo-1", -22.951, -43.182, "Botafogo", 3000, 2),
  // Copacabana — alto, célula de 2 pontos
  P("copa-1", -22.972, -43.188, "Copacabana", 2800, 2),
  P("copa-2", -22.97, -43.185, "Copacabana", 2700, 1),
  // Centro — MAIOR valor (deve ler âmbar profundo)
  P("centro-1", -22.908, -43.176, "Centro", 7300, 4),
]

const NOOP = () => {}

export default function DemoMapa() {
  const [comparar, setComparar] = useState<CompararRecortes>({
    comparar: false,
    aInicio: null,
    aFim: null,
    bInicio: null,
    bFim: null,
  })
  return (
    <div className="dark min-h-screen bg-background p-6 text-foreground">
      <h1 className="mb-3 text-sm font-medium text-text-secondary">
        DEMO — Favos do Mapa de clientes (verificação visual)
      </h1>
      <MapaClientes
        pontos={PONTOS}
        totalSemLocalizacao={0}
        status="success"
        error={null}
        onRetry={NOOP}
        onFiltrarBairro={NOOP}
        desfecho={FILTROS_MAPA_PADRAO.desfecho}
        motivosPerda={FILTROS_MAPA_PADRAO.motivosPerda}
        onDesfechoChange={NOOP}
        onMotivosPerdaChange={NOOP}
        lenteDemanda={false}
        onLenteDemandaChange={NOOP}
        valorMin={null}
        valorMax={null}
        recencia="todos"
        onValorRangeChange={NOOP}
        onRecenciaChange={NOOP}
        periodo="tudo"
        modeloId="todas"
        perfis={[]}
        incluirArquivados={false}
        onPeriodoChange={NOOP}
        dataInicio={null}
        dataFim={null}
        onCustomPeriodoChange={NOOP}
        onModeloChange={NOOP}
        onPerfisChange={NOOP}
        onIncluirArquivadosChange={NOOP}
        comparar={comparar}
        onCompararChange={setComparar}
      />
    </div>
  )
}
