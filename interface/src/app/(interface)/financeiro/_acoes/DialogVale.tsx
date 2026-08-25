"use client"

import { useEffect, useState } from "react"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useModelosOpcoes } from "@/hooks/useModelosOpcoes"
import { api, ApiError } from "@/lib/api"
import type { TemporadaLinha } from "@/tipos/razao"
import {
  hojeISO,
  lerValor,
  type LancamentoManualResponse,
  type SentidoDoLancamentoManual,
  type TipoDoLancamentoManual,
} from "./tipos"

const CAMPO_SELECT =
  "mt-1 h-9 w-full rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"

/**
 * Lançar o vale adiantado ("tem que pagar uma conta de 500 reais, eu adianto"), que debita a
 * modelo e passa a aparecer no extrato dela com a origem `painel`.
 *
 * ⚠️ **"Ficou com ela" não é vale** (ADR-0047 §5). Quando o gestor diz que a modelo ficou com o
 * dinheiro de uma venda, isso é a venda com `bolso = 'dela'` mais a ausência da transferência — o
 * razão já dá o número certo. Lançar um vale além disso contaria o mesmo dinheiro duas vezes, e é
 * por isso que o aviso está na tela, e não só no ADR.
 *
 * O **ajuste** existe ao lado do vale para a realidade que não coube em fato nenhum, e é o único
 * lançamento que pode ser crédito. Vale é sempre débito: adiantamento é dinheiro que ela já pegou.
 */
export function DialogVale({
  open,
  onOpenChange,
  temporadas,
  modeloIdInicial,
  onLancado,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Para amarrar o vale à temporada em que ele foi adiantado (opcional — não muda o saldo). */
  temporadas: TemporadaLinha[]
  modeloIdInicial?: string | null
  onLancado: (lancamento: LancamentoManualResponse) => void
}) {
  const { modelos } = useModelosOpcoes()
  const [modeloId, setModeloId] = useState("")
  const [tipo, setTipo] = useState<TipoDoLancamentoManual>("vale")
  const [sentido, setSentido] = useState<SentidoDoLancamentoManual>("debito")
  const [valor, setValor] = useState("")
  const [data, setData] = useState(hojeISO)
  const [descricao, setDescricao] = useState("")
  const [temporadaId, setTemporadaId] = useState("")
  const [salvando, setSalvando] = useState(false)

  useEffect(() => {
    if (!open) return
    // Reset ao abrir: mesmo padrão do FormRepasse; o lint lê como setState síncrono.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setModeloId(modeloIdInicial ?? "")
    setTipo("vale")
    setSentido("debito")
    setValor("")
    setData(hojeISO())
    setDescricao("")
    setTemporadaId("")
  }, [open, modeloIdInicial])

  const daModelo = temporadas.filter((t) => t.modelo_id === modeloId)
  const valorNum = lerValor(valor)

  async function lancar() {
    if (!modeloId) {
      toast.error("Escolha a modelo.")
      return
    }
    if (valorNum === null || valorNum <= 0) {
      toast.error("Valor inválido.")
      return
    }
    setSalvando(true)
    try {
      const criado = await api<LancamentoManualResponse>("/v1/financeiro/razao/lancamentos", {
        method: "POST",
        body: JSON.stringify({
          modelo_id: modeloId,
          tipo,
          // Vale é sempre débito — o backend recusa com 422 e o CHECK do banco também.
          sentido: tipo === "vale" ? "debito" : sentido,
          valor: valorNum,
          data,
          descricao: descricao.trim() || null,
          temporada_id: temporadaId || null,
        }),
      })
      toast.success(
        tipo === "vale" ? "Vale lançado — já descontado do saldo." : "Ajuste lançado no razão.",
      )
      onLancado(criado)
      onOpenChange(false)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao lançar")
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle>Lançar no razão da modelo</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-3">
          <div role="group" aria-label="Tipo do lançamento" className="flex gap-1">
            {(["vale", "ajuste"] as const).map((t) => (
              <Button
                key={t}
                type="button"
                size="sm"
                variant={tipo === t ? "primary" : "outline"}
                onClick={() => setTipo(t)}
              >
                {t === "vale" ? "Vale adiantado" : "Ajuste"}
              </Button>
            ))}
          </div>

          <p className="rounded-md bg-muted/60 px-3 py-2 text-[11.5px] leading-relaxed text-text-muted">
            {tipo === "vale" ? (
              <>
                Vale é adiantamento <strong>fora</strong> de uma venda. “Ficou com ela”, dito sobre
                uma venda, não é vale — aquilo já é a venda no bolso dela mais a ausência da
                transferência, e lançar um vale por cima contaria o mesmo dinheiro duas vezes.
              </>
            ) : (
              <>
                Ajuste é a correção declarada que não cabe em fato nenhum. Débito = ela deve à
                casa; crédito = a casa deve a ela.
              </>
            )}
          </p>

          <div>
            <Label htmlFor="vale-modelo">Modelo</Label>
            <select
              id="vale-modelo"
              className={CAMPO_SELECT}
              value={modeloId}
              onChange={(e) => {
                setModeloId(e.target.value)
                setTemporadaId("")
              }}
            >
              <option value="">— selecione —</option>
              {(modelos ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nome}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="vale-valor">Valor (R$)</Label>
              <Input
                id="vale-valor"
                inputMode="decimal"
                placeholder="500,00"
                value={valor}
                onChange={(e) => setValor(e.target.value)}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="vale-data">Data</Label>
              <Input
                id="vale-data"
                type="date"
                value={data}
                onChange={(e) => setData(e.target.value)}
                className="mt-1"
              />
            </div>
          </div>

          {tipo === "ajuste" && (
            <div>
              <Label>Direção</Label>
              <div className="mt-1 flex gap-1">
                {(["debito", "credito"] as const).map((s) => (
                  <Button
                    key={s}
                    type="button"
                    size="sm"
                    variant={sentido === s ? "primary" : "outline"}
                    onClick={() => setSentido(s)}
                  >
                    {s === "debito" ? "Débito (ela deve)" : "Crédito (a casa deve)"}
                  </Button>
                ))}
              </div>
            </div>
          )}

          {daModelo.length > 0 && (
            <div>
              <Label htmlFor="vale-temporada">Temporada (opcional)</Label>
              <select
                id="vale-temporada"
                className={CAMPO_SELECT}
                value={temporadaId}
                onChange={(e) => setTemporadaId(e.target.value)}
              >
                <option value="">— nenhuma —</option>
                {daModelo.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.cidade} · {t.data_inicio} → {t.data_fim}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[11px] text-text-muted">
                Só rotula de que viagem foi o adiantamento. O saldo é corrente e contínuo — marcar
                ou não marcar não muda número nenhum.
              </p>
            </div>
          )}

          <div>
            <Label htmlFor="vale-descricao">Descrição (opcional)</Label>
            <Textarea
              id="vale-descricao"
              rows={2}
              placeholder="conta de luz da casa"
              value={descricao}
              onChange={(e) => setDescricao(e.target.value)}
              className="mt-1"
            />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={salvando}>
            Cancelar
          </Button>
          <Button onClick={lancar} disabled={salvando || !modeloId || valorNum === null}>
            {salvando ? "Lançando…" : "Lançar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
