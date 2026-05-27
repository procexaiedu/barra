"use client"

import { useMemo, useState } from "react"
import {
  AlertTriangle,
  ArrowUpRight,
  Banknote,
  CheckCircle2,
  CircleAlert,
  Plus,
  Receipt,
  Trash2,
  Users,
  Wallet,
} from "lucide-react"
import { api, ApiError } from "@/lib/api"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { formatBRL, formatData } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type {
  FinanceiroResumo,
  RepassePagoResponse,
  RepassesPagamentosListaResponse,
  RepassesPorModeloResponse,
  SaldoModelo,
} from "@/tipos/financeiro"
import type { useFinanceiro } from "@/hooks/useFinanceiro"
import { FormRepasse } from "./FormRepasse"
import { DialogPreencherRepasse } from "./DialogPreencherRepasse"
import { KpiCard } from "./KpiCard"
import { ChartComposicaoBruto } from "./charts/ChartComposicaoBruto"
import { ChartDistribuicaoSaldo } from "./charts/ChartDistribuicaoSaldo"
import { ChartRitmoPagamento } from "./charts/ChartRitmoPagamento"

export function RepassesPorModelo({
  repasses,
  pagamentos,
  loading,
  fin,
}: {
  repasses: RepassesPorModeloResponse | null
  pagamentos: RepassesPagamentosListaResponse | null
  loading: boolean
  fin: ReturnType<typeof useFinanceiro>
}) {
  const [formAberto, setFormAberto] = useState<{ modelo_id?: string } | null>(
    null,
  )
  const [dialogRetroAberto, setDialogRetroAberto] = useState<{
    modelo_id: string
    modelo_nome: string
  } | null>(null)

  const carregando = loading && !repasses
  const r = fin.resumo?.resumo ?? null
  const rAnt = fin.resumo?.resumo_anterior ?? null
  const janelaCorrente = fin.repasses?.filtro_aplicado ?? fin.resumo?.filtro_aplicado ?? null

  return (
    <div className="space-y-5">
      <ResumoRepasses resumo={r} anterior={rAnt} loading={carregando} />

      {fin.resumo?.janela_comparacao && (
        <div className="text-[11px] tabular-nums text-text-muted -mt-3">
          deltas vs {fin.resumo.janela_comparacao.de} → {fin.resumo.janela_comparacao.ate}
        </div>
      )}

      {carregando ? (
        <>
          <Skeleton className="h-[160px] rounded-md" />
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Skeleton className="h-[280px] rounded-md" />
            <Skeleton className="h-[280px] rounded-md" />
          </div>
        </>
      ) : (
        r && r.valor_bruto_brl > 0 && (
          <>
            <ChartComposicaoBruto resumo={r} />
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <ChartDistribuicaoSaldo
                items={repasses?.items ?? []}
                onSelecionarModelo={(id) => setFormAberto({ modelo_id: id })}
              />
              <ChartRitmoPagamento
                pagamentos={pagamentos?.items ?? []}
                janelaDe={janelaCorrente?.de ?? null}
                janelaAte={janelaCorrente?.ate ?? null}
              />
            </div>
          </>
        )
      )}

      <section className="space-y-3">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex items-baseline gap-3">
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-muted">
              Saldo por modelo
            </h2>
            {repasses && (
              <span className="text-xs text-text-disabled tabular-nums">
                {repasses.items.length}{" "}
                {repasses.items.length === 1 ? "modelo" : "modelos"} no período
              </span>
            )}
          </div>
          <Button
            size="sm"
            onClick={() => setFormAberto({})}
            disabled={carregando}
          >
            <Plus className="size-4" />
            Registrar pagamento
          </Button>
        </header>

        {carregando ? (
          <Skeleton className="h-44 rounded-md" />
        ) : repasses && repasses.items.length > 0 ? (
          <TabelaSaldo
            items={repasses.items}
            onPagar={(id) => setFormAberto({ modelo_id: id })}
            onPreencher={(id, nome) =>
              setDialogRetroAberto({ modelo_id: id, modelo_nome: nome })
            }
          />
        ) : (
          <EstadoVazio
            icone={<Users className="size-5" />}
            titulo="Sem fechamentos no período"
            descricao="Quando uma modelo fechar atendimentos, o saldo por modelo aparece aqui."
          />
        )}
      </section>

      <section className="space-y-3">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex items-baseline gap-3">
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-muted">
              Pagamentos no período
            </h2>
            {pagamentos && pagamentos.items.length > 0 && (
              <span className="text-xs text-text-disabled tabular-nums">
                {pagamentos.items.length}{" "}
                {pagamentos.items.length === 1 ? "lançamento" : "lançamentos"}
              </span>
            )}
          </div>
        </header>

        {carregando ? (
          <Skeleton className="h-32 rounded-md" />
        ) : pagamentos && pagamentos.items.length > 0 ? (
          <TabelaPagamentos pagamentos={pagamentos} onMudou={fin.refetch} />
        ) : (
          <EstadoVazio
            icone={<Receipt className="size-5" />}
            titulo="Nenhum pagamento neste período"
            descricao="Registre o primeiro pagamento para começar a controlar o saldo. Os lançamentos ficam visíveis aqui e podem ser exportados em CSV."
            primario={
              <Button size="sm" onClick={() => setFormAberto({})}>
                <Plus className="size-4" />
                Registrar pagamento
              </Button>
            }
          />
        )}
      </section>

      <FormRepasse
        open={!!formAberto}
        onOpenChange={(open) => setFormAberto(open ? formAberto : null)}
        modeloIdInicial={formAberto?.modelo_id ?? null}
        onSalvo={() => {
          setFormAberto(null)
          fin.refetch()
        }}
      />
      {dialogRetroAberto && (
        <DialogPreencherRepasse
          open={!!dialogRetroAberto}
          onOpenChange={(open) => setDialogRetroAberto(open ? dialogRetroAberto : null)}
          modeloId={dialogRetroAberto.modelo_id}
          modeloNome={dialogRetroAberto.modelo_nome}
          onSalvo={() => {
            setDialogRetroAberto(null)
            fin.refetch()
          }}
        />
      )}
    </div>
  )
}

// ---------- Resumo executivo ----------

function ResumoRepasses({
  resumo,
  anterior,
  loading,
}: {
  resumo: FinanceiroResumo | null
  anterior: FinanceiroResumo | null
  loading: boolean
}) {
  if (loading || !resumo) {
    return (
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[112px] rounded-md" />
        ))}
      </div>
    )
  }

  const saldoNegativo = resumo.valor_saldo_repasse_brl < 0
  const saldoZero = Math.abs(resumo.valor_saldo_repasse_brl) < 0.005
  const nadaPago = resumo.valor_repasse_pago_brl < 0.005
  // Quando ninguém foi pago, "Calculado" = "Saldo": dois cards mostrando o
  // mesmo número viram ruído. Suavizamos o tom e qualificamos o hint.
  const calculadoIgualSaldo =
    !saldoZero &&
    !saldoNegativo &&
    nadaPago &&
    resumo.valor_repasse_calculado_brl > 0
  const pctPago =
    resumo.valor_repasse_calculado_brl > 0
      ? (resumo.valor_repasse_pago_brl / resumo.valor_repasse_calculado_brl) * 100
      : 0
  const pctRepasseDoBruto =
    resumo.valor_bruto_brl > 0
      ? `${((resumo.valor_repasse_calculado_brl / resumo.valor_bruto_brl) * 100).toFixed(1)}% do bruto`
      : undefined
  const hintCalculado = calculadoIgualSaldo
    ? "= saldo a pagar (nada quitado ainda)"
    : (pctRepasseDoBruto ?? "devido pelos fechamentos")

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <KpiCard
        rotulo="Saldo a pagar"
        valor={resumo.valor_saldo_repasse_brl}
        anterior={anterior?.valor_saldo_repasse_brl ?? null}
        tom={saldoNegativo ? "danger" : saldoZero ? "success" : "warning"}
        destaque
        sentido="maior_pior"
        icone={<Wallet className="size-4" />}
        okQuando={saldoZero}
        okTexto="tudo em dia"
        hint={
          saldoNegativo
            ? "pago a mais (estorno?)"
            : !saldoZero
              ? "aguarda registro de pagamento"
              : undefined
        }
      />
      <KpiCard
        rotulo="Calculado"
        valor={resumo.valor_repasse_calculado_brl}
        anterior={anterior?.valor_repasse_calculado_brl ?? null}
        sentido="neutro"
        tom={calculadoIgualSaldo ? "muted" : "default"}
        icone={<Banknote className="size-4" />}
        hint={hintCalculado}
      />
      <KpiCard
        rotulo="Pago"
        valor={resumo.valor_repasse_pago_brl}
        anterior={anterior?.valor_repasse_pago_brl ?? null}
        tom={resumo.valor_repasse_pago_brl > 0 ? "success" : "muted"}
        sentido="maior_melhor"
        icone={<CheckCircle2 className="size-4" />}
        progresso={pctPago}
        trailing={
          resumo.valor_repasse_calculado_brl > 0
            ? `${pctPago.toFixed(0)}% do calculado`
            : undefined
        }
        hint={
          resumo.valor_repasse_pago_brl === 0
            ? "nenhum pagamento ainda"
            : undefined
        }
      />
      <KpiCard
        rotulo="Fechamentos"
        valor={resumo.fechamentos_total}
        anterior={anterior?.fechamentos_total ?? null}
        formato="int"
        sentido="maior_melhor"
        icone={<Users className="size-4" />}
        hint={
          resumo.fechamentos_sem_snapshot > 0 ? (
            <span className="inline-flex items-center gap-1 text-warn-500">
              <AlertTriangle className="size-3" />
              {resumo.fechamentos_sem_snapshot} sem % definido
            </span>
          ) : undefined
        }
      />
    </div>
  )
}

// ---------- Tabela de saldo ----------

function TabelaSaldo({
  items,
  onPagar,
  onPreencher,
}: {
  items: SaldoModelo[]
  onPagar: (modeloId: string) => void
  onPreencher: (modeloId: string, modeloNome: string) => void
}) {
  const total = useMemo(
    () =>
      items.reduce(
        (acc, s) => {
          acc.bruto += s.valor_bruto
          acc.calculado += s.valor_repasse_calculado
          acc.pago += s.valor_repasse_pago
          acc.saldo += s.saldo
          acc.fech += s.fechamentos_total
          return acc
        },
        { bruto: 0, calculado: 0, pago: 0, saldo: 0, fech: 0 },
      ),
    [items],
  )

  return (
    <div className="overflow-hidden rounded-md border border-border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/80 bg-muted/30 text-[10.5px] uppercase tracking-[0.14em] text-text-muted">
              <th className="px-4 py-2.5 text-left font-medium">Modelo</th>
              <th className="px-3 py-2.5 text-right font-medium">Fech.</th>
              <th className="px-3 py-2.5 text-right font-medium">Bruto</th>
              <th className="px-3 py-2.5 text-right font-medium">Calculado</th>
              <th className="px-3 py-2.5 text-right font-medium">Pago</th>
              <th className="border-l border-border/70 bg-gold-500/[0.04] px-3 py-2.5 text-right font-semibold text-gold-700">
                Saldo
              </th>
              <th className="px-3 py-2.5 text-left font-medium">Pendência</th>
              <th className="px-3 py-2.5"></th>
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <LinhaModelo
                key={s.modelo_id}
                saldo={s}
                onPagar={() => onPagar(s.modelo_id)}
                onPreencher={() => onPreencher(s.modelo_id, s.modelo_nome)}
              />
            ))}
          </tbody>
          {items.length > 1 && (
            <tfoot>
              <tr className="border-t-2 border-border/80 bg-muted/20 text-[12.5px]">
                <td className="px-4 py-2.5 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-text-muted">
                  Total
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-text-secondary">
                  {total.fech}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-text-secondary">
                  {formatBRL(total.bruto)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-text-secondary">
                  {formatBRL(total.calculado)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-text-secondary">
                  {formatBRL(total.pago)}
                </td>
                <td className="border-l border-border/70 bg-gold-500/[0.04] px-3 py-2.5 text-right font-semibold tabular-nums text-gold-700">
                  {formatBRL(total.saldo)}
                </td>
                <td colSpan={2} className="px-3 py-2.5"></td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  )
}

function LinhaModelo({
  saldo,
  onPagar,
  onPreencher,
}: {
  saldo: SaldoModelo
  onPagar: () => void
  onPreencher: () => void
}) {
  const saldoNegativo = saldo.saldo < 0
  const saldoZerado = Math.abs(saldo.saldo) < 0.005
  const temPendencia = saldo.fechamentos_sem_snapshot > 0
  const corSaldo = saldoNegativo
    ? "text-danger-500"
    : saldoZerado
      ? "text-text-disabled"
      : "text-gold-700"

  return (
    <tr
      className={cn(
        "group/linha border-b border-border/40 transition-colors last:border-b-0",
        "hover:bg-muted/25 focus-within:bg-muted/25",
      )}
    >
      <td className="px-4 py-2.5">
        <span className="font-medium text-text-primary">{saldo.modelo_nome}</span>
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums text-text-secondary">
        {saldo.fechamentos_total}
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums text-text-secondary">
        {formatBRL(saldo.valor_bruto)}
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums text-text-secondary">
        {formatBRL(saldo.valor_repasse_calculado)}
      </td>
      <td
        className={cn(
          "px-3 py-2.5 text-right tabular-nums",
          saldo.valor_repasse_pago === 0
            ? "text-text-disabled"
            : "text-text-secondary",
        )}
      >
        {formatBRL(saldo.valor_repasse_pago)}
      </td>
      <td
        className={cn(
          "border-l border-border/70 bg-gold-500/[0.04] px-3 py-2.5 text-right font-semibold tabular-nums",
          corSaldo,
        )}
        title={
          saldoNegativo
            ? "Pago a mais (estorno?) — compense no próximo lançamento"
            : undefined
        }
      >
        {formatBRL(saldo.saldo)}
      </td>
      <td className="px-3 py-2.5">
        {temPendencia ? (
          <button
            type="button"
            onClick={onPreencher}
            className="inline-flex items-center gap-1.5 rounded-full bg-warn-500/12 px-2 py-0.5 text-[11px] font-medium text-warn-500 transition-colors hover:bg-warn-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-warn-500/40 cursor-pointer"
          >
            <span
              aria-hidden
              className="size-1.5 rounded-full bg-warn-500"
            />
            {saldo.fechamentos_sem_snapshot} sem snapshot ·{" "}
            {formatBRL(saldo.valor_sem_snapshot)}
          </button>
        ) : (
          <span className="text-xs text-text-disabled">—</span>
        )}
      </td>
      <td className="px-3 py-2.5 text-right">
        <Button
          size="xs"
          variant={saldoZerado || saldoNegativo ? "outline" : "primary"}
          onClick={onPagar}
          aria-label={`Registrar pagamento para ${saldo.modelo_nome}`}
        >
          {saldoZerado ? "Lançar" : saldoNegativo ? "Ajustar" : "Pagar"}
          <ArrowUpRight className="size-3" />
        </Button>
      </td>
    </tr>
  )
}

// ---------- Tabela de pagamentos ----------

function TabelaPagamentos({
  pagamentos,
  onMudou,
}: {
  pagamentos: RepassesPagamentosListaResponse
  onMudou: () => void
}) {
  return (
    <div className="overflow-hidden rounded-md border border-border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/80 bg-muted/30 text-[10.5px] uppercase tracking-[0.14em] text-text-muted">
              <th className="px-4 py-2.5 text-left font-medium">Data</th>
              <th className="px-3 py-2.5 text-left font-medium">Modelo</th>
              <th className="px-3 py-2.5 text-right font-medium">Valor</th>
              <th className="px-3 py-2.5 text-left font-medium">Forma</th>
              <th className="px-3 py-2.5 text-left font-medium">Observação</th>
              <th className="px-3 py-2.5"></th>
            </tr>
          </thead>
          <tbody>
            {pagamentos.items.map((p) => (
              <LinhaPagamento key={p.id} pagamento={p} onMudou={onMudou} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function LinhaPagamento({
  pagamento,
  onMudou,
}: {
  pagamento: RepassePagoResponse
  onMudou: () => void
}) {
  const [excluindo, setExcluindo] = useState(false)

  async function excluir() {
    if (!confirm("Excluir este pagamento? Saldo será recalculado.")) return
    setExcluindo(true)
    try {
      await api(`/v1/financeiro/repasses/pagamentos/${pagamento.id}`, {
        method: "DELETE",
      })
      toast.success("Pagamento excluído.")
      onMudou()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao excluir")
    } finally {
      setExcluindo(false)
    }
  }

  return (
    <tr className="border-b border-border/40 transition-colors last:border-b-0 hover:bg-muted/25">
      <td className="px-4 py-2.5 text-text-secondary tabular-nums">
        {formatData(pagamento.data_pagamento)}
      </td>
      <td className="px-3 py-2.5 text-text-primary">
        {pagamento.modelo_nome ?? "—"}
      </td>
      <td className="px-3 py-2.5 text-right font-medium tabular-nums text-text-primary">
        {formatBRL(pagamento.valor)}
      </td>
      <td className="px-3 py-2.5">
        <span className="inline-flex h-5 items-center rounded-full bg-muted/60 px-2 text-[11px] font-medium capitalize text-text-secondary">
          {pagamento.forma_pagamento}
        </span>
      </td>
      <td className="px-3 py-2.5 text-text-muted">
        {pagamento.observacao || "—"}
      </td>
      <td className="px-3 py-2.5 text-right">
        <Button
          size="icon-xs"
          variant="ghost"
          onClick={excluir}
          disabled={excluindo}
          aria-label="Excluir pagamento"
        >
          <Trash2 className="size-3.5" />
        </Button>
      </td>
    </tr>
  )
}

// ---------- Empty state ----------

function EstadoVazio({
  icone,
  titulo,
  descricao,
  primario,
  secundario,
}: {
  icone: React.ReactNode
  titulo: string
  descricao: string
  primario?: React.ReactNode
  secundario?: React.ReactNode
}) {
  return (
    <div className="rounded-md border border-dashed border-border bg-card/60 px-6 py-8">
      <div className="mx-auto flex max-w-md flex-col items-center gap-3 text-center">
        <span className="grid size-9 place-items-center rounded-full bg-muted/60 text-text-muted">
          {icone ?? <CircleAlert className="size-5" />}
        </span>
        <div className="space-y-1">
          <h3 className="text-sm font-medium text-text-primary">{titulo}</h3>
          <p className="text-[12.5px] leading-relaxed text-text-muted">
            {descricao}
          </p>
        </div>
        {(primario || secundario) && (
          <div className="mt-1 flex flex-wrap items-center justify-center gap-3">
            {primario}
            {secundario}
          </div>
        )}
      </div>
    </div>
  )
}
