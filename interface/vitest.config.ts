import { defineConfig } from "vitest/config"

// Vitest minimal — só funções puras de src/lib/. Sem jsdom/RTL aqui: testes de
// componente vivem no Playwright (interface/tests/e2e/). Adicionar jsdom só
// quando houver razão real (§2 do CLAUDE.md).
export default defineConfig({
  resolve: {
    tsconfigPaths: true,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    exclude: ["tests/e2e/**", "node_modules/**", ".next/**"],
  },
})
