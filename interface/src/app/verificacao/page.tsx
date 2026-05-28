"use client"

/* DASHBOARD human-readable da verificação agent-native — não faz parte do produto.
   Uma <iframe> por spec do manifesto (isola componentes pesados como deck.gl/Maps).
   "Rodar tudo" lê o contrato (data-verificacao) de cada iframe e roda as MESMAS
   invariantes do headless/agente, mostrando pass/fail por invariante.
   "Quebrar (demo)" recarrega as fixtures com ?quebrar=1 para ver as falhas sendo pegas.
   O middleware libera /verificacao. */

import { useCallback, useRef, useState } from "react"
import { manifesto } from "@/lib/verify/manifest"
import type { ResultadoInvariante } from "@/lib/verify/spec"

type ResultadoSpec = { resultados?: ResultadoInvariante[]; erro?: string }

export default function DashboardVerificacao() {
  const iframes = useRef<Record<string, HTMLIFrameElement | null>>({})
  const [resultados, setResultados] = useState<Record<string, ResultadoSpec>>({})
  const [quebrar, setQuebrar] = useState(false)

  const rodarTudo = useCallback(() => {
    const proximo: Record<string, ResultadoSpec> = {}
    for (const entrada of manifesto) {
      try {
        const doc = iframes.current[entrada.id]?.contentDocument
        const el = doc?.querySelector(entrada.selector)
        const raw = el?.getAttribute("data-verificacao")
        if (!raw) {
          proximo[entrada.id] = { erro: "contrato ausente no DOM (não publicado ou quebrado)" }
          continue
        }
        proximo[entrada.id] = { resultados: entrada.rodar(JSON.parse(raw)) }
      } catch (e) {
        proximo[entrada.id] = { erro: String(e) }
      }
    }
    setResultados(proximo)
  }, [])

  const src = (url: string) => (quebrar ? `${url}?quebrar=1` : url)

  return (
    <div className="min-h-screen bg-background p-6 text-foreground">
      <header className="mb-4 flex items-center gap-4">
        <h1 className="text-base font-semibold">Verificação agent-native</h1>
        <button
          type="button"
          onClick={rodarTudo}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:brightness-110"
        >
          Rodar tudo
        </button>
        <label className="flex items-center gap-2 text-sm text-text-secondary">
          <input
            type="checkbox"
            checked={quebrar}
            onChange={(ev) => {
              setQuebrar(ev.target.checked)
              setResultados({})
            }}
          />
          Quebrar (demo)
        </label>
      </header>

      <div className="flex flex-col gap-6">
        {manifesto.map((entrada) => {
          const r = resultados[entrada.id]
          return (
            <section key={entrada.id} className="rounded-lg ring-1 ring-foreground/10">
              <div className="flex items-center justify-between border-b border-foreground/10 px-4 py-2">
                <h2 className="text-sm font-medium">{entrada.id}</h2>
                <code className="text-xs text-text-muted">{src(entrada.url)}</code>
              </div>

              <div className="grid gap-4 p-4 md:grid-cols-2">
                <iframe
                  ref={(node) => {
                    iframes.current[entrada.id] = node
                  }}
                  // key força reload quando o toggle muda
                  key={src(entrada.url)}
                  src={src(entrada.url)}
                  title={entrada.id}
                  className="h-72 w-full rounded-md border border-foreground/10 bg-card"
                />

                <ul className="flex flex-col gap-1.5 text-sm">
                  {!r ? (
                    <li className="text-text-muted">Clique em “Rodar tudo”.</li>
                  ) : r.erro ? (
                    <li className="font-medium text-danger-500">⚠ {r.erro}</li>
                  ) : (
                    r.resultados?.map((inv) => (
                      <li key={inv.id} className="flex items-start gap-2">
                        <span aria-hidden className={inv.ok ? "text-success-500" : "text-danger-500"}>
                          {inv.ok ? "✓" : "✗"}
                        </span>
                        <span className={inv.ok ? "text-text-secondary" : "font-medium text-danger-500"}>
                          {inv.descricao}
                        </span>
                      </li>
                    ))
                  )}
                </ul>
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}
