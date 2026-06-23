import { seletorContrato } from "../contract"
import type { Spec } from "../spec"

// Estado que o BlocoNorteCotacao publica no contrato. Espelho parcial de NorteCotacao
// (src/tipos/dashboard.ts) — só os campos que as invariantes checam.
export interface EstadoNorte {
  cotadas: number
  fechadas: number
  em_aberto: number
  conversao_cotada_para_fechado_pct: number | null
  receita_bruta_brl: number
  r_por_thread_cotada_brl: number | null
}

export const specNorte: Spec<EstadoNorte> = {
  id: "norte",
  url: "/verificacao/norte",
  selector: seletorContrato("norte"),
  invariantes: [
    {
      id: "fechadas-dentro-cotadas",
      descricao: "0 ≤ fechadas ≤ cotadas",
      checar: (e) => e.fechadas >= 0 && e.fechadas <= e.cotadas,
    },
    {
      id: "em-aberto-dentro-cotadas",
      descricao: "0 ≤ em_aberto ≤ cotadas",
      checar: (e) => e.em_aberto >= 0 && e.em_aberto <= e.cotadas,
    },
    {
      id: "decididas-mais-aberto-cabem-na-coorte",
      descricao: "fechadas + em_aberto ≤ cotadas (perdidas = resto ≥ 0)",
      checar: (e) => e.fechadas + e.em_aberto <= e.cotadas,
    },
    {
      id: "conversao-consistente",
      descricao: "conversao_pct = fechadas/cotadas*100 (null quando 0 cotadas)",
      checar: (e) =>
        e.cotadas === 0
          ? e.conversao_cotada_para_fechado_pct === null
          : e.conversao_cotada_para_fechado_pct !== null &&
            Math.abs(e.conversao_cotada_para_fechado_pct - (e.fechadas / e.cotadas) * 100) <= 0.1,
    },
    {
      id: "r-por-thread-consistente",
      descricao: "r_por_thread = receita/cotadas (null quando 0 cotadas)",
      checar: (e) =>
        e.cotadas === 0
          ? e.r_por_thread_cotada_brl === null
          : e.r_por_thread_cotada_brl !== null &&
            Math.abs(e.r_por_thread_cotada_brl - e.receita_bruta_brl / e.cotadas) <= 0.01,
    },
  ],
}
