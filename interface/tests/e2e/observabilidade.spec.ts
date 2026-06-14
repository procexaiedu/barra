import { expect, test } from "@playwright/test"
import path from "node:path"

const ART = path.resolve(__dirname, ".artifacts")

// Verificacao visual da aba "Avaliar ao vivo" da tela /avaliacao (CLAUDE.md §5). Authed via
// storageState (setup). O backend local (localhost:8000) ja expoe /v1/observabilidade. Captura a
// lista e o dialog de avaliacao para inspecao; nao PERSISTE avaliacao (fecha sem salvar) para nao
// sujar o prod.
test("observabilidade: lista e dialog de avaliacao", async ({ page }) => {
  await page.goto("/avaliacao")

  await expect(page.getByRole("heading", { name: "Avaliação" })).toBeVisible()

  // espera sair do skeleton: ou aparece a lista, ou o empty state.
  await page.waitForLoadState("networkidle")
  await page.waitForTimeout(800)
  await page.screenshot({ path: path.join(ART, "observabilidade-lista.png"), fullPage: true })

  const itens = page.getByRole("button").filter({ hasText: "IA:" })
  const n = await itens.count()
  console.log(`[observabilidade] itens na lista: ${n}`)

  if (n > 0) {
    await itens.first().click()
    await expect(page.getByText("Avaliar resposta da IA")).toBeVisible()
    await page.waitForTimeout(300)
    await page.screenshot({ path: path.join(ART, "observabilidade-dialog.png"), fullPage: true })
    // seleciona "bom" so para ver o estado visual, depois CANCELA (nao salva).
    await page.getByRole("button", { name: /vendedor faria assim/i }).click()
    await page.waitForTimeout(200)
    await page.screenshot({ path: path.join(ART, "observabilidade-dialog-bom.png"), fullPage: true })
    await page.getByRole("button", { name: "Cancelar" }).click()
  }
})
