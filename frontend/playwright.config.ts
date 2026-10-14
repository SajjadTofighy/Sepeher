import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:8000";
export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  workers: 1,
  timeout: 45000,
  use: {
    baseURL,
    headless: true,
    viewport: { width: 1440, height: 1000 },
    ...(process.env.PLAYWRIGHT_CHANNEL
      ? { channel: process.env.PLAYWRIGHT_CHANNEL }
      : {}),
    launchOptions: { args: ["--enable-unsafe-swiftshader"] },
  },
  webServer:
    !process.env.PLAYWRIGHT_BASE_URL && existsSync("../run_local.py")
      ? {
          command: "python3 ../run_local.py --no-install",
          url: "http://127.0.0.1:8000/api/v1/health",
          reuseExistingServer: true,
        }
      : undefined,
  reporter: "list",
});
