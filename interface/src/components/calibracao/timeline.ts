// Reconstrucao do chat de UMA conversa a partir das falas (turnos da IA) dela.
// Puro/testavel — espelha falas.py (_historico_ate) e workers/coordenador.py (quote).

import type { FalaParaRotular } from "@/tipos/calibracao"

export type Mensagem =
  | { tipo: "cliente"; texto: string }
  | { tipo: "ato"; texto: string }
  | { tipo: "ia"; texto: string; citado: string | null; fala: FalaParaRotular }

const PREFIXO_QUOTE = /^\[quote\]\s*/i

/** Separa o marker `[quote]` (literal, no inicio da bolha) do texto exibido.
 *  No WhatsApp real o prefixo some e a bolha vira reply da ultima msg do cliente. */
function tirarQuote(texto: string): { texto: string; tinhaQuote: boolean } {
  const m = texto.match(PREFIXO_QUOTE)
  return m ? { texto: texto.slice(m[0].length), tinhaQuote: true } : { texto, tinhaQuote: false }
}

/** Agrupa as falas da rodada por conversa, preservando a ordem global. */
export function agruparPorConversa(
  falas: FalaParaRotular[],
): { conversaId: string; cenario: string; falas: FalaParaRotular[] }[] {
  const ordem: string[] = []
  const mapa = new Map<string, FalaParaRotular[]>()
  for (const f of falas) {
    let bucket = mapa.get(f.conversa_id)
    if (!bucket) {
      bucket = []
      mapa.set(f.conversa_id, bucket)
      ordem.push(f.conversa_id)
    }
    bucket.push(f)
  }
  return ordem.map((id) => {
    const grupo = mapa.get(id)!
    return { conversaId: id, cenario: grupo[0].cenario, falas: grupo }
  })
}

/** Monta o chat interleaved de uma conversa. A ultima fala carrega o historico
 *  completo (turnos anteriores) + a propria resposta final; cada bolha da IA e
 *  mapeada de volta a sua fala (p/ voto). `[quote]` cita a ultima fala do cliente. */
export function montarChat(falasDaConversa: FalaParaRotular[]): Mensagem[] {
  if (falasDaConversa.length === 0) return []
  const ultima = falasDaConversa[falasDaConversa.length - 1]
  const brutos = [...ultima.historico, "ia: " + ultima.texto_resposta]

  const msgs: Mensagem[] = []
  let iaIdx = 0
  let ultimoCliente: string | null = null

  for (const linha of brutos) {
    if (linha.startsWith("cliente: ")) {
      const texto = linha.slice("cliente: ".length)
      ultimoCliente = texto
      msgs.push({ tipo: "cliente", texto })
    } else if (linha.startsWith("ia: ")) {
      const { texto, tinhaQuote } = tirarQuote(linha.slice("ia: ".length))
      const fala = falasDaConversa[iaIdx] ?? ultima
      iaIdx += 1
      msgs.push({ tipo: "ia", texto, citado: tinhaQuote ? ultimoCliente : null, fala })
    } else {
      // ato: "[💸 cliente enviou ...]" -> sem os colchetes externos
      msgs.push({ tipo: "ato", texto: linha.replace(/^\[/, "").replace(/\]$/, "") })
    }
  }
  return msgs
}
