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
from approvals.models import ApprovalRequest
from knowledge.models import KnowledgeDocument, KnowledgeSource
from tickets.models import HumanHandoff
from tools.models import ToolExecution
from workspaces.models import Workspace
# AgentRun.agent_version and ToolExecution.tool_binding/tool_definition/
# agent_version are all on_delete=PROTECT (agents/models.py, tools/models.py).
# ApprovalRequest.risk_assessment is also on_delete=PROTECT (approvals/models.py)
# against policies.RiskAssessment, which itself CASCADEs from ToolExecution —
# so a real ApprovalRequest row left in place blocks its own ToolExecution's
# deletion one level deeper than the Chunk 1/2 issue. Django's cascade
# collector does not resolve a PROTECT FK against a row that would also be
# deleted in the SAME Workspace.delete() call, so the deletion order below
# is deliberate: ApprovalRequest (and its cascaded ApprovalDecision) first,
# then ToolExecution (which cascades its RiskAssessment/PolicyEvaluation now
# that nothing PROTECTs them), then AgentRun (and its AgentSteps), then the
# workspace cascade can proceed. HumanHandoff has no PROTECT relations
# (workspace CASCADE, agent_run/ticket SET_NULL) so it needs no special
# ordering, but is deleted explicitly here for a clean, auditable log line.
# ToolDefinition rows are global/code-owned (no workspace FK) and are never
# deleted here — sync_tool_definitions() is safely re-run/no-op on the next
# E2E setup. KnowledgeDocument.source is on_delete=PROTECT, but both
# KnowledgeSource and KnowledgeDocument also carry their own direct
# workspace CASCADE, and are deleted explicitly here (before the workspace
# cascade) purely for a clean, auditable log line — same reasoning as
# HumanHandoff above.
deleted_approvals = ApprovalRequest.objects.filter(workspace__name__startswith="E2E ").delete()
deleted_handoffs = HumanHandoff.objects.filter(workspace__name__startswith="E2E ").delete()
deleted_knowledge_documents = KnowledgeDocument.objects.filter(workspace__name__startswith="E2E ").delete()
deleted_knowledge_sources = KnowledgeSource.objects.filter(workspace__name__startswith="E2E ").delete()
deleted_tool_executions = ToolExecution.objects.filter(workspace__name__startswith="E2E ").delete()
deleted_runs = AgentRun.objects.filter(workspace__name__startswith="E2E ").delete()
deleted_users = User.objects.filter(email__startswith="e2e-").delete()
deleted_workspaces = Workspace.objects.filter(name__startswith="E2E ").delete()
print("E2E cleanup:", deleted_approvals, deleted_handoffs, deleted_knowledge_documents, deleted_knowledge_sources, deleted_tool_executions, deleted_runs, deleted_users, deleted_workspaces)
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
