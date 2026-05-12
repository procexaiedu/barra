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
