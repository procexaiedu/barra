"use client"

import { forwardRef, useEffect, useImperativeHandle, useMemo, useState } from "react"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Combobox } from "@/components/ui/combobox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import type {
  EditarDadosPayload,
  TipoAtendimento,
  TiposLocalResponse,
  Urgencia,
} from "@/tipos/atendimentos"

const controlClassName =
  "h-10 w-full rounded-lg border border-border-strong bg-surface-hover px-3 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted hover:bg-surface-pressed focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"

interface ProgramaModelo {
  programa_id: string
  duracao_id: string
  nome: string
  categoria: string | null
  duracao_nome: string
  preco: number
}

interface ProgramaAdicionado {
  programa_id: string
  duracao_id: string
  label: string
}

function parseDecimal(input: string): number | null {
  const normalizado = input.replace(/\s/g, "").replace(/\./g, "").replace(",", ".")
  const valor = Number(normalizado)
  return Number.isFinite(valor) && valor >= 0 ? valor : null
}

export interface FormularioCamposAtendimentoRef {
  coletarDados: () => {
    payload: EditarDadosPayload
    programas: { programa_id: string; duracao_id: string }[]
  }
}

export interface FormularioCamposAtendimentoProps {
  modeloId: string | null
  disabled?: boolean
  variant?: "horizontal" | "stack"
}

export const FormularioCamposAtendimento = forwardRef<
  FormularioCamposAtendimentoRef,
  FormularioCamposAtendimentoProps
>(function FormularioCamposAtendimento(
  { modeloId, disabled = false, variant = "horizontal" },
  ref,
) {
  const [tipo, setTipo] = useState("")
  const [urgencia, setUrgencia] = useState("")
  const [dataDesejada, setDataDesejada] = useState("")
  const [horario, setHorario] = useState("")
  const [duracao, setDuracao] = useState("")
  const [endereco, setEndereco] = useState("")
  const [bairro, setBairro] = useState("")
  const [tipoLocal, setTipoLocal] = useState("")
  const [formaPagamento, setFormaPagamento] = useState("")
  const [valorAcordado, setValorAcordado] = useState("")

  const [programasModelo, setProgramasModelo] = useState<ProgramaModelo[]>([])
  const [adicionados, setAdicionados] = useState<ProgramaAdicionado[]>([])
  const [selecionado, setSelecionado] = useState("")

  const [tiposBackend, setTiposBackend] = useState<string[]>([])
  const [tiposCriadosSessao, setTiposCriadosSessao] = useState<string[]>([])
  const tiposCombinados = useMemo(
    () => Array.from(new Set([...tiposBackend, ...tiposCriadosSessao])).sort(),
    [tiposBackend, tiposCriadosSessao],
  )

  // Reset state quando modeloId muda — pattern oficial do React (state derivado de prop).
  // Ver https://react.dev/reference/react/useState#storing-information-from-previous-renders
  const [modeloIdAnterior, setModeloIdAnterior] = useState(modeloId)
  if (modeloIdAnterior !== modeloId) {
    setModeloIdAnterior(modeloId)
    setProgramasModelo([])
    setAdicionados([])
    setSelecionado("")
  }

  useEffect(() => {
    if (!modeloId) return
    let cancelado = false
    api<ProgramaModelo[]>(`/v1/modelos/${modeloId}/programas`)
      .then((res) => {
        if (!cancelado) setProgramasModelo(res)
      })
      .catch(() => {
        if (!cancelado) setProgramasModelo([])
      })
    return () => {
      cancelado = true
    }
  }, [modeloId])

  useEffect(() => {
    api<TiposLocalResponse>("/v1/atendimentos/tipos-local")
      .then((r) => setTiposBackend(r.items))
      .catch(() => {})
  }, [])

  const valorDecimalInvalido = valorAcordado.trim().length > 0 && parseDecimal(valorAcordado) === null
  const duracaoDecimalInvalida = duracao.trim().length > 0 && parseDecimal(duracao) === null

  useImperativeHandle(
    ref,
    () => ({
      coletarDados: () => {
        const payload: EditarDadosPayload = {}
        if (tipo) payload.tipo_atendimento = tipo as TipoAtendimento
        if (urgencia) payload.urgencia = urgencia as Urgencia
        if (dataDesejada) payload.data_desejada = dataDesejada
        if (horario) payload.horario_desejado = horario
        if (duracao) {
          const d = parseDecimal(duracao)
          if (d !== null) payload.duracao_horas = d
        }
        if (endereco) payload.endereco = endereco
        if (bairro) payload.bairro = bairro
        if (tipoLocal) payload.tipo_local = tipoLocal
        if (formaPagamento) payload.forma_pagamento = formaPagamento
        if (valorAcordado) {
          const v = parseDecimal(valorAcordado)
          if (v !== null) payload.valor_acordado = v
        }
        return {
          payload,
          programas: adicionados.map((a) => ({
            programa_id: a.programa_id,
            duracao_id: a.duracao_id,
          })),
        }
      },
    }),
    [
      tipo,
      urgencia,
      dataDesejada,
      horario,
      duracao,
      endereco,
      bairro,
      tipoLocal,
      formaPagamento,
      valorAcordado,
      adicionados,
    ],
  )

  const activePairs = new Set(adicionados.map((a) => `${a.programa_id}|${a.duracao_id}`))
  const disponiveis = programasModelo.filter(
    (p) => !activePairs.has(`${p.programa_id}|${p.duracao_id}`),
  )

  const handleAdicionarPrograma = () => {
    if (!selecionado) return
    const [progId, durId] = selecionado.split("|")
    const prog = programasModelo.find(
      (p) => p.programa_id === progId && p.duracao_id === durId,
    )
    if (!prog) return
    setAdicionados((prev) => [
      ...prev,
      {
        programa_id: progId,
        duracao_id: durId,
        label: `${prog.nome} – ${prog.duracao_nome}`,
      },
    ])
    setSelecionado("")
  }

  const colunaAtendimento = (
    <ColunaSecao titulo="Atendimento">
      <Campo label="Tipo de atendimento">
        <select
          value={tipo}
          onChange={(e) => setTipo(e.target.value)}
          className={controlClassName}
          disabled={disabled}
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
          disabled={disabled}
        >
          <option value="">—</option>
          <option value="imediato">Agora</option>
          <option value="agendado">Marcado</option>
          <option value="indefinido">Indefinido</option>
          <option value="estimado">Estimado</option>
        </select>
      </Campo>

      <Campo label="Data desejada">
        <Input
          className={controlClassName}
          type="date"
          value={dataDesejada}
          onChange={(e) => setDataDesejada(e.target.value)}
          disabled={disabled}
        />
      </Campo>
      <Campo label="Horário">
        <Input
          className={controlClassName}
          type="time"
          value={horario}
          onChange={(e) => setHorario(e.target.value)}
          disabled={disabled}
        />
      </Campo>
      <Campo label="Duração (h)">
        <Input
          className={cn(controlClassName, duracaoDecimalInvalida && "border-state-lost")}
          inputMode="decimal"
          placeholder="2"
          value={duracao}
          onChange={(e) => setDuracao(e.target.value)}
          disabled={disabled}
        />
      </Campo>
    </ColunaSecao>
  )

  const colunaLocal = (
    <ColunaSecao titulo="Local">
      <Campo label="Endereço">
        <Input
          className={controlClassName}
          placeholder="Rua, número"
          value={endereco}
          onChange={(e) => setEndereco(e.target.value)}
          disabled={disabled}
        />
      </Campo>
      <Campo label="Bairro">
        <Input
          className={controlClassName}
          placeholder="Bairro"
          value={bairro}
          onChange={(e) => setBairro(e.target.value)}
          disabled={disabled}
        />
      </Campo>
      <Campo label="Tipo de local">
        <Combobox
          value={tipoLocal}
          onChange={setTipoLocal}
          options={tiposCombinados}
          placeholder="apartamento, casa…"
          onCreate={(novo) => setTiposCriadosSessao((prev) => [...prev, novo])}
          disabled={disabled}
        />
      </Campo>
    </ColunaSecao>
  )

  const colunaPagamento = (
    <ColunaSecao titulo="Pagamento & programas">
      <div className="grid grid-cols-2 gap-3">
        <Campo label="Forma de pagamento">
          <select
            value={formaPagamento}
            onChange={(e) => setFormaPagamento(e.target.value)}
            className={controlClassName}
            disabled={disabled}
          >
            <option value="">—</option>
            <option value="pix">PIX</option>
            <option value="dinheiro">Dinheiro</option>
            <option value="cartão">Cartão</option>
          </select>
        </Campo>
        <Campo label="Valor acordado (R$)">
          <Input
            className={cn(controlClassName, valorDecimalInvalido && "border-state-lost")}
            inputMode="decimal"
            placeholder="1.200,00"
            value={valorAcordado}
            onChange={(e) => setValorAcordado(e.target.value)}
            disabled={disabled}
          />
        </Campo>
      </div>

      <div className="mt-1 flex min-h-0 flex-1 flex-col gap-1.5">
        <span className="text-[11px] font-medium leading-4 text-text-muted">Programas</span>
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1">
          {adicionados.map((a, i) => (
            <div
              key={`${a.programa_id}|${a.duracao_id}|${i}`}
              className="flex items-center justify-between rounded-lg border border-dashed border-border-subtle bg-surface px-3 py-2 text-sm"
            >
              <span className="text-text-primary">{a.label}</span>
              <button
                type="button"
                onClick={() =>
                  setAdicionados((prev) => prev.filter((_, j) => j !== i))
                }
                className="text-text-muted transition-colors hover:text-text-primary"
                disabled={disabled}
                aria-label={`Remover ${a.label}`}
              >
                <X size={14} />
              </button>
            </div>
          ))}
          {adicionados.length === 0 && disponiveis.length === 0 && (
            <span className="text-xs text-text-muted">
              {modeloId
                ? "Nenhum programa disponível para esta modelo."
                : "Selecione a modelo para listar programas."}
            </span>
          )}
        </div>
        {disponiveis.length > 0 && (
          <div className="mt-1 flex gap-2">
            <select
              value={selecionado}
              onChange={(e) => setSelecionado(e.target.value)}
              className={controlClassName}
              disabled={disabled}
            >
              <option value="">Adicionar programa…</option>
              {disponiveis.map((p) => (
                <option
                  key={`${p.programa_id}|${p.duracao_id}`}
                  value={`${p.programa_id}|${p.duracao_id}`}
                >
                  {p.nome} – {p.duracao_nome}
                </option>
              ))}
            </select>
            <Button
              variant="secondary"
              onClick={handleAdicionarPrograma}
              disabled={!selecionado || disabled}
            >
              Adicionar
            </Button>
          </div>
        )}
      </div>
    </ColunaSecao>
  )

  if (variant === "stack") {
    return (
      <div className="flex flex-col divide-y divide-border-subtle rounded-lg border border-border-subtle bg-surface">
        {colunaAtendimento}
        {colunaLocal}
        {colunaPagamento}
      </div>
    )
  }

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-border-subtle overflow-hidden md:grid-cols-3 md:divide-x md:divide-y-0">
      {colunaAtendimento}
      {colunaLocal}
      {colunaPagamento}
    </div>
  )
})

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
