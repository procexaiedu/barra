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

/** Classes Tailwind do badge por nível (ouro/prata/bronze). */
export const NIVEL_BADGE_CLASS: Record<NivelModelo, string> = {
  A: "border-amber-400/40 bg-amber-400/15 text-amber-300",
  B: "border-slate-300/40 bg-slate-300/15 text-slate-200",
  C: "border-orange-700/40 bg-orange-700/15 text-orange-400",
}
