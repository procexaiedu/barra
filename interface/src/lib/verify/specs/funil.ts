import type { EtapaFunilId } from "@/tipos/dashboard"
import { seletorContrato } from "../contract"
import type { Spec } from "../spec"

// Estado que o FunilVendas publica no contrato. Espelho de FunilCoorte (src/tipos/dashboard.ts).
export interface EstadoFunil {
  topo: number
  perdidos_total: number
  etapas: { id: EtapaFunilId; coorte: number; perdas: number }[]
}

export const specFunil: Spec<EstadoFunil> = {
  id: "funil",
  url: "/verificacao/funil",
  selector: seletorContrato("funil"),
  invariantes: [
    {
      id: "perdas-somam-total",
      descricao: "perdidos_total = soma das perdas por etapa",
      checar: (e) => e.perdidos_total === e.etapas.reduce((s, x) => s + x.perdas, 0),
    },
    {
      id: "coorte-nao-crescente",
      descricao: "coorte não cresce topo→fundo",
      checar: (e) => e.etapas.every((x, i) => i === 0 || x.coorte <= e.etapas[i - 1].coorte),
    },
    {
      id: "topo-bate-primeira-etapa",
      descricao: "topo = coorte da primeira etapa",
      checar: (e) => e.etapas.length === 0 || e.topo === e.etapas[0].coorte,
    },
    {
      id: "perdas-dentro-da-coorte",
      descricao: "0 ≤ perdas ≤ coorte em cada etapa",
      checar: (e) => e.etapas.every((x) => x.perdas >= 0 && x.perdas <= x.coorte),
    },
  ],
}
