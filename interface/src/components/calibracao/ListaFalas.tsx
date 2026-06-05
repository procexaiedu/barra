"use client"

import type { FalaParaRotular } from "@/tipos/calibracao"

import { CartaoFala } from "./CartaoFala"

/** Lista de falas da rodada com progresso do proprio rotulador. */
export function ListaFalas({
  falas,
  onMarcar,
}: {
  falas: FalaParaRotular[]
  onMarcar: (falaPk: string, passou: boolean, observacao: string) => void
}) {
  const rotuladas = falas.filter((f) => f.meu_rotulo !== null).length

  return (
    <div className="flex flex-col gap-4">
      <p className="text-[13px] text-text-muted">
        {rotuladas}/{falas.length} falas rotuladas por você
      </p>
      {falas.map((fala) => (
        <CartaoFala
          key={fala.id}
          fala={fala}
          onMarcar={(passou, obs) => onMarcar(fala.id, passou, obs)}
        />
      ))}
    </div>
  )
}
