import { defineConfig, devices } from "@playwright/test"
import path from "node:path"
import "dotenv/config"

const PORT = process.env.E2E_PORT ?? "3000"
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${PORT}`
const STORAGE_STATE = path.resolve(__dirname, "tests/e2e/.auth/state.json")

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"]],
  timeout: 60_000,
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "smoke",
      testMatch: /smoke\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "setup",
      testMatch: /auth\.setup\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      // Verificação agent-native: rotas /verificacao são públicas, sem storageState.
      name: "verificacao",
      testMatch: /verificacao\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "authed",
      testIgnore: [/smoke\.spec\.ts/, /auth\.setup\.ts/, /verificacao\.spec\.ts/],
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        storageState: STORAGE_STATE,
      },
    },
  ],
  webServer: process.env.E2E_NO_SERVER
    ? undefined
    : {
        command: "pnpm dev",
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
      },
})
