"use client"

import { Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import { AbasModelo } from "@/components/modelos/AbasModelo"
import { AbaFaq } from "@/components/modelos/AbaFaq"
import { AbaMidia } from "@/components/modelos/AbaMidia"
import { AbaPerfil } from "@/components/modelos/AbaPerfil"
import { FotoPerfil } from "@/components/modelos/FotoPerfil"
import type {
  AbaModelo,
  Duracao,
  FaqItem,
  MidiaItem,
  ModeloDetalheResponse,
  PatchModeloInput,
  Programa,
} from "@/tipos/modelos"

const statusBadge = {
  ativa: { variant: "active" as const, label: "Ativa" },
  pausada: { variant: "paused" as const, label: "Pausada" },
  inativa: { variant: "lost" as const, label: "Inativa" },
}

export function DetalheModelo({
  detalhe,
  aba,
  status,
  error,
  actionLoading,
  catalogo,
  duracoes,
  onRetry,
  onAbaChange,
  onDirtyChange,
  onSalvarPerfil,
  onVincularPrograma,
  onAtualizarPrecoPrograma,
  onDesvincularPrograma,
  onTrocarNumero,
  onConectar,
  onPausar,
  onAtivar,
  onDesparear,
  onUploadPerfil,
  onRemoverFoto,
  onAdicionarFaq,
  onEditarFaq,
  onExcluirFaq,
  onAdicionarMidia,
  onOpenMidia,
  onToggleAprovadaMidia,
  onExcluirMidia,
}: {
  detalhe: ModeloDetalheResponse | null
  aba: AbaModelo
  status: "loading" | "success" | "error"
  error: string | null
  actionLoading: boolean
  catalogo: Programa[]
  duracoes: Duracao[]
  onRetry: () => void
  onAbaChange: (aba: AbaModelo) => void
  onDirtyChange: (dirty: boolean) => void
  onSalvarPerfil: (input: PatchModeloInput) => Promise<void>
  onVincularPrograma: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onAtualizarPrecoPrograma: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onDesvincularPrograma: (programaId: string, duracaoId: string) => Promise<void>
  onTrocarNumero: (numero: string) => void
  onConectar: () => void
  onPausar: () => void
  onAtivar: () => void
  onDesparear: () => void
  onUploadPerfil: () => void
  onRemoverFoto: () => Promise<void>
  onAdicionarFaq: () => void
  onEditarFaq: (faq: FaqItem) => void
  onExcluirFaq: (faq: FaqItem) => void
  onAdicionarMidia: () => void
  onOpenMidia: (item: MidiaItem) => void
  onToggleAprovadaMidia: (item: MidiaItem) => void
  onExcluirMidia: (item: MidiaItem) => void
}) {
  if (status === "loading") return <DetalheSkeleton />
  if (status === "error") return <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />
  if (!detalhe) return <EmptyDetalhe />

  const modelo = detalhe.modelo
  const badge = statusBadge[modelo.status]

  return (
    <section aria-label="Detalhe da modelo" className="min-w-0 space-y-5">
      <header className="rounded-lg border border-border bg-card p-6">
        <div className="flex items-start justify-between gap-5">
          <div className="flex min-w-0 gap-4">
            <FotoPerfil url={modelo.foto_perfil_url} nome={modelo.nome} />
            <div className="min-w-0">
              <h2 className="text-[22px] font-semibold leading-[30px] text-text-primary">{modelo.nome}</h2>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Badge variant={badge.variant}>{badge.label}</Badge>
                <Chip warn={!modelo.evolution_instance_id}>{modelo.evolution_instance_id ? "WhatsApp pronto" : "WhatsApp pendente"}</Chip>
              </div>
              <p className="mt-2 text-sm text-text-muted">
                {modelo.nome} — {modelo.idade} anos — {modelo.idiomas.join(", ")} — {modelo.localizacao_operacional ?? "sem região"}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            {!modelo.evolution_instance_id && (
              <Button variant="primary" onClick={onConectar} disabled={actionLoading}>
                {actionLoading && <Loader2 className="animate-spin" />}
                Conectar WhatsApp
              </Button>
            )}
            {modelo.status === "ativa" && modelo.evolution_instance_id && (
              <Button variant="secondary" onClick={onPausar} disabled={actionLoading}>Pausar atendimentos</Button>
            )}
            {modelo.status === "pausada" && (
              <Button variant="primary" onClick={onAtivar} disabled={actionLoading}>
                {actionLoading && <Loader2 className="animate-spin" />}
                Reativar atendimentos
              </Button>
            )}
          </div>
        </div>
      </header>

      <AbasModelo aba={aba} onChange={onAbaChange} />

      {aba === "perfil" && (
        <AbaPerfil
          key={modelo.id}
          modelo={modelo}
          catalogo={catalogo}
          duracoes={duracoes}
          programasVinculados={detalhe.programas}
          onDirtyChange={onDirtyChange}
          onSalvar={onSalvarPerfil}
          onVincularPrograma={onVincularPrograma}
          onAtualizarPrecoPrograma={onAtualizarPrecoPrograma}
          onDesvincularPrograma={onDesvincularPrograma}
          onTrocarNumero={onTrocarNumero}
          onConectar={onConectar}
          onDesparear={onDesparear}
          onUploadPerfil={onUploadPerfil}
          onRemoverFoto={onRemoverFoto}
        />
      )}
      {aba === "faq" && (
        <AbaFaq
          faq={detalhe.faq}
          onAdicionar={onAdicionarFaq}
          onEditar={onEditarFaq}
          onExcluir={onExcluirFaq}
        />
      )}
      {aba === "midia" && (
        <AbaMidia
          midia={detalhe.midia}
          onAdicionar={onAdicionarMidia}
          onOpen={onOpenMidia}
          onToggleAprovada={onToggleAprovadaMidia}
          onDelete={onExcluirMidia}
        />
      )}
    </section>
  )
}

function Chip({ warn, children }: { warn?: boolean; children: React.ReactNode }) {
  return (
    <span className={`rounded-full bg-ink-300 px-3 py-1 text-xs font-medium ${warn ? "text-state-handoff" : "text-text-muted"}`}>
      {children}
    </span>
  )
}

function EmptyDetalhe() {
  return (
    <section aria-label="Detalhe da modelo" className="rounded-lg border border-border bg-card p-6">
      <p className="text-sm text-text-primary">Nenhuma modelo selecionada.</p>
      <p className="mt-1 text-[13px] text-text-muted">Selecione uma modelo na lista ou adicione a primeira.</p>
    </section>
  )
}

function DetalheSkeleton() {
  return (
    <section aria-label="Detalhe da modelo" aria-busy="true" className="space-y-5">
      <Skeleton className="h-24 rounded-lg" />
      <Skeleton className="h-10 rounded-lg" />
      <Skeleton className="h-56 rounded-lg" />
      <Skeleton className="h-56 rounded-lg" />
      <Skeleton className="h-56 rounded-lg" />
    </section>
  )
}
