"use client"

import { Suspense } from "react"
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

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col gap-4">
      <div className="flex-none">
        <HeaderPix />
      </div>

      <div className="flex-none">
        <ToolbarPix
          busca={pix.filtros.busca}
          status={pix.filtros.status}
          modeloIds={pix.filtros.modelo_ids}
          motivo={pix.filtros.motivo_em_revisao}
          periodo={pix.filtros.periodo}
          loading={pix.listaStatus === "loading"}
          onBuscaChange={(busca) => pix.setFiltros((current) => ({ ...current, busca }))}
          onStatusChange={(status) => pix.setFiltros((current) => ({ ...current, status }))}
          onModeloChange={(modelo_ids) => pix.setFiltros((current) => ({ ...current, modelo_ids }))}
          onMotivoChange={(motivo_em_revisao) =>
            pix.setFiltros((current) => ({ ...current, motivo_em_revisao }))
          }
          onPeriodoChange={(periodo) => pix.setFiltros((current) => ({ ...current, periodo }))}
        />
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[360px_minmax(0,1fr)] gap-4">
        <div className="min-h-0 overflow-y-auto">
          <ListaPix
            items={pix.items}
            selectedId={pix.selectedId}
            status={pix.listaStatus}
            error={pix.listaError}
            filtrosAplicados={pix.filtrosAplicados}
            nextCursor={pix.nextCursor}
            carregandoMais={pix.carregandoMais}
            onSelect={pix.selectPix}
            onRetry={pix.refetch}
            onCarregarMais={pix.carregarMais}
          />
        </div>
        <div className="min-h-0 overflow-y-auto">
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
    </div>
  )
}
