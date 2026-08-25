/**
 * O download de uma planilha do Financeiro (ticket 18).
 *
 * `lib/api.ts` não serve aqui: ele desembrulha JSON, e estas rotas devolvem `text/csv` em stream.
 * O que sobra em comum é a sessão do Supabase no header — replicada abaixo, e só ela.
 *
 * O nome do arquivo vem do `Content-Disposition` do backend, nunca do frontend: quem sabe o
 * período, a modelo e a cidade que entraram no arquivo é quem o montou. Inventar um nome aqui
 * produziria "temporadas.csv" para tudo, e o gestor guarda esses arquivos por mês.
 */

import { supabase } from "@/lib/supabase"

const baseURL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

/** Baixa a planilha de `path` (caminho da API, com query string). Lança em erro de HTTP. */
export async function baixarPlanilha(path: string, nomeReserva: string): Promise<void> {
  const {
    data: { session },
  } = await supabase.auth.getSession()
  const r = await fetch(`${baseURL}${path}`, {
    headers: session ? { authorization: `Bearer ${session.access_token}` } : {},
  })
  if (!r.ok) throw new Error(`Erro ${r.status}`)

  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const disposition = r.headers.get("content-disposition") ?? ""
  const nome = disposition.match(/filename="([^"]+)"/)?.[1] ?? nomeReserva
  const a = document.createElement("a")
  a.href = url
  a.download = nome
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
