"use client"

import { useState, useEffect, useMemo } from "react"
import { toast } from "sonner"
import { X } from "lucide-react"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Combobox } from "@/components/ui/combobox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api } from "@/lib/api"
import { formatBRL, formatTelefone } from "@/lib/formatters"
import type {
  AtendimentoDetalheResponse,
  EditarDadosPayload,
  ServicoFechado,
  TiposLocalResponse,
} from "@/tipos/atendimentos"
import { estadoLabel } from "./utils"

const RESPONSAVEL_LABEL: Record<string, string> = {
  IA: "IA",
  Fernando: "Você",
  modelo: "Modelo",
}

interface ProgramaModelo {
  programa_id: string
  duracao_id: string
  nome: string
  categoria: string | null
  duracao_nome: string
  preco: number
}

function parseDecimal(input: string): number | null {
  const normalizado = input.replace(/\s/g, "").replace(/\./g, "").replace(",", ".")
  const valor = Number(normalizado)
  return Number.isFinite(valor) && valor >= 0 ? valor : null
}

const controlClassName =
  "h-10 w-full rounded-lg border border-border-strong bg-surface-hover px-3 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted hover:bg-surface-pressed focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"

export function ModalEdicao({
  detalhe,
  onClose,
  onSalvar,
  onReatribuir,
}: {
  detalhe: AtendimentoDetalheResponse | null
  onClose: () => void
  onSalvar: (id: string, dados: EditarDadosPayload) => Promise<void>
  onReatribuir?: (detalhe: AtendimentoDetalheResponse) => void
}) {
  const at = detalhe?.atendimento
  const [submitting, setSubmitting] = useState(false)

  const [tipo, setTipo] = useState(at?.tipo_atendimento ?? "")
  const [urgencia, setUrgencia] = useState(at?.urgencia ?? "")
  const [dataDesejada, setDataDesejada] = useState(at?.data_desejada ?? "")
  const [horario, setHorario] = useState(at?.horario_desejado ? String(at.horario_desejado).slice(0, 5) : "")
  // O backend serializa Decimal como string com ponto ("3.00", "2500.00") e o parseDecimal
  // trata ponto como separador de milhar BR — sem Number() aqui o valor é multiplicado por 100 ao reabrir.
  const [duracao, setDuracao] = useState(at?.duracao_horas != null ? String(Number(at.duracao_horas)) : "")
  const [endereco, setEndereco] = useState(at?.endereco ?? "")
  const [bairro, setBairro] = useState(at?.bairro ?? "")
  const [tipoLocal, setTipoLocal] = useState(at?.tipo_local ?? "")
  const [formaPagamento, setFormaPagamento] = useState(at?.forma_pagamento ?? "")
  const [valorAcordado, setValorAcordado] = useState(at?.valor_acordado != null ? String(Number(at.valor_acordado)) : "")

  const [programasModelo, setProgramasModelo] = useState<ProgramaModelo[]>([])
  const [removidos, setRemovidos] = useState<Set<string>>(new Set())
  const [adicionados, setAdicionados] = useState<{ programa_id: string; duracao_id: string; label: string }[]>([])
  const [selecionado, setSelecionado] = useState("")

  const [tiposBackend, setTiposBackend] = useState<string[]>([])
  const [tiposCriadosSessao, setTiposCriadosSessao] = useState<string[]>([])
  const tiposCombinados = useMemo(
    () => Array.from(new Set([...tiposBackend, ...tiposCriadosSessao])).sort(),
    [tiposBackend, tiposCriadosSessao],
  )

  const modeloId = detalhe?.modelo.id
  useEffect(() => {
    if (!modeloId) return
    api<ProgramaModelo[]>(`/v1/modelos/${modeloId}/programas`)
      .then(setProgramasModelo)
      .catch(() => {})
  }, [modeloId])

  useEffect(() => {
    api<TiposLocalResponse>("/v1/atendimentos/tipos-local")
      .then((r) => setTiposBackend(r.items))
      .catch(() => {})
  }, [])

  if (!detalhe || !at) return null

  const servicosVisiveis = detalhe.servicos.filter((s) => !removidos.has(s.id))

  const activePairs = new Set([
    ...servicosVisiveis.map((s: ServicoFechado) => `${s.programa_id}|${s.duracao_id}`),
    ...adicionados.map((a) => `${a.programa_id}|${a.duracao_id}`),
  ])
  const disponiveis = programasModelo.filter((p) => !activePairs.has(`${p.programa_id}|${p.duracao_id}`))

  const handleAdicionarPrograma = () => {
    if (!selecionado) return
    const [progId, durId] = selecionado.split("|")
    const prog = programasModelo.find((p) => p.programa_id === progId && p.duracao_id === durId)
    if (!prog) return
    setAdicionados((prev) => [...prev, { programa_id: progId, duracao_id: durId, label: `${prog.nome} – ${prog.duracao_nome}` }])
    setSelecionado("")
  }

  const handleSalvar = async () => {
    const dados: EditarDadosPayload = {}
    if (tipo) dados.tipo_atendimento = tipo as "interno" | "externo"
    if (urgencia) dados.urgencia = urgencia as EditarDadosPayload["urgencia"]
    if (dataDesejada) dados.data_desejada = dataDesejada
    if (horario) dados.horario_desejado = horario
    if (duracao) {
      const d = parseDecimal(duracao)
      if (d !== null) dados.duracao_horas = d
    }
    if (endereco) dados.endereco = endereco
    if (bairro) dados.bairro = bairro
    if (tipoLocal) dados.tipo_local = tipoLocal
    if (formaPagamento) dados.forma_pagamento = formaPagamento
    if (valorAcordado) {
      const v = parseDecimal(valorAcordado)
      if (v !== null) dados.valor_acordado = v
    }

    setSubmitting(true)
    try {
      for (const servicoId of removidos) {
        await api(`/v1/atendimentos/${at.id}/servicos/${servicoId}`, { method: "DELETE" })
      }
      for (const a of adicionados) {
        await api(`/v1/atendimentos/${at.id}/servicos`, {
          method: "POST",
          body: JSON.stringify({ programa_id: a.programa_id, duracao_id: a.duracao_id }),
        })
      }
      await onSalvar(at.id, dados)
      toast.success(`Atendimento #${at.numero_curto} atualizado`)
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={!!detalhe} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="flex max-h-[90vh] w-[min(94vw,72rem)] max-w-none flex-col overflow-hidden rounded-xl border border-border-strong bg-surface-raised p-0 shadow-[0_16px_48px_rgba(0,0,0,0.7)]">
        <div className="border-b border-border-subtle px-5 py-4">
          <DialogTitle className="text-base font-semibold leading-6 text-text-primary">
            Editar #{at.numero_curto}
          </DialogTitle>
          <DialogDescription className="mt-1 text-xs text-text-muted">
            Ajuste os dados operacionais do atendimento.
          </DialogDescription>
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-3 border-b border-border-subtle bg-surface px-5 py-3 text-xs sm:grid-cols-4">
          <ItemContexto label="Cliente" title="Para alterar Cliente ou Modelo, use Reatribuir atendimento">
            <span className="text-text-primary">{detalhe.cliente.nome ?? "Sem nome"}</span>
            <span className="text-text-muted">{formatTelefone(detalhe.cliente.telefone)}</span>
          </ItemContexto>
          <ItemContexto label="Modelo" title="Para alterar Cliente ou Modelo, use Reatribuir atendimento">
            <span className="text-text-primary">{detalhe.modelo.nome}</span>
          </ItemContexto>
          <ItemContexto label="Estado">
            <span className="text-text-primary">{estadoLabel[at.estado]}</span>
            {at.ia_pausada && <span className="text-text-muted">IA pausada</span>}
          </ItemContexto>
          <ItemContexto label="Responsável">
            <span className="text-text-primary">{RESPONSAVEL_LABEL[at.responsavel_atual] ?? at.responsavel_atual}</span>
            {at.estado === "Fechado" && at.valor_final != null && (
              <span className="text-text-muted">{formatBRL(Number(at.valor_final))}</span>
            )}
          </ItemContexto>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-3 divide-x divide-border-subtle overflow-hidden">
          <ColunaSecao titulo="Atendimento">
            <Campo label="Tipo de atendimento">
              <select
                value={tipo}
                onChange={(e) => setTipo(e.target.value)}
                className={controlClassName}
              >
                <option value="">—</option>
                <option value="interno">No local da modelo</option>
                <option value="externo">No local do cliente</option>
              </select>
            </Campo>

            <Campo label="Urgência">
              <select
                value={urgencia}
                onChange={(e) => setUrgencia(e.target.value)}
                className={controlClassName}
              >
                <option value="">—</option>
                <option value="imediato">Agora</option>
                <option value="agendado">Marcado</option>
                <option value="indefinido">Indefinido</option>
                <option value="estimado">Estimado</option>
              </select>
            </Campo>

            <Campo label="Data desejada">
              <Input className={controlClassName} type="date" value={dataDesejada} onChange={(e) => setDataDesejada(e.target.value)} />
            </Campo>
            <Campo label="Horário">
              <Input className={controlClassName} type="time" value={horario} onChange={(e) => setHorario(e.target.value)} />
            </Campo>
            <Campo label="Duração (h)">
              <Input className={controlClassName} inputMode="decimal" placeholder="2" value={duracao} onChange={(e) => setDuracao(e.target.value)} />
            </Campo>
          </ColunaSecao>

          <ColunaSecao titulo="Local">
            <Campo label="Endereço">
              <Input className={controlClassName} placeholder="Rua, número" value={endereco} onChange={(e) => setEndereco(e.target.value)} />
            </Campo>
            <Campo label="Bairro">
              <Input className={controlClassName} placeholder="Bairro" value={bairro} onChange={(e) => setBairro(e.target.value)} />
            </Campo>
            <Campo label="Tipo de local">
              <Combobox
                value={tipoLocal}
                onChange={setTipoLocal}
                options={tiposCombinados}
                placeholder="apartamento, casa…"
                onCreate={(novo) => setTiposCriadosSessao((prev) => [...prev, novo])}
                disabled={submitting}
              />
            </Campo>
          </ColunaSecao>

          <ColunaSecao titulo="Pagamento & programas">
            <div className="grid grid-cols-2 gap-3">
              <Campo label="Forma de pagamento">
                <select
                  value={formaPagamento}
                  onChange={(e) => setFormaPagamento(e.target.value)}
                  className={controlClassName}
                >
                  <option value="">—</option>
                  <option value="pix">PIX</option>
                  <option value="dinheiro">Dinheiro</option>
                  <option value="cartão">Cartão</option>
                </select>
              </Campo>
              <Campo label="Valor acordado (R$)">
                <Input className={controlClassName} inputMode="decimal" placeholder="1.200,00" value={valorAcordado} onChange={(e) => setValorAcordado(e.target.value)} />
              </Campo>
            </div>

            <div className="mt-1 flex min-h-0 flex-1 flex-col gap-1.5">
              <span className="text-[11px] font-medium leading-4 text-text-muted">Programas</span>
              <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1">
                {servicosVisiveis.map((s) => (
                  <div key={s.id} className="flex items-center justify-between rounded-lg border border-border-subtle bg-surface-hover px-3 py-2 text-sm">
                    <span className="text-text-primary">{s.nome}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-text-muted">{s.duracao_nome}</span>
                      <button
                        type="button"
                        onClick={() => setRemovidos((prev) => new Set([...prev, s.id]))}
                        className="text-text-muted transition-colors hover:text-text-primary"
                        disabled={submitting}
                      >
                        <X size={14} />
                      </button>
                    </div>
                  </div>
                ))}
                {adicionados.map((a, i) => (
                  <div key={i} className="flex items-center justify-between rounded-lg border border-dashed border-border-subtle bg-surface px-3 py-2 text-sm">
                    <span className="text-text-primary">{a.label}</span>
                    <button
                      type="button"
                      onClick={() => setAdicionados((prev) => prev.filter((_, j) => j !== i))}
                      className="text-text-muted transition-colors hover:text-text-primary"
                      disabled={submitting}
                    >
                      <X size={14} />
                    </button>
                  </div>
                ))}
                {servicosVisiveis.length === 0 && adicionados.length === 0 && disponiveis.length === 0 && (
                  <span className="text-xs text-text-muted">Nenhum programa disponível para esta modelo.</span>
                )}
              </div>
              {disponiveis.length > 0 && (
                <div className="mt-1 flex gap-2">
                  <select
                    value={selecionado}
                    onChange={(e) => setSelecionado(e.target.value)}
                    className={controlClassName}
                    disabled={submitting}
                  >
                    <option value="">Adicionar programa…</option>
                    {disponiveis.map((p) => (
                      <option key={`${p.programa_id}|${p.duracao_id}`} value={`${p.programa_id}|${p.duracao_id}`}>
                        {p.nome} – {p.duracao_nome}
                      </option>
                    ))}
                  </select>
                  <Button variant="secondary" onClick={handleAdicionarPrograma} disabled={!selecionado || submitting}>
                    Adicionar
                  </Button>
                </div>
              )}
            </div>
          </ColunaSecao>
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-border-subtle bg-surface px-5 py-3">
          <div>
            {onReatribuir && (
              <Button
                variant="ghost"
                onClick={() => onReatribuir(detalhe)}
                disabled={submitting}
              >
                Reatribuir atendimento
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose} disabled={submitting}>Cancelar</Button>
            <Button variant="primary" onClick={handleSalvar} disabled={submitting}>
              {submitting ? "Salvando…" : "Salvar"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Campo({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <Label className="text-[11px] font-medium leading-4 text-text-muted">{label}</Label>
      {children}
    </div>
  )
}

function ColunaSecao({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-0 min-w-0 flex-col gap-3 px-5 py-4">
      <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        {titulo}
      </span>
      <div className="flex min-h-0 flex-1 flex-col gap-3">{children}</div>
    </div>
  )
}

function ItemContexto({ label, children, title }: { label: string; children: React.ReactNode; title?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5" title={title}>
      <span className="text-[10px] font-medium uppercase tracking-wide text-text-muted">{label}</span>
      <div className="flex min-w-0 flex-col leading-tight [&>span]:break-words">{children}</div>
    </div>
  )
}
