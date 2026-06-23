"use client"

/* FIXTURE DE VERIFICAÇÃO agent-native — não faz parte do produto.
   Monta o BlocoNorteCotacao real com um NorteCotacao mock para que o contrato
   (data-verificacao) seja publicado sem auth nem backend. O middleware libera /verificacao.
   `?quebrar=1` publica um estado inconsistente (fechadas > cotadas) para demonstrar as três
   superfícies pegando a falha. */

import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { BlocoNorteCotacao } from "@/components/dashboard/BlocoNorteCotacao"
import type { NorteCotacao } from "@/tipos/dashboard"

// 40 cotadas → 10 fechadas (25%) + 8 em aberto (22 perdidas); R$12.000 / 40 = R$300/thread. Passa tudo.
const NORTE_OK: NorteCotacao = {
  cotadas: 40,
  fechadas: 10,
  em_aberto: 8,
  conversao_cotada_para_fechado_pct: 25.0,
  receita_bruta_brl: 12000,
  r_por_thread_cotada_brl: 300.0,
  nota: "coorte ancorada em cotacao_enviada_em (fixture)",
}

// fechadas (50) > cotadas (40) → quebra "fechadas-dentro-cotadas" e "conversao-consistente".
const NORTE_QUEBRADO: NorteCotacao = { ...NORTE_OK, fechadas: 50 }

function Fixture() {
  const quebrar = useSearchParams().has("quebrar")
  return (
    <div className="min-h-screen bg-background p-6 text-foreground">
      <h1 className="mb-3 text-sm font-medium text-text-secondary">
        FIXTURE — Norte cotada→fechado {quebrar ? "(estado QUEBRADO)" : "(estado OK)"}
      </h1>
      <BlocoNorteCotacao norte={quebrar ? NORTE_QUEBRADO : NORTE_OK} />
    </div>
  )
}

export default function VerificacaoNorte() {
  return (
    <Suspense>
      <Fixture />
    </Suspense>
  )
}
