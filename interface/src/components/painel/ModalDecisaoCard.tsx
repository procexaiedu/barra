"use client"

import { useState, useEffect, type ReactNode } from "react"
import Link from "next/link"
import { ExternalLink, Clock, AlertTriangle, CheckCircle2, XCircle, Circle } from "lucide-react"
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
    // campos expandidos
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
  const mensagensOrdenadas = contexto ? [...contexto.mensagens.slice(0, 6)].reverse() : []
  const isPix = card?.ia_pausada_motivo === "pix_em_revisao"
  const isHandoff = card?.ia_pausada_motivo === "handoff_ia"
  const isModeloAtendendo = card?.ia_pausada_motivo === "modelo_em_atendimento"
  const isEmExecucao = isModeloAtendendo && contexto?.atendimento.estado === "Em_execucao"
  const isConfirmado = isModeloAtendendo && contexto?.atendimento.estado === "Confirmado"

  return (
    <>
      <Dialog open={card !== null} onOpenChange={(v) => { if (!v) onClose() }}>
        <DialogContent className="w-full max-w-lg rounded-xl bg-card p-0 shadow-xl ring-1 ring-border">
          {/* ── header ──────────────────────────────────────────── */}
          <div className="flex items-center gap-2 border-b border-border px-5 py-4">
            {card && (
              <>
                <Badge variant={BADGE_VARIANT[card.ia_pausada_motivo]}>
                  {BADGE_LABEL[card.ia_pausada_motivo]}
                </Badge>
                <DialogTitle className="text-base font-semibold text-text-primary">
                  {nomeCliente}
                </DialogTitle>
                <span className="shrink-0 text-xs text-text-muted">{card.modelo_nome} #{card.numero_curto}</span>
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
          </div>

          {/* ── corpo ───────────────────────────────────────────── */}
          <div className="max-h-[60vh] space-y-4 overflow-y-auto px-5 py-4">
            {loading && (
              <div className="space-y-2">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-24 w-full" />
              </div>
            )}

            {erro && !loading && (
              <p className="text-sm text-danger-500">{erro}</p>
            )}

            {!loading && !erro && contexto && card && (
              <>
                {/* motivo + tempo — sempre visible */}
                <div className="space-y-1.5">
                  <InfoRow
                    label="MOTIVO"
                    value={motivoExibido(card.motivo_escalada, card.ia_pausada_motivo) ?? "—"}
                  />
                  {/* Campo 'Próxima Ação' obsoleto no MVP (task 0855ee14) */}
                  <p className="text-xs text-text-muted">
                    Pausada {formatTempoRelativo(card.ia_pausada_em)}
                  </p>
                </div>

                {/* ── PIX EM REVISÃO ─────────────────────────────── */}
                {isPix && comprovante && (
                  <SecaoPix
                    comprovante={comprovante}
                    pixUrl={pixUrl}
                    valorAcordado={contexto.atendimento.valor_acordado}
                  />
                )}

                {/* ── HANDOFF IA ─────────────────────────────────── */}
                {isHandoff && (
                  <>
                    {contexto.atendimento.resumo_operacional && (
                      <SecaoResumoOperacional resumo={contexto.atendimento.resumo_operacional} />
                    )}
                    <SecaoFichaCliente conversa={contexto.conversa} />
                    <SecaoDadosComerciais atendimento={contexto.atendimento} />
                    {contexto.atendimento.sinais_qualificacao && (
                      <SecaoSinaisQualificacao sinais={contexto.atendimento.sinais_qualificacao} tipo={contexto.atendimento.tipo_atendimento} />
                    )}
                    {mensagensOrdenadas.length > 0 && (
                      <SecaoMensagens mensagens={mensagensOrdenadas} />
                    )}
                  </>
                )}

                {/* ── MODELO EM EXECUÇÃO (cliente chegou) ─────────── */}
                {isEmExecucao && (
                  <>
                    <SecaoTimerEmCampo
                      fotoPortariaEm={contexto.atendimento.foto_portaria_em}
                      previsaoTermino={card.previsao_termino ?? null}
                      expirado={card.expirado}
                    />
                    <SecaoDadosAtendimento
                      atendimento={contexto.atendimento}
                      bloqueio={contexto.bloqueio}
                    />
                    {contexto.atendimento.resumo_operacional && (
                      <SecaoResumoOperacional resumo={contexto.atendimento.resumo_operacional} />
                    )}
                  </>
                )}

                {/* ── MODELO CONFIRMADO (aguardando horário) ───────── */}
                {isConfirmado && (
                  <>
                    <SecaoDadosAtendimento
                      atendimento={contexto.atendimento}
                      bloqueio={contexto.bloqueio}
                    />
                    {comprovante?.valor_extraido != null && (
                      <div className="rounded-md border border-border p-3">
                        <p className="mb-1.5 text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
                          Pix de deslocamento
                        </p>
                        <p className="text-[13px] font-medium text-success-500">
                          {formatBRL(comprovante.valor_extraido)} validado
                        </p>
                      </div>
                    )}
                  </>
                )}
              </>
            )}
          </div>

          {/* ── footer com ações ────────────────────────────────── */}
          {!loading && !erro && contexto && (
            <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
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
            </div>
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

// ── sub-componentes utilitários ───────────────────────────────────────────────

function InfoRow({
  label,
  value,
  destaque = false,
}: {
  label: string
  value: string
  destaque?: boolean
}) {
  return (
    <div>
      <span className="text-xs font-medium uppercase tracking-[0.08em] text-text-muted">{label} </span>
      <span className={cn("text-[13px] text-text-primary", destaque && "font-medium")}>
        {value}
      </span>
    </div>
  )
}

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

function SecaoLabel({ children }: { children: ReactNode }) {
  return (
    <p className="text-xs font-medium uppercase tracking-[0.08em] text-text-muted">{children}</p>
  )
}

// ── Pix em revisão ────────────────────────────────────────────────────────────

function SecaoPix({
  comprovante,
  pixUrl,
  valorAcordado,
}: {
  comprovante: ComprovantePix
  pixUrl: string | null
  valorAcordado: number | null
}) {
  const valorAbaixo =
    valorAcordado != null &&
    comprovante.valor_extraido != null &&
    comprovante.valor_extraido < valorAcordado

  return (
    <div className="space-y-2 rounded-md border border-border p-3">
      <SecaoLabel>Comprovante</SecaoLabel>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
        {valorAcordado != null && (
          <>
            <span className="text-text-muted">Esperado</span>
            <span className="font-medium text-text-primary">{formatBRL(valorAcordado)}</span>
          </>
        )}
        <span className="text-text-muted">Recebido</span>
        <span className={cn("font-medium", valorAbaixo ? "text-warn-500" : "text-text-primary")}>
          {comprovante.valor_extraido != null
            ? formatBRL(comprovante.valor_extraido)
            : "Não extraído"}
        </span>
        {comprovante.titular_extraido && (
          <>
            <span className="text-text-muted">Titular</span>
            <span className="text-text-primary">{comprovante.titular_extraido}</span>
          </>
        )}
        {comprovante.motivo_em_revisao && (
          <>
            <span className="text-text-muted">Motivo</span>
            <span className="text-warn-500">{comprovante.motivo_em_revisao}</span>
          </>
        )}
      </div>
      {pixUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={pixUrl} alt="Comprovante Pix" className="mt-1 max-h-48 w-full rounded object-contain" />
      ) : (
        <div className="mt-1 flex h-16 items-center justify-center rounded border border-border-subtle text-xs text-text-muted">
          Imagem indisponível
        </div>
      )}
    </div>
  )
}

// ── Resumo operacional da IA ──────────────────────────────────────────────────

function SecaoResumoOperacional({ resumo }: { resumo: string }) {
  return (
    <div className="rounded-md border border-border p-3">
      <SecaoLabel>Análise da IA</SecaoLabel>
      <p className="mt-1.5 text-[13px] leading-relaxed text-text-secondary">{resumo}</p>
    </div>
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
    <div className="rounded-md border border-border p-3">
      <div className="mb-2 flex items-center gap-2">
        <SecaoLabel>Cliente</SecaoLabel>
        {conversa?.recorrente && (
          <span className="rounded-full bg-success-500/10 px-2 py-0.5 text-[11px] font-medium text-success-500">
            Recorrente
          </span>
        )}
        {conversa?.recorrente === false && (
          <span className="rounded-full bg-ink-200 px-2 py-0.5 text-[11px] font-medium text-text-muted">
            Novo
          </span>
        )}
      </div>
      <div className="space-y-1.5 text-[13px]">
        {conversa?.ultimo_motivo_perda && (
          <div>
            <span className="text-text-muted">Última perda: </span>
            <span className="text-warn-500">{formatRotulo(conversa.ultimo_motivo_perda)}</span>
          </div>
        )}
        {conversa?.observacoes_internas && (
          <p className="italic text-text-secondary">{conversa.observacoes_internas}</p>
        )}
      </div>
    </div>
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
    <div className="rounded-md border border-border p-3">
      <SecaoLabel>Dados comerciais</SecaoLabel>
      <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
        {atendimento.tipo_atendimento && (
          <>
            <span className="text-text-muted">Tipo</span>
            <span className="capitalize text-text-primary">{atendimento.tipo_atendimento}</span>
          </>
        )}
        {atendimento.valor_acordado != null && (
          <>
            <span className="text-text-muted">Valor</span>
            <span className="font-medium text-text-primary">
              {formatBRL(atendimento.valor_acordado)}
              {atendimento.forma_pagamento && (
                <span className="ml-1 font-normal text-text-muted capitalize">
                  • {atendimento.forma_pagamento}
                </span>
              )}
            </span>
          </>
        )}
        {(atendimento.data_desejada || atendimento.horario_desejado) && (
          <>
            <span className="text-text-muted">Horário</span>
            <span className="text-text-primary">
              {atendimento.data_desejada && formatData(atendimento.data_desejada)}
              {atendimento.horario_desejado && ` às ${atendimento.horario_desejado.slice(0, 5)}`}
            </span>
          </>
        )}
      </div>
    </div>
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
    <div className="rounded-md border border-border p-3">
      <SecaoLabel>Qualificação</SecaoLabel>
      <div className="my-2 flex items-center gap-2">
        <div className="h-1.5 flex-1 rounded-full bg-ink-300">
          <div
            className="h-1.5 rounded-full bg-success-500 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-xs tabular-nums text-text-muted">{pct}%</span>
      </div>
      <p className="mb-2 text-xs text-text-muted">
        {progresso === 0 ? "Nenhum item qualificado" : progresso === total ? "Totalmente qualificado" : `${progresso} de ${total} qualificados`}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {sinaisAplicaveis.map(({ chave, rotulo }) => {
          const v = sq?.[chave]
          const estado = v === true ? "sim" : v === false ? "nao" : "pendente"
          return (
            <span
              key={chave}
              className={cn(
                "flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-medium",
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
    </div>
  )
}

// ── Timer em campo (Em_execucao) ──────────────────────────────────────────────

function SecaoTimerEmCampo({
  fotoPortariaEm,
  previsaoTermino,
  expirado,
}: {
  fotoPortariaEm: string | null
  previsaoTermino: string | null
  expirado: boolean
}) {
  const tempoEmCampo = fotoPortariaEm ? formatTempoRelativo(fotoPortariaEm) : null

  return (
    <div
      className={cn(
        "rounded-md border p-3",
        expirado ? "border-warn-500/40 bg-warn-500/5" : "border-border",
      )}
    >
      <div className="flex items-center gap-2">
        {expirado ? (
          <AlertTriangle size={14} className="shrink-0 text-warn-500" />
        ) : (
          <Clock size={14} className="shrink-0 text-text-muted" />
        )}
        <SecaoLabel>{expirado ? "Passou do horário previsto" : "Em campo"}</SecaoLabel>
      </div>
      <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
        {tempoEmCampo && (
          <>
            <span className="text-text-muted">Desde chegada</span>
            <span className={cn("font-medium", expirado ? "text-warn-500" : "text-text-primary")}>
              {tempoEmCampo}
            </span>
          </>
        )}
        {previsaoTermino && (
          <>
            <span className="text-text-muted">Previsão término</span>
            <span className="text-text-primary">{formatHorario(previsaoTermino)}</span>
          </>
        )}
      </div>
    </div>
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
    <div className="rounded-md border border-border p-3">
      <SecaoLabel>Atendimento</SecaoLabel>
      <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
        {atendimento.tipo_atendimento && (
          <>
            <span className="text-text-muted">Tipo</span>
            <span className="capitalize text-text-primary">
              {atendimento.tipo_atendimento}
              {atendimento.tipo_local && (
                <span className="ml-1 text-text-muted capitalize">• {atendimento.tipo_local}</span>
              )}
            </span>
          </>
        )}
        {atendimento.valor_acordado != null && (
          <>
            <span className="text-text-muted">Valor</span>
            <span className="font-medium text-text-primary">{formatBRL(atendimento.valor_acordado)}</span>
          </>
        )}
        {enderecoCompleto && (
          <>
            <span className="text-text-muted">Endereço</span>
            <span className="text-text-primary">{enderecoCompleto}</span>
          </>
        )}
        {(atendimento.horario_desejado || atendimento.duracao_horas != null) && (
          <>
            <span className="text-text-muted">Horário</span>
            <span className="text-text-primary">
              {atendimento.horario_desejado && atendimento.horario_desejado.slice(0, 5)}
              {atendimento.duracao_horas != null && (
                <span className="ml-1 text-text-muted">• {atendimento.duracao_horas}h</span>
              )}
            </span>
          </>
        )}
        {bloqueio && (
          <>
            <span className="text-text-muted">Agenda</span>
            <span className="text-text-primary">
              {formatHorario(bloqueio.inicio)} – {formatHorario(bloqueio.fim)}
            </span>
          </>
        )}
      </div>
    </div>
  )
}

// ── Mensagens ─────────────────────────────────────────────────────────────────

function SecaoMensagens({ mensagens }: { mensagens: Mensagem[] }) {
  return (
    <div className="space-y-1.5">
      <SecaoLabel>Últimas mensagens</SecaoLabel>
      <div className="max-h-44 space-y-1.5 overflow-y-auto rounded-md border border-border p-2">
        {mensagens.map((msg) => (
          <div
            key={msg.id}
            className={cn(
              "max-w-[80%] rounded-md px-2.5 py-1.5 text-[13px]",
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
    </div>
  )
}
