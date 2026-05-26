import type { MotivoPerda } from "@/tipos/clientes"

/** Ordem canônica do enum barravips.motivo_perda_enum (CONTEXT.md, ADR 0008). */
export const MOTIVOS_PERDA: MotivoPerda[] = [
  "preco",
  "sumiu",
  "risco",
  "indisponibilidade",
  "fora_de_area",
  "outro",
]

/** Slug ASCII (banco) → rótulo PT-BR (UI). */
export const MOTIVO_PERDA_LABEL: Record<MotivoPerda, string> = {
  preco: "Preço",
  sumiu: "Sumiu",
  risco: "Risco",
  indisponibilidade: "Indisponibilidade",
  fora_de_area: "Fora da área",
  outro: "Outro",
}

export function rotuloMotivoPerda(slug: string): string {
  return MOTIVO_PERDA_LABEL[slug as MotivoPerda] ?? slug
}
