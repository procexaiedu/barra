"use client"

import { useState, useEffect, type ReactNode } from "react"
import Link from "next/link"
import {
  ExternalLink,
  Clock,
  CheckCircle2,
  XCircle,
  Circle,
  ReceiptText,
  Sparkles,
  User,
  MessageSquare,
  CreditCard,
  Target,
  CalendarClock,
  MapPin,
  Image as ImageIcon,
} from "lucide-react"
import { toast } from "sonner"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
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
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { formatTempoRelativo, formatBRL, formatData, formatHorario, formatRotulo } from "@/lib/formatters"
import { motivoExibido, sinaisParaTipo } from "@/components/atendimentos/utils"
import { cn } from "@/lib/utils"
import type { CardDestaque, IaPausadaMotivo } from "@/tipos/painel"

// ── tipos locais ──────────────────────────────────────────────────────────────

type MotivoRejeicao =
  | "valor_incorreto"
  | "comprovante_ilegivel"
  | "conta_destino_errada"
  | "duplicado"
  | "fora_da_janela"
  | "outro"

type MotivoPerda = "preco" | "sumiu" | "risco" | "indisponibilidade" | "fora_de_area" | "outro"

const MOTIVO_REJEICAO_LABEL: Record<MotivoRejeicao, string> = {
  valor_incorreto: "Valor incorreto",
  comprovante_ilegivel: "Comprovante ilegível",
  conta_destino_errada: "Conta de destino errada",
  duplicado: "Duplicado",
  fora_da_janela: "Fora da janela de tempo",
  outro: "Outro",
}

const MOTIVO_PERDA_LABEL: Record<MotivoPerda, string> = {
  preco: "Preço",
  sumiu: "Sumiu",
  risco: "Risco",
  indisponibilidade: "Indisponibilidade",
  fora_de_area: "Fora da área",
  outro: "Outro",
}

type Mensagem = {
  id: string
  direcao: "cliente" | "ia" | "modelo_manual"
  tipo: string
  conteudo: string | null
}

type ComprovantePix = {
  id: string
  valor_extraido: number | null
  titular_extraido: string | null
  motivo_em_revisao: string | null
}

type SinaisQualificacao = {
  informa_horario?: boolean
  informa_local?: boolean
  aceita_valor?: boolean
  envia_pix?: boolean
}

type ContextoData = {
  atendimento: {
    motivo_escalada: string | null
    proxima_acao_esperada: string | null
    valor_acordado: number | null
    ia_pausada_em: string
    estado: string | null
    tipo_atendimento: string | null
    data_desejada: string | null
    horario_desejado: string | null
    duracao_horas: number | null
    endereco: string | null
    bairro: string | null
    tipo_local: string | null
    referencia_local: string | null
    forma_pagamento: string | null
    resumo_operacional: string | null
    sinais_qualificacao: SinaisQualificacao | null
    foto_portaria_em: string | null
    pix_status: string | null
  }
  conversa: {
    id: string
    recorrente: boolean | null
    observacoes_internas: string | null
    ultimo_motivo_perda: string | null
  } | null
  bloqueio: {
    id: string
    inicio: string
    fim: string
    estado: string
  } | null
  mensagens: Mensagem[]
  comprovantes_pix: ComprovantePix[]
}

// ── mapa de badge ─────────────────────────────────────────────────────────────

const BADGE_VARIANT: Record<IaPausadaMotivo, "revisao" | "handoff" | "paused"> = {
  pix_em_revisao: "revisao",
  handoff_ia: "handoff",
  modelo_em_atendimento: "paused",
}

const BADGE_LABEL: Record<IaPausadaMotivo, string> = {
  pix_em_revisao: "Pix em revisão",
  handoff_ia: "Aguardando você",
  modelo_em_atendimento: "Modelo atendendo",
}

// ── componente principal ──────────────────────────────────────────────────────

export function ModalDecisaoCard({
  card,
  onClose,
}: {
  card: CardDestaque | null
  onClose: () => void
}) {
  const [contexto, setContexto] = useState<ContextoData | null>(null)
  const [pixUrl, setPixUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [loadingAcao, setLoadingAcao] = useState(false)

  // dialogs
  const [rejeitarAberto, setRejeitarAberto] = useState(false)
  const [motivoRejeicao, setMotivoRejeicao] = useState<MotivoRejeicao>("valor_incorreto")
  const [observacaoRejeicao, setObservacaoRejeicao] = useState("")
  const [fecharAberto, setFecharAberto] = useState(false)
  const [valorFinal, setValorFinal] = useState("")
  const [perderAberto, setPerderAberto] = useState(false)
  const [motivoPerda, setMotivoPerda] = useState<MotivoPerda>("preco")
  const [observacaoPerda, setObservacaoPerda] = useState("")

  const atendimentoId = card?.atendimento_id
  useEffect(() => {
    if (!atendimentoId) return
    let active = true
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true)
    setErro(null)
    setContexto(null)
    setPixUrl(null)

    api<{ atendimento: ContextoData["atendimento"]; conversa: ContextoData["conversa"]; bloqueio: ContextoData["bloqueio"]; mensagens: Mensagem[]; comprovantes_pix: ComprovantePix[] }>(
      `/v1/atendimentos/${atendimentoId}`,
    )
      .then(async (data) => {
        if (!active) return
        setContexto({
          atendimento: data.atendimento,
          conversa: data.conversa ?? null,
          bloqueio: data.bloqueio ?? null,
          mensagens: data.mensagens,
          comprovantes_pix: data.comprovantes_pix,
        })
        if (data.comprovantes_pix.length > 0) {
          try {
            const { url } = await api<{ url: string }>(
              `/v1/pix/${data.comprovantes_pix[0].id}/comprovante-url`,
            )
            if (active) setPixUrl(url)
          } catch {
            // URL do comprovante é opcional
          }
        }
      })
      .catch((e) => {
        if (active) setErro(e instanceof Error ? e.message : "Erro ao carregar contexto")
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => { active = false }
  }, [atendimentoId])

  async function handleDevolver() {
    if (!card) return
    setLoadingAcao(true)
    try {
      await api(`/v1/atendimentos/${card.atendimento_id}/devolver`, {
        method: "POST",
        body: JSON.stringify({}),
      })
      toast.success(`Atendimento #${card.numero_curto} devolvido para a IA`)
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao devolver")
    } finally {
      setLoadingAcao(false)
    }
  }

  async function handleAprovarPix() {
    if (!card || !contexto?.comprovantes_pix[0]) return
    setLoadingAcao(true)
    try {
      await api(`/v1/pix/${contexto.comprovantes_pix[0].id}/aprovar`, {
        method: "POST",
        body: JSON.stringify({}),
      })
      toast.success("Pix aprovado — saída confirmada")
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao aprovar Pix")
    } finally {
      setLoadingAcao(false)
    }
  }

  async function handleRejeitarPix() {
    if (!card || !contexto?.comprovantes_pix[0]) return
    setLoadingAcao(true)
    try {
      await api(`/v1/pix/${contexto.comprovantes_pix[0].id}/rejeitar`, {
        method: "POST",
        body: JSON.stringify({ motivo: motivoRejeicao, observacao: observacaoRejeicao || null }),
      })
      toast.success("Pix rejeitado — cliente será notificado")
      setRejeitarAberto(false)
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao rejeitar Pix")
    } finally {
      setLoadingAcao(false)
    }
  }

  async function handleFechar() {
    if (!card) return
    const valor = parseFloat(valorFinal.replace(",", "."))
    if (isNaN(valor) || valor <= 0) {
      toast.error("Informe um valor válido")
      return
    }
    setLoadingAcao(true)
    try {
      await api(`/v1/atendimentos/${card.atendimento_id}/fechar`, {
        method: "POST",
        body: JSON.stringify({ valor_final: valor }),
      })
      toast.success(`Atendimento #${card.numero_curto} fechado — ${formatBRL(valor)}`)
      setFecharAberto(false)
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao fechar")
    } finally {
      setLoadingAcao(false)
    }
  }

  async function handlePerder() {
    if (!card) return
    if (motivoPerda === "outro" && !observacaoPerda.trim()) {
      toast.error("Informe o motivo quando selecionar 'Outro'")
      return
    }
    setLoadingAcao(true)
    try {
      await api(`/v1/atendimentos/${card.atendimento_id}/perder`, {
        method: "POST",
        body: JSON.stringify({
          motivo: motivoPerda,
          observacao: observacaoPerda || null,
        }),
      })
      toast.success(`Atendimento #${card.numero_curto} registrado como perdido`)
      setPerderAberto(false)
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao registrar perda")
    } finally {
      setLoadingAcao(false)
    }
  }

  const nomeCliente = card ? (card.cliente_nome ?? card.cliente_telefone_formatado) : ""
  const comprovante = contexto?.comprovantes_pix[0] ?? null
  const mensagensOrdenadas = contexto ? [...contexto.mensagens.slice(0, 10)].reverse() : []
  const isPix = card?.ia_pausada_motivo === "pix_em_revisao"
  const isHandoff = card?.ia_pausada_motivo === "handoff_ia"
  const isModeloAtendendo = card?.ia_pausada_motivo === "modelo_em_atendimento"
  const isEmExecucao = isModeloAtendendo && contexto?.atendimento.estado === "Em_execucao"
  const isConfirmado = isModeloAtendendo && contexto?.atendimento.estado === "Confirmado"

  const motivoTexto = card
    ? motivoExibido(card.motivo_escalada, card.ia_pausada_motivo) ?? "Aguardando decisão"
    : ""

  return (
    <>
      <Dialog open={card !== null} onOpenChange={(v) => { if (!v) onClose() }}>
        <DialogContent className="flex w-[min(96vw,88rem)] max-h-[92vh] min-h-[70vh] flex-col rounded-xl bg-card p-0 shadow-xl ring-1 ring-border">
          {/* ── header ──────────────────────────────────────────── */}
          <header className="flex items-center gap-3 border-b border-border px-8 py-4">
            {card && (
              <>
                <Badge variant={BADGE_VARIANT[card.ia_pausada_motivo]}>
                  {BADGE_LABEL[card.ia_pausada_motivo]}
                </Badge>
                <DialogTitle className="text-base font-semibold text-text-primary">
                  {nomeCliente}
                </DialogTitle>
                <span className="shrink-0 text-xs text-text-muted">
                  {card.modelo_nome} · #{card.numero_curto}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  nativeButton={false}
                  className="ml-auto shrink-0 gap-1 px-2 text-xs text-text-muted"
                  render={
                    <Link
                      href={`/atendimentos?id=${card.atendimento_id}`}
                      onClick={onClose}
                      aria-label="Ver atendimento completo"
                    />
                  }
                >
                  <ExternalLink size={13} />
                  Ver completo
                </Button>
              </>
            )}
          </header>

          {/* ── corpo ───────────────────────────────────────────── */}
          <div className="flex-1 overflow-y-auto px-8 py-6">
            {loading && (
              <div className="space-y-4">
                <Skeleton className="h-32 w-full rounded-md" />
                <div className="grid gap-4 lg:grid-cols-2">
                  <Skeleton className="h-44 w-full rounded-md" />
                  <Skeleton className="h-44 w-full rounded-md" />
                </div>
              </div>
            )}

            {erro && !loading && (
              <p className="text-sm text-danger-500">{erro}</p>
            )}

            {!loading && !erro && contexto && card && (
              <>
                {/* ── HERO KPI ──────────────────────────────────── */}
                <HeroKPI
                  card={card}
                  motivoTexto={motivoTexto}
                  contexto={contexto}
                  isPix={isPix}
                  isEmExecucao={isEmExecucao}
                />

                {/* ── GRID ───────────────────────────────────────── */}
                {/* Pix: 2 col (info + imagem grande). Outros casos: 3 col em xl */}
                <div className={cn(
                  "mt-6 grid gap-6",
                  isPix ? "lg:grid-cols-2" : "lg:grid-cols-2 xl:grid-cols-3"
                )}>
                  {/* PIX EM REVISÃO */}
                  {isPix && comprovante && (
                    <>
                      <SecaoPix
                        comprovante={comprovante}
                        valorAcordado={contexto.atendimento.valor_acordado}
                      />
                      <SecaoComprovanteImagem pixUrl={pixUrl} />
                    </>
                  )}

                  {/* HANDOFF IA — 3 colunas em xl: cliente | comercial+sinais | resumo+mensagens */}
                  {isHandoff && (
                    <>
                      <div className="space-y-4">
                        <SecaoFichaCliente conversa={contexto.conversa} />
                        {contexto.atendimento.sinais_qualificacao && (
                          <SecaoSinaisQualificacao
                            sinais={contexto.atendimento.sinais_qualificacao}
                            tipo={contexto.atendimento.tipo_atendimento}
                          />
                        )}
                      </div>
                      <div className="space-y-4">
                        <SecaoDadosComerciais atendimento={contexto.atendimento} />
                        {contexto.atendimento.resumo_operacional && (
                          <SecaoResumoOperacional resumo={contexto.atendimento.resumo_operacional} />
                        )}
                      </div>
                      <div className="space-y-4">
                        {mensagensOrdenadas.length > 0 && (
                          <SecaoMensagens mensagens={mensagensOrdenadas} />
                        )}
                      </div>
                    </>
                  )}

                  {/* MODELO EM EXECUÇÃO */}
                  {isEmExecucao && (
                    <>
                      <SecaoDadosAtendimento
                        atendimento={contexto.atendimento}
                        bloqueio={contexto.bloqueio}
                      />
                      {contexto.atendimento.resumo_operacional ? (
                        <SecaoResumoOperacional resumo={contexto.atendimento.resumo_operacional} />
                      ) : (
                        <SecaoBloco
                          titulo="Análise da IA"
                          icone={<Sparkles size={14} strokeWidth={1.75} className="text-gold-500" />}
                        >
                          <p className="text-[13px] text-text-disabled">
                            Sem análise registrada para esta etapa.
                          </p>
                        </SecaoBloco>
                      )}
                    </>
                  )}

                  {/* MODELO CONFIRMADO */}
                  {isConfirmado && (
                    <>
                      <SecaoDadosAtendimento
                        atendimento={contexto.atendimento}
                        bloqueio={contexto.bloqueio}
                      />
                      <SecaoBloco
                        titulo="Pix de deslocamento"
                        icone={<CreditCard size={14} strokeWidth={1.75} className="text-success-500" />}
                      >
                        {comprovante?.valor_extraido != null ? (
                          <div className="flex items-center gap-2">
                            <CheckCircle2 size={16} className="text-success-500" />
                            <span className="text-[14px] font-medium text-success-500">
                              {formatBRL(comprovante.valor_extraido)} validado
                            </span>
                          </div>
                        ) : (
                          <p className="text-[13px] text-text-disabled">
                            Sem comprovante de Pix vinculado.
                          </p>
                        )}
                      </SecaoBloco>
                    </>
                  )}
                </div>
              </>
            )}
          </div>

          {/* ── footer com ações ────────────────────────────────── */}
          {!loading && !erro && contexto && (
            <footer className="flex justify-end gap-2 border-t border-border px-8 py-3">
              <Button variant="ghost" size="sm" onClick={onClose} disabled={loadingAcao}>
                Cancelar
              </Button>

              {isPix && comprovante && (
                <>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setRejeitarAberto(true)}
                    disabled={loadingAcao}
                  >
                    Rejeitar Pix
                  </Button>
                  <Button size="sm" onClick={handleAprovarPix} disabled={loadingAcao}>
                    {loadingAcao ? "Aprovando…" : "Aprovar Pix"}
                  </Button>
                </>
              )}

              {isEmExecucao && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleDevolver}
                    disabled={loadingAcao}
                    className="text-text-muted"
                  >
                    Devolver IA
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setPerderAberto(true)}
                    disabled={loadingAcao}
                  >
                    Perdeu
                  </Button>
                  <Button size="sm" onClick={() => setFecharAberto(true)} disabled={loadingAcao}>
                    Fechar
                  </Button>
                </>
              )}

              {(isHandoff || isConfirmado) && (
                <Button size="sm" onClick={handleDevolver} disabled={loadingAcao}>
                  {loadingAcao ? "Devolvendo…" : "Devolver para IA"}
                </Button>
              )}
            </footer>
          )}
        </DialogContent>
      </Dialog>

      {/* ── AlertDialog: rejeitar Pix ──────────────────────────── */}
      <AlertDialog open={rejeitarAberto} onOpenChange={setRejeitarAberto}>
        <AlertDialogContent className="max-w-md bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-text-primary">
              Rejeitar Pix #{card?.numero_curto}?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-text-secondary">
              A IA notificará o cliente para reenviar um comprovante válido.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-3 py-1">
            <FormField label="Motivo">
              <select
                value={motivoRejeicao}
                onChange={(e) => setMotivoRejeicao(e.target.value as MotivoRejeicao)}
                className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-ring"
              >
                {(Object.keys(MOTIVO_REJEICAO_LABEL) as MotivoRejeicao[]).map((m) => (
                  <option key={m} value={m}>{MOTIVO_REJEICAO_LABEL[m]}</option>
                ))}
              </select>
            </FormField>
            <FormField label={`Observação${motivoRejeicao !== "outro" ? " (opcional)" : ""}`}>
              <textarea
                value={observacaoRejeicao}
                onChange={(e) => setObservacaoRejeicao(e.target.value)}
                rows={2}
                maxLength={500}
                placeholder={motivoRejeicao === "outro" ? "Descreva o motivo…" : ""}
                className="w-full resize-none rounded-md border border-border bg-card px-3 py-2 text-sm text-text-primary placeholder:text-text-disabled focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </FormField>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={loadingAcao}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRejeitarPix}
              disabled={loadingAcao || (motivoRejeicao === "outro" && !observacaoRejeicao.trim())}
            >
              {loadingAcao ? "Rejeitando…" : "Confirmar rejeição"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* ── AlertDialog: fechar atendimento ──────────────────────── */}
      <AlertDialog open={fecharAberto} onOpenChange={setFecharAberto}>
        <AlertDialogContent className="max-w-sm bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-text-primary">
              Fechar #{card?.numero_curto}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-text-secondary">
              Informe o valor total pago pelo cliente.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="py-1">
            <FormField label="Valor final (R$)">
              <input
                type="text"
                inputMode="decimal"
                value={valorFinal}
                onChange={(e) => setValorFinal(e.target.value)}
                placeholder="Ex: 800,00"
                className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-text-primary placeholder:text-text-disabled focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </FormField>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={loadingAcao}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleFechar}
              disabled={loadingAcao || !valorFinal.trim()}
            >
              {loadingAcao ? "Fechando…" : "Confirmar fechamento"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* ── AlertDialog: registrar perda ─────────────────────────── */}
      <AlertDialog open={perderAberto} onOpenChange={setPerderAberto}>
        <AlertDialogContent className="max-w-md bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-text-primary">
              Registrar perda #{card?.numero_curto}?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-text-secondary">
              O atendimento será encerrado como perdido.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-3 py-1">
            <FormField label="Motivo">
              <select
                value={motivoPerda}
                onChange={(e) => setMotivoPerda(e.target.value as MotivoPerda)}
                className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-ring"
              >
                {(Object.keys(MOTIVO_PERDA_LABEL) as MotivoPerda[]).map((m) => (
                  <option key={m} value={m}>{MOTIVO_PERDA_LABEL[m]}</option>
                ))}
              </select>
            </FormField>
            <FormField label={`Observação${motivoPerda !== "outro" ? " (opcional)" : ""}`}>
              <textarea
                value={observacaoPerda}
                onChange={(e) => setObservacaoPerda(e.target.value)}
                rows={2}
                maxLength={500}
                placeholder={motivoPerda === "outro" ? "Descreva o motivo…" : ""}
                className="w-full resize-none rounded-md border border-border bg-card px-3 py-2 text-sm text-text-primary placeholder:text-text-disabled focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </FormField>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={loadingAcao}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={handlePerder}
              disabled={loadingAcao || (motivoPerda === "outro" && !observacaoPerda.trim())}
            >
              {loadingAcao ? "Registrando…" : "Confirmar perda"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

// ── Hero KPI ──────────────────────────────────────────────────────────────────

function HeroKPI({
  card,
  motivoTexto,
  contexto,
  isPix,
  isEmExecucao,
}: {
  card: CardDestaque
  motivoTexto: string
  contexto: ContextoData
  isPix: boolean
  isEmExecucao: boolean
}) {
  // Para Pix em revisão, o KPI principal é o valor recebido.
  // Para Em execução, é o tempo desde a chegada.
  // Para os demais, é o motivo + tempo pausada.
  const comprovante = contexto.comprovantes_pix[0] ?? null
  const valorAcordado = contexto.atendimento.valor_acordado
  const tempoEmCampo = contexto.atendimento.foto_portaria_em
    ? formatTempoRelativo(contexto.atendimento.foto_portaria_em)
    : null

  let kpiLabel: string
  let kpiValor: ReactNode
  let kpiColor = "text-gold-500"

  if (isPix && comprovante) {
    const valorRecebido = comprovante.valor_extraido
    const valorAbaixo =
      valorAcordado != null && valorRecebido != null && valorRecebido < valorAcordado
    kpiLabel = "Valor recebido"
    kpiValor = valorRecebido != null ? formatBRL(valorRecebido) : "Não extraído"
    kpiColor = valorAbaixo ? "text-warn-500" : "text-gold-500"
  } else if (isEmExecucao && tempoEmCampo) {
    kpiLabel = card.expirado ? "Tempo em campo (excedido)" : "Tempo em campo"
    kpiValor = tempoEmCampo
    kpiColor = card.expirado ? "text-warn-500" : "text-gold-500"
  } else {
    kpiLabel = "Motivo"
    kpiValor = motivoTexto
    kpiColor = "text-gold-500"
  }

  return (
    <div className="overflow-hidden rounded-md border border-ink-300 bg-ink-200">
      <div className="flex flex-wrap items-end justify-between gap-3 px-6 py-5">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            {kpiLabel}
          </p>
          <p
            className={cn(
              "mt-1 font-serif text-[34px] font-medium leading-tight tabular-nums",
              kpiColor,
            )}
          >
            {kpiValor}
          </p>
        </div>
        {isPix && valorAcordado != null && (
          <div className="text-right">
            <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
              Esperado
            </p>
            <p className="mt-1 font-serif text-[26px] font-medium leading-tight tabular-nums text-text-primary">
              {formatBRL(valorAcordado)}
            </p>
          </div>
        )}
      </div>
      <div className="grid grid-cols-2 gap-px border-t border-ink-300 bg-ink-300 sm:grid-cols-4 xl:grid-cols-5">
        <StatTile
          label="Pausada"
          icone={<Clock size={11} strokeWidth={1.75} className="text-text-muted" />}
        >
          {formatTempoRelativo(card.ia_pausada_em)}
        </StatTile>
        <StatTile
          label="Cliente"
          icone={<User size={11} strokeWidth={1.75} className="text-text-muted" />}
        >
          <span className="truncate">{card.cliente_nome ?? card.cliente_telefone_formatado}</span>
        </StatTile>
        <StatTile
          label="Modelo"
          icone={<Sparkles size={11} strokeWidth={1.75} className="text-text-muted" />}
        >
          <span className="truncate">{card.modelo_nome}</span>
        </StatTile>
        {isEmExecucao && card.previsao_termino ? (
          <StatTile
            label="Previsão término"
            icone={<CalendarClock size={11} strokeWidth={1.75} className="text-info-500" />}
          >
            {formatHorario(card.previsao_termino)}
          </StatTile>
        ) : valorAcordado != null && !isPix ? (
          <StatTile
            label="Valor acordado"
            icone={<ReceiptText size={11} strokeWidth={1.75} className="text-gold-500" />}
          >
            {formatBRL(valorAcordado)}
          </StatTile>
        ) : (
          <StatTile
            label="Atendimento"
            icone={<Target size={11} strokeWidth={1.75} className="text-text-muted" />}
          >
            #{card.numero_curto}
          </StatTile>
        )}
      </div>
    </div>
  )
}

// ── sub-componentes utilitários ───────────────────────────────────────────────

function FormField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
        {label}
      </label>
      {children}
    </div>
  )
}

function StatTile({ label, icone, children }: { label: string; icone?: ReactNode; children: ReactNode }) {
  return (
    <div className="bg-ink-200 px-4 py-3">
      <p className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] leading-none text-text-muted">
        {icone}
        <span>{label}</span>
      </p>
      <div className="text-[14px] leading-tight text-text-primary">{children}</div>
    </div>
  )
}

function SecaoBloco({
  titulo,
  icone,
  children,
  highlight = false,
}: {
  titulo: string
  icone: ReactNode
  children: ReactNode
  highlight?: boolean
}) {
  return (
    <section
      className={cn(
        "rounded-md border p-4",
        highlight ? "border-warn-500/40 bg-warn-500/5" : "border-border bg-card",
      )}
    >
      <header className="mb-3 flex items-center gap-2">
        {icone}
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-muted">
          {titulo}
        </h3>
      </header>
      {children}
    </section>
  )
}

function DefinitionList({ children }: { children: ReactNode }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-[13px]">
      {children}
    </dl>
  )
}

function DefRow({
  label,
  value,
  destaque = false,
  warn = false,
}: {
  label: string
  value: ReactNode
  destaque?: boolean
  warn?: boolean
}) {
  return (
    <>
      <dt className="text-text-muted">{label}</dt>
      <dd
        className={cn(
          "text-text-primary",
          destaque && "font-medium",
          warn && "text-warn-500",
        )}
      >
        {value}
      </dd>
    </>
  )
}

// ── Pix em revisão ────────────────────────────────────────────────────────────

function SecaoPix({
  comprovante,
  valorAcordado,
}: {
  comprovante: ComprovantePix
  valorAcordado: number | null
}) {
  const valorAbaixo =
    valorAcordado != null &&
    comprovante.valor_extraido != null &&
    comprovante.valor_extraido < valorAcordado

  return (
    <SecaoBloco
      titulo="Comprovante Pix"
      icone={<CreditCard size={14} strokeWidth={1.75} className="text-text-muted" />}
    >
      <DefinitionList>
        {valorAcordado != null && (
          <DefRow
            label="Esperado"
            value={formatBRL(valorAcordado)}
            destaque
          />
        )}
        <DefRow
          label="Recebido"
          value={
            comprovante.valor_extraido != null
              ? formatBRL(comprovante.valor_extraido)
              : "Não extraído"
          }
          destaque
          warn={valorAbaixo}
        />
        {comprovante.titular_extraido && (
          <DefRow label="Titular" value={comprovante.titular_extraido} />
        )}
        {comprovante.motivo_em_revisao && (
          <DefRow
            label="Motivo em revisão"
            value={comprovante.motivo_em_revisao}
            warn
          />
        )}
      </DefinitionList>
    </SecaoBloco>
  )
}

function SecaoComprovanteImagem({ pixUrl }: { pixUrl: string | null }) {
  return (
    <SecaoBloco
      titulo="Imagem do comprovante"
      icone={<ImageIcon size={14} strokeWidth={1.75} className="text-text-muted" />}
    >
      {pixUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={pixUrl}
          alt="Comprovante Pix"
          className="max-h-[420px] w-full rounded-md border border-border bg-ink-200 object-contain"
        />
      ) : (
        <div className="flex h-48 items-center justify-center rounded-md border border-dashed border-border-subtle text-xs text-text-muted">
          Imagem indisponível
        </div>
      )}
    </SecaoBloco>
  )
}

// ── Resumo operacional da IA ──────────────────────────────────────────────────

function SecaoResumoOperacional({ resumo }: { resumo: string }) {
  return (
    <SecaoBloco
      titulo="Análise da IA"
      icone={<Sparkles size={14} strokeWidth={1.75} className="text-gold-500" />}
    >
      <p className="text-[14px] leading-relaxed text-text-secondary">{resumo}</p>
    </SecaoBloco>
  )
}

// ── Ficha do cliente ──────────────────────────────────────────────────────────

function SecaoFichaCliente({
  conversa,
}: {
  conversa: ContextoData["conversa"]
}) {
  const temDados = conversa && (
    conversa.recorrente != null ||
    conversa.observacoes_internas ||
    conversa.ultimo_motivo_perda
  )

  if (!temDados) return null

  return (
    <SecaoBloco
      titulo="Cliente"
      icone={<User size={14} strokeWidth={1.75} className="text-text-muted" />}
    >
      <div className="mb-3 flex items-center gap-2">
        {conversa?.recorrente && (
          <span className="rounded-full bg-success-500/10 px-2.5 py-0.5 text-[12px] font-medium text-success-500">
            Recorrente
          </span>
        )}
        {conversa?.recorrente === false && (
          <span className="rounded-full bg-ink-200 px-2.5 py-0.5 text-[12px] font-medium text-text-muted">
            Novo
          </span>
        )}
      </div>
      <div className="space-y-2 text-[13px]">
        {conversa?.ultimo_motivo_perda && (
          <div>
            <span className="text-text-muted">Última perda: </span>
            <span className="font-medium text-warn-500">
              {formatRotulo(conversa.ultimo_motivo_perda)}
            </span>
          </div>
        )}
        {conversa?.observacoes_internas && (
          <p className="rounded-md bg-ink-200 px-3 py-2 italic text-text-secondary">
            {conversa.observacoes_internas}
          </p>
        )}
      </div>
    </SecaoBloco>
  )
}

// ── Dados comerciais ──────────────────────────────────────────────────────────

function SecaoDadosComerciais({
  atendimento,
}: {
  atendimento: ContextoData["atendimento"]
}) {
  const temDados =
    atendimento.tipo_atendimento ||
    atendimento.valor_acordado != null ||
    atendimento.data_desejada ||
    atendimento.horario_desejado

  if (!temDados) return null

  return (
    <SecaoBloco
      titulo="Dados comerciais"
      icone={<ReceiptText size={14} strokeWidth={1.75} className="text-gold-500" />}
    >
      <DefinitionList>
        {atendimento.tipo_atendimento && (
          <DefRow
            label="Tipo"
            value={<span className="capitalize">{atendimento.tipo_atendimento}</span>}
          />
        )}
        {atendimento.valor_acordado != null && (
          <DefRow
            label="Valor"
            value={
              <>
                <span className="font-medium">{formatBRL(atendimento.valor_acordado)}</span>
                {atendimento.forma_pagamento && (
                  <span className="ml-1 capitalize text-text-muted">
                    · {atendimento.forma_pagamento}
                  </span>
                )}
              </>
            }
          />
        )}
        {(atendimento.data_desejada || atendimento.horario_desejado) && (
          <DefRow
            label="Quando"
            value={
              <>
                {atendimento.data_desejada && formatData(atendimento.data_desejada)}
                {atendimento.horario_desejado && ` às ${atendimento.horario_desejado.slice(0, 5)}`}
              </>
            }
          />
        )}
      </DefinitionList>
    </SecaoBloco>
  )
}

// ── Sinais de qualificação ────────────────────────────────────────────────────

function SecaoSinaisQualificacao({ sinais, tipo }: { sinais: SinaisQualificacao | null; tipo: string | null }) {
  const sq = sinais as Record<string, unknown> | null
  const sinaisAplicaveis = sinaisParaTipo(tipo)
  const total = sinaisAplicaveis.length
  const progresso = sinaisAplicaveis.filter(({ chave }) => sq?.[chave] === true).length
  const pct = total > 0 ? Math.round((progresso / total) * 100) : 0

  return (
    <SecaoBloco
      titulo="Qualificação"
      icone={<CheckCircle2 size={14} strokeWidth={1.75} className="text-success-500" />}
    >
      <div className="mb-3 flex items-center gap-3">
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-300">
          <div
            className="h-full rounded-full bg-success-500 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-[13px] font-medium tabular-nums text-text-primary">{pct}%</span>
      </div>
      <p className="mb-3 text-xs text-text-muted">
        {progresso === 0
          ? "Nenhum item qualificado"
          : progresso === total
            ? "Totalmente qualificado"
            : `${progresso} de ${total} qualificados`}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {sinaisAplicaveis.map(({ chave, rotulo }) => {
          const v = sq?.[chave]
          const estado = v === true ? "sim" : v === false ? "nao" : "pendente"
          return (
            <span
              key={chave}
              className={cn(
                "flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium",
                estado === "sim"
                  ? "bg-success-500/10 text-success-500"
                  : estado === "nao"
                    ? "bg-danger-500/10 text-danger-500"
                    : "bg-ink-300 text-text-muted",
              )}
            >
              {estado === "sim" ? <CheckCircle2 size={11} /> : estado === "nao" ? <XCircle size={11} /> : <Circle size={11} />}
              {rotulo}
            </span>
          )
        })}
      </div>
    </SecaoBloco>
  )
}

// ── Dados do atendimento (endereço, tipo, duração, bloqueio) ──────────────────

function SecaoDadosAtendimento({
  atendimento,
  bloqueio,
}: {
  atendimento: ContextoData["atendimento"]
  bloqueio: ContextoData["bloqueio"]
}) {
  const temDados =
    atendimento.tipo_atendimento ||
    atendimento.valor_acordado != null ||
    atendimento.endereco ||
    atendimento.horario_desejado ||
    atendimento.duracao_horas != null ||
    bloqueio

  if (!temDados) return null

  const enderecoCompleto = [
    atendimento.endereco,
    atendimento.bairro,
    atendimento.referencia_local,
  ]
    .filter(Boolean)
    .join(" — ")

  return (
    <SecaoBloco
      titulo="Atendimento"
      icone={<MapPin size={14} strokeWidth={1.75} className="text-info-500" />}
    >
      <DefinitionList>
        {atendimento.tipo_atendimento && (
          <DefRow
            label="Tipo"
            value={
              <>
                <span className="capitalize">{atendimento.tipo_atendimento}</span>
                {atendimento.tipo_local && (
                  <span className="ml-1 capitalize text-text-muted">
                    · {atendimento.tipo_local}
                  </span>
                )}
              </>
            }
          />
        )}
        {atendimento.valor_acordado != null && (
          <DefRow
            label="Valor"
            value={<span className="font-medium">{formatBRL(atendimento.valor_acordado)}</span>}
          />
        )}
        {enderecoCompleto && (
          <DefRow label="Endereço" value={enderecoCompleto} />
        )}
        {(atendimento.horario_desejado || atendimento.duracao_horas != null) && (
          <DefRow
            label="Horário"
            value={
              <>
                {atendimento.horario_desejado && atendimento.horario_desejado.slice(0, 5)}
                {atendimento.duracao_horas != null && (
                  <span className="ml-1 text-text-muted">· {atendimento.duracao_horas}h</span>
                )}
              </>
            }
          />
        )}
        {bloqueio && (
          <DefRow
            label="Agenda"
            value={`${formatHorario(bloqueio.inicio)} – ${formatHorario(bloqueio.fim)}`}
          />
        )}
      </DefinitionList>
    </SecaoBloco>
  )
}

// ── Mensagens ─────────────────────────────────────────────────────────────────

function SecaoMensagens({ mensagens }: { mensagens: Mensagem[] }) {
  return (
    <SecaoBloco
      titulo="Últimas mensagens"
      icone={<MessageSquare size={14} strokeWidth={1.75} className="text-text-muted" />}
    >
      <div className="max-h-[320px] space-y-2 overflow-y-auto pr-1">
        {mensagens.map((msg) => (
          <div
            key={msg.id}
            className={cn(
              "max-w-[85%] rounded-md px-3 py-2 text-[13px] leading-snug",
              msg.direcao === "cliente"
                ? "ml-auto bg-ink-200 text-text-primary"
                : "mr-auto bg-ink-100 text-text-secondary",
            )}
          >
            {msg.conteudo ?? (
              <span className="italic text-text-muted">
                {msg.tipo === "audio" ? "Áudio" : msg.tipo === "imagem" ? "Imagem" : "Mídia"}
              </span>
            )}
          </div>
        ))}
      </div>
    </SecaoBloco>
  )
}

