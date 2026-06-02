"use client"

import { useState } from "react"
import { toast } from "sonner"
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ModalNovoAtendimento } from "@/components/atendimentos/ModalNovoAtendimento"
import { ApiError, api } from "@/lib/api"
import { formatTelefone } from "@/lib/formatters"
import type {
  AtendimentoCriadoResponse,
  AtendimentoDetalheResponse,
  CriarAtendimentoRequest,
  CriarAtendimentoResultado,
  EditarDadosPayload,
} from "@/tipos/atendimentos"
import type { Cliente, CriarClienteRequest } from "@/tipos/clientes"

interface ModalReatribuirProps {
  detalhe: AtendimentoDetalheResponse | null
  onClose: () => void
  onCriarCliente: (payload: CriarClienteRequest) => Promise<Cliente>
  onConcluido: (novoAtendimentoId: string) => Promise<void> | void
}

function snapshotOperacional(detalhe: AtendimentoDetalheResponse): EditarDadosPayload {
  const at = detalhe.atendimento
  const dados: EditarDadosPayload = {}
  if (at.tipo_atendimento) dados.tipo_atendimento = at.tipo_atendimento
  if (at.urgencia) dados.urgencia = at.urgencia
  if (at.data_desejada) dados.data_desejada = at.data_desejada
  if (at.horario_desejado) dados.horario_desejado = String(at.horario_desejado).slice(0, 5)
  if (at.duracao_horas != null) {
    const v = Number(at.duracao_horas)
    if (Number.isFinite(v)) dados.duracao_horas = v
  }
  if (at.endereco) dados.endereco = at.endereco
  if (at.bairro) dados.bairro = at.bairro
  if (at.tipo_local) dados.tipo_local = at.tipo_local
  if (at.forma_pagamento) dados.forma_pagamento = at.forma_pagamento
  if (at.valor_acordado != null) {
    const v = Number(at.valor_acordado)
    if (Number.isFinite(v)) dados.valor_acordado = v
  }
  return dados
}

export function ModalReatribuir({
  detalhe,
  onClose,
  onCriarCliente,
  onConcluido,
}: ModalReatribuirProps) {
  const [passo, setPasso] = useState<1 | 2>(1)
  const [motivo, setMotivo] = useState("")

  if (!detalhe) return null

  const at = detalhe.atendimento

  const reiniciar = () => {
    setPasso(1)
    setMotivo("")
  }

  const handleClose = () => {
    reiniciar()
    onClose()
  }

  const orquestrarCriacao = async (
    payload: CriarAtendimentoRequest
  ): Promise<CriarAtendimentoResultado> => {
    // Passo a: cancelar (Perdido + motivo reatribuicao) o atendimento antigo.
    const observacao = motivo.trim() ? `reatribuicao: ${motivo.trim()}` : "reatribuicao"
    try {
      await api(`/v1/atendimentos/${at.id}/perder`, {
        method: "POST",
        body: JSON.stringify({ motivo: "outro", observacao }),
      })
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Erro desconhecido"
      throw new Error(`Não foi possível cancelar o atendimento antigo: ${detail}`)
    }

    // Passo b: criar o novo atendimento. Pode falhar com 409 (atendimento_aberto_existente
    // ou cliente_arquivado) — operador escolhe outro destino; o antigo permanece Perdido.
    let novo: AtendimentoCriadoResponse
    try {
      novo = await api<AtendimentoCriadoResponse>("/v1/atendimentos", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    } catch (e) {
      if (
        e instanceof ApiError &&
        e.status === 409 &&
        e.detail === "atendimento_aberto_existente"
      ) {
        const atendimentoId = (e.details?.atendimento_id as string | undefined) ?? null
        if (atendimentoId) {
          return { tipo: "existente", atendimento_id: atendimentoId }
        }
      }
      throw e
    }

    // Passo c: copiar snapshot operacional. Falha aqui não derruba a reatribuição.
    const dados = snapshotOperacional(detalhe)
    if (Object.keys(dados).length > 0) {
      try {
        await api(`/v1/atendimentos/${novo.id}/dados`, {
          method: "PATCH",
          body: JSON.stringify(dados),
        })
      } catch {
        toast.warning(
          `Reatribuição feita, mas dados operacionais não foram copiados; edite manualmente o atendimento #${novo.numero_curto}.`
        )
      }
    }

    return { tipo: "criado", atendimento: novo }
  }

  const handleCriado = async (novoId: string) => {
    try {
      await onConcluido(novoId)
    } finally {
      reiniciar()
    }
  }

  if (passo === 2) {
    return (
      <ModalNovoAtendimento
        open
        onClose={() => {
          // Voltar para o passo 1 se cancelar sem criar.
          setPasso(1)
        }}
        onCriar={orquestrarCriacao}
        onCriarCliente={onCriarCliente}
        onCriado={handleCriado}
      />
    )
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) handleClose()
      }}
    >
      <DialogContent size="sm">
        <DialogHeader className="flex-col items-start gap-1">
          <DialogTitle>Reatribuir atendimento #{at.numero_curto}</DialogTitle>
          <DialogDescription>
            O atendimento atual será marcado como Perdido (motivo: reatribuição) e um novo
            atendimento será criado para o par escolhido.
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
        <div className="mt-5 space-y-3 rounded-md bg-muted px-4 py-3 text-sm">
          <div className="flex justify-between gap-3">
            <span className="text-text-muted">Cliente atual</span>
            <span className="text-right text-text-primary">
              {detalhe.cliente.nome ?? "Sem nome"}{" "}
              <span className="text-text-muted">
                · {formatTelefone(detalhe.cliente.telefone)}
              </span>
            </span>
          </div>
          <div className="flex justify-between gap-3">
            <span className="text-text-muted">Modelo atual</span>
            <span className="text-right text-text-primary">{detalhe.modelo.nome}</span>
          </div>
        </div>

        <p className="mt-4 text-xs text-text-muted">
          As mensagens trocadas permanecem no par antigo. O novo atendimento começa limpo.
        </p>

        <div className="mt-4">
          <Label htmlFor="reatribuir-motivo">Motivo (opcional)</Label>
          <Input
            id="reatribuir-motivo"
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
            placeholder="Ex.: cliente trocou de modelo"
            className="mt-2 h-10"
            autoComplete="off"
          />
        </div>
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={handleClose}>
            Cancelar
          </Button>
          <Button variant="primary" onClick={() => setPasso(2)}>
            Continuar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
