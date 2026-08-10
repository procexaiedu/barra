import { expect, test } from "@playwright/test"

test("login page renders", async ({ page }) => {
  await page.goto("/login")
  await expect(page).toHaveURL(/\/login/)
  await expect(page.locator("body")).toBeVisible()
})

test.describe("rotas autenticadas (sem login)", () => {
  test("/modelos redireciona para /login", async ({ page }) => {
    await page.goto("/modelos")
    await page.waitForURL(/\/login/, { timeout: 10_000 })
    await expect(page).toHaveURL(/\/login/)
  })
})

// Regressão da auditoria de segurança: estas rotas eram fixtures TEMP com bypass
// explícito no middleware e ficaram públicas em produção (uma delas renderizava o
// chrome completo do painel). Foram removidas; o middleware não deve ter exceção
// para nenhuma delas. Reintroduzir o bypass faz este teste falhar.
test.describe("fixtures TEMP removidas não são públicas", () => {
  for (const rota of ["/demo-mapa", "/painel-preview", "/verificacao", "/verificacao/funil"]) {
    test(`${rota} redireciona para /login`, async ({ page }) => {
      await page.goto(rota)
      await page.waitForURL(/\/login/, { timeout: 10_000 })
      await expect(page).toHaveURL(/\/login/)
    })
  }
})
