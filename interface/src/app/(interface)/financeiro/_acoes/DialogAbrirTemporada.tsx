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
import { hojeISO, type TemporadaResponse } from "./tipos"

const CAMPO_SELECT =
  "mt-1 h-9 w-full rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"

/**
 * Abrir a temporada: a viagem da modelo para uma cidade, que é a unidade de pagamento do negócio
 * ("fecha pra mim a temporada da fulana, do dia tal ao dia tal").
 *
 * Deliberadamente **sem nenhum campo de dinheiro**: cidade e datas são o recorte, e o saldo é
 * derivado a cada leitura (ADR-0045 §7). Um campo de valor aqui criaria um segundo número
 * concorrente para a mesma temporada.
 *
 * O backend recusa (409) sobreposição com outra temporada viva da mesma modelo — duas temporadas
 * cruzadas fariam a mesma venda entrar nas duas, e ela seria paga duas vezes.
 */
export function DialogAbrirTemporada({
  open,
  onOpenChange,
  onAberta,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onAberta: (temporada: TemporadaResponse) => void
}) {
  const { modelos } = useModelosOpcoes()
  const [modeloId, setModeloId] = useState("")
  const [cidade, setCidade] = useState("")
  const [inicio, setInicio] = useState(hojeISO)
  const [fim, setFim] = useState(hojeISO)
  const [observacao, setObservacao] = useState("")
  const [salvando, setSalvando] = useState(false)

  useEffect(() => {
    if (!open) return
    // Reset ao abrir: mesmo padrão do FormRepasse.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setModeloId("")
    setCidade("")
    setInicio(hojeISO())
    setFim(hojeISO())
    setObservacao("")
  }, [open])

  const periodoInvertido = fim < inicio

  async function abrir() {
    if (!modeloId) {
      toast.error("Escolha a modelo.")
      return
    }
    if (!cidade.trim()) {
      toast.error("Informe a cidade da temporada.")
      return
    }
    if (periodoInvertido) {
      toast.error("O fim não pode ser antes do início.")
      return
    }
    setSalvando(true)
    try {
      const criada = await api<TemporadaResponse>("/v1/financeiro/temporadas", {
        method: "POST",
        body: JSON.stringify({
          modelo_id: modeloId,
          cidade: cidade.trim(),
          data_inicio: inicio,
          data_fim: fim,
          observacao: observacao.trim() || null,
        }),
      })
      toast.success(`Temporada de ${criada.modelo_nome} em ${criada.cidade} aberta.`)
      onAberta(criada)
      onOpenChange(false)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao abrir a temporada")
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle>Abrir temporada</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-3">
          <div>
            <Label htmlFor="temporada-modelo">Modelo</Label>
            <select
              id="temporada-modelo"
              className={CAMPO_SELECT}
              value={modeloId}
              onChange={(e) => setModeloId(e.target.value)}
            >
              <option value="">— selecione —</option>
              {(modelos ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nome}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="temporada-cidade">Cidade</Label>
            <Input
              id="temporada-cidade"
              placeholder="Goiânia"
              value={cidade}
              onChange={(e) => setCidade(e.target.value)}
              className="mt-1"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="temporada-inicio">Início</Label>
              <Input
                id="temporada-inicio"
                type="date"
                value={inicio}
                onChange={(e) => setInicio(e.target.value)}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="temporada-fim">Fim</Label>
              <Input
                id="temporada-fim"
                type="date"
                value={fim}
                onChange={(e) => setFim(e.target.value)}
                className="mt-1"
              />
            </div>
          </div>
          {periodoInvertido && (
            <p className="text-[11.5px] text-warn-500">O fim não pode ser antes do início.</p>
          )}
          <div>
            <Label htmlFor="temporada-obs">Observação (opcional)</Label>
            <Textarea
              id="temporada-obs"
              rows={2}
              value={observacao}
              onChange={(e) => setObservacao(e.target.value)}
              className="mt-1"
            />
          </div>
          <p className="rounded-md bg-muted/60 px-3 py-2 text-[11.5px] leading-relaxed text-text-muted">
            A temporada é só o recorte de que período você está falando quando paga. Ela não guarda
            saldo nenhum: o número é apurado a cada leitura, e comprovante que chegar depois muda o
            resultado sem ninguém reabrir nada.
          </p>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={salvando}>
            Cancelar
          </Button>
          <Button onClick={abrir} disabled={salvando || !modeloId || !cidade.trim()}>
            {salvando ? "Abrindo…" : "Abrir"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
