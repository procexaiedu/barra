/**
 * A aba **Telefonistas** (ticket 22, ADR-0048): o cadastro em que o dono mexe no percentual de
 * comissão de quem vende.
 *
 * "Telefonista" é o **Vendedor** dito no vocabulário do grupo financeiro — a tabela do backend
 * continua sendo `barravips.vendedores`, e não existe entidade nova. Cada nome abaixo é o nome
 * literal de `api/src/barra/dominio/financeiro/schemas.py`; divergir aqui não quebra o build,
 * quebra a tela em produção.
 *
 * ⚠️ Comissão do telefonista **não é** comissão da modelo. São duas pessoas, duas bases e duas
 * telas: a dela é o `percentual_repasse` com snapshot na venda, e o extrato da temporada dela
 * (que ela lê junto com o gestor) não mostra nada disto.
 */

/** `GET /v1/financeiro/telefonistas` → `TelefonistaResponse`. */
export interface Telefonista {
  id: string
  nome: string
  /** Em pontos percentuais: `7` = 7% do faturamento BRUTO vendido (ADR-0048 §2). */
  percentual_comissao: number
  ativo: boolean
  /** O vínculo com a venda: quem postou a ficha (ADR-0048 §5). Sem ele, nunca há comissão. */
  whatsapp_jid: string | null
}

export interface TelefonistasListaResponse {
  items: Telefonista[]
}

/** A referência que o dono deu, e o DEFAULT da coluna: telefonista novo entra com 7%. */
export const PERCENTUAL_PADRAO = 7

/**
 * A faixa **operacional** de 1 a 10% — não é validação.
 *
 * O backend aceita 0..100 porque o CHECK do banco é 0..100 e o próprio dono divagou "ou até 100%".
 * A tela AVISA quando o número sai do usual; recusar seria inventar uma invariante que o domínio
 * negou (ADR-0048, alternativas rejeitadas).
 */
export const FAIXA_MIN = 1
export const FAIXA_MAX = 10

export function foraDaFaixaOperacional(percentual: number): boolean {
  return percentual < FAIXA_MIN || percentual > FAIXA_MAX
}

/**
 * Aceita "7", "7,5" e "7.5" — o gestor digita das três formas. `null` = não é número.
 *
 * Sem o tratamento de milhar de `lerValor` (dinheiro): percentual não passa de dois dígitos aqui,
 * e "1.5" nesse campo é um e meio por cento, nunca mil e quinhentos.
 */
export function lerPercentual(bruto: string): number | null {
  const texto = bruto.trim().replace("%", "").replace(",", ".")
  if (texto === "") return null
  const n = Number(texto)
  return Number.isFinite(n) ? n : null
}

/** "7%" / "7,5%" — vírgula decimal, e sem casa quando o número é inteiro. */
export function formatPercentual(percentual: number): string {
  const texto = Number.isInteger(percentual)
    ? String(percentual)
    : String(percentual).replace(".", ",")
  return `${texto}%`
}
