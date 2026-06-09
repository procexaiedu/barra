#!/usr/bin/env node
// Driver agent-native do painel Next.js (interface/).
//
// Lança o Chromium do Playwright (já dependência do projeto via @playwright/test),
// navega a uma rota, opcionalmente lê o contrato `data-verificacao` publicado no
// DOM (mesmo contrato que `pnpm verify` valida) e salva um screenshot em disco.
//
// Uso (a partir de interface/, com `pnpm dev` já rodando em :3000):
//   node .claude/skills/run-interface/driver.mjs <rota> [--out arquivo.png] [--contract <selector>] [--full]
//
// Exemplos:
//   node .claude/skills/run-interface/driver.mjs /verificacao --out /tmp/barra-run/verificacao.png
//   node .claude/skills/run-interface/driver.mjs /demo-mapa --out /tmp/barra-run/mapa.png --full
//   node .claude/skills/run-interface/driver.mjs /verificacao/funil --contract '[data-verificacao]'
//
// Rotas públicas (sem auth, liberadas no proxy.ts/middleware):
//   /verificacao  /verificacao/funil  /verificacao/kanban  /demo-mapa  /painel-preview
//
// Variáveis: BASE_URL (default http://localhost:3000).

import { chromium } from "@playwright/test"

const BASE = process.env.BASE_URL ?? "http://localhost:3000"

const args = process.argv.slice(2)
const rota = args.find((a) => !a.startsWith("--")) ?? "/verificacao"
const out = valorDe("--out") ?? `/tmp/barra-run/${rota.replace(/\W+/g, "_").replace(/^_|_$/g, "")}.png`
const contrato = valorDe("--contract")
const full = args.includes("--full")

function valorDe(flag) {
  const i = args.indexOf(flag)
  return i >= 0 ? args[i + 1] : undefined
}

const url = BASE + rota
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

const erros = []
page.on("console", (m) => m.type() === "error" && erros.push(m.text()))
page.on("pageerror", (e) => erros.push(String(e)))

let status = "?"
try {
  const resp = await page.goto(url, { waitUntil: "networkidle", timeout: 30_000 })
  status = resp ? resp.status() : "no-response"
} catch (e) {
  console.error(`✗ navegação falhou: ${e.message}`)
  await browser.close()
  process.exit(1)
}

await page.screenshot({ path: out, fullPage: full })

let contratoOut = null
if (contrato) {
  const el = page.locator(contrato).first()
  const raw = (await el.count()) ? await el.getAttribute("data-verificacao") : null
  contratoOut = raw ? JSON.parse(raw) : "(contrato ausente)"
}

await browser.close()

console.log(
  JSON.stringify(
    {
      url,
      http: status,
      screenshot: out,
      console_errors: erros.slice(0, 10),
      contrato: contratoOut,
    },
    null,
    2,
  ),
)
process.exit(0)
