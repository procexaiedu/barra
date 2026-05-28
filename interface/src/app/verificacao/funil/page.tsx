"use client"

/* FIXTURE DE VERIFICAÇÃO agent-native — não faz parte do produto.
   Monta o FunilVendas real com um FunilCoorte mock para que o contrato (data-verificacao)
   seja publicado sem auth nem backend. O middleware libera /verificacao.
   `?quebrar=1` publica um estado inconsistente (perdidos_total ≠ soma das perdas) para
   demonstrar as três superfícies pegando a falha. */

import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { FunilVendas } from "@/components/dashboard/FunilVendas"
import type { FunilCoorte } from "@/tipos/dashboard"

// 100 → 60 → 40 → 33 (não-crescente); perdas 30+10+5+0 = 45 = perdidos_total. Passa tudo.
const FUNIL_OK: FunilCoorte = {
  topo: 100,
  etapas: [
    { id: "Qualificando", coorte: 100, perdas: 30 },
    { id: "Aguardando", coorte: 60, perdas: 10 },
    { id: "Em_execucao", coorte: 40, perdas: 5 },
    { id: "Fechado", coorte: 33, perdas: 0 },
  ],
  perdidos_total: 45,
}

// perdidos_total mente (99 ≠ 45) → quebra a invariante "perdas-somam-total".
const FUNIL_QUEBRADO: FunilCoorte = { ...FUNIL_OK, perdidos_total: 99 }

function Fixture() {
  const quebrar = useSearchParams().has("quebrar")
  return (
    <div className="min-h-screen bg-background p-6 text-foreground">
      <h1 className="mb-3 text-sm font-medium text-text-secondary">
        FIXTURE — Funil de vendas {quebrar ? "(estado QUEBRADO)" : "(estado OK)"}
      </h1>
      <FunilVendas funil={quebrar ? FUNIL_QUEBRADO : FUNIL_OK} />
    </div>
  )
}

export default function VerificacaoFunil() {
  return (
    <Suspense>
      <Fixture />
    </Suspense>
  )
}
