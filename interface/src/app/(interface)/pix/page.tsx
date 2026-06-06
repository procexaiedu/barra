"use client"

import { Suspense, useState } from "react"
import { DetalhePix } from "@/components/pix/DetalhePix"
import { PageHeader } from "@/components/layout/PageHeader"
import { PainelDetalheResponsivo } from "@/components/layout/PainelDetalheResponsivo"
import { ListaPix } from "@/components/pix/ListaPix"
import { ToolbarPix } from "@/components/pix/ToolbarPix"
import { usePix } from "@/hooks/usePix"

const TITULO_PIX = "Pix de deslocamento"
const DESCRICAO_PIX = "Aprove Pix duvidosos e revise os já validados."

export default function PixPage() {
  return (
    <Suspense fallback={<PageHeader title={TITULO_PIX} description={DESCRICAO_PIX} />}>
      <PixConteudo />
    </Suspense>
  )
}

function PixConteudo() {
  const pix = usePix()
  const [detalheAberto, setDetalheAberto] = useState(false)

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col gap-4">
      <div className="flex-none">
        <PageHeader title={TITULO_PIX} description={DESCRICAO_PIX} />
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

      <PainelDetalheResponsivo
        className="flex-1"
        tituloDetalhe="Detalhe do Pix"
        detalheAberto={detalheAberto}
        onFecharDetalhe={() => setDetalheAberto(false)}
        lista={
          <ListaPix
            items={pix.items}
            selectedId={pix.selectedId}
            status={pix.listaStatus}
            error={pix.listaError}
            filtrosAplicados={pix.filtrosAplicados}
            nextCursor={pix.nextCursor}
            carregandoMais={pix.carregandoMais}
            onSelect={(id) => {
              pix.selectPix(id)
              setDetalheAberto(true)
            }}
            onRetry={pix.refetch}
            onCarregarMais={pix.carregarMais}
          />
        }
        detalhe={
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
        }
      />
    </div>
  )
}
