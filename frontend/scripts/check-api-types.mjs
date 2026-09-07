#!/usr/bin/env node
/**
 * Fails (non-zero exit) if frontend/openapi.yaml or frontend/src/types/api.ts
 * are stale relative to the backend's current OpenAPI schema — i.e. the
 * backend's API surface changed and `npm run generate:api-types` was never
 * re-run and committed.
 *
 * Regenerates into a throwaway temp directory and diffs against the
 * committed files. Never writes to the real, tracked files — a developer's
 * working tree is untouched by running the check.
 *
 * Requires a backend virtualenv at backend/venv (see the repository root
 * README's Quick Start).
 */
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { generateSchemaAndTypes, resolveRoots } from "./lib/generate-schema.mjs";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const { frontendRoot, backendRoot } = resolveRoots(path.join(scriptsDir, "lib"));

const committedSchemaPath = path.join(frontendRoot, "openapi.yaml");
const committedTypesPath = path.join(frontendRoot, "src", "types", "api.ts");

const tmpDir = mkdtempSync(path.join(os.tmpdir(), "sp-api-types-check-"));
const freshSchemaPath = path.join(tmpDir, "openapi.yaml");
const freshTypesPath = path.join(tmpDir, "api.ts");

function readOrExit(filePath, label) {
  try {
    return readFileSync(filePath, "utf-8");
  } catch {
    console.error(`Expected ${label} at ${filePath} — has it ever been generated/committed?`);
    process.exit(1);
  }
}

try {
  await generateSchemaAndTypes({
    backendRoot,
    schemaOutPath: freshSchemaPath,
    typesOutPath: freshTypesPath,
    cwd: frontendRoot,
  });

  const committedSchema = readOrExit(committedSchemaPath, "the committed OpenAPI schema");
  const committedTypes = readOrExit(committedTypesPath, "the committed generated types");
  const freshSchema = readFileSync(freshSchemaPath, "utf-8");
  const freshTypes = readFileSync(freshTypesPath, "utf-8");

  const schemaDrifted = committedSchema !== freshSchema;
  const typesDrifted = committedTypes !== freshTypes;

  if (schemaDrifted || typesDrifted) {
    console.error(
      "API contract drift detected — the backend's OpenAPI schema has changed" +
        " since these files were last regenerated:",
    );
    if (schemaDrifted)
      console.error(`  stale: ${path.relative(frontendRoot, committedSchemaPath)}`);
    if (typesDrifted) console.error(`  stale: ${path.relative(frontendRoot, committedTypesPath)}`);
    console.error("\nRun `npm run generate:api-types` and commit the result.");
    process.exit(1);
  }

  console.log("API contract is up to date with the backend's OpenAPI schema.");
} catch (err) {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
} finally {
  rmSync(tmpDir, { recursive: true, force: true });
}
