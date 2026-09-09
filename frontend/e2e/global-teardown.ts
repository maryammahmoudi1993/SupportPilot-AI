/** Deletes every synthetic E2E record, unconditionally, regardless of test outcome. */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { DATA_FILE } from "./global-setup";

const BACKEND_ROOT = path.resolve(__dirname, "..", "..", "backend");
const PYTHON = path.join(BACKEND_ROOT, "venv", "Scripts", "python.exe");

const CLEANUP_SCRIPT = `
from accounts.models import User
from agents.models import AgentRun
from workspaces.models import Workspace
# AgentRun.agent_version is on_delete=PROTECT (agents/models.py) — Django's
# cascade collector does not resolve that against an AgentVersion cascading
# to deletion in the SAME Workspace.delete() call, so a real AgentRun row
# left in place raises ProtectedError before the workspace delete completes.
# Delete AgentRuns (and their AgentSteps, which cascade from the run) for
# every E2E workspace first, then the workspace cascade can proceed.
deleted_runs = AgentRun.objects.filter(workspace__name__startswith="E2E ").delete()
deleted_users = User.objects.filter(email__startswith="e2e-").delete()
deleted_workspaces = Workspace.objects.filter(name__startswith="E2E ").delete()
print("E2E cleanup:", deleted_runs, deleted_users, deleted_workspaces)
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
