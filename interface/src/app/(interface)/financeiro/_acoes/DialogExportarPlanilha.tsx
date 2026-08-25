"use client"

import { useEffect, useState } from "react"
import { Download } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { formatData } from "@/lib/formatters"
import type { EstadoDaTemporada, TemporadaLinha } from "@/tipos/razao"
import { baixarPlanilha } from "./baixarPlanilha"

const CAMPO_SELECT =
  "mt-1 h-9 w-full rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"

const TUDO = "__todas__"

/**
 * Exportar a temporada em planilha — a planilha-espelho prometida ao gestor: *"é como se fosse um
 * extrato bancário — no final do mês eu vou olhar o sistema e vou olhar pra planilha e tem que
 * estar se falando igual"*.
 *
 * Os números NÃO são remontados aqui. O arquivo vem pronto do backend, das mesmas funções que
 * montam esta tela (`/temporadas` e `/modelos/{id}/extrato`), e é isso que faz "bate com a tela"
 * ser verdade por construção: um segundo cálculo no frontend seria a segunda fonte de verdade que
 * este ticket existe para evitar.
 *
 * ⚠️ A planilha é uma FOTO do saldo no instante do download (ADR-0045 §7), não um fechamento: um
 * comprovante que chegar depois muda o próximo arquivo. Por isso ela carrega "Gerado em", e por
 * isso este diálogo não fecha temporada nenhuma — quem fecha é o `DialogFecharTemporada`.
 */
export function DialogExportarPlanilha({
  open,
  onOpenChange,
  temporadas,
  estado,
  periodo,
  de,
  ate,
  modeloIds,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** As temporadas que a tela está mostrando — as mesmas que o arquivo vai conter. */
  temporadas: TemporadaLinha[]
  /** O filtro de estado da tela; `null` = todas. */
  estado: EstadoDaTemporada | null
  /** O período do header, usado só quando "limitar ao período" está marcado. */
  periodo: string
  de: string | null
  ate: string | null
  modeloIds: string[]
}) {
  const [alvo, setAlvo] = useState<string>(TUDO)
  const [limitarAoPeriodo, setLimitarAoPeriodo] = useState(false)
  const [detalhado, setDetalhado] = useState(true)
  const [baixando, setBaixando] = useState(false)

  useEffect(() => {
    if (!open) return
    // Reset ao abrir: mesmo padrão dos outros diálogos de `_acoes`.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAlvo(TUDO)
    setLimitarAoPeriodo(false)
    setDetalhado(true)
  }, [open])

  function montarPath(): string {
    if (alvo !== TUDO) return `/v1/financeiro/temporadas/${alvo}/export`

    const params = new URLSearchParams()
    if (estado) params.set("estado", estado)
    for (const id of modeloIds) params.append("modelo_id", id)
    if (limitarAoPeriodo) {
      params.set("periodo", periodo)
      if (periodo === "custom" && de && ate) {
        params.set("de", de)
        params.set("ate", ate)
      }
    }
    if (detalhado) params.set("detalhado", "true")
    const qs = params.toString()
    return `/v1/financeiro/temporadas/export${qs ? `?${qs}` : ""}`
  }

  async function baixar() {
    setBaixando(true)
    try {
      await baixarPlanilha(montarPath(), "temporadas.csv")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Falha ao exportar a planilha")
    } finally {
      setBaixando(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle>Exportar planilha</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div>
            <Label htmlFor="exportar-alvo">O que exportar</Label>
            <select
              id="exportar-alvo"
              className={CAMPO_SELECT}
              value={alvo}
              onChange={(e) => setAlvo(e.target.value)}
            >
              <option value={TUDO}>Todas as temporadas desta lista</option>
              {temporadas.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.modelo_nome} · {t.cidade} · {formatData(t.data_inicio)} →{" "}
                  {formatData(t.data_fim)}
                </option>
              ))}
            </select>
          </div>

          {alvo === TUDO ? (
            <div className="flex flex-col gap-2">
              <label className="flex items-start gap-2 text-[12px] text-text-secondary">
                <input
                  type="checkbox"
                  checked={detalhado}
                  onChange={(e) => setDetalhado(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  Incluir o <strong>extrato completo</strong> de cada temporada abaixo da lista —
                  lançamento a lançamento, com a origem de cada um.
                </span>
              </label>
              <label className="flex items-start gap-2 text-[12px] text-text-secondary">
                <input
                  type="checkbox"
                  checked={limitarAoPeriodo}
                  onChange={(e) => setLimitarAoPeriodo(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  Limitar ao <strong>período do filtro</strong>. Entram as temporadas que encostam
                  na janela; sem isto, entram todas as da lista.
                </span>
              </label>
            </div>
          ) : (
            <p className="text-[12px] text-text-muted">
              Sai o extrato daquela temporada: lançamentos com a origem, conferência por forma,
              pagamentos já feitos e o saldo com sinal.
            </p>
          )}

          <p className="text-[11.5px] text-text-muted">
            CSV com separador <code>;</code> e acentuação UTF-8 — abre no Excel e no Google Sheets
            sem escolher nada na importação. Os números são os desta tela: a planilha é a foto do
            saldo no instante do download, e comprovante que chegar depois muda o próximo arquivo.
          </p>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={baixando}>
            Cancelar
          </Button>
          <Button onClick={baixar} disabled={baixando}>
            <Download size={15} strokeWidth={1.5} />
            {baixando ? "Gerando…" : "Baixar planilha"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
