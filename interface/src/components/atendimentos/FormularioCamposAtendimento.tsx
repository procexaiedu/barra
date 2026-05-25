"use client"

import { forwardRef, useEffect, useImperativeHandle, useMemo, useState } from "react"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Combobox } from "@/components/ui/combobox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import { useConflitoAgenda } from "@/hooks/useConflitoAgenda"
import { useTiposLocal } from "@/hooks/useTiposLocal"
import { CampoLocalAutocomplete } from "@/components/comum/CampoLocalAutocomplete"
import { AlertaConflito } from "./AlertaConflito"
import { ModalRemoverTipoLocal } from "./ModalRemoverTipoLocal"
import type {
  EditarDadosPayload,
  TipoAtendimento,
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
  horas: number | null
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

// Formata um número para o campo (vírgula decimal, sem separador de milhar),
// compatível com parseDecimal na hora de enviar ao backend.
function formatValorCampo(valor: number): string {
  return valor.toFixed(2).replace(".", ",")
}

// Formata horas para o campo de duração: inteiro quando possível ("3"), senão
// com vírgula decimal ("2,5"), compatível com parseDecimal ao enviar ao backend.
function formatHorasCampo(horas: number): string {
  return Number.isInteger(horas) ? String(horas) : horas.toFixed(2).replace(".", ",")
}

export interface FormularioCamposAtendimentoRef {
  coletarDados: () => {
    payload: EditarDadosPayload
    programas: { programa_id: string; duracao_id: string }[]
  }
}

export interface PeriodoHerdado {
  data: string
  horario: string
  duracaoHoras: number
}

export interface FormularioCamposAtendimentoProps {
  modeloId: string | null
  disabled?: boolean
  variant?: "horizontal" | "stack"
  /**
   * Quando true, os campos data/horário/duração ficam ocultos e os valores são
   * herdados de `periodoHerdado` (caso do sub-form dentro do modal de
   * agendamento, onde esses campos já existem no header do agendamento).
   */
  herdarPeriodo?: boolean
  periodoHerdado?: PeriodoHerdado
  /** bloqueio do próprio atendimento em edição — não conta como conflito de agenda */
  excluirBloqueioId?: string | null
  /** notifica o pai quando há conflito de agenda, para desabilitar o Salvar */
  onConflitoChange?: (temConflito: boolean) => void
}

export const FormularioCamposAtendimento = forwardRef<
  FormularioCamposAtendimentoRef,
  FormularioCamposAtendimentoProps
>(function FormularioCamposAtendimento(
  {
    modeloId,
    disabled = false,
    variant = "horizontal",
    herdarPeriodo = false,
    periodoHerdado,
    excluirBloqueioId,
    onConflitoChange,
  },
  ref,
) {
  const [tipo, setTipo] = useState("")
  const [urgencia, setUrgencia] = useState("")
  const [dataDesejada, setDataDesejada] = useState("")
  const [horario, setHorario] = useState("")
  const [duracao, setDuracao] = useState("")
  // Enquanto false, o campo de duração espelha o MAX das horas dos programas.
  // Vira true assim que o usuário edita a duração à mão.
  const [duracaoEditadaManual, setDuracaoEditadaManual] = useState(false)
  const [endereco, setEndereco] = useState("")
  const [enderecoFormatado, setEnderecoFormatado] = useState<string | null>(null)
  const [latitude, setLatitude] = useState<number | null>(null)
  const [longitude, setLongitude] = useState<number | null>(null)
  const [placeId, setPlaceId] = useState<string | null>(null)
  const [bairro, setBairro] = useState("")
  // Vira true quando o usuário edita o bairro à mão; impede que uma nova seleção
  // de endereço sobrescreva a edição manual.
  const [bairroEditadoManual, setBairroEditadoManual] = useState(false)
  const [tipoLocal, setTipoLocal] = useState("")
  const [formaPagamento, setFormaPagamento] = useState("")
  const [valorAcordado, setValorAcordado] = useState("")
  // Enquanto false, o valor acordado é recalculado a partir dos programas.
  // Vira true assim que o usuário edita o campo manualmente.
  const [valorEditadoManual, setValorEditadoManual] = useState(false)

  const [programasModelo, setProgramasModelo] = useState<ProgramaModelo[]>([])
  const [adicionados, setAdicionados] = useState<ProgramaAdicionado[]>([])
  const [selecionado, setSelecionado] = useState("")

  const {
    tiposCombinados,
    adicionarTipoSessao,
    iniciarRemocao,
    remocao,
    cancelarRemocao,
    aposRemover,
  } = useTiposLocal()

  // Reset state quando modeloId muda — pattern oficial do React (state derivado de prop).
  // Ver https://react.dev/reference/react/useState#storing-information-from-previous-renders
  const [modeloIdAnterior, setModeloIdAnterior] = useState(modeloId)
  if (modeloIdAnterior !== modeloId) {
    setModeloIdAnterior(modeloId)
    setProgramasModelo([])
    setAdicionados([])
    setSelecionado("")
    setValorAcordado("")
    setValorEditadoManual(false)
    setDuracao("")
    setDuracaoEditadaManual(false)
  }

  // Soma dos preços dos programas atualmente adicionados (ignora preco null/NaN).
  const valorCalculado = useMemo(() => {
    return adicionados.reduce((total, a) => {
      const prog = programasModelo.find(
        (p) => p.programa_id === a.programa_id && p.duracao_id === a.duracao_id,
      )
      const preco = prog?.preco
      return Number.isFinite(preco) ? total + (preco as number) : total
    }, 0)
  }, [adicionados, programasModelo])

  // Enquanto o usuário não editou manualmente e há programas, o campo espelha a
  // soma dos programas (valor derivado, sem setState em efeito). Assim que ele
  // edita, passa a valer o que está em valorAcordado e o hint some.
  const recalculaAutomaticamente = !valorEditadoManual && adicionados.length > 0
  const valorAcordadoExibido = recalculaAutomaticamente
    ? formatValorCampo(valorCalculado)
    : valorAcordado

  // Maior duração (em horas) entre os programas adicionados — nunca a soma. Itens
  // que não alongam o atendimento simplesmente não elevam o MAX; horas null não contam.
  const duracaoCalculada = useMemo(() => {
    let max: number | null = null
    for (const a of adicionados) {
      const prog = programasModelo.find(
        (p) => p.programa_id === a.programa_id && p.duracao_id === a.duracao_id,
      )
      const h = prog?.horas
      if (typeof h === "number" && (max === null || h > max)) max = h
    }
    return max
  }, [adicionados, programasModelo])

  const recalculaDuracaoAutomaticamente =
    !herdarPeriodo && !duracaoEditadaManual && duracaoCalculada !== null
  const duracaoExibida = recalculaDuracaoAutomaticamente
    ? formatHorasCampo(duracaoCalculada as number)
    : duracao

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

  const valorDecimalInvalido =
    valorAcordadoExibido.trim().length > 0 && parseDecimal(valorAcordadoExibido) === null
  const duracaoDecimalInvalida =
    duracaoExibida.trim().length > 0 && parseDecimal(duracaoExibida) === null

  // Período efetivo: herdado do agendamento (sub-form da agenda) ou dos campos locais.
  const periodoData = herdarPeriodo ? periodoHerdado?.data ?? "" : dataDesejada
  const periodoHorario = herdarPeriodo ? periodoHerdado?.horario ?? "" : horario
  const periodoDuracaoHoras = herdarPeriodo
    ? periodoHerdado?.duracaoHoras ?? 0
    : parseDecimal(duracaoExibida) ?? 0

  const { conflitos } = useConflitoAgenda({
    modelo_id: modeloId,
    data: periodoData,
    horario: periodoHorario,
    duracao_horas: periodoDuracaoHoras,
    excluir_bloqueio_id: excluirBloqueioId ?? null,
  })

  const temConflito = conflitos.length > 0
  useEffect(() => {
    onConflitoChange?.(temConflito)
  }, [temConflito, onConflitoChange])

  useImperativeHandle(
    ref,
    () => ({
      coletarDados: () => {
        const payload: EditarDadosPayload = {}
        if (tipo) payload.tipo_atendimento = tipo as TipoAtendimento
        if (urgencia) payload.urgencia = urgencia as Urgencia
        if (herdarPeriodo && periodoHerdado) {
          if (periodoHerdado.data) payload.data_desejada = periodoHerdado.data
          if (periodoHerdado.horario) payload.horario_desejado = periodoHerdado.horario
          if (Number.isFinite(periodoHerdado.duracaoHoras) && periodoHerdado.duracaoHoras > 0) {
            payload.duracao_horas = periodoHerdado.duracaoHoras
          }
        } else {
          if (dataDesejada) payload.data_desejada = dataDesejada
          if (horario) payload.horario_desejado = horario
          if (duracaoExibida) {
            const d = parseDecimal(duracaoExibida)
            if (d !== null) payload.duracao_horas = d
          }
        }
        if (endereco) payload.endereco = endereco
        if (enderecoFormatado) payload.endereco_formatado = enderecoFormatado
        if (latitude !== null) payload.latitude = latitude
        if (longitude !== null) payload.longitude = longitude
        if (placeId) payload.place_id = placeId
        if (bairro) payload.bairro = bairro
        if (tipoLocal) payload.tipo_local = tipoLocal
        if (formaPagamento) payload.forma_pagamento = formaPagamento
        if (valorAcordadoExibido) {
          const v = parseDecimal(valorAcordadoExibido)
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
      duracaoExibida,
      endereco,
      enderecoFormatado,
      latitude,
      longitude,
      placeId,
      bairro,
      tipoLocal,
      formaPagamento,
      valorAcordadoExibido,
      adicionados,
      herdarPeriodo,
      periodoHerdado,
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

      {herdarPeriodo ? (
        <p className="text-[11px] leading-4 text-text-muted">
          Data, horário e duração são herdados do agendamento acima.
        </p>
      ) : (
        <>
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
              value={duracaoExibida}
              onChange={(e) => {
                setDuracaoEditadaManual(true)
                setDuracao(e.target.value)
              }}
              disabled={disabled}
            />
            {recalculaDuracaoAutomaticamente && (
              <span className="text-[11px] leading-4 text-text-muted">
                Sugerido a partir dos programas
              </span>
            )}
          </Campo>
        </>
      )}
    </ColunaSecao>
  )

  const colunaLocal = (
    <ColunaSecao titulo="Local">
      <Campo label="Endereço">
        <CampoLocalAutocomplete
          valorInicial={endereco}
          enderecoFormatadoAtual={enderecoFormatado}
          onSelecionar={(local) => {
            setEndereco(local.endereco_formatado)
            setEnderecoFormatado(local.endereco_formatado)
            setLatitude(local.latitude)
            setLongitude(local.longitude)
            setPlaceId(local.place_id)
            if (!bairroEditadoManual) setBairro(local.localizacao_curta)
          }}
          onLimpar={() => {
            setEndereco("")
            setEnderecoFormatado(null)
            setLatitude(null)
            setLongitude(null)
            setPlaceId(null)
          }}
        />
      </Campo>
      <Campo label="Bairro">
        <Input
          className={controlClassName}
          placeholder="Bairro"
          value={bairro}
          onChange={(e) => {
            setBairroEditadoManual(true)
            setBairro(e.target.value)
          }}
          disabled={disabled}
        />
      </Campo>
      <Campo label="Tipo de local">
        <Combobox
          value={tipoLocal}
          onChange={setTipoLocal}
          options={tiposCombinados}
          placeholder="apartamento, casa…"
          onCreate={adicionarTipoSessao}
          onDeletarItem={iniciarRemocao}
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
            value={valorAcordadoExibido}
            onChange={(e) => {
              setValorEditadoManual(true)
              setValorAcordado(e.target.value)
            }}
            disabled={disabled}
          />
          {recalculaAutomaticamente && (
            <span className="text-[11px] leading-4 text-text-muted">
              Recalculado a partir dos programas
            </span>
          )}
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

  const modalRemoverTipo = (
    <ModalRemoverTipoLocal
      nome={remocao?.nome ?? null}
      contagem={remocao?.contagem ?? 0}
      tiposExistentes={tiposCombinados}
      onRemovido={aposRemover}
      onCancelar={cancelarRemocao}
    />
  )

  if (variant === "stack") {
    return (
      <div className="flex flex-col gap-3">
        <div className="flex flex-col divide-y divide-border-subtle rounded-lg border border-border-subtle bg-surface">
          {colunaAtendimento}
          {colunaLocal}
          {colunaPagamento}
        </div>
        {temConflito && <AlertaConflito conflitos={conflitos} />}
        {modalRemoverTipo}
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-border-subtle overflow-hidden md:grid-cols-3 md:divide-x md:divide-y-0">
        {colunaAtendimento}
        {colunaLocal}
        {colunaPagamento}
      </div>
      {temConflito && (
        <div className="border-t border-border-subtle px-5 py-3">
          <AlertaConflito conflitos={conflitos} />
        </div>
      )}
      {modalRemoverTipo}
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
