"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { AlertTriangle, Info, Loader2, Plus, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import type {
  BloqueioForaAlerta,
  DisponibilidadeResponse,
  DisponibilidadeSalvarResponse,
  RegraDisponibilidade,
  StatusModelo,
} from "@/tipos/modelos"

const DIAS_CURTO = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"] as const
const DIAS_INDEX = [0, 1, 2, 3, 4, 5, 6] as const

interface Janela {
  key: string
  hora_inicio: string
  hora_fim: string
  dias: number[]
}

interface Vigencia {
  data_inicio: string
  data_fim: string | null
}

function hojeIso(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

function novaJanela(): Janela {
  return { key: crypto.randomUUID(), hora_inicio: "", hora_fim: "", dias: [] }
}

function parseHorario(hhmm: string): number | null {
  if (!/^\d{2}:\d{2}$/.test(hhmm)) return null
  const [h, m] = hhmm.split(":").map(Number)
  if (h > 23 || m > 59) return null
  return h * 60 + m
}

function cruzaMeiaNoite(j: Janela): boolean {
  const ini = parseHorario(j.hora_inicio)
  const fim = parseHorario(j.hora_fim)
  if (ini === null || fim === null) return false
  return fim < ini
}

function janelaCheia24h(j: Janela): boolean {
  const ini = parseHorario(j.hora_inicio)
  const fim = parseHorario(j.hora_fim)
  return ini !== null && fim !== null && ini === fim
}

function formatarDataCurta(yyyymmdd: string): string {
  const [y, m, d] = yyyymmdd.split("-")
  return `${d}/${m}/${y.slice(2)}`
}

function formatarVigencia(v: Vigencia): string {
  const ini = v.data_inicio === hojeIso() ? "a partir de hoje" : `de ${formatarDataCurta(v.data_inicio)}`
  const fim = v.data_fim === null ? "sem prazo final" : `até ${formatarDataCurta(v.data_fim)}`
  return `${ini}, ${fim}.`
}

function formatHoraCurta(hhmm: string): string {
  const [h, m] = hhmm.split(":")
  return m === "00" ? `${h}h` : `${h}h${m}`
}

function vigenciasIguais(a: Vigencia, b: Vigencia): boolean {
  return a.data_inicio === b.data_inicio && a.data_fim === b.data_fim
}

function janelasIguais(a: Janela[], b: Janela[]): boolean {
  if (a.length !== b.length) return false
  const norm = (xs: Janela[]) =>
    xs.map((j) => `${j.hora_inicio}|${j.hora_fim}|${[...j.dias].sort().join(",")}`).sort()
  const A = norm(a)
  const B = norm(b)
  return A.every((s, i) => s === B[i])
}

// Agrupa regras-do-backend por (hora_inicio, hora_fim) e infere vigência global.
function agruparRegras(regras: RegraDisponibilidade[]): {
  vigencia: Vigencia
  janelas: Janela[]
  vigenciaHeterogenea: boolean
} {
  if (regras.length === 0) {
    return {
      vigencia: { data_inicio: hojeIso(), data_fim: null },
      janelas: [],
      vigenciaHeterogenea: false,
    }
  }
  const inicios = [...regras.map((r) => r.data_inicio)].sort()
  const algumSemFim = regras.some((r) => r.data_fim === null)
  const fimDerivado: string | null = algumSemFim
    ? null
    : [...regras.map((r) => r.data_fim as string)].sort().at(-1) ?? null
  const inicioDerivado = inicios[0]
  const vigenciaHeterogenea = regras.some(
    (r) => r.data_inicio !== inicioDerivado || r.data_fim !== fimDerivado,
  )

  const buckets = new Map<string, Janela>()
  for (const r of regras) {
    const chave = `${r.hora_inicio}|${r.hora_fim}`
    let j = buckets.get(chave)
    if (!j) {
      j = { key: crypto.randomUUID(), hora_inicio: r.hora_inicio, hora_fim: r.hora_fim, dias: [] }
      buckets.set(chave, j)
    }
    if (!j.dias.includes(r.dia_semana)) j.dias.push(r.dia_semana)
  }
  const janelas = Array.from(buckets.values())
  janelas.forEach((j) => j.dias.sort())
  return {
    vigencia: { data_inicio: inicioDerivado, data_fim: fimDerivado },
    janelas,
    vigenciaHeterogenea,
  }
}

function expandirParaRegras(vigencia: Vigencia, janelas: Janela[]): RegraDisponibilidade[] {
  const out: RegraDisponibilidade[] = []
  for (const j of janelas) {
    for (const d of j.dias) {
      out.push({
        data_inicio: vigencia.data_inicio,
        data_fim: vigencia.data_fim,
        dia_semana: d,
        hora_inicio: j.hora_inicio,
        hora_fim: j.hora_fim,
      })
    }
  }
  return out
}

export function DisponibilidadeModelo({
  modeloId,
  statusModelo,
}: {
  modeloId: string
  statusModelo?: StatusModelo
}) {
  const [vigencia, setVigencia] = useState<Vigencia>({ data_inicio: hojeIso(), data_fim: null })
  const [janelas, setJanelas] = useState<Janela[]>([])
  const [pristine, setPristine] = useState<{ vigencia: Vigencia; janelas: Janela[] }>({
    vigencia: { data_inicio: hojeIso(), data_fim: null },
    janelas: [],
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [alerta, setAlerta] = useState<BloqueioForaAlerta[]>([])
  const [vigenciaHeterogenea, setVigenciaHeterogenea] = useState(false)

  const carregar = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api<DisponibilidadeResponse>(`/v1/modelos/${modeloId}/disponibilidade`)
      const { vigencia: v, janelas: j, vigenciaHeterogenea: het } = agruparRegras(res.regras)
      setVigencia(v)
      setJanelas(j)
      setPristine({ vigencia: v, janelas: j.map((x) => ({ ...x, dias: [...x.dias] })) })
      setVigenciaHeterogenea(het)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao carregar período")
    } finally {
      setLoading(false)
    }
  }, [modeloId])

  useEffect(() => {
    const t = setTimeout(carregar, 0)
    return () => clearTimeout(t)
  }, [carregar])

  const dirty =
    !vigenciasIguais(vigencia, pristine.vigencia) || !janelasIguais(janelas, pristine.janelas)

  const pendentes = useMemo(() => {
    let n = 0
    if (!vigenciasIguais(vigencia, pristine.vigencia)) n += 1
    if (!janelasIguais(janelas, pristine.janelas)) {
      n += Math.max(1, Math.abs(janelas.length - pristine.janelas.length))
    }
    return n
  }, [vigencia, janelas, pristine])

  const adicionarJanela = () => setJanelas((js) => [...js, novaJanela()])
  const atualizarJanela = (key: string, patch: Partial<Janela>) =>
    setJanelas((js) => js.map((j) => (j.key === key ? { ...j, ...patch } : j)))
  const removerJanela = (key: string) => setJanelas((js) => js.filter((j) => j.key !== key))
  const toggleDia = (key: string, dia: number) =>
    setJanelas((js) =>
      js.map((j) =>
        j.key === key
          ? {
              ...j,
              dias: j.dias.includes(dia)
                ? j.dias.filter((d) => d !== dia)
                : [...j.dias, dia].sort(),
            }
          : j,
      ),
    )

  const salvar = async () => {
    for (const j of janelas) {
      if (parseHorario(j.hora_inicio) === null || parseHorario(j.hora_fim) === null) {
        toast.error("Preencha hora de início e fim de todas as janelas")
        return
      }
      if (j.dias.length === 0) {
        toast.error("Cada janela precisa de ao menos um dia selecionado")
        return
      }
    }
    if (!vigencia.data_inicio) {
      toast.error("Data de início da vigência é obrigatória")
      return
    }
    if (vigencia.data_fim && vigencia.data_fim < vigencia.data_inicio) {
      toast.error("Data fim não pode ser anterior à de início")
      return
    }
    setSaving(true)
    try {
      const body = { regras: expandirParaRegras(vigencia, janelas) }
      const res = await api<DisponibilidadeSalvarResponse>(
        `/v1/modelos/${modeloId}/disponibilidade`,
        { method: "PUT", body: JSON.stringify(body) },
      )
      const { vigencia: v, janelas: j, vigenciaHeterogenea: het } = agruparRegras(res.regras)
      setVigencia(v)
      setJanelas(j)
      setPristine({ vigencia: v, janelas: j.map((x) => ({ ...x, dias: [...x.dias] })) })
      setVigenciaHeterogenea(het)
      setAlerta(res.bloqueios_fora)
      toast.success("Período de trabalho salvo")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar")
    } finally {
      setSaving(false)
    }
  }

  const statusInativo = statusModelo === "pausada" || statusModelo === "inativa"

  return (
    <section className="flex flex-col gap-4">
      {statusInativo && <BannerStatus status={statusModelo!} />}

      <div className="rounded-lg bg-card p-6 shadow-elev-1 ring-1 ring-border-subtle">
        <header className="mb-4">
          <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
            <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
            Período de trabalho
          </h2>
          <p className="mt-1 max-w-prose pl-[14px] text-sm text-text-muted">
            Defina os dias e horários em que a modelo aceita encontro. Fora desses dias e horários, o
            sistema não cria agendamento e a IA não sugere. Sem nenhuma janela, ela é tratada como
            disponível sempre.
          </p>
        </header>

        <BarraVigencia
          vigencia={vigencia}
          onChange={setVigencia}
          heterogenea={vigenciaHeterogenea}
        />

        {loading ? (
          <div className="flex items-center justify-center py-10 text-text-muted">
            <Loader2 className="animate-spin" size={16} strokeWidth={1.5} />
          </div>
        ) : janelas.length === 0 ? (
          <EstadoVazio onAdicionar={adicionarJanela} />
        ) : (
          <>
            <div className="mt-5 space-y-2">
              {janelas.map((j) => (
                <CartaoJanela
                  key={j.key}
                  janela={j}
                  onChangeHorario={(patch) => atualizarJanela(j.key, patch)}
                  onToggleDia={(dia) => toggleDia(j.key, dia)}
                  onRemove={() => removerJanela(j.key)}
                />
              ))}
            </div>
            <div className="mt-2">
              <Button variant="ghost" size="sm" onClick={adicionarJanela}>
                <Plus size={13} strokeWidth={1.5} />
                Adicionar janela
              </Button>
            </div>
            <MiniTimeline janelas={janelas} />
          </>
        )}

        {!loading && (
          <div className="mt-5 flex items-center justify-between gap-3 border-t border-border pt-4">
            <p className="text-xs text-text-muted">
              {dirty ? "Há alterações não salvas." : "Tudo salvo."}
            </p>
            <Button
              variant="primary"
              size="sm"
              onClick={salvar}
              disabled={!dirty || saving}
            >
              {saving && <Loader2 size={14} className="animate-spin" />}
              {dirty
                ? `Salvar alterações${pendentes > 0 ? ` · ${pendentes}` : ""}`
                : "Salvar período"}
            </Button>
          </div>
        )}

        {alerta.length > 0 && <AlertaBloqueiosFora alerta={alerta} />}
      </div>
    </section>
  )
}

function BannerStatus({ status }: { status: StatusModelo }) {
  const label = status === "pausada" ? "Modelo pausada" : "Modelo inativa"
  return (
    <div className="flex items-start gap-3 rounded-lg border border-state-info/40 bg-state-info/10 px-4 py-3">
      <Info size={15} strokeWidth={1.5} className="mt-0.5 shrink-0 text-state-info" />
      <div className="text-sm">
        <span className="font-medium text-text-primary">{label}.</span>{" "}
        <span className="text-text-secondary">A IA não responde no momento.</span>{" "}
        <span className="text-text-muted">
          A configuração desta seção fica salva. Reative no topo da página para voltar a operar.
        </span>
      </div>
    </div>
  )
}

function BarraVigencia({
  vigencia,
  onChange,
  heterogenea,
}: {
  vigencia: Vigencia
  onChange: (v: Vigencia) => void
  heterogenea: boolean
}) {
  const [open, setOpen] = useState(false)
  const [draftInicio, setDraftInicio] = useState(vigencia.data_inicio)
  const [draftFim, setDraftFim] = useState<string>(vigencia.data_fim ?? "")
  const [semFim, setSemFim] = useState<boolean>(vigencia.data_fim === null)

  const aoMudarOpen = (proximo: boolean) => {
    if (proximo) {
      // Sincroniza o rascunho com a vigência atual ao abrir; o draft só vira commit ao Aplicar.
      setDraftInicio(vigencia.data_inicio)
      setDraftFim(vigencia.data_fim ?? "")
      setSemFim(vigencia.data_fim === null)
    }
    setOpen(proximo)
  }

  const aplicar = () => {
    if (!draftInicio) {
      toast.error("Data de início é obrigatória")
      return
    }
    if (!semFim && draftFim && draftFim < draftInicio) {
      toast.error("Data fim não pode ser anterior à de início")
      return
    }
    onChange({
      data_inicio: draftInicio,
      data_fim: semFim ? null : draftFim || null,
    })
    setOpen(false)
  }

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-muted/40 px-3 py-2 text-sm">
        <span>
          <span className="text-text-muted">Vigência:</span>{" "}
          <span className="text-text-primary">{formatarVigencia(vigencia)}</span>
        </span>
        <Popover open={open} onOpenChange={aoMudarOpen}>
          <PopoverTrigger className="text-xs text-text-link underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            alterar
          </PopoverTrigger>
          <PopoverContent className="w-72 space-y-3">
            <div>
              <label className="block text-[11px] font-medium uppercase tracking-wide text-text-muted">
                Início
              </label>
              <Input
                type="date"
                value={draftInicio}
                onChange={(e) => setDraftInicio(e.target.value)}
                className="mt-1 h-9 bg-input text-sm"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium uppercase tracking-wide text-text-muted">
                Fim
              </label>
              <Input
                type="date"
                disabled={semFim}
                value={draftFim}
                onChange={(e) => setDraftFim(e.target.value)}
                className="mt-1 h-9 bg-input text-sm disabled:opacity-40"
              />
              <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs text-text-secondary">
                <input
                  type="checkbox"
                  checked={semFim}
                  onChange={(e) => setSemFim(e.target.checked)}
                  className="size-3.5 rounded border-input bg-transparent accent-primary"
                />
                Sem prazo final
              </label>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
                Cancelar
              </Button>
              <Button variant="primary" size="sm" onClick={aplicar}>
                Aplicar
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      </div>
      {heterogenea && (
        <p className="px-3 text-[11px] text-state-handoff">
          Configuração antiga com vigências diferentes detectada. Salvar substituirá pelo intervalo
          mostrado acima.
        </p>
      )}
    </div>
  )
}

function EstadoVazio({ onAdicionar }: { onAdicionar: () => void }) {
  return (
    <div className="mt-5 rounded-lg border border-dashed border-state-handoff/40 bg-state-handoff/5 px-5 py-6">
      <div className="flex items-start gap-3">
        <AlertTriangle
          size={16}
          strokeWidth={1.5}
          className="mt-0.5 shrink-0 text-state-handoff"
        />
        <div className="space-y-2">
          <p className="text-sm font-medium text-text-primary">Sem janela configurada</p>
          <p className="text-sm text-text-secondary">
            A modelo é tratada como disponível{" "}
            <strong className="text-text-primary">sempre</strong>. A IA pode sugerir qualquer
            horário do dia, qualquer dia da semana.
          </p>
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Button variant="primary" size="sm" onClick={onAdicionar}>
              <Plus size={13} strokeWidth={1.5} />
              Adicionar primeira janela
            </Button>
            <span className="text-xs text-text-muted">
              Quer parar de atender de vez? Pause a modelo no topo da página.
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

function CartaoJanela({
  janela,
  onChangeHorario,
  onToggleDia,
  onRemove,
}: {
  janela: Janela
  onChangeHorario: (patch: Partial<Janela>) => void
  onToggleDia: (dia: number) => void
  onRemove: () => void
}) {
  const cruza = cruzaMeiaNoite(janela)
  const cheia24h = janelaCheia24h(janela)
  const horariosValidos =
    parseHorario(janela.hora_inicio) !== null && parseHorario(janela.hora_fim) !== null

  return (
    <div className="rounded-md border border-border bg-surface p-3 shadow-elev-1">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Input
            type="time"
            aria-label="Hora de início"
            value={janela.hora_inicio}
            onChange={(e) => onChangeHorario({ hora_inicio: e.target.value })}
            className="h-9 w-[7rem] bg-input text-sm tabular-nums"
          />
          <span className="text-text-muted">→</span>
          <Input
            type="time"
            aria-label="Hora de fim"
            value={janela.hora_fim}
            onChange={(e) => onChangeHorario({ hora_fim: e.target.value })}
            className="h-9 w-[7rem] bg-input text-sm tabular-nums"
          />
        </div>
        {horariosValidos && cheia24h && (
          <span className="rounded-full bg-state-info/15 px-2 py-0.5 text-[11px] text-state-info">
            24 horas
          </span>
        )}
        {horariosValidos && cruza && !cheia24h && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-text-secondary">
            » dia seguinte
          </span>
        )}
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onRemove}
          aria-label="Remover janela"
          className="ml-auto hover:text-state-lost"
        >
          <X size={14} strokeWidth={1.5} />
        </Button>
      </div>
      <div className="mt-3 flex flex-wrap gap-1">
        {DIAS_INDEX.map((i) => {
          const ativo = janela.dias.includes(i)
          return (
            <button
              key={i}
              type="button"
              onClick={() => onToggleDia(i)}
              aria-pressed={ativo}
              className={cn(
                "h-7 min-w-[2.75rem] rounded-full border px-2 text-xs font-medium capitalize transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                ativo
                  ? "border-gold-500 bg-gold-500/15 text-text-primary"
                  : "border-border bg-transparent text-text-muted hover:border-border-strong hover:text-text-secondary",
              )}
            >
              {DIAS_CURTO[i]}
            </button>
          )
        })}
      </div>
      {horariosValidos && cruza && !cheia24h && janela.dias.length > 0 && (
        <p className="mt-2 text-[11px] text-text-muted">
          {janela.dias
            .map((d) => {
              const prox = (d + 1) % 7
              return `${DIAS_CURTO[d]} ${janela.hora_inicio} → ${DIAS_CURTO[prox]} ${janela.hora_fim}`
            })
            .join(" · ")}
        </p>
      )}
    </div>
  )
}

function MiniTimeline({ janelas }: { janelas: Janela[] }) {
  // 48 células de 30 min; cobre uma janela testando cada célula contra a regra do dia
  // (e a regra do dia anterior, quando a janela cruza a meia-noite).
  const CELLS = 48

  const celulaCoberta = useMemo(() => {
    const matrix: boolean[][] = []
    for (let dia = 0; dia < 7; dia++) {
      const linha: boolean[] = []
      for (let cell = 0; cell < CELLS; cell++) {
        const cellMin = cell * 30
        let coberta = false
        for (const j of janelas) {
          if (j.dias.length === 0) continue
          const ini = parseHorario(j.hora_inicio)
          const fim = parseHorario(j.hora_fim)
          if (ini === null || fim === null) continue
          const cruza = fim < ini
          const cheia24 = ini === fim
          if (cheia24) {
            if (j.dias.includes(dia)) {
              coberta = true
              break
            }
            continue
          }
          if (!cruza) {
            if (j.dias.includes(dia) && cellMin >= ini && cellMin < fim) {
              coberta = true
              break
            }
          } else {
            if (j.dias.includes(dia) && cellMin >= ini) {
              coberta = true
              break
            }
            const diaAnterior = (dia + 6) % 7
            if (j.dias.includes(diaAnterior) && cellMin < fim) {
              coberta = true
              break
            }
          }
        }
        linha.push(coberta)
      }
      matrix.push(linha)
    }
    return matrix
  }, [janelas])

  function resumoDia(dia: number): string {
    const ativas: string[] = []
    for (const j of janelas) {
      if (j.dias.includes(dia)) {
        if (janelaCheia24h(j)) ativas.push("24 h")
        else if (parseHorario(j.hora_inicio) !== null && parseHorario(j.hora_fim) !== null) {
          ativas.push(`${formatHoraCurta(j.hora_inicio)}–${formatHoraCurta(j.hora_fim)}`)
        }
      }
    }
    return ativas.length === 0 ? "folga" : ativas.join(", ")
  }

  return (
    <div className="mt-5 rounded-md border border-border bg-muted/30 p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[11px] font-medium uppercase tracking-wide text-text-muted">Como fica</p>
        <div className="hidden gap-6 text-[10px] text-text-muted sm:flex">
          <span>00h</span>
          <span>06h</span>
          <span>12h</span>
          <span>18h</span>
          <span>24h</span>
        </div>
      </div>
      <div className="space-y-1">
        {DIAS_INDEX.map((dia) => (
          <div key={dia} className="flex items-center gap-2">
            <span className="w-9 shrink-0 text-[11px] uppercase tracking-wide text-text-muted">
              {DIAS_CURTO[dia]}
            </span>
            <div className="flex h-3 flex-1 overflow-hidden rounded-sm bg-input/40 ring-1 ring-border/40">
              {celulaCoberta[dia].map((coberta, cell) => (
                <div
                  key={cell}
                  className={cn(
                    "flex-1",
                    coberta ? "bg-gold-500/70" : "bg-transparent",
                    cell !== 0 && cell % 12 === 0 && "border-l border-border/40",
                  )}
                />
              ))}
            </div>
            <span className="w-28 shrink-0 truncate text-right text-[11px] text-text-secondary">
              {resumoDia(dia)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function AlertaBloqueiosFora({ alerta }: { alerta: BloqueioForaAlerta[] }) {
  return (
    <div className="mt-5 rounded-lg border border-state-handoff/40 bg-state-handoff/10 px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-medium text-state-handoff">
        <AlertTriangle size={15} strokeWidth={1.5} />
        {alerta.length} agendamento(s) futuro(s) ficaram fora do novo período
      </div>
      <p className="mt-1 text-xs text-text-muted">
        Não foram cancelados — revise na Agenda se quiser ajustar.
      </p>
      <ul className="mt-2 space-y-1 text-xs text-text-secondary">
        {alerta.map((b) => (
          <li key={b.id}>
            {b.numero_curto ? `#${b.numero_curto} · ` : ""}
            {b.cliente_nome ?? "sem cliente"} · {formatarQuando(b.inicio)}
          </li>
        ))}
      </ul>
    </div>
  )
}

function formatarQuando(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}
