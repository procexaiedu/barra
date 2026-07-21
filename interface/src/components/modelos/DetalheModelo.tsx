"use client"

import { Loader2, UserRound } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import { AbasModelo } from "@/components/modelos/AbasModelo"
import { AbaMidia } from "@/components/modelos/AbaMidia"
import { AbaPerfil } from "@/components/modelos/AbaPerfil"
import { DisponibilidadeModelo } from "@/components/modelos/DisponibilidadeModelo"
import { FotoPerfil } from "@/components/modelos/FotoPerfil"
import type {
  AbaModelo,
  Duracao,
  DuracaoInput,
  Fetiche,
  FeticheInput,
  MidiaItem,
  ModeloDetalheResponse,
  PatchModeloInput,
  Programa,
  ProgramaInput,
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
  onCriarPrograma,
  onCriarDuracao,
  catalogoFetiches,
  onVincularFetiche,
  onAtualizarFetiche,
  onDesvincularFetiche,
  onCriarFetiche,
  onTrocarNumero,
  onConectar,
  onPausar,
  onAtivar,
  onDesparear,
  onUploadPerfil,
  onRemoverFoto,
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
  onCriarPrograma: (input: ProgramaInput) => Promise<Programa>
  onCriarDuracao: (input: DuracaoInput) => Promise<Duracao>
  catalogoFetiches: Fetiche[]
  onVincularFetiche: (feticheId: string, pago: boolean) => Promise<void>
  onAtualizarFetiche: (feticheId: string, pago: boolean) => Promise<void>
  onDesvincularFetiche: (feticheId: string) => Promise<void>
  onCriarFetiche: (input: FeticheInput) => Promise<Fetiche>
  onTrocarNumero: (numero: string) => void
  onConectar: () => void
  onPausar: () => void
  onAtivar: () => void
  onDesparear: () => void
  onUploadPerfil: () => void
  onRemoverFoto: () => Promise<void>
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
    <section aria-label="Detalhe da modelo" className="flex min-w-0 flex-col gap-4">
      <Card className="px-4 shadow-elev-1">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <FotoPerfil url={modelo.foto_perfil_url} nome={modelo.nome} size="sm" />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="truncate text-base font-semibold text-text-primary">{modelo.nome}</h2>
                <Badge variant={badge.variant} className="shrink-0 px-2 py-0.5 text-[11px]">{badge.label}</Badge>
              </div>
              <p className="truncate text-xs text-text-muted">
                {modelo.idade} anos · {modelo.idiomas.join(", ")} · {modelo.localizacao_operacional ?? "sem região"}
                {modelo.evolution_status !== "conectado" && (
                  <span
                    className={
                      modelo.evolution_status === "pareando" ? "ml-2 text-state-info" : "ml-2 text-state-handoff"
                    }
                  >
                    {modelo.evolution_status === "pareando" ? "Pareando…" : "WhatsApp pendente"}
                  </span>
                )}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            {modelo.evolution_status !== "conectado" && (
              <Button variant="primary" size="sm" onClick={onConectar} disabled={actionLoading}>
                {actionLoading && <Loader2 className="animate-spin" />}
                {modelo.evolution_status === "pareando" ? "Reabrir QR" : "Conectar WhatsApp"}
              </Button>
            )}
            {modelo.status === "ativa" && modelo.evolution_status === "conectado" && (
              <Button variant="secondary" size="sm" onClick={onPausar} disabled={actionLoading}>Pausar atendimentos</Button>
            )}
            {modelo.status === "pausada" && (
              <Button variant="primary" size="sm" onClick={onAtivar} disabled={actionLoading}>
                {actionLoading && <Loader2 className="animate-spin" />}
                Reativar atendimentos
              </Button>
            )}
          </div>
        </div>
      </Card>

      <AbasModelo aba={aba} onChange={onAbaChange} />

      {aba === "perfil" && (
        <AbaPerfil
          key={modelo.id}
          modelo={modelo}
          catalogo={catalogo}
          duracoes={duracoes}
          programasVinculados={detalhe.programas}
          fetichesVinculados={detalhe.fetiches}
          catalogoFetiches={catalogoFetiches}
          onDirtyChange={onDirtyChange}
          onSalvar={onSalvarPerfil}
          onVincularPrograma={onVincularPrograma}
          onAtualizarPrecoPrograma={onAtualizarPrecoPrograma}
          onDesvincularPrograma={onDesvincularPrograma}
          onCriarPrograma={onCriarPrograma}
          onCriarDuracao={onCriarDuracao}
          onVincularFetiche={onVincularFetiche}
          onAtualizarFetiche={onAtualizarFetiche}
          onDesvincularFetiche={onDesvincularFetiche}
          onCriarFetiche={onCriarFetiche}
          onTrocarNumero={onTrocarNumero}
          onConectar={onConectar}
          onDesparear={onDesparear}
          onUploadPerfil={onUploadPerfil}
          onRemoverFoto={onRemoverFoto}
        />
      )}
      {aba === "disponibilidade" && (
        <DisponibilidadeModelo key={modelo.id} modeloId={modelo.id} statusModelo={modelo.status} />
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

function EmptyDetalhe() {
  return (
    <section aria-label="Detalhe da modelo">
      <Card>
        <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
          <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
            <UserRound size={22} strokeWidth={1.75} className="text-text-muted" />
          </div>
          <div>
            <p className="text-sm font-medium text-text-primary">Nenhuma modelo selecionada.</p>
            <p className="mt-1 text-[13px] text-text-muted">Selecione uma modelo na lista ou adicione a primeira.</p>
          </div>
        </div>
      </Card>
    </section>
  )
}

function DetalheSkeleton() {
  return (
    <section aria-label="Detalhe da modelo" aria-busy="true" className="flex flex-col gap-4">
      <Skeleton className="h-[72px] rounded-lg" />
      <Skeleton className="h-10 rounded-lg" />
      <Skeleton className="h-56 rounded-lg" />
      <Skeleton className="h-56 rounded-lg" />
      <Skeleton className="h-56 rounded-lg" />
    </section>
  )
}
