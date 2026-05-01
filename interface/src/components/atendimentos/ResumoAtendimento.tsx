"use client"

import Link from "next/link"
import { ReceiptText } from "lucide-react"
import { Card } from "@/components/ui/card"
import { formatBRL, formatData, formatDataHora } from "@/lib/formatters"
import type { AtendimentoDetalheResponse } from "@/tipos/atendimentos"
import { estadoLabel, tipoLabel, urgenciaLabel, valorAusente } from "@/components/atendimentos/utils"

function asNumber(valor: number | string | null) {
  if (valor === null) return null
  const n = typeof valor === "number" ? valor : Number(valor)
  return Number.isFinite(n) ? n : null
}

function horario(valor: string | null) {
  if (!valor) return "Não informado"
  return valor.slice(0, 5)
}

export function ResumoAtendimento({ detalhe }: { detalhe: AtendimentoDetalheResponse }) {
  const atendimento = detalhe.atendimento
  const valorAcordado = asNumber(atendimento.valor_acordado)
  const sinais = atendimento.sinais_qualificacao
    ? Object.entries(atendimento.sinais_qualificacao).filter(([, value]) => typeof value === "boolean")
    : []

  return (
    <Card className="rounded-lg p-6">
      <div className="mb-5 flex items-center gap-2">
        <ReceiptText size={18} strokeWidth={1.5} className="text-text-muted" />
        <h2 className="text-base font-semibold text-text-primary">Resumo operacional</h2>
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <ResumoGrupo
          titulo="Comercial"
          itens={[
            ["Estado", estadoLabel[atendimento.estado]],
            ["Tipo", atendimento.tipo_atendimento ? tipoLabel[atendimento.tipo_atendimento] : "Não informado"],
            ["Urgência", atendimento.urgencia ? urgenciaLabel[atendimento.urgencia] : "Não informado"],
            ["Valor acordado", valorAcordado === null ? "Não informado" : formatBRL(valorAcordado)],
            ["Forma de pagamento", valorAusente(atendimento.forma_pagamento)],
          ]}
        />
        <ResumoGrupo
          titulo="Agenda/local"
          itens={[
            ["Data desejada", valorAusente(atendimento.data_desejada, formatData)],
            ["Horário desejado", horario(atendimento.horario_desejado)],
            ["Duração", valorAusente(atendimento.duracao_horas, (v) => `${v} h`)],
            ["Endereço", valorAusente(atendimento.endereco)],
            ["Bairro", valorAusente(atendimento.bairro)],
            ["Tipo local", valorAusente(atendimento.tipo_local)],
          ]}
        />
        <ResumoGrupo
          titulo="IA/handoff"
          itens={[
            ["Responsável atual", atendimento.responsavel_atual],
            ["Motivo de escalada", valorAusente(atendimento.motivo_escalada)],
            ["Próxima ação esperada", valorAusente(atendimento.proxima_acao_esperada)],
            ["Resumo operacional", valorAusente(atendimento.resumo_operacional)],
          ]}
        />
        <ResumoGrupo
          titulo="Pix"
          itens={[
            ["Pix", valorAusente(atendimento.pix_status)],
            ["Último comprovante", detalhe.comprovantes_pix[0] ? formatDataHora(detalhe.comprovantes_pix[0].created_at) : "Não informado"],
          ]}
        />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
            Qualificação
          </h3>
          {sinais.length === 0 ? (
            <p className="text-[13px] text-text-muted">Não informado</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {sinais.map(([key, value]) => (
                <span key={key} className="rounded-full bg-ink-300 px-3 py-1 text-xs text-text-secondary">
                  {key.replaceAll("_", " ")}: {value ? "sim" : "não"}
                </span>
              ))}
            </div>
          )}
        </div>

        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
            Bloqueio
          </h3>
          {detalhe.bloqueio ? (
            <div className="space-y-1 text-[13px] text-text-secondary">
              <p>{formatDataHora(detalhe.bloqueio.inicio)} · {detalhe.bloqueio.estado}</p>
              <Link
                href={`/agenda?bloqueio=${detalhe.bloqueio.id}`}
                className="text-text-link focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
              >
                Abrir na agenda
              </Link>
            </div>
          ) : (
            <p className="text-[13px] text-text-muted">Não informado</p>
          )}
        </div>
      </div>
    </Card>
  )
}

function ResumoGrupo({ titulo, itens }: { titulo: string; itens: [string, string][] }) {
  return (
    <dl>
      <dt className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
        {titulo}
      </dt>
      <dd>
        <div className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2 text-[13px]">
          {itens.map(([label, valor]) => (
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
