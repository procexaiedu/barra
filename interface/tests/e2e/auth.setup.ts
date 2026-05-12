import { expect, test as setup } from "@playwright/test"
import path from "node:path"

export const STORAGE_STATE = path.resolve(__dirname, ".auth/state.json")

setup("autentica e salva sessão", async ({ page }) => {
  const email = process.env.E2E_USER_EMAIL
  const password = process.env.E2E_USER_PASSWORD
  if (!email || !password) {
    throw new Error("Defina E2E_USER_EMAIL e E2E_USER_PASSWORD para rodar os testes autenticados.")
  }

  await page.goto("/login")
  await page.locator("#email").fill(email)
  await page.locator("#password").fill(password)
  await page.getByRole("button", { name: /acessar painel/i }).click()

  await page.waitForURL((url) => !/\/login$/.test(url.pathname), { timeout: 30_000 })
  await expect(page).not.toHaveURL(/\/login$/)

  await page.context().storageState({ path: STORAGE_STATE })
})
