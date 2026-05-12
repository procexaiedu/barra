import { expect, test } from "@playwright/test"

// Ignora storageState do project authed (este spec faz seu próprio login UI).
test.use({ storageState: { cookies: [], origins: [] } })

const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
)

const STAMP = Date.now()
const SUFIXO_NUMERO = String(STAMP).slice(-9)
const NOME_MODELO = `E2E Mídia ${STAMP}`
const NUMERO_WHATSAPP = `+5521${SUFIXO_NUMERO}`
const TAG = `e2e-${STAMP}`
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "https://zinrqzsxvpqfoogohrwg.supabase.co"
const SUPABASE_ANON = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "sb_publishable_Wnf-V2dnSmpEhx5QTXtxNw_SH6BT0M_"

test.describe("CRUD de mídia da modelo — fluxo real contra MinIO", () => {
  test.describe.configure({ mode: "serial" })

  let modeloId: string | null = null
  let jwt: string | null = null

  test.afterAll(async ({ request }) => {
    if (modeloId && jwt) {
      await request
        .patch(`${API_BASE}/v1/modelos/${modeloId}`, {
          headers: { authorization: `Bearer ${jwt}` },
          data: { status: "inativa" },
        })
        .catch(() => undefined)
    }
  })

  test("cria modelo sandbox via API, faz upload, toggle ativa/inativa, deleta permanente", async ({
    page,
    request,
  }) => {
    // JWT via Supabase REST direto (para chamar a API backend).
    const email = process.env.E2E_USER_EMAIL
    const password = process.env.E2E_USER_PASSWORD
    expect(email && password).toBeTruthy()
    const tokenResp = await request.post(`${SUPABASE_URL}/auth/v1/token?grant_type=password`, {
      headers: { apikey: SUPABASE_ANON, "content-type": "application/json" },
      data: { email, password },
    })
    expect(tokenResp.ok(), `login Supabase falhou: ${tokenResp.status()} ${await tokenResp.text()}`).toBeTruthy()
    jwt = (await tokenResp.json()).access_token
    expect(jwt).toBeTruthy()

    // Login via UI para o middleware/cookies do Next entenderem a sessão.
    test.setTimeout(180_000)
    await page.goto("/login", { waitUntil: "domcontentloaded" })
    await page.locator("#email").fill(email!)
    await page.locator("#password").fill(password!)
    await page.getByRole("button", { name: /acessar painel/i }).click()
    await page.waitForURL((url) => !/\/login$/.test(url.pathname), { timeout: 60_000 })

    // 1) Cria modelo sandbox via API real.
    const criar = await request.post(`${API_BASE}/v1/modelos`, {
      headers: { authorization: `Bearer ${jwt}`, "content-type": "application/json" },
      data: {
        nome: NOME_MODELO,
        idade: 25,
        numero_whatsapp: NUMERO_WHATSAPP,
        valor_padrao: 0,
        idiomas: ["pt-BR"],
        tipo_atendimento_aceito: ["interno"],
      },
    })
    expect(criar.ok(), `criação falhou: ${criar.status()} ${await criar.text()}`).toBeTruthy()
    const criado = await criar.json()
    modeloId = criado.id as string

    // 2) Abre direto o detalhe da modelo na aba mídia.
    await page.goto(`/modelos?modelo=${modeloId}&aba=midia`)
    await expect(page.getByRole("button", { name: /adicionar mídia|adicionar midia/i })).toBeVisible({
      timeout: 15_000,
    })

    // 3) Upload de foto.
    await page.getByRole("button", { name: /adicionar mídia|adicionar midia/i }).click()
    const upload = page.getByRole("dialog", { name: /adicionar mídia|adicionar midia/i })
    await expect(upload).toBeVisible()

    await upload.locator('input[type="file"]').setInputFiles({
      name: `${TAG}.png`,
      mimeType: "image/png",
      buffer: PNG_1X1,
    })
    await upload.getByLabel(/^tag$/i).fill(TAG)
    await upload.getByRole("button", { name: /^enviar$/i }).click()
    await expect(upload).toBeHidden({ timeout: 30_000 })

    // 4) Item aparece no grid.
    const grid = page.getByRole("region", { name: /mídia da modelo|midia da modelo/i })
    const item = grid.getByRole("article").filter({ hasText: TAG }).first()
    await expect(item).toBeVisible({ timeout: 15_000 })
    await expect(item.locator("img")).toBeVisible()

    // 5) Toggle: inativa.
    await item.getByRole("button", { name: /^inativar$/i }).click()
    await expect(item.getByText(/^Inativa$/i)).toBeVisible({ timeout: 10_000 })

    // 6) Filtro "Inativas" mostra o item.
    const selectStatus = page.getByLabel(/^status$/i)
    await selectStatus.selectOption({ label: "Inativas" })
    await expect(grid.getByRole("article").filter({ hasText: TAG })).toHaveCount(1)

    // 7) Toggle: ativa de volta.
    await item.getByRole("button", { name: /^ativar$/i }).click()
    await selectStatus.selectOption({ label: "Ativas" })
    await expect(grid.getByRole("article").filter({ hasText: TAG })).toHaveCount(1)
    await expect(item.getByText(/^Inativa$/i)).toBeHidden()

    // 8) Capturar object_key da mídia antes do delete, para validar no MinIO.
    const listResp = await request.get(`${API_BASE}/v1/modelos/${modeloId}/midia`, {
      headers: { authorization: `Bearer ${jwt}` },
    })
    expect(listResp.ok()).toBeTruthy()
    const lista = await listResp.json()
    const midia = (lista as Array<{ object_key: string; tag: string }>).find((m) => m.tag === TAG)
    expect(midia).toBeTruthy()
    const objectKey = midia!.object_key
    console.log(`[E2E] object_key = ${objectKey}`)

    // 9) Delete permanente.
    await item.getByRole("button", { name: /^remover$/i }).click()
    const confirm = page.getByRole("alertdialog")
    await expect(confirm.getByText(/remover esta mídia\??/i)).toBeVisible()
    await confirm.getByRole("button", { name: /^remover$/i }).click()
    await expect(confirm).toBeHidden({ timeout: 10_000 })

    await selectStatus.selectOption({ label: "Todas" })
    await expect(grid.getByRole("article").filter({ hasText: TAG })).toHaveCount(0, {
      timeout: 10_000,
    })

    // 10) Confirma que GET retorna lista sem o item.
    const apos = await request.get(`${API_BASE}/v1/modelos/${modeloId}/midia`, {
      headers: { authorization: `Bearer ${jwt}` },
    })
    const apósLista = (await apos.json()) as Array<{ tag: string }>
    expect(apósLista.find((m) => m.tag === TAG)).toBeUndefined()

    // Marca o object_key no contexto do worker para o smoke check externo.
    test.info().annotations.push({ type: "minio.object_key.deleted", description: objectKey })
  })
})
