// Contrato de verificação agent-native.
//
// Um componente publica seu estado relevante no DOM como um blob JSON num atributo
// `data-verificacao` (+ `data-verify="<id>"` como seletor). As três superfícies de
// verificação — dashboard human-readable, agente pelo browser (Playwright MCP) e
// headless/CI — leem esse blob de volta e rodam as mesmas invariantes sobre ele.
// O agente lê o estado publicado em vez de raspar a UI renderizada.

export interface ContratoProps {
  "data-verify": string
  "data-verificacao": string
}

// Espalhe o retorno no elemento raiz do componente: <section {...emitirContrato("funil", estado)} ...>
export function emitirContrato(id: string, estado: unknown): ContratoProps {
  return {
    "data-verify": id,
    "data-verificacao": JSON.stringify(estado),
  }
}

// Lê e parseia o contrato de um elemento; null se ausente ou inválido (= contrato quebrado).
export function lerContrato<T = unknown>(el: Element | null): T | null {
  const raw = el?.getAttribute("data-verificacao")
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

export function seletorContrato(id: string): string {
  return `[data-verify="${id}"]`
}
