"use client"

import { AlertTriangle, Info } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import { formatBRL, formatData } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type {
  ExtratoDaModeloResponse,
  LinhaDoExtrato,
  SinalizacaoDoExtrato,
} from "@/tipos/razao"
import {
  ROTULO_DA_DIVERGENCIA,
  ROTULO_DA_LINHA,
  ROTULO_DA_ORIGEM,
  ROTULO_DA_PENDENCIA,
} from "@/tipos/razao"
import { ConferenciaPorForma } from "./ConferenciaPorForma"
import { FaltaPagar, SaldoComSinal } from "./SaldoComSinal"

/**
 * O "financeiro individual": o extrato da modelo, com a origem de cada lançamento.
 *
 * ⚠️ Não mostra comissão de telefonista (ADR-0048, última consequência): é outra conta, de outra
 * pessoa, e a modelo lê esta tela junto com o gestor.
 *
 * Uma venda no bolso dela rende DUAS linhas — o débito do bruto e o crédito da comissão. Isso não
 * é redundância: são as duas linhas juntas que explicam por que o saldo deu o que deu, e é
 * exatamente a conta que a ata diz que elas não fazem de cabeça.
 */
export function ExtratoDaModelo({
  extrato,
  loading,
  error,
  onRetry,
}: {
  extrato: ExtratoDaModeloResponse | null
  loading: boolean
  error: string | null
  onRetry: () => void
}) {
  if (loading && !extrato) {
    return (
      <div aria-busy="true" className="flex flex-col gap-4">
        <Skeleton className="h-[110px] w-full rounded-lg" />
        <Skeleton className="h-[120px] w-full rounded-lg" />
        <Skeleton className="h-[260px] w-full rounded-lg" />
      </div>
    )
  }

  if (error && !extrato) {
    return (
      <div className="rounded-lg border border-danger-500/40 bg-[color:var(--danger-500)]/8 px-4 py-3">
        <p className="text-[13px] text-text-primary">{error}</p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 text-[12px] font-medium text-text-brand underline underline-offset-2"
        >
          Tentar de novo
        </button>
      </div>
    )
  }

  if (!extrato) return null

  return (
    <div className="flex flex-col gap-5">
      <section
        aria-label="Saldo do razão"
        className="flex flex-wrap items-end justify-between gap-6 rounded-lg bg-card p-4 ring-1 ring-border-subtle shadow-elev-1"
      >
        <SaldoComSinal saldo={extrato.saldo} tamanho="lg" nome={extrato.modelo_nome} />
        <div className="flex flex-wrap items-end gap-6">
          <Numero rotulo="Débitos" valor={extrato.saldo.debitos_brl} />
          <Numero rotulo="Créditos" valor={extrato.saldo.creditos_brl} />
          <FaltaPagar saldo={extrato.saldo} />
        </div>
      </section>

      <p className="flex items-start gap-1.5 text-[11.5px] leading-snug text-text-muted">
        <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <span>
          O saldo é derivado dos fatos, sempre — a temporada não congela cálculo nenhum. Um
          comprovante que chegar depois recalcula o número sem ninguém reabrir nada.
          {extrato.percentual_repasse !== null && (
            <>
              {" "}Comissão de cadastro:{" "}
              <span className="font-mono tabular-nums text-text-secondary">
                {extrato.percentual_repasse}%
              </span>{" "}
              — cada venda usa o percentual congelado nela.
            </>
          )}
        </span>
      </p>

      <ConferenciaPorForma conferencia={extrato.conferencia} loading={false} />

      {extrato.pendencias.length > 0 && (
        <BlocoSinais
          titulo="Pendências"
          tom="warn"
          descricao="Fila, não erro: é o que ninguém disse ainda. Nada aqui trava a leitura da tela nem a venda."
          itens={extrato.pendencias}
          rotulos={ROTULO_DA_PENDENCIA}
        />
      )}

      {extrato.divergencias.length > 0 && (
        <BlocoSinais
          titulo="Divergências"
          tom="warn"
          descricao="O saldo está contando de um jeito que alguém precisa olhar."
          itens={extrato.divergencias}
          rotulos={ROTULO_DA_DIVERGENCIA}
        />
      )}

      <Lancamentos linhas={extrato.linhas} />

      {extrato.pagamentos.length > 0 && (
        <section
          aria-label="Pagamentos já feitos"
          className="overflow-hidden rounded-lg bg-card ring-1 ring-border-subtle shadow-elev-1"
        >
          <header className="flex items-baseline justify-between gap-2 border-b border-border bg-muted/40 px-4 py-2">
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-text-primary">
              Pagamentos já feitos
            </h2>
            <span className="font-mono text-[11px] tabular-nums text-text-muted">
              {formatBRL(extrato.saldo.pago_brl)}
            </span>
          </header>
          <ul>
            {extrato.pagamentos.map((p) => (
              <li
                key={p.id}
                className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border px-4 py-2 last:border-b-0"
              >
                <span className="flex flex-wrap items-baseline gap-x-2 text-[13px] text-text-primary">
                  <span className="font-mono text-[11.5px] tabular-nums text-text-muted">
                    {formatData(p.data)}
                  </span>
                  <span>{p.forma_pagamento}</span>
                  {p.observacao && (
                    <span className="text-[11.5px] text-text-muted">{p.observacao}</span>
                  )}
                </span>
                <span className="font-mono text-[13px] tabular-nums text-text-primary">
                  {formatBRL(p.valor_brl)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function Numero({ rotulo, valor }: { rotulo: string; valor: number }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
        {rotulo}
      </span>
      <span className="font-mono text-base font-semibold tabular-nums leading-none text-text-primary">
        {formatBRL(valor)}
      </span>
    </div>
  )
}

function BlocoSinais({
  titulo,
  descricao,
  itens,
  rotulos,
  tom,
}: {
  titulo: string
  descricao: string
  itens: SinalizacaoDoExtrato[]
  rotulos: Record<string, string>
  tom: "warn"
}) {
  return (
    <section
      role="status"
      className={cn(
        "rounded-lg border px-4 py-3",
        tom === "warn" && "border-warn-500/40 bg-[color:var(--warn-500)]/8",
      )}
    >
      <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-warn-500">
        <AlertTriangle className="size-3.5" aria-hidden />
        {titulo}
      </p>
      <p className="mt-1 text-[12px] text-text-muted">{descricao}</p>
      <ul className="mt-2 flex flex-col gap-1">
        {itens.map((s) => (
          <li key={s.tipo} className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
            <span className="font-mono tabular-nums text-warn-500">{s.quantidade}×</span>
            <span className="text-text-primary">{rotulos[s.tipo] ?? s.tipo}</span>
            <span className="font-mono text-[11.5px] tabular-nums text-text-muted">
              {formatBRL(s.valor_brl)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Lancamentos({ linhas }: { linhas: LinhaDoExtrato[] }) {
  if (linhas.length === 0) {
    return (
      <div className="rounded-lg bg-card px-4 py-10 text-center ring-1 ring-border-subtle">
        <p className="text-[13px] text-text-primary">Nenhum lançamento neste recorte.</p>
      </div>
    )
  }

  return (
    <section
      aria-label="Lançamentos do razão"
      className="overflow-hidden rounded-lg bg-card ring-1 ring-border-subtle shadow-elev-1"
    >
      <header className="flex items-baseline justify-between gap-2 border-b border-border bg-muted/40 px-4 py-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-text-primary">
          Lançamentos
        </h2>
        <span className="text-[11px] text-text-muted">
          {linhas.length} {linhas.length === 1 ? "linha" : "linhas"}
        </span>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-border text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-muted">
              <th scope="col" className="px-4 py-2 text-left">Data</th>
              <th scope="col" className="px-4 py-2 text-left">Lançamento</th>
              <th scope="col" className="px-4 py-2 text-left">Origem</th>
              <th scope="col" className="px-4 py-2 text-right">Débito</th>
              <th scope="col" className="px-4 py-2 text-right">Crédito</th>
            </tr>
          </thead>
          <tbody>
            {linhas.map((l, i) => (
              <tr
                key={`${l.origem}-${l.origem_id ?? i}-${l.tipo}-${i}`}
                className="border-b border-border last:border-b-0"
              >
                <td className="whitespace-nowrap px-4 py-2 font-mono text-[11.5px] tabular-nums text-text-muted">
                  {formatData(l.data)}
                </td>
                <td className="px-4 py-2 text-text-primary">
                  {ROTULO_DA_LINHA[l.tipo] ?? l.tipo}
                  {l.descricao && (
                    <span className="ml-2 text-[11.5px] text-text-muted">{l.descricao}</span>
                  )}
                </td>
                <td className="px-4 py-2 text-[11.5px] text-text-muted">
                  {ROTULO_DA_ORIGEM[l.origem] ?? l.origem}
                </td>
                <td className="px-4 py-2 text-right font-mono tabular-nums text-warn-500">
                  {l.debito_brl > 0 ? formatBRL(l.debito_brl) : "—"}
                </td>
                <td className="px-4 py-2 text-right font-mono tabular-nums text-success-500">
                  {l.credito_brl > 0 ? formatBRL(l.credito_brl) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
