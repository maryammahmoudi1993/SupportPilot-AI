#!/usr/bin/env node
/**
 * Regenerates frontend/src/types/api.ts from the backend's live OpenAPI
 * schema (drf-spectacular). This is the single source of truth for the
 * frontend/backend API contract — never hand-edit the generated output.
 *
 * Run whenever the backend's API surface changes, and commit the
 * regenerated frontend/openapi.yaml + frontend/src/types/api.ts together
 * with the frontend change that needed them.
 *
 * Requires a backend virtualenv at backend/venv (see the repository root
 * README's Quick Start). No network calls and no running server are
 * required — the schema is built by importing the Django app config.
 *
 * See scripts/check-api-types.mjs for the non-destructive drift check.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";

import { generateSchemaAndTypes, resolveRoots } from "./lib/generate-schema.mjs";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const { frontendRoot, backendRoot } = resolveRoots(path.join(scriptsDir, "lib"));
const schemaPath = path.join(frontendRoot, "openapi.yaml");
const typesPath = path.join(frontendRoot, "src", "types", "api.ts");

try {
  console.log("[1/2] Generating OpenAPI schema from backend (drf-spectacular)...");
  console.log("[2/2] Generating TypeScript types (openapi-typescript)...");
  await generateSchemaAndTypes({
    backendRoot,
    schemaOutPath: schemaPath,
    typesOutPath: typesPath,
    cwd: frontendRoot,
  });
  console.log(`\nDone. Regenerated:\n  ${schemaPath}\n  ${typesPath}`);
} catch (err) {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
}
