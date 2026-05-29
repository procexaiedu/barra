"use client"

import { useState, useEffect } from "react"
import { toast } from "sonner"
import { X } from "lucide-react"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Combobox } from "@/components/ui/combobox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api } from "@/lib/api"
import { formatBRL, formatTelefone } from "@/lib/formatters"
import { useConflitoAgenda } from "@/hooks/useConflitoAgenda"
import { useTiposLocal } from "@/hooks/useTiposLocal"
import { CampoLocalAutocomplete } from "@/components/comum/CampoLocalAutocomplete"
import { FeticheValor } from "@/components/comum/FeticheValor"
import type {
  AtendimentoDetalheResponse,
  EditarDadosPayload,
  ServicoFechado,
} from "@/tipos/atendimentos"
import { AlertaConflito } from "./AlertaConflito"
import { ModalRemoverTipoLocal } from "./ModalRemoverTipoLocal"
import { badgeForEstado, estadoLabel } from "./utils"

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
  horas: number | null
  preco: number
}

interface FeticheModelo {
  fetiche_id: string
  nome: string
  preco: number | null
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
  // Enquanto false (ou enquanto os programas não forem mexidos), respeita a duração
  // vinda do backend. Vira true se o usuário editar a duração à mão.
  const [duracaoEditadaManual, setDuracaoEditadaManual] = useState(false)
  const [endereco, setEndereco] = useState(at?.endereco ?? "")
  const [enderecoFormatado, setEnderecoFormatado] = useState<string | null>(at?.endereco_formatado ?? null)
  const [latitude, setLatitude] = useState<number | null>(at?.latitude != null ? Number(at.latitude) : null)
  const [longitude, setLongitude] = useState<number | null>(at?.longitude != null ? Number(at.longitude) : null)
  const [placeId, setPlaceId] = useState<string | null>(at?.place_id ?? null)
  const [bairro, setBairro] = useState(at?.bairro ?? "")
  // Vira true quando o usuário edita o bairro à mão; impede que uma nova seleção
  // de endereço sobrescreva a edição manual.
  const [bairroEditadoManual, setBairroEditadoManual] = useState(false)
  const [tipoLocal, setTipoLocal] = useState(at?.tipo_local ?? "")
  const [formaPagamento, setFormaPagamento] = useState(at?.forma_pagamento ?? "")
  const [valorAcordado, setValorAcordado] = useState(at?.valor_acordado != null ? String(Number(at.valor_acordado)) : "")
  // Enquanto false, o campo passa a refletir a soma dos programas assim que o
  // usuário mexer na lista. Vira true se ele editar o valor manualmente.
  const [valorEditadoManual, setValorEditadoManual] = useState(false)
  // Só recalcula depois que a lista de programas é alterada nesta sessão; ao
  // abrir, respeita o valor vindo do backend.
  const [programasMexidos, setProgramasMexidos] = useState(false)

  const [programasModelo, setProgramasModelo] = useState<ProgramaModelo[]>([])
  const [removidos, setRemovidos] = useState<Set<string>>(new Set())
  const [adicionados, setAdicionados] = useState<{ programa_id: string; duracao_id: string; label: string }[]>([])
  const [selecionado, setSelecionado] = useState("")

  const [fetichesModelo, setFetichesModelo] = useState<FeticheModelo[]>([])
  const [removidosFet, setRemovidosFet] = useState<Set<string>>(new Set())
  const [adicionadosFet, setAdicionadosFet] = useState<{ fetiche_id: string; nome: string; preco: number | null }[]>([])
  const [selecionadoFet, setSelecionadoFet] = useState("")

  const {
    tiposCombinados,
    adicionarTipoSessao,
    iniciarRemocao,
    remocao,
    cancelarRemocao,
    aposRemover,
  } = useTiposLocal()

  const modeloId = detalhe?.modelo.id
  useEffect(() => {
    if (!modeloId) return
    api<ProgramaModelo[]>(`/v1/modelos/${modeloId}/programas`)
      .then(setProgramasModelo)
      .catch(() => {})
    api<FeticheModelo[]>(`/v1/modelos/${modeloId}/fetiches`)
      .then(setFetichesModelo)
      .catch(() => {})
  }, [modeloId])

  // Calculado antes do hook de conflito para que o alerta de agenda enxergue a
  // duração efetiva (sugerida ou manual), e não a anterior.
  const servicosVisiveis = (detalhe?.servicos ?? []).filter((s) => !removidos.has(s.id))
  const horasPorDuracao = new Map(
    programasModelo
      .filter((p) => typeof p.horas === "number")
      .map((p) => [p.duracao_id, p.horas as number]),
  )
  // Maior duração (em horas) entre serviços e adicionados — nunca a soma.
  const duracaoCalculada = (() => {
    let max: number | null = null
    for (const id of [
      ...servicosVisiveis.map((s) => s.duracao_id),
      ...adicionados.map((a) => a.duracao_id),
    ]) {
      const h = horasPorDuracao.get(id)
      if (typeof h === "number" && (max === null || h > max)) max = h
    }
    return max
  })()
  // Após mexer nos programas e enquanto não houver edição manual, o campo reflete o
  // MAX. Antes disso, respeita a duração vinda do backend.
  const recalculaDuracaoAutomaticamente = programasMexidos && !duracaoEditadaManual
  const duracaoExibida =
    recalculaDuracaoAutomaticamente && duracaoCalculada !== null
      ? formatHorasCampo(duracaoCalculada)
      : duracao

  const duracaoHoras = parseDecimal(duracaoExibida) ?? 0
  const { conflitos } = useConflitoAgenda({
    modelo_id: modeloId ?? null,
    data: dataDesejada,
    horario,
    duracao_horas: duracaoHoras,
    excluir_bloqueio_id: detalhe?.bloqueio?.id ?? null,
  })

  if (!detalhe || !at) return null

  const activePairs = new Set([
    ...servicosVisiveis.map((s: ServicoFechado) => `${s.programa_id}|${s.duracao_id}`),
    ...adicionados.map((a) => `${a.programa_id}|${a.duracao_id}`),
  ])
  const disponiveis = programasModelo.filter((p) => !activePairs.has(`${p.programa_id}|${p.duracao_id}`))

  // Soma dos preços dos programas atuais: serviços existentes (preco_snapshot)
  // mais os adicionados nesta sessão (preco do catálogo). Ignora preço null/NaN.
  const somaServicos = servicosVisiveis.reduce(
    (total, s) => (Number.isFinite(s.preco_snapshot) ? total + s.preco_snapshot : total),
    0,
  )
  const somaAdicionados = adicionados.reduce((total, a) => {
    const prog = programasModelo.find(
      (p) => p.programa_id === a.programa_id && p.duracao_id === a.duracao_id,
    )
    const preco = prog?.preco
    return Number.isFinite(preco) ? total + (preco as number) : total
  }, 0)
  const valorCalculado = somaServicos + somaAdicionados

  // Após mexer nos programas e enquanto não houver edição manual, o campo reflete
  // a soma (valor derivado). Antes disso, respeita o valor vindo do backend.
  const recalculaAutomaticamente = programasMexidos && !valorEditadoManual
  const valorAcordadoExibido = recalculaAutomaticamente
    ? formatValorCampo(valorCalculado)
    : valorAcordado

  const handleAdicionarPrograma = () => {
    if (!selecionado) return
    const [progId, durId] = selecionado.split("|")
    const prog = programasModelo.find((p) => p.programa_id === progId && p.duracao_id === durId)
    if (!prog) return
    setAdicionados((prev) => [...prev, { programa_id: progId, duracao_id: durId, label: `${prog.nome} – ${prog.duracao_nome}` }])
    setSelecionado("")
    setProgramasMexidos(true)
  }

  // Fetiches: composição registrada (preco_snapshot), não soma no valor (Valor final manual).
  const fetichesVisiveis = (detalhe.fetiches ?? []).filter((f) => !removidosFet.has(f.id))
  const fetichesAtivos = new Set([
    ...fetichesVisiveis.map((f) => f.fetiche_id),
    ...adicionadosFet.map((a) => a.fetiche_id),
  ])
  const fetichesDisponiveis = fetichesModelo.filter((f) => !fetichesAtivos.has(f.fetiche_id))

  const handleAdicionarFetiche = () => {
    if (!selecionadoFet) return
    const fet = fetichesModelo.find((f) => f.fetiche_id === selecionadoFet)
    if (!fet) return
    setAdicionadosFet((prev) => [...prev, { fetiche_id: fet.fetiche_id, nome: fet.nome, preco: fet.preco }])
    setSelecionadoFet("")
  }

  const handleSalvar = async () => {
    const dados: EditarDadosPayload = {}
    if (tipo) dados.tipo_atendimento = tipo as "interno" | "externo"
    if (urgencia) dados.urgencia = urgencia as EditarDadosPayload["urgencia"]
    if (dataDesejada) dados.data_desejada = dataDesejada
    if (horario) dados.horario_desejado = horario
    if (duracaoExibida) {
      const d = parseDecimal(duracaoExibida)
      if (d !== null) dados.duracao_horas = d
    }
    if (endereco) dados.endereco = endereco
    if (enderecoFormatado) dados.endereco_formatado = enderecoFormatado
    if (latitude !== null) dados.latitude = latitude
    if (longitude !== null) dados.longitude = longitude
    if (placeId) dados.place_id = placeId
    if (bairro) dados.bairro = bairro
    if (tipoLocal) dados.tipo_local = tipoLocal
    if (formaPagamento) dados.forma_pagamento = formaPagamento
    if (valorAcordadoExibido) {
      const v = parseDecimal(valorAcordadoExibido)
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
      for (const fetVinculoId of removidosFet) {
        await api(`/v1/atendimentos/${at.id}/fetiches/${fetVinculoId}`, { method: "DELETE" })
      }
      for (const a of adicionadosFet) {
        await api(`/v1/atendimentos/${at.id}/fetiches`, {
          method: "POST",
          body: JSON.stringify({ fetiche_id: a.fetiche_id }),
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
          <DialogTitle className="font-serif text-xl font-medium leading-tight text-text-primary">
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
            <Badge variant={badgeForEstado(at.estado)} className="w-fit px-2 py-0.5 text-[11px]">
              {estadoLabel[at.estado]}
            </Badge>
            {at.ia_pausada && <span className="mt-1 text-text-muted">IA pausada</span>}
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
              <Input
                className={controlClassName}
                inputMode="decimal"
                placeholder="2"
                value={duracaoExibida}
                onChange={(e) => {
                  setDuracaoEditadaManual(true)
                  setDuracao(e.target.value)
                }}
              />
              {recalculaDuracaoAutomaticamente && (
                <span className="text-[11px] leading-4 text-text-muted">
                  Sugerido a partir dos programas
                </span>
              )}
            </Campo>
          </ColunaSecao>

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
              <span className="text-[11px] leading-4 text-text-muted">
                {tipo === "interno"
                  ? "No local da modelo — o ponto de encontro é o endereço dela. Registre aqui só o endereço do cliente, se precisar."
                  : "Endereço do cliente (onde a modelo vai)."}
              </span>
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
                  <option value="cartao">Cartão</option>
                </select>
              </Campo>
              <Campo label="Valor acordado (R$)">
                <Input
                  className={controlClassName}
                  inputMode="decimal"
                  placeholder="1.200,00"
                  value={valorAcordadoExibido}
                  onChange={(e) => {
                    setValorEditadoManual(true)
                    setValorAcordado(e.target.value)
                  }}
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
                {servicosVisiveis.map((s) => (
                  <div key={s.id} className="flex items-center justify-between rounded-lg border border-border-subtle bg-surface-hover px-3 py-2 text-sm">
                    <span className="text-text-primary">{s.nome}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-text-muted">{s.duracao_nome}</span>
                      <button
                        type="button"
                        onClick={() => {
                          setRemovidos((prev) => new Set([...prev, s.id]))
                          setProgramasMexidos(true)
                        }}
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
                      onClick={() => {
                        setAdicionados((prev) => prev.filter((_, j) => j !== i))
                        setProgramasMexidos(true)
                      }}
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

              <span className="mt-2 text-[11px] font-medium leading-4 text-text-muted">Fetiches</span>
              <div className="flex flex-col gap-1">
                {fetichesVisiveis.map((f) => (
                  <div key={f.id} className="flex items-center justify-between rounded-lg border border-border-subtle bg-surface-hover px-3 py-2 text-sm">
                    <span className="text-text-primary">{f.nome}</span>
                    <div className="flex items-center gap-2">
                      <FeticheValor preco={f.preco_snapshot} />
                      <button
                        type="button"
                        onClick={() => setRemovidosFet((prev) => new Set([...prev, f.id]))}
                        className="text-text-muted transition-colors hover:text-text-primary"
                        disabled={submitting}
                      >
                        <X size={14} />
                      </button>
                    </div>
                  </div>
                ))}
                {adicionadosFet.map((a, i) => (
                  <div key={i} className="flex items-center justify-between rounded-lg border border-dashed border-border-subtle bg-surface px-3 py-2 text-sm">
                    <span className="text-text-primary">{a.nome}</span>
                    <div className="flex items-center gap-2">
                      <FeticheValor preco={a.preco} />
                      <button
                        type="button"
                        onClick={() => setAdicionadosFet((prev) => prev.filter((_, j) => j !== i))}
                        className="text-text-muted transition-colors hover:text-text-primary"
                        disabled={submitting}
                      >
                        <X size={14} />
                      </button>
                    </div>
                  </div>
                ))}
                {fetichesVisiveis.length === 0 && adicionadosFet.length === 0 && fetichesDisponiveis.length === 0 && (
                  <span className="text-xs text-text-muted">Nenhum fetiche marcado para esta modelo.</span>
                )}
              </div>
              {fetichesDisponiveis.length > 0 && (
                <div className="mt-1 flex gap-2">
                  <select
                    value={selecionadoFet}
                    onChange={(e) => setSelecionadoFet(e.target.value)}
                    className={controlClassName}
                    disabled={submitting}
                  >
                    <option value="">Adicionar fetiche…</option>
                    {fetichesDisponiveis.map((f) => (
                      <option key={f.fetiche_id} value={f.fetiche_id}>
                        {f.nome}{f.preco === null ? "" : ` (+${formatBRL(f.preco)})`}
                      </option>
                    ))}
                  </select>
                  <Button variant="secondary" onClick={handleAdicionarFetiche} disabled={!selecionadoFet || submitting}>
                    Adicionar
                  </Button>
                </div>
              )}
            </div>
          </ColunaSecao>
        </div>

        {conflitos.length > 0 && (
          <div className="border-t border-border-subtle bg-surface px-5 pt-3">
            <AlertaConflito conflitos={conflitos} />
          </div>
        )}

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
            <Button variant="primary" onClick={handleSalvar} disabled={submitting || conflitos.length > 0}>
              {submitting ? "Salvando…" : "Salvar"}
            </Button>
          </div>
        </div>
      </DialogContent>
      <ModalRemoverTipoLocal
        nome={remocao?.nome ?? null}
        contagem={remocao?.contagem ?? 0}
        tiposExistentes={tiposCombinados}
        onRemovido={aposRemover}
        onCancelar={cancelarRemocao}
      />
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
      <span className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        <span className="h-2.5 w-0.5 rounded-full bg-gold-500" aria-hidden />
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
