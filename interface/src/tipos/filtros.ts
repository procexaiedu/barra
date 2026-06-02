/** Contrato de período compartilhado por todo o painel. Espelha o `Literal` do
 *  backend (`api/src/barra/core/janela.py`): hoje | 7d | 30d | mes | tudo | custom.
 *  "tudo" (rótulo "Todos") é ancorado no 1º registro real no backend — não puxa 2020. */
export type PresetPeriodo = "hoje" | "7d" | "30d" | "mes" | "tudo" | "custom"

export interface PeriodoSelecionado {
  periodo: PresetPeriodo
  /** ISO `YYYY-MM-DD`. Preenchidos quando `periodo === "custom"`; nos presets o
   *  componente também resolve `de/ate` client-side (útil p/ endpoints de lista),
   *  exceto "tudo" (que é janela aberta → `null`). */
  de: string | null
  ate: string | null
}

export const PERIODO_LABEL: Record<PresetPeriodo, string> = {
  hoje: "Hoje",
  "7d": "7 dias",
  "30d": "30 dias",
  mes: "Este mês",
  tudo: "Todos",
  custom: "Personalizado",
}

/** Ordem/visibilidade padrão das pills no Popover. Surfaces podem passar um
 *  subconjunto via prop `presets`. "custom" é sempre renderizado à parte. */
export const PRESETS_PERIODO_PADRAO: PresetPeriodo[] = ["hoje", "7d", "30d", "mes", "tudo"]
