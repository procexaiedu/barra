import { test, expect } from "@playwright/test"
import { manifesto } from "../../src/lib/verify/manifest"

// Superfície HEADLESS / CI da verificação agent-native.
// Para cada spec do manifesto: navega à fixture, lê o contrato publicado no DOM
// (data-verificacao) e roda as MESMAS invariantes do dashboard/agente sobre ele.
// `pnpm verify` roda este project. As rotas /verificacao são públicas (middleware).

for (const entrada of manifesto) {
  test(`verificação: ${entrada.id}`, async ({ page }) => {
    await page.goto(entrada.url)

    const el = page.locator(entrada.selector).first()
    await expect(el, `contrato [${entrada.id}] não encontrado em ${entrada.url}`).toBeAttached()

    const raw = await el.getAttribute("data-verificacao")
    expect(raw, `contrato ausente em ${entrada.url}`).toBeTruthy()

    const resultados = entrada.rodar(JSON.parse(raw!))
    const falhas = resultados.filter((r) => !r.ok).map((r) => r.descricao)
    expect(falhas, `invariantes violadas em ${entrada.id}: ${falhas.join("; ")}`).toEqual([])
  })
}
