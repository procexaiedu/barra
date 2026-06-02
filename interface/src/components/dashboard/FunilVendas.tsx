"use client"

import { useRouter } from "next/navigation"
import type { EtapaFunilId, FunilCoorte } from "@/tipos/dashboard"
import { cn } from "@/lib/utils"
import { emitirContrato } from "@/lib/verify/contract"

interface Props {
  funil: FunilCoorte
}

// Etapas de progressão (Perdido não é barra — vira saída lateral). Degradê ouro
// que escurece conforme afunila e termina em verde no fechamento. Os ids casam
// com o param ?estado= aceito por /atendimentos.
const META: Record<EtapaFunilId, { rotulo: string; cor: string }> = {
  Qualificando: { rotulo: "Qualificando", cor: "var(--seq-1)" },
  Aguardando: { rotulo: "Aguardando", cor: "var(--seq-2)" },
  Em_execucao: { rotulo: "Em atendimento", cor: "var(--seq-3)" },
  Fechado: { rotulo: "Fechado", cor: "var(--success-500)" },
}

// Largura mínima do trapézio (em % da coluna) para que etapas pequenas — mas não
// vazias — continuem visíveis e clicáveis. Etapa vazia (coorte 0) some de fato.
const LARGURA_MINIMA = 18
const NUM_FMT = new Intl.NumberFormat("pt-BR")
const PCT_FMT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })

export function FunilVendas({ funil }: Props) {
  const router = useRouter()
  const { topo, etapas, perdidos_total } = funil

  const largura = (coorte: number) =>
    topo > 0 && coorte > 0
      ? Math.min(Math.max((coorte / topo) * 100, LARGURA_MINIMA), 100)
      : 0

  return (
    <section
      {...emitirContrato("funil", { topo, perdidos_total, etapas })}
      aria-label="Funil de vendas por etapa"
      className="flex flex-col gap-3"
    >
      <header className="flex items-center justify-between">
        <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
          <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
          Funil de vendas
        </h2>
        <span className="text-xs font-medium text-text-muted">
          <span className="font-mono tabular-nums">{NUM_FMT.format(topo)}</span>{" "}
          {topo === 1 ? "atendimento" : "atendimentos"} no período
        </span>
      </header>

      <div className="rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        {topo === 0 ? (
          <div className="flex flex-col gap-1 rounded-md bg-muted p-4">
            <span className="text-sm text-text-primary">
              Nenhum atendimento no período selecionado.
            </span>
            <span className="text-[13px] text-text-muted">Ajuste o período no topo da página.</span>
          </div>
        ) : (
          <>
            <ol className="flex flex-col gap-0.5">
              {etapas.map((etapa, i) => {
                const meta = META[etapa.id]
                const topW = largura(etapa.coorte)
                const proxima = etapas[i + 1]
                const botW = proxima ? largura(proxima.coorte) : topW
                const pctTopo = topo > 0 ? (etapa.coorte / topo) * 100 : 0
                const pctPerda = etapa.coorte > 0 ? (etapa.perdas / etapa.coorte) * 100 : 0
                const inativo = etapa.coorte === 0
                // Trapézio centrado: estreita de topW (topo) para botW (próxima etapa).
                const clip = `polygon(${50 - topW / 2}% 0%, ${50 + topW / 2}% 0%, ${50 + botW / 2}% 100%, ${50 - botW / 2}% 100%)`

                return (
                  <li
                    key={etapa.id}
                    className="grid grid-cols-[84px_1fr_40px_52px] items-stretch gap-2 sm:grid-cols-[120px_1fr_52px_76px] sm:gap-3"
                  >
                    <span
                      className={cn(
                        "self-center truncate text-[13px]",
                        inativo ? "text-text-muted" : "text-text-primary"
                      )}
                    >
                      {meta.rotulo}
                    </span>

                    <button
                      type="button"
                      onClick={
                        inativo
                          ? undefined
                          : () =>
                              router.push(`/atendimentos?estado=${encodeURIComponent(etapa.id)}`)
                      }
                      disabled={inativo}
                      title={`${meta.rotulo}: ${NUM_FMT.format(etapa.coorte)} chegaram até aqui (${PCT_FMT.format(pctTopo)}% do topo)`}
                      aria-label={`${meta.rotulo}: ${NUM_FMT.format(etapa.coorte)} atendimentos, ${PCT_FMT.format(pctTopo)}% do topo`}
                      className={cn(
                        "group relative h-14 w-full rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
                        inativo ? "cursor-default" : "cursor-pointer"
                      )}
                    >
                      {topW > 0 ? (
                        <span
                          aria-hidden
                          className="absolute inset-0 transition-[filter] group-hover:brightness-110"
                          style={{ background: meta.cor, clipPath: clip }}
                        />
                      ) : null}
                    </button>

                    {/* Faixa de saída lateral: perdas que saíram nesta etapa. */}
                    <div className="flex items-center justify-start">
                      {etapa.perdas > 0 ? (
                        <button
                          type="button"
                          onClick={() => router.push("/atendimentos?estado=Perdido")}
                          title={`${NUM_FMT.format(etapa.perdas)} perdidos saíram em ${meta.rotulo} (${PCT_FMT.format(pctPerda)}% da etapa)`}
                          aria-label={`${NUM_FMT.format(etapa.perdas)} perdidos saíram na etapa ${meta.rotulo}`}
                          className="flex items-center gap-0.5 rounded-sm text-[11px] font-medium tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          style={{ color: "var(--danger-500)" }}
                        >
                          <span aria-hidden>↘</span>
                          {NUM_FMT.format(etapa.perdas)}
                        </button>
                      ) : null}
                    </div>

                    <span className="flex flex-col items-end justify-center leading-tight">
                      <span
                        className={cn(
                          "font-mono text-sm font-semibold tabular-nums",
                          inativo ? "text-text-muted" : "text-text-primary"
                        )}
                      >
                        {NUM_FMT.format(etapa.coorte)}
                      </span>
                      <span className="text-[11px] tabular-nums text-text-muted">
                        {PCT_FMT.format(pctTopo)}%
                      </span>
                    </span>
                  </li>
                )
              })}
            </ol>

            {perdidos_total > 0 ? (
              <p className="mt-4 flex items-center gap-1.5 text-xs text-text-muted">
                <span
                  aria-hidden
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ background: "var(--danger-500)" }}
                />
                {NUM_FMT.format(perdidos_total)} {perdidos_total === 1 ? "perdido" : "perdidos"} no
                período (saídas laterais)
              </p>
            ) : null}
          </>
        )}
      </div>
    </section>
  )
}
