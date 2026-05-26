"use client"

import { useCallback, useEffect, useState } from "react"
import { Plus, Power } from "lucide-react"
import { api, ApiError } from "@/lib/api"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { formatBRL, formatData } from "@/lib/formatters"
import {
  CATEGORIAS_DESPESA,
  ROTULO_CATEGORIA,
  type CategoriaDespesa,
  type DespesaRecorrente,
} from "@/tipos/financeiro"

export function ListaRecorrentes({ onMudou }: { onMudou: () => void }) {
  const [items, setItems] = useState<DespesaRecorrente[] | null>(null)
  const [incluirInativas, setIncluirInativas] = useState(false)
  const [formAberto, setFormAberto] = useState(false)

  const carregar = useCallback(async () => {
    try {
      const data = await api<DespesaRecorrente[]>(
        `/v1/financeiro/despesas-recorrentes?incluir_inativas=${incluirInativas}`
      )
      setItems(data)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao carregar")
    }
  }, [incluirInativas])

  useEffect(() => {
    // Carregamento ao montar / quando filtros mudam — `carregar` é async e
    // só faz setItens após o await; o lint não consegue inferir.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    carregar()
  }, [carregar])

  async function desativar(rec: DespesaRecorrente) {
    if (!confirm(`Desativar "${rec.descricao}" a partir do próximo mês?`)) return
    const hoje = new Date()
    const proxMes = new Date(hoje.getFullYear(), hoje.getMonth() + 1, 1)
    const inativoEm = proxMes.toISOString().slice(0, 10)
    try {
      await api(
        `/v1/financeiro/despesas-recorrentes/${rec.id}/desativar?inativo_em=${inativoEm}`,
        { method: "POST" }
      )
      toast.success("Template desativado.")
      carregar()
      onMudou()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao desativar")
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm text-text-muted">
          <input
            type="checkbox"
            checked={incluirInativas}
            onChange={(e) => setIncluirInativas(e.target.checked)}
          />
          Incluir desativadas
        </label>
        <Button size="sm" onClick={() => setFormAberto(true)}>
          <Plus className="size-4" />
          Novo template
        </Button>
      </div>

      {!items ? (
        <Skeleton className="h-40" />
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-text-muted">
          Nenhum template cadastrado.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/30 text-xs uppercase text-text-muted">
                <th className="px-3 py-2 text-left">Descrição</th>
                <th className="px-3 py-2 text-left">Categoria</th>
                <th className="px-3 py-2 text-right">Valor</th>
                <th className="px-3 py-2 text-left">Dia</th>
                <th className="px-3 py-2 text-left">Desde</th>
                <th className="px-3 py-2 text-left">Inativo em</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className="border-b border-border/60 hover:bg-muted/20">
                  <td className="px-3 py-2">{r.descricao}</td>
                  <td className="px-3 py-2">{ROTULO_CATEGORIA[r.categoria]}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatBRL(r.valor)}</td>
                  <td className="px-3 py-2">{r.dia_do_mes}</td>
                  <td className="px-3 py-2 text-text-muted">{formatData(r.ativo_desde)}</td>
                  <td className="px-3 py-2 text-text-muted">
                    {r.inativo_em ? formatData(r.inativo_em) : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {!r.inativo_em && (
                      <Button
                        size="xs"
                        variant="ghost"
                        onClick={() => desativar(r)}
                        aria-label="Desativar"
                      >
                        <Power className="size-3.5" />
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <FormRecorrente
        open={formAberto}
        onOpenChange={setFormAberto}
        onSalvo={() => {
          setFormAberto(false)
          carregar()
          onMudou()
        }}
      />
    </div>
  )
}

function FormRecorrente({
  open,
  onOpenChange,
  onSalvo,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSalvo: () => void
}) {
  const [categoria, setCategoria] = useState<CategoriaDespesa>("software")
  const [valor, setValor] = useState("")
  const [descricao, setDescricao] = useState("")
  const [diaDoMes, setDiaDoMes] = useState(1)
  const [ativoDesde, setAtivoDesde] = useState<string>(() => {
    const d = new Date()
    return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10)
  })
  const [salvando, setSalvando] = useState(false)

  async function salvar() {
    const valorNum = parseFloat(valor.replace(",", "."))
    if (!Number.isFinite(valorNum) || valorNum <= 0) {
      toast.error("Valor inválido.")
      return
    }
    if (!descricao.trim()) {
      toast.error("Descrição obrigatória.")
      return
    }
    setSalvando(true)
    try {
      await api("/v1/financeiro/despesas-recorrentes", {
        method: "POST",
        body: JSON.stringify({
          categoria,
          valor: valorNum,
          descricao,
          dia_do_mes: diaDoMes,
          ativo_desde: ativoDesde,
        }),
      })
      toast.success("Template criado.")
      onSalvo()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao salvar")
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full max-w-md rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        <DialogTitle className="text-lg font-semibold">Novo template recorrente</DialogTitle>
        <div className="mt-4 space-y-3">
          <div>
            <Label>Descrição</Label>
            <Input
              value={descricao}
              onChange={(e) => setDescricao(e.target.value)}
              placeholder="ex.: Vercel"
              className="mt-1"
            />
          </div>
          <div>
            <Label>Categoria</Label>
            <select
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              value={categoria}
              onChange={(e) => setCategoria(e.target.value as CategoriaDespesa)}
            >
              {CATEGORIAS_DESPESA.map((c) => (
                <option key={c} value={c}>
                  {ROTULO_CATEGORIA[c]}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Valor (R$)</Label>
              <Input
                inputMode="decimal"
                placeholder="0,00"
                value={valor}
                onChange={(e) => setValor(e.target.value)}
                className="mt-1"
              />
            </div>
            <div>
              <Label>Dia do mês</Label>
              <Input
                type="number"
                min={1}
                max={28}
                value={diaDoMes}
                onChange={(e) => setDiaDoMes(parseInt(e.target.value || "1", 10))}
                className="mt-1"
              />
            </div>
          </div>
          <div>
            <Label>Ativo desde (1º do mês)</Label>
            <Input
              type="date"
              value={ativoDesde}
              onChange={(e) => setAtivoDesde(e.target.value)}
              className="mt-1"
            />
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={salvando}>
            Cancelar
          </Button>
          <Button onClick={salvar} disabled={salvando || !valor || !descricao}>
            {salvando ? "Salvando…" : "Salvar"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
