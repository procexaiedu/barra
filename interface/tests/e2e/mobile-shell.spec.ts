import { expect, test } from "@playwright/test"

// Verificação NÃO-MUTANTE do shell responsivo: confere a navegação mobile
// (bottom nav + drawer) em viewport de celular e a sidebar em desktop. Não
// depende dos dados da página — só do layout (interface)/layout.tsx.

const MOBILE = { width: 375, height: 812 }
const DESKTOP = { width: 1280, height: 800 }

test("mobile (375px): bottom nav visível, sidebar oculta, drawer abre", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE)
  await page.goto("/")
  await expect(page).not.toHaveURL(/\/login$/)

  // Sem o antigo bloqueio de mobile.
  await expect(
    page.getByText(/disponível apenas em desktop/i)
  ).toHaveCount(0)

  const bottomNav = page.getByRole("navigation", {
    name: /navegação principal \(mobile\)/i,
  })
  await expect(bottomNav).toBeVisible()

  // Os 4 destinos principais + botão "Mais".
  await expect(bottomNav.getByRole("link", { name: "Painel" })).toBeVisible()
  await expect(bottomNav.getByRole("link", { name: "Atendimentos" })).toBeVisible()
  await expect(bottomNav.getByRole("link", { name: "Agenda" })).toBeVisible()
  await expect(bottomNav.getByRole("link", { name: "Pix" })).toBeVisible()
  const maisBtn = bottomNav.getByRole("button", { name: /mais opções/i })
  await expect(maisBtn).toBeVisible()

  // Sidebar de desktop não aparece em mobile.
  await expect(
    page.getByRole("navigation", { name: /^navegação principal$/i })
  ).toBeHidden()

  // Abrir o drawer revela os destinos secundários.
  await maisBtn.click()
  const drawer = page.getByRole("dialog")
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole("link", { name: "Clientes" })).toBeVisible()
  await expect(drawer.getByRole("link", { name: "Financeiro" })).toBeVisible()
  await expect(drawer.getByRole("button", { name: /sair/i })).toBeVisible()
})

const ROTAS = [
  "/",
  "/atendimentos",
  "/agenda",
  "/pix",
  "/tarefas",
  "/clientes",
  "/modelos",
  "/dashboard",
  "/financeiro",
  "/calibracao",
]

for (const rota of ROTAS) {
  test(`mobile (375px): ${rota} sem overflow horizontal`, async ({ page }) => {
    await page.setViewportSize(MOBILE)
    await page.goto(rota)
    await expect(page).not.toHaveURL(/\/login$/)
    // Deixa o layout assentar (skeletons, fontes, resolução do useIsMobile).
    await page.waitForTimeout(800)
    const overflow = await page.evaluate(() => {
      const el = document.documentElement
      return el.scrollWidth - el.clientWidth
    })
    // Tolerância de 1px para arredondamento sub-pixel.
    expect(overflow, `${rota} tem scroll horizontal de ${overflow}px`).toBeLessThanOrEqual(1)
  })
}

test("desktop (1280px): sidebar visível, bottom nav oculta", async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto("/")
  await expect(page).not.toHaveURL(/\/login$/)

  await expect(
    page.getByRole("navigation", { name: /^navegação principal$/i })
  ).toBeVisible()
  await expect(
    page.getByRole("navigation", { name: /navegação principal \(mobile\)/i })
  ).toBeHidden()
})
