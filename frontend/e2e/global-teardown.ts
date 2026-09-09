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
from tools.models import ToolExecution
from workspaces.models import Workspace
# AgentRun.agent_version and ToolExecution.tool_binding/tool_definition/
# agent_version are all on_delete=PROTECT (agents/models.py, tools/models.py)
# — Django's cascade collector does not resolve a PROTECT FK against a
# referenced row (AgentVersion, ToolBinding) cascading to deletion in the
# SAME Workspace.delete() call, so a real ToolExecution/AgentRun row left in
# place raises ProtectedError before the workspace delete completes. Delete
# ToolExecutions first (they PROTECT ToolBinding, which itself would
# otherwise cascade-delete from AgentVersion), then AgentRuns (and their
# AgentSteps, which cascade from the run), then the workspace cascade can
# proceed. ToolDefinition rows are global/code-owned (no workspace FK) and
# are never deleted here — sync_tool_definitions() is safely re-run/no-op on
# the next E2E setup.
deleted_tool_executions = ToolExecution.objects.filter(workspace__name__startswith="E2E ").delete()
deleted_runs = AgentRun.objects.filter(workspace__name__startswith="E2E ").delete()
deleted_users = User.objects.filter(email__startswith="e2e-").delete()
deleted_workspaces = Workspace.objects.filter(name__startswith="E2E ").delete()
print("E2E cleanup:", deleted_tool_executions, deleted_runs, deleted_users, deleted_workspaces)
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
