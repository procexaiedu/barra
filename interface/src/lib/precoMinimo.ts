import { formatBRL } from "@/lib/formatters"

/**
 * Preço mínimo da linha de tabela (ADR-0037): piso ABSOLUTO daquele par programa × duração — o
 * menor valor que a IA pode ofertar ali. Ele clampa a escada de desconto POR CIMA do percentual
 * global: `oferta = max(preço × (1 − pct), preco_minimo)`.
 *
 * Três estados, e os três significam coisas diferentes no painel:
 *  - `null`  → a linha não tem piso próprio; só o percentual global da casa manda;
 *  - `< preco` → a linha desce até esse valor e não menos;
 *  - `== preco` → linha NÃO descontável (o caso do Pernoite e dos 30min da Catarina).
 *
 * `undefined` não é estado de negócio: é o backend que ainda não devolve a coluna na LISTAGEM
 * (`_programas()` em api/dominio/modelos/routes.py serializa o piso só no POST/PATCH de um
 * vínculo). Desconhecido ≠ "sem mínimo" — por isso a UI não desenha pílula nenhuma nesse caso e,
 * sobretudo, NUNCA manda `preco_minimo` num PATCH que o operador não tocou (mandaria `null` e
 * apagaria o piso de quem tem).
 */

/** Tolerância de centavo: os dois lados vêm do mesmo NUMERIC serializado como float. */
const EPSILON = 0.005

export type EstadoPiso =
  | { tipo: "desconhecido" }
  | { tipo: "sem_piso" }
  | { tipo: "piso"; valor: number }
  | { tipo: "nao_descontavel"; valor: number }

export function estadoDoPiso(preco: number, precoMinimo: number | null | undefined): EstadoPiso {
  if (precoMinimo === undefined) return { tipo: "desconhecido" }
  if (precoMinimo === null) return { tipo: "sem_piso" }
  if (Math.abs(precoMinimo - preco) < EPSILON) return { tipo: "nao_descontavel", valor: precoMinimo }
  return { tipo: "piso", valor: precoMinimo }
}

export type LeituraMinimo = { minimo: number | null } | { erro: string }

/**
 * Lê o campo "mínimo": vazio = sem piso (`null`); número = o piso. Espelha no cliente o CHECK
 * `modelo_programas_preco_minimo_ate_preco` — piso acima do preço faria a escada clampada devolver
 * um valor MAIOR que a tabela, ou seja, a IA cotaria mais caro justamente ao dar desconto.
 */
export function lerPrecoMinimo(texto: string, preco: number): LeituraMinimo {
  if (!texto.trim()) return { minimo: null }
  const minimo = Number(texto.replace(",", "."))
  if (isNaN(minimo) || minimo < 0) {
    return { erro: "Informe um mínimo válido (ou deixe vazio para a linha não ter mínimo)" }
  }
  if (minimo - preco > EPSILON) {
    return {
      erro: `O mínimo (${formatBRL(minimo)}) não pode ser maior que o preço (${formatBRL(preco)}).`,
    }
  }
  return { minimo }
}

/** `true` quando o operador de fato mexeu no piso — só então o campo entra no PATCH. */
export function minimoAlterado(minimo: number | null, original: number | null | undefined): boolean {
  if (original === null || original === undefined) return minimo !== null
  if (minimo === null) return true
  return Math.abs(minimo - original) >= EPSILON
}

/**
 * Corpo do PATCH de preço. O backend usa `model_fields_set`: `preco_minimo` AUSENTE preserva o
 * piso cadastrado, `null` explícito o limpa. Por isso `preco_minimo` só entra quando mudou —
 * `undefined` no retorno significa "não mande esta chave".
 */
export function corpoAtualizarPreco(args: {
  preco: number
  minimo: number | null
  minimoOriginal: number | null | undefined
}): { preco: number; preco_minimo?: number | null } {
  return minimoAlterado(args.minimo, args.minimoOriginal)
    ? { preco: args.preco, preco_minimo: args.minimo }
    : { preco: args.preco }
}

/**
 * O 422 de "preço abaixo do piso cadastrado" (rota PATCH, quando o corpo não trouxe o piso).
 * Acontece quando a UI não conhecia o piso — devolve o valor que o servidor conhece para
 * preencher o campo e deixar o operador ajustar os dois de uma vez.
 */
const RE_PISO_DO_ERRO = /preco_minimo\s+cadastrado\s+\(([\d.,]+)\)/i

export function pisoDoErro422(detalhe: string): number | null {
  const achado = RE_PISO_DO_ERRO.exec(detalhe)
  if (!achado) return null
  const valor = Number(achado[1].replace(",", "."))
  return isNaN(valor) ? null : valor
}

export function mensagemPrecoAbaixoDoPiso(preco: number, piso: number): string {
  return `${formatBRL(preco)} fica abaixo do mínimo desta linha (${formatBRL(piso)}). Ajuste o campo "Mínimo" junto — ou apague-o para tirar o piso.`
}

/** Preço novo furaria o piso já cadastrado (o mesmo caso que o backend recusa com 422). */
export function precoViolaPiso(preco: number, piso: number | null | undefined): piso is number {
  return piso !== null && piso !== undefined && piso - preco > EPSILON
}
