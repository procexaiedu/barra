"use client"

import { Suspense, useCallback, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Loader2, UserPlus } from "lucide-react"
import { toast } from "sonner"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { PageHeader } from "@/components/layout/PageHeader"
import { PainelDetalheResponsivo } from "@/components/layout/PainelDetalheResponsivo"
import { ToolbarModelos } from "@/components/modelos/ToolbarModelos"
import { ResumoModelos } from "@/components/modelos/ResumoModelos"
import { ListaModelos } from "@/components/modelos/ListaModelos"
import { DetalheModelo } from "@/components/modelos/DetalheModelo"
import { PainelProgramas } from "@/components/modelos/PainelProgramas"
import { PainelFetiches } from "@/components/modelos/PainelFetiches"
import { DialogCriarModelo } from "@/components/modelos/DialogCriarModelo"
import { DialogConectarWhatsapp, type QrModalStatus } from "@/components/modelos/DialogConectarWhatsapp"
import { DialogMidiaUpload } from "@/components/modelos/DialogMidiaUpload"
import { DialogVisualizarMidia } from "@/components/modelos/DialogVisualizarMidia"
import { useModelos } from "@/hooks/useModelos"
import { useProgramas } from "@/hooks/useProgramas"
import { useFetiches } from "@/hooks/useFetiches"
import type { AbaModelo, ConectarWhatsappResponse, MidiaItem } from "@/tipos/modelos"

type Confirmacao =
  | { tipo: "pausar" }
  | { tipo: "ativar" }
  | { tipo: "desparear" }
  | { tipo: "trocar-numero"; numero: string }
  | { tipo: "excluir-midia"; midia: MidiaItem }
  | { tipo: "descartar"; action: () => void }
  | null

type ViewModelos = "lista" | "programas" | "fetiches"

export default function Modelos() {
  return (
    <Suspense fallback={<div className="text-sm text-text-muted">Carregando modelos...</div>}>
      <ModelosConteudo />
    </Suspense>
  )
}

function ModelosConteudo() {
  const router = useRouter()
  const modelos = useModelos()
  const programas = useProgramas()
  const fetiches = useFetiches()
  const [view, setView] = useState<ViewModelos>("lista")
  const [criarOpen, setCriarOpen] = useState(false)
  const [uploadDialog, setUploadDialog] = useState<"midia" | "perfil" | null>(null)
  const [midiaAberta, setMidiaAberta] = useState<MidiaItem | null>(null)
  const [confirmacao, setConfirmacao] = useState<Confirmacao>(null)
  const [qrOpen, setQrOpen] = useState(false)
  const [criarQrAtivo, setCriarQrAtivo] = useState(false)
  const [qr, setQr] = useState<ConectarWhatsappResponse | null>(null)
  const [qrStatus, setQrStatus] = useState<QrModalStatus>("loading")
  const [qrError, setQrError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [detalheAberto, setDetalheAberto] = useState(false)

  const detalhe = modelos.detalhe
  const modelo = detalhe?.modelo ?? null
  const conectado = modelo?.evolution_status === "conectado"
  const esconderAdicionar =
    view === "programas" ||
    !conectado ||
    modelo?.status === "pausada" ||
    modelos.aba === "midia"

  // Status efetivo passado ao modal: deriva 'conectado' do detalhe quando o
  // modal já está aguardando o scan. Evita setState dentro de useEffect.
  const qrStatusEfetivo: QrModalStatus =
    (qrStatus === "aguardando_scan" || qrStatus === "conectando") && conectado
      ? "conectado"
      : qrStatus

  // Auto-fecha o modal ~800ms após o pareamento convergir (tanto o modal
  // dedicado quanto o fluxo embutido no DialogCriarModelo).
  useEffect(() => {
    if (!(qrOpen || criarQrAtivo) || qrStatusEfetivo !== "conectado") return
    toast.success("WhatsApp conectado")
    const timer = setTimeout(() => {
      if (qrOpen) setQrOpen(false)
      if (criarQrAtivo) {
        setCriarOpen(false)
        setCriarQrAtivo(false)
      }
    }, 800)
    return () => clearTimeout(timer)
  }, [qrOpen, criarQrAtivo, qrStatusEfetivo])

  // Polling defensivo: enquanto o modal aguarda o scan (ou já está conectando),
  // batemos no GET /whatsapp/status, que faz auto-cure consultando
  // connectionState na Evolution. Cobre dev sem tunnel (webhook não chega).
  // Vale para o modal dedicado e para a etapa de QR embutida no
  // DialogCriarModelo. Ao ver 'connecting' marcamos "conectando": isso para o
  // refresh de QR (abaixo), que reiniciaria o handshake do Baileys.
  useEffect(() => {
    if (
      (!qrOpen && !criarQrAtivo) ||
      (qrStatus !== "aguardando_scan" && qrStatus !== "conectando") ||
      !modelo?.id
    )
      return
    const id = modelo.id
    const intervalo = setInterval(async () => {
      try {
        const status = await modelos.whatsappStatus(id)
        if (status.status === "conectado") {
          await modelos.recarregarDetalhe()
        } else if (status.conexao_estado === "connecting") {
          setQrStatus((s) => (s === "aguardando_scan" ? "conectando" : s))
        }
      } catch {
        // silencioso: pequenas falhas de polling não devem travar o modal
      }
    }, 3000)
    return () => clearInterval(intervalo)
  }, [qrOpen, criarQrAtivo, qrStatus, modelo?.id, modelos])

  const protegerDirty = (action: () => void) => {
    if (modelos.dirty) setConfirmacao({ tipo: "descartar", action })
    else action()
  }

  const conectar = useCallback(
    async (confirmarRotacao = false) => {
      setQrOpen(true)
      setQrStatus("loading")
      setQrError(null)
      try {
        const res = await modelos.conectarWhatsapp(confirmarRotacao)
        setQr(res)
        setQrStatus(res?.status === "conectado" ? "conectado" : "aguardando_scan")
        // Recarregar detalhe para refletir evolution_status='pareando' no badge
        // antes do scan acontecer.
        await modelos.recarregarDetalhe()
      } catch (e) {
        setQrStatus("erro")
        setQrError(e instanceof Error ? e.message : "Erro ao conectar WhatsApp")
      }
    },
    [modelos],
  )

  // QR da Evolution expira em ~20-30s; enquanto o modal aguarda scan,
  // regeneramos o QR a cada 20s para o usuário nunca cair num código
  // expirado. POST /conectar-whatsapp é idempotente (instância já criada
  // → 403/401 tratados em criar_instancia).
  useEffect(() => {
    if ((!qrOpen && !criarQrAtivo) || qrStatus !== "aguardando_scan") return
    const intervalo = setInterval(() => {
      void conectar(true)
    }, 20000)
    return () => clearInterval(intervalo)
  }, [qrOpen, criarQrAtivo, qrStatus, conectar])

  const executarConfirmacao = async () => {
    if (!confirmacao || !modelo) return
    setSubmitting(true)
    try {
      if (confirmacao.tipo === "pausar") {
        await modelos.pausarModelo()
        toast.success(`Atendimentos de ${modelo.nome} pausados`)
      }
      if (confirmacao.tipo === "ativar") {
        const res = await modelos.ativarModelo()
        if (res && res.conversas_pausadas_pendentes > 0) {
          toast.success(`Atendimentos de ${modelo.nome} reativados`, {
            action: {
              label: "Ver conversas",
              onClick: () => router.push(`/atendimentos?ia_pausada=true&modelo_id=${modelo.id}`),
            },
          })
        } else {
          toast.success(`Atendimentos de ${modelo.nome} reativados`)
        }
      }
      if (confirmacao.tipo === "desparear") {
        await modelos.desparearWhatsapp()
        toast.success("WhatsApp removido")
      }
      if (confirmacao.tipo === "trocar-numero") {
        await modelos.patchModelo({ numero_whatsapp: confirmacao.numero })
        toast.success("WhatsApp atualizado")
        await conectar(true)
      }
      if (confirmacao.tipo === "excluir-midia") {
        await modelos.deletarMidia(confirmacao.midia.id)
        toast.success("Mídia removida")
      }
      if (confirmacao.tipo === "descartar") {
        modelos.setDirty(false)
        confirmacao.action()
      }
      setConfirmacao(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao executar ação")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-4">
        <PageHeader
          title="Modelos"
          description="Cadastro, conexão de WhatsApp e cardápio de cada modelo da agência."
          action={
            esconderAdicionar
              ? undefined
              : {
                  label: "Adicionar modelo",
                  onClick: () => setCriarOpen(true),
                  icon: <UserPlus size={16} strokeWidth={1.5} />,
                }
          }
        />

        <div role="tablist" aria-label="Visão" className="flex gap-1 border-b border-border">
          <TabBtn active={view === "lista"} onClick={() => protegerDirty(() => setView("lista"))}>
            Modelos
          </TabBtn>
          <TabBtn active={view === "programas"} onClick={() => protegerDirty(() => setView("programas"))}>
            Programas
          </TabBtn>
          <TabBtn active={view === "fetiches"} onClick={() => protegerDirty(() => setView("fetiches"))}>
            Fetiches
          </TabBtn>
        </div>
      </div>

      {view === "lista" && (
        <div className="flex flex-col gap-4">
          <ToolbarModelos filtros={modelos.filtros} onChange={(filtros) => modelos.setFiltros(filtros)} />
          <ResumoModelos resumo={modelos.resumo} status={modelos.resumoStatus} />
          <PainelDetalheResponsivo
            gridClassName="lg:grid-cols-[340px_1fr]"
            tituloDetalhe="Modelo"
            detalheAberto={detalheAberto}
            onFecharDetalhe={() => protegerDirty(() => setDetalheAberto(false))}
            lista={
              <ListaModelos
                items={modelos.items}
                selectedId={modelos.selectedId}
                status={modelos.listaStatus}
                error={modelos.listaError}
                filtrosAplicados={modelos.filtrosAplicados}
                nextCursor={modelos.nextCursor}
                onRetry={modelos.refetch}
                onAdicionar={() => setCriarOpen(true)}
                onCarregarMais={modelos.carregarMais}
                onSelect={(id) =>
                  protegerDirty(() => {
                    modelos.selecionarModelo(id)
                    setDetalheAberto(true)
                  })
                }
              />
            }
            detalhe={
              <DetalheModelo
              detalhe={modelos.detalhe}
              aba={modelos.aba}
              status={modelos.detalheStatus}
              error={modelos.detalheError}
              actionLoading={submitting}
              catalogo={programas.programas}
              duracoes={programas.duracoes}
              onRetry={modelos.refetch}
              onAbaChange={(aba: AbaModelo) => protegerDirty(() => modelos.setAba(aba))}
              onDirtyChange={modelos.setDirty}
              onSalvarPerfil={async (input) => {
                await modelos.patchModelo(input)
              }}
              onVincularPrograma={modelos.vincularProgramaModelo}
              onAtualizarPrecoPrograma={modelos.atualizarPrecoProgramaModelo}
              onDesvincularPrograma={modelos.desvincularProgramaModelo}
              onCriarPrograma={programas.criarPrograma}
              onCriarDuracao={programas.criarDuracao}
              catalogoFetiches={fetiches.fetiches}
              onVincularFetiche={modelos.vincularFeticheModelo}
              onAtualizarPrecoFetiche={modelos.atualizarPrecoFeticheModelo}
              onDesvincularFetiche={modelos.desvincularFeticheModelo}
              onCriarFetiche={fetiches.criarFetiche}
              onTrocarNumero={(numero) => setConfirmacao({ tipo: "trocar-numero", numero })}
              onConectar={() => conectar(false)}
              onPausar={() => setConfirmacao({ tipo: "pausar" })}
              onAtivar={() => setConfirmacao({ tipo: "ativar" })}
              onDesparear={() => setConfirmacao({ tipo: "desparear" })}
              onUploadPerfil={() => setUploadDialog("perfil")}
              onRemoverFoto={() => modelos.atualizarFotoPerfil(null)}
              onAdicionarMidia={() => setUploadDialog("midia")}
              onOpenMidia={setMidiaAberta}
              onToggleAprovadaMidia={(midia) => modelos.atualizarMidia(midia.id, { aprovada: !midia.aprovada })}
              onExcluirMidia={(midia) => setConfirmacao({ tipo: "excluir-midia", midia })}
              />
            }
          />
        </div>
      )}

      {view === "programas" && (
        <PainelProgramas
          programas={programas.programas}
          duracoes={programas.duracoes}
          status={programas.status}
          error={programas.error}
          onRetry={programas.carregar}
          onCriarPrograma={programas.criarPrograma}
          onAtualizarPrograma={programas.atualizarPrograma}
          onExcluirPrograma={programas.excluirPrograma}
          onCriarDuracao={programas.criarDuracao}
          onAtualizarDuracao={programas.atualizarDuracao}
          onExcluirDuracao={programas.excluirDuracao}
        />
      )}

      {view === "fetiches" && (
        <PainelFetiches
          fetiches={fetiches.fetiches}
          status={fetiches.status}
          error={fetiches.error}
          onRetry={fetiches.carregar}
          onCriar={fetiches.criarFetiche}
          onAtualizar={fetiches.atualizarFetiche}
          onExcluir={fetiches.excluirFetiche}
        />
      )}

      <DialogCriarModelo
        open={criarOpen}
        onOpenChange={(value) => {
          setCriarOpen(value)
          if (!value && criarQrAtivo) {
            setCriarQrAtivo(false)
            setQr(null)
            setQrStatus("loading")
            setQrError(null)
          }
        }}
        onCriar={async (input) => {
          await modelos.criarModelo(input)
        }}
        onConectar={async () => {
          setCriarQrAtivo(true)
          await conectar(false)
        }}
        qr={qr}
        qrStatus={qrStatusEfetivo}
        qrError={qrError}
        onAtualizar={() => conectar(true)}
      />
      <DialogConectarWhatsapp
        open={qrOpen}
        modelo={modelo}
        qr={qr}
        status={qrStatusEfetivo}
        error={qrError}
        onOpenChange={setQrOpen}
        onAtualizar={() => conectar(true)}
      />
      <DialogMidiaUpload
        open={uploadDialog !== null}
        modo={uploadDialog ?? "midia"}
        onOpenChange={(open) => !open && setUploadDialog(null)}
        onCriarUploadUrl={modelos.criarUploadUrl}
        onConfirmarMidia={modelos.criarMidia}
        onConfirmarPerfil={modelos.atualizarFotoPerfil}
      />
      <DialogVisualizarMidia midia={midiaAberta} onOpenChange={(open) => !open && setMidiaAberta(null)} />
      <ConfirmacaoDialog
        confirmacao={confirmacao}
        nome={modelo?.nome ?? ""}
        conversasPausadas={detalhe?.indicadores.conversas_ia_pausada ?? 0}
        emExecucao={0}
        submitting={submitting}
        onCancel={() => setConfirmacao(null)}
        onConfirm={executarConfirmacao}
      />
    </div>
  )
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`relative px-3 pb-2.5 pt-1 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
        active
          ? "text-text-primary after:absolute after:inset-x-0 after:-bottom-px after:h-px after:bg-gold-500"
          : "text-text-muted hover:text-text-secondary"
      }`}
    >
      {children}
    </button>
  )
}

function ConfirmacaoDialog({
  confirmacao,
  nome,
  conversasPausadas,
  emExecucao,
  submitting,
  onCancel,
  onConfirm,
}: {
  confirmacao: Confirmacao
  nome: string
  conversasPausadas: number
  emExecucao: number
  submitting: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const textos = getTextos(confirmacao, nome, conversasPausadas, emExecucao)
  return (
    <AlertDialog open={confirmacao !== null} onOpenChange={(open) => !open && onCancel()}>
      <AlertDialogContent className="max-w-md bg-card">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-lg font-semibold text-text-primary">{textos.titulo}</AlertDialogTitle>
          <AlertDialogDescription className="whitespace-pre-line text-sm text-text-secondary">{textos.descricao}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={submitting} onClick={onCancel}>Cancelar</AlertDialogCancel>
          <AlertDialogAction variant={textos.variant} onClick={onConfirm} disabled={submitting}>
            {submitting && <Loader2 className="animate-spin" />}
            {textos.confirmar}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function getTextos(
  confirmacao: Confirmacao,
  nome: string,
  conversasPausadas: number,
  emExecucao: number
) {
  if (confirmacao?.tipo === "pausar") {
    return {
      titulo: `Pausar ${nome}?`,
      descricao: `${conversasPausadas} conversa(s) ativa(s) ficam em pausa. ${emExecucao} atendimento(s) em andamento continuam preservados.`,
      confirmar: "Confirmar pausa",
      variant: "primary" as const,
    }
  }
  if (confirmacao?.tipo === "ativar") {
    return {
      titulo: `Reativar ${nome}?`,
      descricao: "A modelo volta a receber novos atendimentos. Conversas pausadas continuam paradas até você liberar uma por uma na Central de Atendimentos.",
      confirmar: "Confirmar reativação",
      variant: "primary" as const,
    }
  }
  if (confirmacao?.tipo === "desparear") {
    return {
      titulo: `Remover WhatsApp de ${nome}?`,
      descricao: "Novas mensagens automáticas ficam pausadas até o número ser conectado novamente.",
      confirmar: "Remover conexão",
      variant: "danger" as const,
    }
  }
  if (confirmacao?.tipo === "trocar-numero") {
    return {
      titulo: `Trocar número de ${nome}?`,
      descricao: "A conexão atual será removida. Depois disso, escaneie um novo QR code para ativar o número.",
      confirmar: "Confirmar troca",
      variant: "primary" as const,
    }
  }
  if (confirmacao?.tipo === "excluir-midia") {
    return {
      titulo: "Remover esta mídia?",
      descricao: "Esta foto ou vídeo deixa de ficar disponível no atendimento.",
      confirmar: "Remover",
      variant: "danger" as const,
    }
  }
  if (confirmacao?.tipo === "descartar") {
    return {
      titulo: "Descartar alterações não salvas?",
      descricao: "As alterações locais deste bloco serão perdidas.",
      confirmar: "Descartar",
      variant: "danger" as const,
    }
  }
  return { titulo: "", descricao: "", confirmar: "Confirmar", variant: "primary" as const }
}
