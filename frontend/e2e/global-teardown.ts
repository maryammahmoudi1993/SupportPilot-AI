/** Deletes every synthetic E2E record, unconditionally, regardless of test outcome. */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { DATA_FILE } from "./global-setup";

const BACKEND_ROOT = path.resolve(__dirname, "..", "..", "backend");
const PYTHON = path.join(BACKEND_ROOT, "venv", "Scripts", "python.exe");

const CLEANUP_SCRIPT = `
from accounts.models import User
from workspaces.models import Workspace
deleted_users = User.objects.filter(email__startswith="e2e-").delete()
deleted_workspaces = Workspace.objects.filter(name__startswith="E2E ").delete()
print("E2E cleanup:", deleted_users, deleted_workspaces)
`;

export default async function globalTeardown(): Promise<void> {
  execFileSync(PYTHON, ["manage.py", "shell", "-c", CLEANUP_SCRIPT], {
    cwd: BACKEND_ROOT,
    encoding: "utf-8",
  });
  try {
    fs.unlinkSync(DATA_FILE);
  } catch {
    // Already gone / never written — fine.
  }
}
