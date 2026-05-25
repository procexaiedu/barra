import { expect, test } from "@playwright/test"

// Verificação NÃO-MUTANTE: carrega a aba (dispara o GET pelo stack inteiro), confere o
// render e a interação local de "Adicionar regra". Não clica em Salvar — nada persiste.
test("aba Período de trabalho: GET 200 pelo stack + editor renderiza + adiciona regra local", async ({
  page,
}) => {
  await page.goto("/modelos")
  await expect(page).toHaveURL(/\/modelos/)
  const tab = page.getByRole("tab", { name: /período de trabalho/i })
  await expect(tab).toBeVisible({ timeout: 30_000 })

  // Clicar na aba dispara GET /v1/modelos/{id}/disponibilidade — confirma o backend ponta a ponta.
  const [resp] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes("/disponibilidade") && r.request().method() === "GET",
    ),
    tab.click(),
  ])
  expect(resp.status()).toBe(200)

  const secao = page
    .getByRole("heading", { level: 2, name: /^período de trabalho$/i })
    .locator("xpath=ancestor::section[1]")
  await expect(secao).toBeVisible({ timeout: 15_000 })

  // Adiciona uma regra local (sem salvar) e confirma que a linha surge (select de dia).
  await secao.getByRole("button", { name: /adicionar regra/i }).first().click()
  await expect(secao.getByRole("combobox", { name: /dia da semana/i }).first()).toBeVisible()
})
