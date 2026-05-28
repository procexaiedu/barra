import { rodarSpec, type ResultadoInvariante, type Spec } from "./spec"
import { specFunil } from "./specs/funil"
import { specKanban } from "./specs/kanban"
import { specMapa } from "./specs/mapa"

// Registro central das specs de verificação agent-native. Lido pelo dashboard
// (/verificacao), pelo spec headless (pnpm verify) e pela doc do agente.
//
// `registrar` apaga o tipo do estado na fronteira do registro (cada spec é tipada
// contra seu próprio EstadoX nos arquivos specs/*.ts; aqui o consumidor só chama
// `rodar(estadoParseado)`), sem precisar de `any`.

export interface EntradaManifesto {
  id: string
  url: string
  selector: string
  rodar: (estado: unknown) => ResultadoInvariante[]
}

function registrar<T>(spec: Spec<T>): EntradaManifesto {
  return {
    id: spec.id,
    url: spec.url,
    selector: spec.selector,
    rodar: (estado) => rodarSpec(estado as T, spec),
  }
}

export const manifesto: EntradaManifesto[] = [
  registrar(specFunil),
  registrar(specMapa),
  registrar(specKanban),
]
