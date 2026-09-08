/**
 * Creates synthetic backend data for the E2E suite: one user with two real
 * workspace memberships (owner + support_agent) and one user with zero
 * memberships. Shells out to the real Django backend (`manage.py shell`) —
 * no mocks, no fixtures baked into the frontend — so the suite exercises
 * the actual `/auth/login/`, `/auth/me/`, and workspace-scoped contract.
 *
 * Output (`.e2e-data.json`, gitignored) is read by tests and by
 * `global-teardown.ts`. Cleaned up unconditionally in teardown; also wipes
 * any leftover `e2e-*`/`E2E *` data from a prior aborted run before
 * creating fresh records, so a crashed run never leaves stale rows that
 * silently corrupt the next one.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const BACKEND_ROOT = path.resolve(__dirname, "..", "..", "backend");
const PYTHON = path.join(BACKEND_ROOT, "venv", "Scripts", "python.exe");
export const DATA_FILE = path.resolve(__dirname, ".e2e-data.json");

const SETUP_SCRIPT = `
import json
from accounts.models import User
from customers.models import Customer
from workspaces.models import Workspace, WorkspaceMembership, WorkspaceRole

PASSWORD = "e2e-Test-Passw0rd!"

def make_user(username, email, first, last):
    u = User(username=username, email=email, first_name=first, last_name=last, is_active=True)
    u.set_password(PASSWORD)
    u.save()
    return u

User.objects.filter(email__startswith="e2e-").delete()
Workspace.objects.filter(name__startswith="E2E ").delete()

primary = make_user("e2e-primary", "e2e-primary@example.com", "E2E", "Primary")
zero = make_user("e2e-zero", "e2e-zero@example.com", "E2E", "ZeroWorkspace")

ws_a = Workspace.objects.create(name="E2E Workspace A")
ws_b = Workspace.objects.create(name="E2E Workspace B")
WorkspaceMembership.objects.create(workspace=ws_a, user=primary, role=WorkspaceRole.OWNER)
WorkspaceMembership.objects.create(workspace=ws_b, user=primary, role=WorkspaceRole.SUPPORT_AGENT)

# Customers domain (Phase 19 Chunk 1) — real cross-workspace data so the
# real-backend smoke and later Phase 19 E2E specs can prove tenant
# isolation, search, and pagination against the actual API, not a mock.
# Customer rows cascade-delete with their workspace (Customer.workspace,
# on_delete=CASCADE) so no separate cleanup is needed here.
ws_a_customer = Customer.objects.create(
    workspace=ws_a, first_name="Ada", last_name="Lovelace",
    email="ada.lovelace@example.com", company="Analytical Engines Ltd", is_active=True,
)
Customer.objects.create(
    workspace=ws_a, first_name="Grace", last_name="Hopper",
    email="grace.hopper@example.com", company="COBOL Systems", is_active=True,
)
Customer.objects.create(
    workspace=ws_a, first_name="Retired", last_name="Account",
    email="retired.account@example.com", company="Formerly Inc", is_active=False,
)
ws_b_customer = Customer.objects.create(
    workspace=ws_b, first_name="Bob", last_name="Belcher",
    email="bob.belcher@example.com", company="Globex Burgers", is_active=True,
)

print(json.dumps({
    "primaryEmail": primary.email,
    "primaryPassword": PASSWORD,
    "zeroEmail": zero.email,
    "zeroPassword": PASSWORD,
    "workspaceAId": str(ws_a.id),
    "workspaceAName": ws_a.name,
    "workspaceBId": str(ws_b.id),
    "workspaceBName": ws_b.name,
    # Memberships list from /auth/me/ is ordered by -created_at (selectors.py
    # list_active_memberships_for_user) - the LAST-created membership (B)
    # sorts first and is the deterministic default active workspace, not A.
    "defaultWorkspaceName": ws_b.name,
    "defaultWorkspaceId": str(ws_b.id),
    "otherWorkspaceName": ws_a.name,
    "otherWorkspaceId": str(ws_a.id),
    "workspaceACustomerId": str(ws_a_customer.id),
    "workspaceACustomerName": ws_a_customer.display_name,
    "workspaceBCustomerId": str(ws_b_customer.id),
    "workspaceBCustomerName": ws_b_customer.display_name,
}))
`;

export default async function globalSetup(): Promise<void> {
  const output = execFileSync(PYTHON, ["manage.py", "shell", "-c", SETUP_SCRIPT], {
    cwd: BACKEND_ROOT,
    encoding: "utf-8",
  });
  const jsonLine = output
    .trim()
    .split("\n")
    .filter((line) => line.trim().startsWith("{"))
    .pop();
  if (!jsonLine) {
    throw new Error(`E2E global setup: could not find JSON output from Django shell.\n${output}`);
  }
  fs.writeFileSync(DATA_FILE, jsonLine);
}
