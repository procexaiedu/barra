import { expect, test, type Page } from "@playwright/test"

const STAMP = Date.now()
const PROGRAMA_NOVO = `E2E Serviço ${STAMP}`
const DURACAO_NOVA = `E2E ${STAMP % 100000} min`
const PRECO_1 = "800"
const MINIMO_1 = "600"
const PRECO_EDITADO = "950"
const FETICHE_NOVO = `E2E Fetiche ${STAMP}`
const PRECO_FETICHE = "350"

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

    // Preço e mínimo (ADR-0037): a linha nasce com piso = 600 sobre um preço de 800.
    await blocoServicoNovo.getByLabel(new RegExp(`^Preço de tabela — ${DURACAO_NOVA}$`)).fill(PRECO_1)
    await blocoServicoNovo.getByLabel(new RegExp(`^Preço mínimo — ${DURACAO_NOVA}$`)).fill(MINIMO_1)

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

  // O piso vai gravado no POST, mas a LISTAGEM do backend (`_programas()` em
  // api/dominio/modelos/routes.py) ainda não serializa `preco_minimo` — sem ele a pílula não tem
  // o que desenhar. Reativar assim que o campo entrar no GET.
  test.fixme("mostra o mínimo cadastrado na linha", async ({ page }) => {
    await abrirPrimeiraModelo(page)
    const cardServicos = page
      .getByRole("heading", { level: 2, name: "Serviços e preços" })
      .locator("xpath=ancestor::section[1]")
    const linhaNova = cardServicos.locator("li").filter({ hasText: DURACAO_NOVA }).first()
    await expect(linhaNova).toContainText(/mín\./)
    await expect(linhaNova).toContainText(/600/)
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
    // Reajuste que NÃO toca no mínimo: o campo fica como veio e o PATCH sai sem `preco_minimo`,
    // preservando o piso cadastrado (ADR-0037).
    const inputEdit = linhaNova.getByLabel("Preço de tabela")
    await expect(linhaNova.getByLabel(/^Preço mínimo/)).toBeVisible()
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

// O cadastro do fetiche digita o PREÇO do extra (ADR-0030, revisão de 11/08/2026): campo vazio =
// incluso, campo com valor = o extra cobrado, fixo.
test.describe("fetiches — preço do extra", () => {
  test("cria fetiche incluso, digita o preço do extra e mantém o valor após recarregar", async ({ page }) => {
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

    // Criado sem preço = incluso.
    await expect(linhaFetiche.getByText("incluso")).toBeVisible()

    await linhaFetiche.getByRole("button", { name: /editar preço do fetiche/i }).click()
    await linhaFetiche.locator('input[type="number"]').fill(PRECO_FETICHE)
    await linhaFetiche.getByRole("button", { name: /salvar preço/i }).click()
    await expect(linhaFetiche.getByText(/350,00/)).toBeVisible({ timeout: 10_000 })

    await page.reload()
    const linhaFeticheDepois = cardServicos.locator("li").filter({ hasText: FETICHE_NOVO }).first()
    await expect(linhaFeticheDepois.getByText(/350,00/)).toBeVisible({ timeout: 10_000 })

    await linhaFeticheDepois.getByRole("button", { name: /remover fetiche/i }).click()
    await expect(cardServicos.locator("li").filter({ hasText: FETICHE_NOVO })).toHaveCount(0, { timeout: 10_000 })
  })
})
