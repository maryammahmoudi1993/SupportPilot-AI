import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/tests/setup.ts"],
    globals: false,
    css: true,
    // Vitest injects `env` into process.env before any module (including
    // setupFiles) is evaluated — required here because setup.ts itself
    // transitively imports modules that read NEXT_PUBLIC_API_BASE_URL at
    // import time (src/lib/config.ts's fail-fast validation), and ESM
    // hoists imports ahead of any in-file assignment that would otherwise
    // set a fallback too late.
    env: {
      NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000",
    },
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/types/**", "src/app/**/*.tsx", "src/tests/**"],
    },
  },
});
