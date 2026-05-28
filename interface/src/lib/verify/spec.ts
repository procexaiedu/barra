// Invariantes e specs de verificação. As invariantes são funções TS puras sobre o
// estado parseado do contrato — fonte de verdade única, importada pelo dashboard
// (client), pelo spec headless (node) e descrita na doc do agente.

export interface Invariante<T> {
  id: string
  descricao: string
  checar: (estado: T) => boolean
}

export interface Spec<T> {
  id: string
  url: string // rota de fixture (sem auth) onde o contrato é publicado
  selector: string // seletor CSS do elemento que carrega o contrato
  invariantes: Invariante<T>[]
}

export interface ResultadoInvariante {
  id: string
  descricao: string
  ok: boolean
}

export function rodarSpec<T>(estado: T, spec: Spec<T>): ResultadoInvariante[] {
  return spec.invariantes.map((inv) => ({
    id: inv.id,
    descricao: inv.descricao,
    ok: checarSeguro(inv, estado),
  }))
}

// Uma invariante que estoura (ex.: campo ausente no contrato) conta como falha, não crash.
function checarSeguro<T>(inv: Invariante<T>, estado: T): boolean {
  try {
    return inv.checar(estado)
  } catch {
    return false
  }
}
