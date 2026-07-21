import { expect, test, type Page } from "@playwright/test"

const STAMP = Date.now()
const PROGRAMA_NOVO = `E2E Serviço ${STAMP}`
const DURACAO_NOVA = `E2E ${STAMP % 100000} min`
const PRECO_1 = "800"
const PRECO_EDITADO = "950"
const FETICHE_NOVO = `E2E Fetiche ${STAMP}`

async function abrirPrimeiraModelo(page: Page): Promise<void> {
  await page.goto("/modelos")
  await expect(page).toHaveURL(/\/modelos/)
  await expect(page.getByRole("heading", { level: 2, name: "Serviços e preços" }).locator("xpath=ancestor::section[1]")).toBeVisible({ timeout: 30_000 })
}

test.describe("card de serviços e modal — fluxo inline + edição + remoção", () => {
  test.describe.configure({ mode: "serial" })

  test("cria serviço e duração inline pelo modal e adiciona vínculo", async ({ page }) => {
    await abrirPrimeiraModelo(page)
    const cardServicos = page
      .getByRole("heading", { level: 2, name: "Serviços e preços" })
      .locator("xpath=ancestor::section[1]")

    await cardServicos.getByRole("button", { name: /adicionar serviço/i }).click()
    const modal = page.getByRole("dialog", { name: /adicionar serviço/i })
    await expect(modal).toBeVisible()

    // Criar serviço inline
    await modal.getByRole("button", { name: /novo serviço/i }).click()
    const inputNovoServico = modal.getByPlaceholder(/beijo grego/i)
    await inputNovoServico.fill(PROGRAMA_NOVO)
    await modal.getByRole("button", { name: /^criar$/i }).first().click()
    await expect(inputNovoServico).toBeHidden({ timeout: 10_000 })

    // Bloco do serviço recém-criado aparece, já selecionado
    const blocoServicoNovo = modal.locator("div", {
      has: page.locator(`h4:has-text("${PROGRAMA_NOVO}")`),
    }).first()
    await expect(blocoServicoNovo).toBeVisible()

    // Criar duração inline dentro desse bloco
    await blocoServicoNovo.getByRole("button", { name: /nova duração/i }).click()
    const inputDuracao = modal.getByPlaceholder(/45 min/i)
    await inputDuracao.fill(DURACAO_NOVA)
    await modal.getByRole("button", { name: /^criar$/i }).first().click()
    await expect(inputDuracao).toBeHidden({ timeout: 10_000 })

    const chipDuracaoNova = blocoServicoNovo.getByRole("button", { name: new RegExp(DURACAO_NOVA, "i") })
    await expect(chipDuracaoNova).toHaveAttribute("aria-pressed", "true")

    // Preço
    const precoInput = blocoServicoNovo.locator('input[type="number"]').first()
    await precoInput.fill(PRECO_1)

    // Salva
    await modal.getByRole("button", { name: /^adicionar/i }).click()
    await expect(modal).toBeHidden({ timeout: 15_000 })

    // Linha aparece no card de serviços
    const grupoNovo = cardServicos.locator("div", {
      has: page.locator(`h3:has-text("${PROGRAMA_NOVO}")`),
    }).first()
    await expect(grupoNovo).toBeVisible({ timeout: 10_000 })
    await expect(grupoNovo.getByText(DURACAO_NOVA).first()).toBeVisible()
  })

  test("edita preço e remove o vínculo", async ({ page }) => {
    await abrirPrimeiraModelo(page)
    const cardServicos = page
      .getByRole("heading", { level: 2, name: "Serviços e preços" })
      .locator("xpath=ancestor::section[1]")

    const grupoNovo = cardServicos.locator("div", {
      has: page.locator(`h3:has-text("${PROGRAMA_NOVO}")`),
    }).first()
    const linhaNova = grupoNovo.locator("li").filter({ hasText: DURACAO_NOVA }).first()
    await expect(linhaNova).toBeVisible({ timeout: 10_000 })

    await linhaNova.getByRole("button", { name: /editar preço/i }).click()
    const inputEdit = linhaNova.locator('input[type="number"]')
    await inputEdit.fill(PRECO_EDITADO)
    await linhaNova.getByRole("button", { name: /salvar preço/i }).click()
    await expect(inputEdit).toBeHidden({ timeout: 10_000 })
    await expect(linhaNova).toContainText(/9[\s,.]?50/)

    await linhaNova.getByRole("button", { name: /remover serviço/i }).click()
    await expect(
      cardServicos.locator("li").filter({ hasText: DURACAO_NOVA }),
    ).toHaveCount(0, { timeout: 10_000 })
  })

  test("aba Programas global mostra serviço e duração criados inline", async ({ page }) => {
    await page.goto("/modelos")
    await page.getByRole("tab", { name: /^programas$/i }).click()

    const secProgramas = page.locator("section", { hasText: /^Programas/ }).first()
    const secDuracoes = page.locator("section", { hasText: /^Durações/ }).first()
    await expect(secProgramas.getByText(PROGRAMA_NOVO)).toBeVisible({ timeout: 10_000 })
    await expect(secDuracoes.getByText(DURACAO_NOVA)).toBeVisible({ timeout: 10_000 })
  })
})

// Fetiches viram toggle incluso/pago no cadastro (ADR-0030, ticket 02) — sem campo de valor.
test.describe("fetiches — toggle incluso/pago", () => {
  test("cria fetiche, marca como pago pelo toggle e mantém o estado após recarregar", async ({ page }) => {
    await abrirPrimeiraModelo(page)
    const cardServicos = page
      .getByRole("heading", { level: 2, name: "Serviços e preços" })
      .locator("xpath=ancestor::section[1]")
    const blocoFetiches = cardServicos
      .locator("div", { has: page.getByRole("heading", { level: 3, name: "Fetiches" }) })
      .first()

    await blocoFetiches.getByRole("button", { name: /criar novo fetiche no catálogo/i }).click()
    const inputNovoFetiche = blocoFetiches.getByPlaceholder(/nome do novo fetiche/i)
    await inputNovoFetiche.fill(FETICHE_NOVO)
    await blocoFetiches.getByRole("button", { name: /criar e marcar/i }).click()
    await expect(inputNovoFetiche).toBeHidden({ timeout: 10_000 })

    const linhaFetiche = blocoFetiches.locator("li").filter({ hasText: FETICHE_NOVO }).first()
    await expect(linhaFetiche).toBeVisible({ timeout: 10_000 })

    // Não há campo numérico de preço — só o toggle.
    await expect(linhaFetiche.locator('input[type="number"]')).toHaveCount(0)

    const toggle = linhaFetiche.getByRole("switch")
    await expect(toggle).toHaveAttribute("aria-checked", "false")
    await expect(linhaFetiche.getByText("Incluso")).toBeVisible()

    await toggle.click()
    await expect(toggle).toHaveAttribute("aria-checked", "true")
    await expect(linhaFetiche.getByText("Pago")).toBeVisible()

    await page.reload()
    const linhaFeticheDepois = cardServicos.locator("li").filter({ hasText: FETICHE_NOVO }).first()
    await expect(linhaFeticheDepois.getByRole("switch")).toHaveAttribute("aria-checked", "true", { timeout: 10_000 })

    await linhaFeticheDepois.getByRole("button", { name: /remover fetiche/i }).click()
    await expect(cardServicos.locator("li").filter({ hasText: FETICHE_NOVO })).toHaveCount(0, { timeout: 10_000 })
  })
})
