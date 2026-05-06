"use client"

import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { BannerErro } from "@/components/layout/BannerErro"
import { Skeleton } from "@/components/ui/skeleton"
import { formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import type {
  ComprovanteUrlResponse,
  MotivoRejeicao,
  PixDetalheResponse,
} from "@/tipos/pix"
import { AcoesPix } from "./AcoesPix"
import { AtendimentoVinculadoPix } from "./AtendimentoVinculadoPix"
import { ChecagensPix } from "./ChecagensPix"
import { ComprovantePix } from "./ComprovantePix"
import { DialogVisualizarComprovante } from "./DialogVisualizarComprovante"
import { LinhaTempoPix } from "./LinhaTempoPix"
import { MetadadosPix } from "./MetadadosPix"
import { badgeForStatusPix, statusItemPix } from "./utils"

export function DetalhePix({
  detalhe,
  status,
  error,
  comprovante,
  comprovanteStatus,
  onRetry,
  onAprovar,
  onRejeitar,
  onReabrir,
  onRecarregarComprovante,
}: {
  detalhe: PixDetalheResponse | null
  status: "loading" | "success" | "error"
  error: string | null
  comprovante: ComprovanteUrlResponse | null
  comprovanteStatus: "idle" | "loading" | "success" | "error"
  onRetry: () => void
  onAprovar: (id: string) => Promise<void>
  onRejeitar: (id: string, motivo: MotivoRejeicao, observacao: string | null) => Promise<void>
  onReabrir: (id: string) => Promise<void>
  onRecarregarComprovante: () => void
}) {
  const [modalAberto, setModalAberto] = useState(false)

  if (status === "loading") {
    return (
      <section
        aria-label="Detalhe do Pix"
        aria-busy="true"
        className="space-y-4"
      >
        <Skeleton className="h-16 rounded-lg" />
        <Skeleton className="h-12 rounded-lg" />
        <Skeleton className="h-24 rounded-lg" />
        <Skeleton className="h-40 rounded-lg" />
        <Skeleton className="h-32 rounded-lg" />
        <Skeleton className="h-24 rounded-lg" />
        <Skeleton className="h-40 rounded-lg" />
      </section>
    )
  }

  if (status === "error") {
    return (
      <section aria-label="Detalhe do Pix">
        <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />
      </section>
    )
  }

  if (detalhe === null) {
    return (
      <section
        aria-label="Detalhe do Pix"
        className="rounded-lg border border-border bg-card p-6 text-[13px] text-text-muted"
      >
        Selecione um Pix na lista para ver os detalhes.
      </section>
    )
  }

  const status_ = statusItemPix(detalhe.pix.decisao_pipeline, detalhe.pix.decisao_final)
  const badge = badgeForStatusPix(status_)
  const cliente = detalhe.cliente.nome ?? formatTelefone(detalhe.cliente.telefone)

  return (
    <section aria-label="Detalhe do Pix" className="space-y-3">
      <header className="rounded-lg border border-border bg-card p-5">
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant={badge.variant}>{badge.label}</Badge>
          <span className="ml-auto text-xs text-text-muted">
            Recebido {formatTempoRelativo(detalhe.pix.created_at)}
          </span>
        </div>
        <h2 className="mt-3 text-[22px] font-semibold leading-[30px] text-text-primary">
          {cliente}
        </h2>
        <p className="mt-1 text-[13px] text-text-muted">
          Conversa com {detalhe.modelo.nome}
        </p>
      </header>

      <AcoesPix
        detalhe={detalhe}
        onAprovar={onAprovar}
        onRejeitar={onRejeitar}
        onReabrir={onReabrir}
      />

      <ComprovantePix
        pix={detalhe.pix}
        comprovanteStatus={comprovanteStatus}
        onVisualizar={() => setModalAberto(true)}
        onTentarNovamente={onRecarregarComprovante}
      />

      <div className="grid grid-cols-2 gap-3">
        <MetadadosPix pix={detalhe.pix} />
        <ChecagensPix checagens={detalhe.checagens} />
      </div>
      <AtendimentoVinculadoPix atendimento={detalhe.atendimento} />
      <LinhaTempoPix eventos={detalhe.eventos} />

      <DialogVisualizarComprovante
        open={modalAberto}
        onOpenChange={setModalAberto}
        pix={detalhe.pix}
        comprovante={comprovante}
        comprovanteStatus={comprovanteStatus}
        onTentarNovamente={onRecarregarComprovante}
        onAprovar={() => onAprovar(detalhe.pix.id)}
        onRejeitar={(motivo, obs) => onRejeitar(detalhe.pix.id, motivo, obs)}
      />
    </section>
  )
}
