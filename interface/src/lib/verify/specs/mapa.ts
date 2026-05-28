import { seletorContrato } from "../contract"
import type { Spec } from "../spec"

// Estado que o MapaClientes publica. Regra de domínio (CONTEXT.md / ADR 0008):
// cliente sem externo geocodificado não some — entra no contador "sem localização".
export interface EstadoMapa {
  pins: number
  semLocalizacao: number
  totalClientes: number
}

export const specMapa: Spec<EstadoMapa> = {
  id: "mapa",
  url: "/demo-mapa",
  selector: seletorContrato("mapa"),
  invariantes: [
    {
      id: "todo-cliente-contabilizado",
      descricao: "total de clientes = pins no mapa + sem localização",
      checar: (e) => e.totalClientes === e.pins + e.semLocalizacao,
    },
    {
      id: "contagens-nao-negativas",
      descricao: "pins e sem-localização não-negativos",
      checar: (e) => e.pins >= 0 && e.semLocalizacao >= 0,
    },
  ],
}
