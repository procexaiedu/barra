"use client"

import Link from "next/link"
import { ReceiptText, CheckCircle2, XCircle, Circle } from "lucide-react"
import { Card } from "@/components/ui/card"
import { formatBRL, formatData, formatDataHora, formatRotulo } from "@/lib/formatters"
import type { AtendimentoDetalheResponse, ServicoFechado } from "@/tipos/atendimentos"
import { estadoLabel, formatEnum, motivoExibido, SINAIS_CANONICOS, tipoLabel, urgenciaLabel } from "@/components/atendimentos/utils"

function asNumber(valor: number | string | null) {
  if (valor === null) return null
  const n = typeof valor === "number" ? valor : Number(valor)
  return Number.isFinite(n) ? n : null
}

export function ResumoAtendimento({
  detalhe,
}: {
  detalhe: AtendimentoDetalheResponse
}) {
  const atendimento = detalhe.atendimento
  const valorAcordado = asNumber(atendimento.valor_acordado)
  const sq = atendimento.sinais_qualificacao as Record<string, unknown> | null
  const total = SINAIS_CANONICOS.length
  const progresso = SINAIS_CANONICOS.filter(({ chave }) => { const v = sq?.[chave]; return v === true || v === false }).length

  const itensPausada: [string, string | null][] = atendimento.ia_pausada
    ? [["Por que pausou", motivoExibido(atendimento.motivo_escalada, atendimento.ia_pausada_motivo) ?? "Não informado ainda"]]
    : []

  return (
    <Card className="rounded-lg p-4">
      <div className="mb-4 flex items-center gap-2">
        <ReceiptText size={16} strokeWidth={1.5} className="text-text-muted" />
        <h2 className="text-sm font-semibold text-text-primary">Resumo do atendimento</h2>
      </div>
      {atendimento.ia_pausada && (
        <div className="mb-4 rounded-md bg-state-handoff/5 p-2.5 ring-1 ring-state-handoff/20">
          <ResumoGrupo
            titulo="IA"
            itens={[
              ["Responsável", formatRotulo(atendimento.responsavel_atual) ?? atendimento.responsavel_atual],
              ...itensPausada,
              ["Próxima ação", atendimento.proxima_acao_esperada ?? "Não informado ainda"],
              ["Resumo", atendimento.resumo_operacional ?? "Não informado ainda"],
            ]}
          />
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        <ResumoGrupo
          titulo="Comercial"
          itens={[
            ["Estado", estadoLabel[atendimento.estado]],
            ["Tipo", atendimento.tipo_atendimento ? tipoLabel[atendimento.tipo_atendimento] : null],
            ["Quando", atendimento.urgencia ? urgenciaLabel[atendimento.urgencia] : null],
            ["Valor acordado", valorAcordado !== null ? formatBRL(valorAcordado) : null],
            ["Forma de pagamento", atendimento.forma_pagamento ? (formatRotulo(atendimento.forma_pagamento) ?? atendimento.forma_pagamento) : null],
          ]}
        />
        <ResumoGrupo
          titulo="Agenda/local"
          itens={[
            ["Data desejada", atendimento.data_desejada ? formatData(atendimento.data_desejada) : null],
            ["Horário desejado", atendimento.horario_desejado ? atendimento.horario_desejado.slice(0, 5) : null],
            ["Duração", atendimento.duracao_horas ? `${atendimento.duracao_horas} h` : null],
            ["Endereço", atendimento.endereco ?? null],
            ["Bairro", atendimento.bairro ?? null],
            ["Tipo local", atendimento.tipo_local ? (formatRotulo(atendimento.tipo_local) ?? atendimento.tipo_local) : null],
          ]}
        />
        {!atendimento.ia_pausada && (
          <ResumoGrupo
            titulo="IA"
            itens={[
              ["Responsável", formatRotulo(atendimento.responsavel_atual) ?? atendimento.responsavel_atual],
              ["Próxima ação", atendimento.proxima_acao_esperada ?? "Não informado ainda"],
              ["Resumo", atendimento.resumo_operacional ?? "Não informado ainda"],
            ]}
          />
        )}
        <ResumoGrupo
          titulo="Pix"
          itens={[
            ["Pix", atendimento.pix_status ? (formatEnum(String(atendimento.pix_status)) ?? String(atendimento.pix_status)) : null],
            ["Último comprovante", detalhe.comprovantes_pix[0] ? formatDataHora(detalhe.comprovantes_pix[0].created_at) : null],
          ]}
        />
      </div>

      <SecaoProgramas programas={detalhe.servicos} />

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
            Qualificação
          </h3>
          <div className="mb-1 h-1.5 w-full rounded-full bg-ink-300">
            <div
              className="h-1.5 rounded-full bg-success-500 transition-all"
              style={{ width: `${(progresso / total) * 100}%` }}
            />
          </div>
          <p className="mb-2 text-xs text-text-muted">
            {progresso === 0 ? "Nenhum item qualificado" : progresso === total ? "Totalmente qualificado" : `${progresso} de ${total} qualificados`}
          </p>
          <div className="flex flex-col gap-1.5">
            {SINAIS_CANONICOS.map(({ chave, rotulo }) => {
              const v = sq?.[chave]
              const estado = v === true ? "sim" : v === false ? "nao" : "pendente"
              return (
                <span key={chave} className={`flex items-center gap-1.5 text-xs ${estado === "sim" ? "text-success-500" : estado === "nao" ? "text-danger-500" : "text-text-muted"}`}>
                  {estado === "sim" ? <CheckCircle2 size={13} /> : estado === "nao" ? <XCircle size={13} /> : <Circle size={13} />}
                  {rotulo}
                </span>
              )
            })}
          </div>
        </div>

        {detalhe.bloqueio && (
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
              Bloqueio
            </h3>
            <div className="space-y-1 text-[13px] text-text-secondary">
              <p>{formatDataHora(detalhe.bloqueio.inicio)} · {formatRotulo(detalhe.bloqueio.estado) ?? detalhe.bloqueio.estado}</p>
              <Link
                href={`/agenda?bloqueio=${detalhe.bloqueio.id}`}
                className="text-text-link focus-visible:ring-2 focus-visible:ring-gold-700 focus-visible:ring-offset-2 focus-visible:outline-none"
              >
                Abrir na agenda
              </Link>
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}

function SecaoProgramas({ programas }: { programas: ServicoFechado[] }) {
  return (
    <div className="mt-4">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
        Programas
      </h3>

      {programas.length === 0 ? (
        <p className="text-[13px] text-text-muted">Nenhum programa fechado.</p>
      ) : (
        <div className="space-y-1">
          {programas.map((s) => (
            <div key={s.id} className="flex items-center justify-between text-[13px]">
              <span className="text-text-primary">{s.nome} · {s.duracao_nome}</span>
              <span className="font-medium text-text-primary">{formatBRL(s.preco_snapshot)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ResumoGrupo({ titulo, itens }: { titulo: string; itens: [string, string | null][] }) {
  const visiveis = itens.filter(([, v]) => v !== null) as [string, string][]
  if (visiveis.length === 0) return null
  return (
    <dl>
      <dt className="mb-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
        {titulo}
      </dt>
      <dd>
        <div className="grid grid-cols-[130px_1fr] gap-x-3 gap-y-1 text-[12px]">
          {visiveis.map(([label, valor]) => (
            <div key={label} className="contents">
              <span className="text-text-muted">{label}</span>
              <span className="min-w-0 break-words text-text-primary">{valor}</span>
            </div>
          ))}
        </div>
      </dd>
    </dl>
  )
}
