"use client"

import { Suspense, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Loader2 } from "lucide-react"
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
import { HeaderModelos } from "@/components/modelos/HeaderModelos"
import { ToolbarModelos } from "@/components/modelos/ToolbarModelos"
import { ListaModelos } from "@/components/modelos/ListaModelos"
import { DetalheModelo } from "@/components/modelos/DetalheModelo"
import { PainelProgramas } from "@/components/modelos/PainelProgramas"
import { DialogCriarModelo } from "@/components/modelos/DialogCriarModelo"
import { DialogConectarWhatsapp } from "@/components/modelos/DialogConectarWhatsapp"
import { DialogFaq } from "@/components/modelos/DialogFaq"
import { DialogMidiaUpload } from "@/components/modelos/DialogMidiaUpload"
import { DialogVisualizarMidia } from "@/components/modelos/DialogVisualizarMidia"
import { useModelos } from "@/hooks/useModelos"
import { useProgramas } from "@/hooks/useProgramas"
import type { AbaModelo, ConectarWhatsappResponse, FaqItem, MidiaItem } from "@/tipos/modelos"

type Confirmacao =
  | { tipo: "pausar" }
  | { tipo: "ativar" }
  | { tipo: "desparear" }
  | { tipo: "trocar-numero"; numero: string }
  | { tipo: "excluir-faq"; faq: FaqItem }
  | { tipo: "excluir-midia"; midia: MidiaItem }
  | { tipo: "descartar"; action: () => void }
  | null

type ViewModelos = "lista" | "programas"

export default function Modelos() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-[1280px] text-sm text-text-muted">Carregando modelos...</div>}>
      <ModelosConteudo />
    </Suspense>
  )
}

function ModelosConteudo() {
  const router = useRouter()
  const modelos = useModelos()
  const programas = useProgramas()
  const [view, setView] = useState<ViewModelos>("lista")
  const [criarOpen, setCriarOpen] = useState(false)
  const [faqDialog, setFaqDialog] = useState<{ open: boolean; faq: FaqItem | null }>({ open: false, faq: null })
  const [uploadDialog, setUploadDialog] = useState<"midia" | "perfil" | null>(null)
  const [midiaAberta, setMidiaAberta] = useState<MidiaItem | null>(null)
  const [confirmacao, setConfirmacao] = useState<Confirmacao>(null)
  const [qrOpen, setQrOpen] = useState(false)
  const [qr, setQr] = useState<ConectarWhatsappResponse | null>(null)
  const [qrStatus, setQrStatus] = useState<"idle" | "loading" | "success" | "error">("idle")
  const [qrError, setQrError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const detalhe = modelos.detalhe
  const modelo = detalhe?.modelo ?? null
  const esconderAdicionar =
    view === "programas" ||
    modelo?.evolution_instance_id === null ||
    modelo?.status === "pausada" ||
    modelos.aba === "midia"

  useEffect(() => {
    if (qrOpen && modelo?.evolution_instance_id) {
      toast.success("WhatsApp conectado")
      const timer = setTimeout(() => setQrOpen(false), 0)
      return () => clearTimeout(timer)
    }
  }, [modelo?.evolution_instance_id, qrOpen])

  const protegerDirty = (action: () => void) => {
    if (modelos.dirty) setConfirmacao({ tipo: "descartar", action })
    else action()
  }

  const conectar = async (confirmarRotacao = false) => {
    setQrOpen(true)
    setQrStatus("loading")
    setQrError(null)
    try {
      const res = await modelos.conectarWhatsapp(confirmarRotacao)
      setQr(res)
      setQrStatus("success")
    } catch (e) {
      setQrStatus("error")
      setQrError(e instanceof Error ? e.message : "Erro ao conectar WhatsApp")
    }
  }

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
      if (confirmacao.tipo === "excluir-faq") {
        await modelos.deletarFaq(confirmacao.faq.id)
        toast.success("Resposta removida")
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
    <div className="mx-auto max-w-[1280px] space-y-6">
      <HeaderModelos esconderAdicionar={esconderAdicionar} onAdicionar={() => setCriarOpen(true)} />

      <div className="flex gap-2 border-b border-border pb-0">
        <TabBtn active={view === "lista"} onClick={() => protegerDirty(() => setView("lista"))}>
          Modelos
        </TabBtn>
        <TabBtn active={view === "programas"} onClick={() => protegerDirty(() => setView("programas"))}>
          Programas
        </TabBtn>
      </div>

      {view === "lista" && (
        <>
          <ToolbarModelos filtros={modelos.filtros} onChange={(filtros) => modelos.setFiltros(filtros)} />
          <div className="grid gap-6 xl:grid-cols-[360px_1fr]">
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
              onSelect={(id) => protegerDirty(() => modelos.selecionarModelo(id))}
            />
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
              onTrocarNumero={(numero) => setConfirmacao({ tipo: "trocar-numero", numero })}
              onConectar={() => conectar(false)}
              onPausar={() => setConfirmacao({ tipo: "pausar" })}
              onAtivar={() => setConfirmacao({ tipo: "ativar" })}
              onDesparear={() => setConfirmacao({ tipo: "desparear" })}
              onUploadPerfil={() => setUploadDialog("perfil")}
              onRemoverFoto={() => modelos.atualizarFotoPerfil(null)}
              onAdicionarFaq={() => setFaqDialog({ open: true, faq: null })}
              onEditarFaq={(faq) => setFaqDialog({ open: true, faq })}
              onExcluirFaq={(faq) => setConfirmacao({ tipo: "excluir-faq", faq })}
              onAdicionarMidia={() => setUploadDialog("midia")}
              onOpenMidia={setMidiaAberta}
              onToggleAprovadaMidia={(midia) => modelos.atualizarMidia(midia.id, { aprovada: !midia.aprovada })}
              onExcluirMidia={(midia) => setConfirmacao({ tipo: "excluir-midia", midia })}
            />
          </div>
        </>
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

      <DialogCriarModelo
        open={criarOpen}
        onOpenChange={setCriarOpen}
        onCriar={async (input) => {
          await modelos.criarModelo(input)
        }}
      />
      <DialogConectarWhatsapp
        open={qrOpen}
        modelo={modelo}
        qr={qr}
        status={qrStatus}
        error={qrError}
        onOpenChange={setQrOpen}
        onAtualizar={() => conectar(true)}
      />
      {faqDialog.open && (
        <DialogFaq
          key={faqDialog.faq?.id ?? "nova"}
          open={faqDialog.open}
          faq={faqDialog.faq}
          onOpenChange={(open) => setFaqDialog((atual) => ({ ...atual, open }))}
          onSalvar={modelos.salvarFaq}
        />
      )}
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
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium transition-colors ${
        active
          ? "border-b-2 border-primary text-text-primary"
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
  if (confirmacao?.tipo === "excluir-faq") {
    return {
      titulo: "Remover esta resposta?",
      descricao: "Esta orientação deixa de aparecer nos atendimentos.",
      confirmar: "Remover",
      variant: "danger" as const,
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
