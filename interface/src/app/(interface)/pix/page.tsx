"use client"

import { Suspense, useMemo } from "react"
import { DetalhePix } from "@/components/pix/DetalhePix"
import { HeaderPix } from "@/components/pix/HeaderPix"
import { ListaPix } from "@/components/pix/ListaPix"
import { ToolbarPix } from "@/components/pix/ToolbarPix"
import { usePix } from "@/hooks/usePix"

export default function PixPage() {
  return (
    <Suspense fallback={<HeaderPix />}>
      <PixConteudo />
    </Suspense>
  )
}

function PixConteudo() {
  const pix = usePix()

  const modelosDisponiveis = useMemo(() => {
    const map = new Map<string, string>()
    for (const item of pix.items) {
      if (!map.has(item.modelo.id)) map.set(item.modelo.id, item.modelo.nome)
    }
    if (pix.detalhe && !map.has(pix.detalhe.modelo.id)) {
      map.set(pix.detalhe.modelo.id, pix.detalhe.modelo.nome)
    }
    return Array.from(map.entries())
      .map(([id, nome]) => ({ id, nome }))
      .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"))
  }, [pix.items, pix.detalhe])

  return (
    <div className="space-y-6">
      <HeaderPix />

      <ToolbarPix
        busca={pix.filtros.busca}
        status={pix.filtros.status}
        modeloId={pix.filtros.modelo_id}
        motivo={pix.filtros.motivo_em_revisao}
        periodo={pix.filtros.periodo}
        loading={pix.listaStatus === "loading"}
        modelos={modelosDisponiveis}
        onBuscaChange={(busca) => pix.setFiltros((current) => ({ ...current, busca }))}
        onStatusChange={(status) => pix.setFiltros((current) => ({ ...current, status }))}
        onModeloChange={(modelo_id) => pix.setFiltros((current) => ({ ...current, modelo_id }))}
        onMotivoChange={(motivo_em_revisao) =>
          pix.setFiltros((current) => ({ ...current, motivo_em_revisao }))
        }
        onPeriodoChange={(periodo) => pix.setFiltros((current) => ({ ...current, periodo }))}
      />

      <div className="grid min-h-[calc(100vh-250px)] grid-cols-[360px_minmax(0,1fr)] gap-6">
        <ListaPix
          items={pix.items}
          selectedId={pix.selectedId}
          status={pix.listaStatus}
          error={pix.listaError}
          filtrosAplicados={pix.filtrosAplicados}
          nextCursor={pix.nextCursor}
          onSelect={pix.selectPix}
          onRetry={pix.refetch}
          onCarregarMais={pix.carregarMais}
        />
        <DetalhePix
          detalhe={pix.detalhe}
          status={pix.detalheStatus}
          error={pix.detalheError}
          comprovante={pix.comprovante}
          comprovanteStatus={pix.comprovanteStatus}
          onRetry={pix.refetch}
          onAprovar={pix.aprovar}
          onRejeitar={pix.rejeitar}
          onReabrir={pix.reabrir}
          onRecarregarComprovante={pix.recarregarComprovante}
        />
      </div>
    </div>
  )
}
