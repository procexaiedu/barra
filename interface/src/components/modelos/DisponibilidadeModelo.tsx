"use client"

import { useCallback, useEffect, useState } from "react"
import { AlertTriangle, Loader2, Plus, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import type {
  BloqueioForaAlerta,
  DisponibilidadeResponse,
  DisponibilidadeSalvarResponse,
  RegraDisponibilidade,
} from "@/tipos/modelos"

const DIAS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]

// Estado local de uma regra; `key` só para o React (não vai para a API).
interface RegraLocal extends RegraDisponibilidade {
  key: string
}

function novaRegra(): RegraLocal {
  return {
    key: crypto.randomUUID(),
    data_inicio: "",
    data_fim: null,
    dia_semana: 1,
    hora_inicio: "14:00",
    hora_fim: "22:00",
  }
}

export function DisponibilidadeModelo({ modeloId }: { modeloId: string }) {
  const [regras, setRegras] = useState<RegraLocal[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [alerta, setAlerta] = useState<BloqueioForaAlerta[]>([])

  const carregar = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api<DisponibilidadeResponse>(`/v1/modelos/${modeloId}/disponibilidade`)
      setRegras(res.regras.map((r) => ({ ...r, key: crypto.randomUUID() })))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao carregar período")
    } finally {
      setLoading(false)
    }
  }, [modeloId])

  useEffect(() => {
    // setTimeout(…, 0) evita setState síncrono dentro do effect (padrão do useModelos).
    const t = setTimeout(carregar, 0)
    return () => clearTimeout(t)
  }, [carregar])

  const atualizar = (key: string, patch: Partial<RegraDisponibilidade>) => {
    setRegras((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  }

  const remover = (key: string) => setRegras((rs) => rs.filter((r) => r.key !== key))
  const adicionar = () => setRegras((rs) => [...rs, novaRegra()])

  const salvar = async () => {
    for (const r of regras) {
      if (!r.data_inicio || !r.hora_inicio || !r.hora_fim) {
        toast.error("Preencha data de início e horários de todas as regras")
        return
      }
      if (r.data_fim && r.data_fim < r.data_inicio) {
        toast.error("A data de fim não pode ser anterior à de início")
        return
      }
    }
    setSaving(true)
    try {
      const body = {
        regras: regras.map((r) => ({
          data_inicio: r.data_inicio,
          data_fim: r.data_fim,
          dia_semana: r.dia_semana,
          hora_inicio: r.hora_inicio,
          hora_fim: r.hora_fim,
        })),
      }
      const res = await api<DisponibilidadeSalvarResponse>(
        `/v1/modelos/${modeloId}/disponibilidade`,
        { method: "PUT", body: JSON.stringify(body) },
      )
      setRegras(res.regras.map((r) => ({ ...r, key: crypto.randomUUID() })))
      setAlerta(res.bloqueios_fora)
      toast.success("Período de trabalho salvo")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar")
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="rounded-lg border border-border bg-card p-6">
      <header className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-text-primary">Período de trabalho</h2>
          <p className="mt-1 max-w-prose text-sm text-text-muted">
            Defina os dias e horários em que a modelo aceita encontro. Fora desses dias/horários,
            o sistema não cria agendamento (e a IA não sugere). Sem nenhuma regra, ela é tratada
            como disponível sempre.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={adicionar} disabled={loading}>
          <Plus size={13} strokeWidth={1.5} />
          Adicionar regra
        </Button>
      </header>

      {loading ? (
        <div className="flex items-center justify-center py-10 text-text-muted">
          <Loader2 className="animate-spin" />
        </div>
      ) : regras.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-muted px-4 py-10 text-center">
          <p className="text-sm text-text-secondary">Sem período configurado.</p>
          <p className="mt-1 text-xs text-text-muted">
            A modelo está disponível sempre. Use{" "}
            <button
              type="button"
              onClick={adicionar}
              className="cursor-pointer text-text-primary underline-offset-2 hover:underline"
            >
              Adicionar regra
            </button>{" "}
            para restringir a uma janela.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="hidden grid-cols-[5.5rem_6rem_6rem_1fr_1fr_2rem] gap-2 px-1 text-[11px] font-medium uppercase tracking-wide text-text-muted sm:grid">
            <span>Dia</span>
            <span>Início</span>
            <span>Fim</span>
            <span>De</span>
            <span>Até</span>
            <span />
          </div>
          {regras.map((r) => (
            <LinhaRegra
              key={r.key}
              regra={r}
              onChange={(patch) => atualizar(r.key, patch)}
              onRemove={() => remover(r.key)}
            />
          ))}
        </div>
      )}

      {!loading && (
        <div className="mt-5 flex justify-end">
          <Button variant="primary" size="sm" onClick={salvar} disabled={saving}>
            {saving && <Loader2 size={14} className="animate-spin" />}
            Salvar período
          </Button>
        </div>
      )}

      {alerta.length > 0 && (
        <div className="mt-4 rounded-lg border border-state-handoff/40 bg-state-handoff/10 px-4 py-3">
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
      )}
    </section>
  )
}

function LinhaRegra({
  regra,
  onChange,
  onRemove,
}: {
  regra: RegraDisponibilidade
  onChange: (patch: Partial<RegraDisponibilidade>) => void
  onRemove: () => void
}) {
  const semFim = regra.data_fim === null
  return (
    <div className="grid grid-cols-2 items-center gap-2 rounded-lg border border-border bg-card p-2 sm:grid-cols-[5.5rem_6rem_6rem_1fr_1fr_2rem] sm:border-0 sm:bg-transparent sm:p-1">
      <select
        aria-label="Dia da semana"
        value={regra.dia_semana}
        onChange={(e) => onChange({ dia_semana: Number(e.target.value) })}
        className="h-9 rounded-md border border-border bg-input px-2 text-sm text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {DIAS.map((d, i) => (
          <option key={i} value={i}>
            {d}
          </option>
        ))}
      </select>
      <Input
        type="time"
        aria-label="Hora de início"
        value={regra.hora_inicio}
        onChange={(e) => onChange({ hora_inicio: e.target.value })}
        className="h-9 bg-input text-sm"
      />
      <Input
        type="time"
        aria-label="Hora de fim"
        value={regra.hora_fim}
        onChange={(e) => onChange({ hora_fim: e.target.value })}
        className="h-9 bg-input text-sm"
      />
      <Input
        type="date"
        aria-label="Data de início"
        value={regra.data_inicio}
        onChange={(e) => onChange({ data_inicio: e.target.value })}
        className="h-9 bg-input text-sm"
      />
      <div className="flex items-center gap-2">
        {semFim ? (
          <label className="flex h-9 flex-1 cursor-pointer items-center gap-1.5 rounded-md border border-border bg-input px-2 text-xs text-text-muted">
            <input
              type="checkbox"
              checked
              onChange={() => onChange({ data_fim: regra.data_inicio || "" })}
            />
            Sem data de fim
          </label>
        ) : (
          <>
            <Input
              type="date"
              aria-label="Data de fim"
              value={regra.data_fim ?? ""}
              onChange={(e) => onChange({ data_fim: e.target.value })}
              className="h-9 bg-input text-sm"
            />
            <button
              type="button"
              onClick={() => onChange({ data_fim: null })}
              className="shrink-0 text-[11px] text-text-muted underline-offset-2 hover:underline"
              title="Marcar como sem data de fim"
            >
              sem fim
            </button>
          </>
        )}
      </div>
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={onRemove}
        aria-label="Remover regra"
        className="justify-self-end hover:text-state-lost"
      >
        <X size={14} strokeWidth={1.5} />
      </Button>
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
