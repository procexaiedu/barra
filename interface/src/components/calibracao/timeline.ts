// Reconstrucao do chat de UMA conversa a partir das falas (turnos da IA) dela.
// Puro/testavel — espelha falas.py (_historico_ate), workers/_chunking.py (bolhas+quote)
// e workers/coordenador.py (quote cita a ultima msg do cliente).

import type { FalaParaRotular } from "@/tipos/calibracao"

/** Uma bolha da IA no WhatsApp: o texto + (se citou) a ultima fala do cliente. */
export interface Bolha {
  texto: string
  citado: string | null
}

export type Mensagem =
  | { tipo: "cliente"; texto: string }
  | { tipo: "ato"; texto: string }
  | { tipo: "ia"; bolhas: Bolha[]; fala: FalaParaRotular }

// --- Espelho fiel de workers/_chunking.py: um turno da IA vira N bolhas ----------
const MAX_CHARS = 600
const MAX_CHUNKS = 6
const PREFIXO_QUOTE = /^\s*\[quote\]\s*/i

function tirarQuote(bloco: string): [string, boolean] {
  return PREFIXO_QUOTE.test(bloco) ? [bloco.replace(PREFIXO_QUOTE, ""), true] : [bloco, false]
}

/** Colapsa espacos/tabs por linha, preserva \n simples, descarta linhas vazias. */
function normalizaBloco(bloco: string): string {
  return bloco
    .split("\n")
    .map((linha) => linha.split(/\s+/).filter(Boolean).join(" "))
    .filter((linha) => linha.length > 0)
    .join("\n")
}

/** Fallback so quando o bloco passou de 600 chars: sub-divide por sentenca. */
function subdividir(bloco: string): string[] {
  const out: string[] = []
  let atual = ""
  for (const p of bloco.split(/(?<=[.!?])\s+/)) {
    if (p.length > MAX_CHARS) {
      if (atual) {
        out.push(atual)
        atual = ""
      }
      out.push(p)
    } else if (atual.length + p.length + 1 > MAX_CHARS) {
      out.push(atual)
      atual = p
    } else {
      atual = `${atual} ${p}`.trim()
    }
  }
  if (atual) out.push(atual)
  return out
}

/** Divide o texto de UM turno da IA nas mesmas bolhas que o WhatsApp receberia,
 *  com a flag de quote por bolha (espelha chunk_texto). */
export function dividirBolhas(texto: string): { texto: string; quote: boolean }[] {
  const out: string[] = []
  const flags: boolean[] = []
  for (const bruto of texto.trim().split(/\n\s*\n/)) {
    const [blocoRaw, quote] = tirarQuote(bruto)
    const bloco = normalizaBloco(blocoRaw)
    if (!bloco) continue
    if (bloco.length <= MAX_CHARS) {
      out.push(bloco)
      flags.push(quote)
    } else {
      const sub = subdividir(bloco)
      out.push(...sub)
      flags.push(...sub.map(() => quote))
    }
  }
  if (out.length <= MAX_CHUNKS) return out.map((t, i) => ({ texto: t, quote: flags[i] }))
  // cap: funde o excedente no ultimo chunk (anti-spam); flag = OR dos fundidos.
  const cabeca = out.slice(0, MAX_CHUNKS - 1)
  const cauda = out.slice(MAX_CHUNKS - 1)
  const cabecaFlags = flags.slice(0, MAX_CHUNKS - 1)
  const caudaFlags = flags.slice(MAX_CHUNKS - 1)
  return [...cabeca, cauda.join("\n\n")].map((t, i) => ({
    texto: t,
    quote: i < cabeca.length ? cabecaFlags[i] : caudaFlags.some(Boolean),
  }))
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
 *  completo (turnos anteriores) + a propria resposta final; cada turno da IA e
 *  mapeado de volta a sua fala (p/ voto) e quebrado nas bolhas do WhatsApp.
 *  `[quote]` numa bolha cita a ultima fala do cliente ate ali. */
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
      const fala = falasDaConversa[iaIdx] ?? ultima
      iaIdx += 1
      const bolhas = dividirBolhas(linha.slice("ia: ".length)).map((b) => ({
        texto: b.texto,
        citado: b.quote ? ultimoCliente : null,
      }))
      msgs.push({ tipo: "ia", bolhas, fala })
    } else {
      // ato: "[💸 cliente enviou ...]" -> sem os colchetes externos
      msgs.push({ tipo: "ato", texto: linha.replace(/^\[/, "").replace(/\]$/, "") })
    }
  }
  return msgs
}
