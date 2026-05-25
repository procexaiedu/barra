import type { PerfilFisico } from "@/tipos/clientes"

/** Ordem canônica de exibição. Espelha o enum barravips.perfil_fisico_enum (ADR 0006). */
export const PERFIS_FISICOS: PerfilFisico[] = [
  "loira",
  "morena",
  "ruiva",
  "negra",
  "asiatica",
  "outra",
]

/** Slug ASCII (banco) → rótulo acentuado/respeitoso (UI). */
export const PERFIL_FISICO_LABEL: Record<PerfilFisico, string> = {
  loira: "Loira",
  morena: "Morena",
  ruiva: "Ruiva",
  negra: "Negra",
  asiatica: "Asiática",
  outra: "Outra",
}

export function rotuloPerfil(slug: string): string {
  return PERFIL_FISICO_LABEL[slug as PerfilFisico] ?? slug
}
