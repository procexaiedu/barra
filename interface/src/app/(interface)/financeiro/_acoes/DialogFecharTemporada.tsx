"use client"

import { useEffect, useState } from "react"
import { AlertTriangle, Check } from "lucide-react"
import { toast } from "sonner"
import { FaltaPagar, SaldoComSinal } from "@/components/financeiro/SaldoComSinal"
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
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { api, ApiError } from "@/lib/api"
import { formatBRL, formatData } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import {
  ROTULO_DA_DIVERGENCIA,
  ROTULO_DA_PENDENCIA,
  type SinalizacaoDoExtrato,
  type TemporadaLinha,
} from "@/tipos/razao"
import {
  FORMAS_DO_PAGAMENTO,
  hojeISO,
  lerValor,
  type FechamentoDaTemporada,
  type FormaDoPagamento,
} from "./tipos"

const CAMPO_SELECT =
  "mt-1 h-9 w-full rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"

/**
 * Fechar a temporada pelo painel: ver as pendências abertas, registrar o pagamento feito à modelo
 * e marcar a viagem como fechada.
 *
 * ⚠️ **Fechar é ação do painel, nunca frase no grupo** (ADR-0045 §8) — move dinheiro de verdade, e
 * a modelo está dentro do grupo.
 *
 * ⚠️ **Fechar não congela cálculo** (ADR-0045 §7). O que fica gravado é o PAGAMENTO (fato, com
 * data) e a marca de rotina; o saldo segue derivado. Um comprovante de R$ 600 que chegar depois
 * recalcula o número e a diferença reaparece aqui como "falta pagar" — sem reabertura, porque
 * nunca houve congelamento. É por isso que a tela fica aberta depois de confirmar, mostrando o
 * resultado recalculado em vez de sumir.
 */
export function DialogFecharTemporada({
  open,
  onOpenChange,
  temporadas,
  temporadaIdInicial,
  onFechado,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  temporadas: TemporadaLinha[]
  temporadaIdInicial?: string | null
  onFechado: () => void
}) {
  const candidatas = temporadas.filter((t) => t.estado !== "cancelada")
  const [temporadaId, setTemporadaId] = useState("")
  const [fechamento, setFechamento] = useState<FechamentoDaTemporada | null>(null)
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  const [valor, setValor] = useState("")
  const [data, setData] = useState(hojeISO)
  const [forma, setForma] = useState<FormaDoPagamento>("pix")
  const [observacao, setObservacao] = useState("")
  const [marcarFechada, setMarcarFechada] = useState(true)
  const [confirmando, setConfirmando] = useState(false)

  useEffect(() => {
    if (!open) return
    // Reset ao abrir: mesmo padrão do FormRepasse.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTemporadaId(temporadaIdInicial ?? candidatas[0]?.id ?? "")
    setFechamento(null)
    setErro(null)
    setData(hojeISO())
    setForma("pix")
    setObservacao("")
    setMarcarFechada(true)
    setValor("")
    // `candidatas` é derivado de `temporadas` a cada render; depender dele reabriria o efeito em
    // loop. A lista só interessa no instante da abertura.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, temporadaIdInicial])

  // O fechamento é buscado a cada abertura e a cada troca de temporada, e NUNCA é cacheado: ele é
  // apurado na hora (ADR-0045 §7), então um comprovante que chegou entre uma abertura e outra tem
  // que mudar o número aqui. Depois de confirmar, a resposta do POST já é o estado recalculado —
  // por isso não há refetch no caminho de escrita.
  useEffect(() => {
    if (!open || !temporadaId) return
    let cancelado = false
    // Mesmo padrão do `useTemporadas`: o setState marca o carregamento antes do await.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCarregando(true)
    api<FechamentoDaTemporada>(`/v1/financeiro/temporadas/${temporadaId}/fechamento`)
      .then((dados) => {
        if (cancelado) return
        setFechamento(dados)
        aplicarSugestao(dados)
        setErro(null)
      })
      .catch((e: unknown) => {
        if (cancelado) return
        setFechamento(null)
        setErro(e instanceof ApiError ? e.detail : e instanceof Error ? e.message : "Erro")
      })
      .finally(() => {
        if (!cancelado) setCarregando(false)
      })
    return () => {
      cancelado = true
    }
  }, [open, temporadaId])

  /** Pré-preenche o campo com o que a casa ainda deve; vazio quando não há nada a pagar. */
  function aplicarSugestao(dados: FechamentoDaTemporada) {
    setValor(
      dados.sugestao_de_pagamento_brl > 0 ? dados.sugestao_de_pagamento_brl.toFixed(2) : "",
    )
  }

  const valorNum = lerValor(valor)
  const pagando = valorNum !== null && valorNum > 0

  async function confirmar() {
    if (!temporadaId) return
    if (valor.trim() !== "" && (valorNum === null || valorNum <= 0)) {
      toast.error("Valor inválido. Deixe em branco para fechar sem pagamento.")
      return
    }
    if (!pagando && !marcarFechada) {
      toast.error("Nada a fazer: informe um valor a pagar ou marque a temporada como fechada.")
      return
    }
    setConfirmando(true)
    try {
      const depois = await api<FechamentoDaTemporada>(
        `/v1/financeiro/temporadas/${temporadaId}/fechamento`,
        {
          method: "POST",
          body: JSON.stringify({
            valor: pagando ? valorNum : null,
            data_pagamento: pagando ? data : null,
            forma_pagamento: forma,
            observacao: observacao.trim() || null,
            marcar_fechada: marcarFechada,
          }),
        },
      )
      setFechamento(depois)
      aplicarSugestao(depois)
      setObservacao("")
      toast.success(
        depois.sugestao_de_pagamento_brl > 0.004
          ? `Registrado. Ainda falta pagar ${formatBRL(depois.sugestao_de_pagamento_brl)}.`
          : "Registrado. Nada mais a pagar nesta temporada.",
      )
      onFechado()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao fechar")
    } finally {
      setConfirmando(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Fechar temporada</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div>
            <Label htmlFor="fechar-temporada">Temporada</Label>
            <select
              id="fechar-temporada"
              className={CAMPO_SELECT}
              value={temporadaId}
              onChange={(e) => setTemporadaId(e.target.value)}
            >
              <option value="">— selecione —</option>
              {candidatas.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.modelo_nome} · {t.cidade} · {formatData(t.data_inicio)} →{" "}
                  {formatData(t.data_fim)}
                  {t.estado === "fechada" ? " (fechada)" : ""}
                </option>
              ))}
            </select>
          </div>

          {carregando && !fechamento && <Skeleton className="h-40 w-full rounded-lg" />}
          {erro && (
            <p className="rounded-md border border-danger-500/40 bg-[color:var(--danger-500)]/8 px-3 py-2 text-[12.5px] text-text-primary">
              {erro}
            </p>
          )}

          {fechamento && (
            <>
              <div className="flex flex-wrap items-end justify-between gap-4 rounded-lg bg-muted/40 px-4 py-3">
                <SaldoComSinal
                  saldo={fechamento.saldo}
                  nome={fechamento.temporada.modelo_nome}
                  tamanho="lg"
                />
                <FaltaPagar saldo={fechamento.saldo} />
                <div className="flex flex-col gap-0.5">
                  <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
                    Vendido
                  </span>
                  <span className="font-mono text-base font-semibold tabular-nums leading-none text-text-primary">
                    {formatBRL(fechamento.vendido_brl)}
                  </span>
                  <span className="font-mono text-[10.5px] tabular-nums text-text-muted">
                    {fechamento.vendas} {fechamento.vendas === 1 ? "venda" : "vendas"}
                  </span>
                </div>
              </div>

              <Sinalizacoes
                titulo="Pendências abertas"
                itens={fechamento.pendencias}
                rotulos={ROTULO_DA_PENDENCIA}
                vazio="Nenhuma pendência aberta neste período."
                ajuda="Pendência é fila, não erro — você pode fechar assim mesmo. Ela só muda o número quando alguém disser o que falta."
              />

              {fechamento.divergencias.length > 0 && (
                <Sinalizacoes
                  titulo="Divergências"
                  itens={fechamento.divergencias}
                  rotulos={ROTULO_DA_DIVERGENCIA}
                  vazio=""
                  ajuda="O saldo está contando de um jeito que alguém precisa olhar."
                />
              )}

              {fechamento.vales.length > 0 && (
                <section>
                  <h3 className="text-[12px] font-semibold text-text-primary">
                    Vales e ajustes no período
                  </h3>
                  <ul className="mt-1.5 flex flex-col gap-1">
                    {fechamento.vales.map((v) => (
                      <li
                        key={v.id}
                        className="flex items-center justify-between gap-3 text-[12px] text-text-secondary"
                      >
                        <span className="truncate">
                          {formatData(v.data)} · {v.tipo === "vale" ? "Vale" : "Ajuste"}
                          {v.descricao ? ` · ${v.descricao}` : ""}
                          <span className="ml-1.5 text-text-muted">({v.origem})</span>
                        </span>
                        <span
                          className={cn(
                            "shrink-0 font-mono tabular-nums",
                            v.sentido === "debito" ? "text-warn-500" : "text-success-500",
                          )}
                        >
                          {v.sentido === "debito" ? "−" : "+"}
                          {formatBRL(v.valor_brl)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {fechamento.pagamentos.length > 0 && (
                <section>
                  <h3 className="text-[12px] font-semibold text-text-primary">
                    Pagamentos já feitos nesta temporada
                  </h3>
                  <ul className="mt-1.5 flex flex-col gap-1">
                    {fechamento.pagamentos.map((p) => (
                      <li
                        key={p.id}
                        className="flex items-center justify-between gap-3 text-[12px] text-text-secondary"
                      >
                        <span className="truncate">
                          {formatData(p.data)} · {p.forma_pagamento}
                          {p.observacao ? ` · ${p.observacao}` : ""}
                        </span>
                        <span className="shrink-0 font-mono tabular-nums text-text-primary">
                          {formatBRL(p.valor_brl)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section className="border-t border-border pt-3">
                <h3 className="text-[12px] font-semibold text-text-primary">
                  Registrar o pagamento
                </h3>
                <p className="mt-0.5 text-[11.5px] text-text-muted">
                  Deixe o valor em branco para fechar sem pagamento — é o caso normal quando ela é
                  que deve à casa.
                </p>
                <div className="mt-2 grid grid-cols-2 gap-3">
                  <div>
                    <Label htmlFor="fechar-valor">Valor pago (R$)</Label>
                    <Input
                      id="fechar-valor"
                      inputMode="decimal"
                      placeholder="0,00"
                      value={valor}
                      onChange={(e) => setValor(e.target.value)}
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor="fechar-data">Data do pagamento</Label>
                    <Input
                      id="fechar-data"
                      type="date"
                      value={data}
                      onChange={(e) => setData(e.target.value)}
                      className="mt-1"
                      disabled={!pagando}
                    />
                  </div>
                </div>
                <div className="mt-3">
                  <Label>Forma</Label>
                  <div className="mt-1 flex gap-1">
                    {FORMAS_DO_PAGAMENTO.map((f) => (
                      <Button
                        key={f}
                        type="button"
                        size="sm"
                        variant={forma === f ? "primary" : "outline"}
                        onClick={() => setForma(f)}
                        disabled={!pagando}
                      >
                        {f}
                      </Button>
                    ))}
                  </div>
                </div>
                <div className="mt-3">
                  <Label htmlFor="fechar-obs">Observação (opcional)</Label>
                  <Textarea
                    id="fechar-obs"
                    rows={2}
                    value={observacao}
                    onChange={(e) => setObservacao(e.target.value)}
                    className="mt-1"
                  />
                </div>
                <label className="mt-3 flex items-start gap-2 text-[12px] text-text-secondary">
                  <input
                    type="checkbox"
                    checked={marcarFechada}
                    onChange={(e) => setMarcarFechada(e.target.checked)}
                    className="mt-0.5"
                  />
                  <span>
                    Marcar a temporada como <strong>fechada</strong>. É marca de rotina, não trava:
                    o saldo continua sendo recalculado, e comprovante que chegar depois muda o
                    número sem ninguém reabrir nada.
                  </span>
                </label>
              </section>
            </>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={confirmando}>
            Fechar janela
          </Button>
          <Button onClick={confirmar} disabled={confirmando || !fechamento}>
            {confirmando ? "Registrando…" : pagando ? "Pagar e fechar" : "Fechar sem pagamento"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Pendência e divergência aparecem, contadas e somadas, e nunca travam o fechamento. */
function Sinalizacoes({
  titulo,
  itens,
  rotulos,
  vazio,
  ajuda,
}: {
  titulo: string
  itens: SinalizacaoDoExtrato[]
  rotulos: Record<string, string>
  vazio: string
  ajuda: string
}) {
  return (
    <section>
      <h3 className="flex items-center gap-1.5 text-[12px] font-semibold text-text-primary">
        {itens.length > 0 ? (
          <AlertTriangle className="size-3.5 text-warn-500" aria-hidden />
        ) : (
          <Check className="size-3.5 text-success-500" aria-hidden />
        )}
        {titulo}
      </h3>
      {itens.length === 0 ? (
        <p className="mt-1 text-[12px] text-text-muted">{vazio}</p>
      ) : (
        <>
          <ul className="mt-1.5 flex flex-col gap-1">
            {itens.map((s) => (
              <li
                key={s.tipo}
                className="flex items-center justify-between gap-3 text-[12px] text-text-secondary"
              >
                <span className="truncate">
                  <span className="font-mono tabular-nums text-text-primary">{s.quantidade}</span>{" "}
                  {rotulos[s.tipo] ?? s.tipo}
                </span>
                <span className="shrink-0 font-mono tabular-nums text-text-muted">
                  {formatBRL(s.valor_brl)}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[11px] text-text-muted">{ajuda}</p>
        </>
      )}
    </section>
  )
}
