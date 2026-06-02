"use client"

/* ROTA TEMPORÁRIA DE VERIFICAÇÃO VISUAL — não faz parte do produto.
   Espelha o chrome de (interface)/page.tsx com mock data para screenshots
   antes/depois sem depender de auth nem do backend. Remover ao final. */

import { useState } from "react"
import { CheckCircle2, CalendarOff, LayoutList, LayoutGrid } from "lucide-react"
import { HeaderPainel } from "@/components/painel/HeaderPainel"
import { CardDestaque } from "@/components/painel/CardDestaque"
import { TileMetrica } from "@/components/painel/TileMetrica"
import { LinhaAgenda } from "@/components/painel/LinhaAgenda"
import { Sidebar } from "@/components/layout/Sidebar"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { formatBRL, formatDiaSemana, formatData } from "@/lib/formatters"
import type {
  CardDestaque as CardT,
  MetricasDia,
  LinhaAgenda as LinhaT,
} from "@/tipos/painel"

const min = (n: number) => new Date(Date.now() - n * 60_000).toISOString()
const hoje = new Date().toISOString().slice(0, 10)
const iso = (hhmm: string) => `${hoje}T${hhmm}:00-03:00`

const CARDS: CardT[] = [
  {
    atendimento_id: "a1", numero_curto: 142, cliente_nome: "Ricardo Menezes",
    cliente_telefone_formatado: "(21) 99876-5432", ia_pausada_motivo: "pix_em_revisao",
    motivo_escalada: "pix_duvidoso", proxima_acao_esperada: null, responsavel_atual: "Fernando",
    ia_pausada_em: min(96), previsao_termino: null, expirado: false, modelo_nome: "Valentina",
  },
  {
    atendimento_id: "a2", numero_curto: 138, cliente_nome: "Cliente novo",
    cliente_telefone_formatado: "(11) 98123-4455", ia_pausada_motivo: "handoff_ia",
    motivo_escalada: "preco_negociacao", proxima_acao_esperada: null, responsavel_atual: "Fernando",
    ia_pausada_em: min(17), previsao_termino: null, expirado: false, modelo_nome: "Helena",
  },
  {
    atendimento_id: "a3", numero_curto: 151, cliente_nome: "André Pacheco",
    cliente_telefone_formatado: "(21) 99111-2233", ia_pausada_motivo: "modelo_em_atendimento",
    motivo_escalada: "tempo_excedido", proxima_acao_esperada: null, responsavel_atual: "modelo",
    ia_pausada_em: min(204), previsao_termino: null, expirado: true, modelo_nome: "Valentina",
  },
  {
    atendimento_id: "a4", numero_curto: 149, cliente_nome: "Marcelo Tavares",
    cliente_telefone_formatado: "(21) 98777-0099", ia_pausada_motivo: "handoff_ia",
    motivo_escalada: "comportamento_ambiguo", proxima_acao_esperada: null, responsavel_atual: "Fernando",
    ia_pausada_em: min(6), previsao_termino: null, expirado: false, modelo_nome: "Helena",
  },
]

const METRICAS_CHEIA: MetricasDia = {
  abertos: 7, fechamentos_hoje: 4, perdas_hoje: 2, valor_bruto_hoje_brl: 8400,
  lucro_hoje_brl: 3360, ticket_medio_brl: 2100, taxa_conversao_pct: 66.7,
  pix_em_revisao_pendentes: 1,
  tendencia: {
    fechamentos_delta: 2, fechamentos_ontem: 2, perdas_delta: -1, perdas_ontem: 3,
    valor_bruto_delta_brl: 1800, valor_bruto_ontem_brl: 6600,
  },
}

const METRICAS_ZERO: MetricasDia = {
  abertos: 0, fechamentos_hoje: 0, perdas_hoje: 0, valor_bruto_hoje_brl: 0,
  lucro_hoje_brl: 0, ticket_medio_brl: null, taxa_conversao_pct: null,
  pix_em_revisao_pendentes: 0,
  tendencia: {
    fechamentos_delta: 0, fechamentos_ontem: 0, perdas_delta: 0, perdas_ontem: 0,
    valor_bruto_delta_brl: 0, valor_bruto_ontem_brl: 0,
  },
}

const AGENDA: LinhaT[] = [
  { id: "b1", modelo_id: "m1", inicio: iso("14:00"), fim: iso("15:00"), estado: "em_atendimento", origem: "ia", cliente_nome: "Ricardo Menezes", observacao: null, atendimento_id: "a1", modelo_nome: "Valentina" },
  { id: "b2", modelo_id: "m1", inicio: iso("16:00"), fim: iso("17:30"), estado: "bloqueado", origem: "painel_fernando", cliente_nome: "André Pacheco", observacao: null, atendimento_id: "a3", modelo_nome: "Valentina" },
  { id: "b3", modelo_id: "m2", inicio: iso("19:00"), fim: iso("20:00"), estado: "concluido", origem: "manual", cliente_nome: null, observacao: "Bloqueio manual — jantar", atendimento_id: null, modelo_nome: "Helena" },
  { id: "b4", modelo_id: "m2", inicio: iso("21:00"), fim: iso("22:00"), estado: "cancelado", origem: "ia", cliente_nome: "Lucas Andrade", observacao: null, atendimento_id: "a9", modelo_nome: "Helena" },
]

/* Réplica fiel do chrome de (interface)/page.tsx — ao editar a página real, espelhar aqui. */
function PainelChrome({
  cards, metricas, agenda, mostrarModelo,
}: {
  cards: CardT[]
  metricas: MetricasDia
  agenda: LinhaT[]
  mostrarModelo: boolean
}) {
  const [compacto, setCompacto] = useState(false)
  return (
    <div>
      <HeaderPainel modeloIds={[]} onModeloChange={() => {}} />

      <section aria-label="Aguardando você" className="px-8 py-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
            <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
            Aguardando você
          </h2>
          {cards.length > 0 && (
            <div className="flex items-center gap-3">
              <span className="text-xs font-medium text-text-muted">{cards.length} aguardando ação</span>
              <button
                type="button"
                onClick={() => setCompacto((c) => !c)}
                title={compacto ? "Modo grade" : "Modo compacto"}
                className="rounded p-1 text-text-muted transition-colors hover:bg-accent hover:text-text-primary"
              >
                {compacto ? <LayoutGrid size={16} /> : <LayoutList size={16} />}
              </button>
            </div>
          )}
        </div>

        {cards.length > 0 && !compacto && (
          <div className="mb-3 flex items-center gap-5">
            <span className="flex items-center gap-1.5 text-xs text-text-muted">
              <span className="h-2 w-2 rounded-full bg-state-lost" />
              Pix em revisão
            </span>
            <span className="flex items-center gap-1.5 text-xs text-text-muted">
              <span className="h-2 w-2 rounded-full bg-state-handoff" />
              Aguardando decisão
            </span>
            <span className="flex items-center gap-1.5 text-xs text-text-muted">
              <span className="h-2 w-2 rounded-full bg-state-info" />
              Modelo com o cliente
            </span>
          </div>
        )}

        {cards.length === 0 ? (
          <Card className="rounded-lg bg-card">
            <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
              <div className="flex size-11 items-center justify-center rounded-full bg-success-500/10 ring-1 ring-success-500/20">
                <CheckCircle2 size={22} strokeWidth={1.75} className="text-success-500" />
              </div>
              <div>
                <p className="text-sm font-medium text-text-primary">Nada precisa de você agora.</p>
                <p className="mt-1 text-[13px] text-text-muted">
                  Atendimentos que precisarem da sua decisão aparecem aqui.
                </p>
              </div>
            </div>
          </Card>
        ) : compacto ? (
          <Card className="max-h-44 overflow-y-auto rounded-lg bg-card">
            {cards.map((card) => (
              <CardDestaque key={card.atendimento_id} card={card} compacto onAbrirContexto={() => {}} />
            ))}
          </Card>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {cards.map((card) => (
              <CardDestaque key={card.atendimento_id} card={card} onAbrirContexto={() => {}} />
            ))}
          </div>
        )}
      </section>

      <section aria-label="Métricas de hoje" className="px-8 py-5">
        <div className="mb-4">
          <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
            <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
            Hoje
          </h2>
          <p className="mt-1 pl-[14px] text-xs capitalize text-text-muted">
            {formatDiaSemana(new Date())} · {formatData(new Date().toISOString())}
          </p>
        </div>
        <div className="grid grid-cols-5 gap-4">
          <TileMetrica
            label="ATENDIMENTOS ABERTOS"
            valor={String(metricas.abertos)}
            tooltip="Conversas ainda em andamento"
            isZero={metricas.abertos === 0}
            metricaSecundaria={{ label: "Em handoff", valor: String(cards.length) }}
          />
          <TileMetrica
            label="FECHAMENTOS HOJE"
            valor={String(metricas.fechamentos_hoje)}
            colorClass="text-success-500"
            tooltip="Atendimentos pagos e encerrados hoje"
            isZero={metricas.fechamentos_hoje === 0}
            tendencia={metricas.tendencia && { delta: metricas.tendencia.fechamentos_delta, label: "vs ontem" }}
            metricaSecundaria={{ label: "Ticket médio", valor: metricas.ticket_medio_brl != null ? formatBRL(metricas.ticket_medio_brl) : "—" }}
          />
          <TileMetrica
            label="PERDAS HOJE"
            valor={String(metricas.perdas_hoje)}
            colorClass="text-danger-500"
            tooltip="Atendimentos que não se converteram hoje"
            isZero={metricas.perdas_hoje === 0}
            tendencia={metricas.tendencia && { delta: metricas.tendencia.perdas_delta, label: "vs ontem", inverso: true }}
            metricaSecundaria={{ label: "Conversão", valor: metricas.taxa_conversao_pct != null ? `${metricas.taxa_conversao_pct.toFixed(0)}%` : "—" }}
          />
          <TileMetrica
            label="VALOR BRUTO HOJE"
            valor={formatBRL(metricas.valor_bruto_hoje_brl)}
            tooltip="Soma dos valores finais dos fechamentos"
            isZero={metricas.valor_bruto_hoje_brl === 0}
            tendencia={metricas.tendencia && { delta: metricas.tendencia.valor_bruto_delta_brl, label: "vs ontem", formatDelta: formatBRL }}
            metricaSecundaria={{ label: "Fechamentos", valor: String(metricas.fechamentos_hoje) }}
          />
          <TileMetrica
            label="LUCRO HOJE"
            valor={formatBRL(metricas.lucro_hoje_brl)}
            colorClass="text-success-500"
            tooltip="Valor bruto menos repasses às modelos"
            isZero={metricas.lucro_hoje_brl === 0}
            metricaSecundaria={{ label: "Margem", valor: metricas.valor_bruto_hoje_brl > 0 ? `${Math.round(metricas.lucro_hoje_brl / metricas.valor_bruto_hoje_brl * 100)}%` : "—" }}
          />
        </div>
      </section>

      <section aria-label="Agenda de hoje" className="px-8 py-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
            <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
            Agenda de hoje
          </h2>
          <Button variant="ghost" size="sm" onClick={() => {}}>Bloquear horário</Button>
        </div>
        {agenda.length === 0 ? (
          <Card className="rounded-lg bg-card">
            <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
              <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
                <CalendarOff size={22} strokeWidth={1.75} className="text-text-muted" />
              </div>
              <div>
                <p className="text-sm font-medium text-text-primary">Nenhum horário reservado hoje.</p>
                <p className="mt-1 text-[13px] text-text-muted">Reservas e bloqueios de hoje aparecem aqui.</p>
              </div>
            </div>
          </Card>
        ) : (
          <Card className="overflow-hidden rounded-lg bg-card">
            {agenda.map((linha) => (
              <LinhaAgenda key={linha.id} linha={linha} mostrarModelo={mostrarModelo} onAbrirDetalhes={() => {}} />
            ))}
          </Card>
        )}
      </section>
    </div>
  )
}

function Divisor({ texto }: { texto: string }) {
  return (
    <div className="flex items-center gap-3 px-8 pt-8 pb-2">
      <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-muted">{texto}</span>
      <span className="h-px flex-1 bg-border-subtle" />
    </div>
  )
}

export default function PainelPreview() {
  return (
    <div className="dark flex min-h-screen bg-background text-foreground">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-8">
        <Divisor texto="Estado populado" />
        <PainelChrome cards={CARDS} metricas={METRICAS_CHEIA} agenda={AGENDA} mostrarModelo />
        <Divisor texto="Estado vazio / dia calmo" />
        <PainelChrome cards={[]} metricas={METRICAS_ZERO} agenda={[]} mostrarModelo />
      </main>
    </div>
  )
}
