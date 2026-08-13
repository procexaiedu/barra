import type { NivelModelo } from "@/tipos/modelos"

/**
 * Nível/categoria interna da modelo (A/B/C). Painel-only — a IA conversacional
 * NUNCA lê este dado. null = "Sem classificação". A=ouro, B=prata, C=bronze.
 */
export const NIVEIS: NivelModelo[] = ["A", "B", "C"]

export const NIVEL_LABEL: Record<NivelModelo, string> = {
  A: "A",
  B: "B",
  C: "C",
}

/**
 * Classes do badge por nível (ouro/prata/bronze) sobre tokens semânticos — cor
 * crua do Tailwind não troca entre os temas e afundava para ~1,2:1 no claro.
 * O texto usa a escala `text-*`, que já é pareada com a superfície nos dois
 * temas; a identidade do nível fica no fio e no fundo.
 */
export const NIVEL_BADGE_CLASS: Record<NivelModelo, string> = {
  A: "border-border-brand/50 bg-state-active/15 text-text-brand",
  B: "border-border-strong bg-surface-hover text-text-secondary",
  C: "border-state-handoff/40 bg-state-handoff/15 text-text-secondary",
}
