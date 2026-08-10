// Contrato de verificação agent-native.
//
// Um componente publica seu estado relevante no DOM como um blob JSON num atributo
// `data-verificacao` (+ `data-verify="<id>"` como seletor). O agente lê esse blob
// pelo browser (Playwright MCP, no project `authed`) em vez de raspar a UI
// renderizada. As fixtures públicas que existiam para isso foram removidas — eram
// bypass de auth em produção —, então a leitura hoje é sempre em rota autenticada.

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
