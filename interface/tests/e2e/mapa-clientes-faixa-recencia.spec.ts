import { expect, test } from "@playwright/test"

// MAPA-11 — faixa de R$ + recência (ortogonais ao MAPA-8 e à lente MAPA-9).
// Cobertura: o controle vira input e a UI dispara um fetch novo com o filtro
// correto na querystring (assert via `waitForRequest`). Mock determinístico do
// endpoint para não acoplar ao volume real do banco — mesmo padrão do
// `mapa-clientes-calor.spec.ts`.

function diasAtras(dias: number): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() - dias)
  return d.toISOString()
}

const PONTOS = [
  {
    cliente_id: "c-baixo",
    nome: "Cliente baixo",
    latitude: -22.97,
    longitude: -43.18,
    bairro: "Copacabana",
    endereco_formatado: "Av. Atlântica, 100",
    estado: "Fechado",
    perfis: [],
    total_atendimentos: 1,
    valor_total: 10,
    ultima_data: diasAtras(0),
    recorrente: false,
  },
  {
    cliente_id: "c-meio",
    nome: "Cliente meio",
    latitude: -22.98,
    longitude: -43.19,
    bairro: "Ipanema",
    endereco_formatado: "R. Visconde, 200",
    estado: "Fechado",
    perfis: [],
    total_atendimentos: 1,
    valor_total: 500,
    ultima_data: diasAtras(30),
    recorrente: false,
  },
  {
    cliente_id: "c-alto",
    nome: "Cliente alto",
    latitude: -22.99,
    longitude: -43.2,
    bairro: "Leblon",
    endereco_formatado: "R. Dias Ferreira, 300",
    estado: "Fechado",
    perfis: [],
    total_atendimentos: 1,
    valor_total: 5000,
    ultima_data: diasAtras(180),
    recorrente: false,
  },
]

test.describe("Mapa de clientes — MAPA-11 (faixa de R$ + recência)", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/v1/crm/clientes/mapa*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ pontos: PONTOS, total_sem_localizacao: 0 }),
      })
    })
  })

  test("Ativos dispara fetch com recencia=ativos", async ({ page }) => {
    await page.goto("/clientes")
    await page.getByRole("tab", { name: /^mapa$/i }).click()

    // Recência agora vive dentro do PopoverFiltrosMapa — abre antes.
    await page.getByRole("button", { name: /abrir filtros do mapa/i }).click()
    const grupo = page.getByRole("radiogroup", { name: /filtro por recência/i })
    await expect(grupo).toBeVisible({ timeout: 30_000 })

    const req = page.waitForRequest((r) =>
      r.url().includes("/v1/crm/clientes/mapa") && r.url().includes("recencia=ativos"),
    )
    await grupo.getByRole("radio", { name: /ativos/i }).click()
    await req
  })

  test("Dormentes dispara fetch com recencia=dormentes", async ({ page }) => {
    await page.goto("/clientes")
    await page.getByRole("tab", { name: /^mapa$/i }).click()

    await page.getByRole("button", { name: /abrir filtros do mapa/i }).click()
    const grupo = page.getByRole("radiogroup", { name: /filtro por recência/i })
    await expect(grupo).toBeVisible({ timeout: 30_000 })

    const req = page.waitForRequest((r) =>
      r.url().includes("/v1/crm/clientes/mapa") && r.url().includes("recencia=dormentes"),
    )
    await grupo.getByRole("radio", { name: /dormentes/i }).click()
    await req
  })

  test("Faixa de R$ dispara fetch com valor_min e valor_max", async ({ page }) => {
    await page.goto("/clientes")
    await page.getByRole("tab", { name: /^mapa$/i }).click()

    // Faixa de R$ agora vive dentro do PopoverFiltrosMapa — abre antes.
    await page.getByRole("button", { name: /abrir filtros do mapa/i }).click()
    const trigger = page.getByRole("button", { name: /filtrar por faixa de r\$/i })
    await expect(trigger).toBeVisible({ timeout: 30_000 })
    await trigger.click()

    const min = page.locator('input[type="number"]').first()
    const max = page.locator('input[type="number"]').nth(1)

    const reqMin = page.waitForRequest((r) =>
      r.url().includes("/v1/crm/clientes/mapa") && r.url().includes("valor_min=100"),
    )
    await min.fill("100")
    await reqMin

    const reqMax = page.waitForRequest((r) =>
      r.url().includes("/v1/crm/clientes/mapa") &&
      r.url().includes("valor_min=100") &&
      r.url().includes("valor_max=1000"),
    )
    await max.fill("1000")
    await reqMax
  })
})
