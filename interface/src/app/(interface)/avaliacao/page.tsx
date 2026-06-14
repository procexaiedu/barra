"use client"

import { useState } from "react"

import { PageHeader } from "@/components/layout/PageHeader"
import { PainelObservabilidade } from "@/components/observabilidade/PainelObservabilidade"
import { PainelCalibracao } from "@/components/calibracao/PainelCalibracao"
import { cn } from "@/lib/utils"

type Aba = "ao-vivo" | "calibrar"

const ABAS: { id: Aba; label: string; descricao: string }[] = [
  {
    id: "ao-vivo",
    label: "Avaliar ao vivo",
    descricao:
      "Cada resposta do agente, avaliada por você — vira o gabarito que mede se a IA substitui o vendedor.",
  },
  {
    id: "calibrar",
    label: "Calibrar judge",
    descricao:
      "Rotule cada fala da IA (✓ passou / ✕ não passou) para calibrar o judge. Você e a sócia marcam de forma independente.",
  },
]

/** Tela de Avaliação: funde as antigas /observabilidade (ao vivo, single-rater)
 *  e /calibracao (rodadas .jsonl, double-blind) em abas. Só a casca de UI é
 *  compartilhada — cada aba mantém seu hook, schema e fluxo a jusante intactos. */
export default function AvaliacaoPage() {
  const [aba, setAba] = useState<Aba>("ao-vivo")
  const ativa = ABAS.find((a) => a.id === aba) ?? ABAS[0]

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Avaliação" description={ativa.descricao} />

      <div
        role="tablist"
        aria-label="Modo de avaliação"
        className="flex items-center gap-0.5 self-start rounded-lg border border-border p-0.5"
      >
        {ABAS.map((a) => (
          <button
            key={a.id}
            type="button"
            role="tab"
            aria-selected={aba === a.id}
            onClick={() => setAba(a.id)}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-all duration-150",
              aba === a.id
                ? "bg-accent text-text-brand"
                : "text-text-muted hover:text-text-primary",
            )}
          >
            {a.label}
          </button>
        ))}
      </div>

      {aba === "ao-vivo" ? <PainelObservabilidade /> : <PainelCalibracao />}
    </div>
  )
}
