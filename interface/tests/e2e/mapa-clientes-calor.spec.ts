import { expect, test } from "@playwright/test"

// MAPA-7 — guarda de honestidade do toggle Calor.
// Critério de aceite: "abaixo do limiar N, o toggle Calor fica desabilitado
// com a explicação". O mock evita acoplar o teste ao volume real de pontos no
// banco — o limiar é 30; aqui simulamos 5 (claramente abaixo).

function pontoFake(i: number) {
  return {
    cliente_id: `c${i}`,
    nome: `Cliente ${i}`,
    latitude: -22.97 + i * 0.001,
    longitude: -43.18 + i * 0.001,
    bairro: `Bairro ${i}`,
    endereco_formatado: `Rua ${i}, 100 — Bairro, Cidade`,
    estado: "Fechado",
    perfis: [],
    total_atendimentos: 1,
    valor_total: 100,
    ultima_data: null,
    recorrente: false,
  }
}

function respostaMapa(qtd: number) {
  return {
    pontos: Array.from({ length: qtd }, (_, i) => pontoFake(i)),
    total_sem_localizacao: 0,
  }
}

test("camada Calor fica desabilitada com poucos pontos (<30)", async ({ page }) => {
  await page.route("**/v1/crm/clientes/mapa*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(respostaMapa(5)),
    })
  })

  await page.goto("/clientes")
  await page.getByRole("tab", { name: /^mapa$/i }).click()

  const camadaGroup = page.getByRole("radiogroup", { name: /camada do mapa/i })
  await expect(camadaGroup).toBeVisible({ timeout: 30_000 })

  const botaoCalor = camadaGroup.getByRole("radio", { name: /^calor$/i })
  await expect(botaoCalor).toBeVisible()
  await expect(botaoCalor).toHaveAttribute("aria-disabled", "true")
  await expect(botaoCalor).toHaveAttribute(
    "title",
    /poucos pontos para um calor confi[áa]vel/i,
  )

  // Hexbin segue habilitado — não regredimos o MAPA-6.
  const botaoHexbin = camadaGroup.getByRole("radio", { name: /^hexbin$/i })
  await expect(botaoHexbin).not.toHaveAttribute("aria-disabled", "true")

  // Bolhas continua selecionada (default) mesmo após "tentativa" de clique no Calor.
  const botaoBolhas = camadaGroup.getByRole("radio", { name: /^bolhas$/i })
  await expect(botaoBolhas).toHaveAttribute("aria-checked", "true")
})
