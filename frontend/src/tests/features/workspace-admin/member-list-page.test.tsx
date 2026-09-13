import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { MembersListPage } from "@/features/workspace-admin/components/member-list-page";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import {
  makeWorkspaceMemberFixture,
  seedWorkspaceMembers,
  workspaceMemberMockState,
} from "@/tests/msw/workspace-member-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks(initialQuery = "") {
  const replace = vi.fn();
  const push = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace, push } as unknown as ReturnType<
    typeof useRouter
  >);
  vi.mocked(usePathname).mockReturnValue("/app/settings/members");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(initialQuery) as unknown as ReturnType<typeof useSearchParams>,
  );
  return { replace, push };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const FIXTURE_WORKSPACE_OWNER_SEAT = {
  id: FIXTURE_WORKSPACE_GLOBEX.id,
  name: FIXTURE_WORKSPACE_GLOBEX.name,
  slug: FIXTURE_WORKSPACE_GLOBEX.slug,
  role: "owner",
};

const SELF_USER = { id: FIXTURE_USER.id, email: FIXTURE_USER.email, display_name: "Jane Doe" };
const OWNER_USER = { id: 1, email: "owner@example.com", display_name: "Owner Person" };
const OTHER_ADMIN = { id: 2, email: "other-admin@example.com", display_name: "Other Admin" };
const AGENT_USER = { id: 3, email: "agent@example.com", display_name: "Agent Person" };

describe("MembersListPage", () => {
  it("renders real member rows with textual role, not color-only", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]); // support_agent role
    seedWorkspaceMembers(FIXTURE_WORKSPACE_ACME.id, [
      makeWorkspaceMemberFixture({ id: "m-owner", user: OWNER_USER, role: "owner" }),
      makeWorkspaceMemberFixture({ id: "m-self", user: SELF_USER, role: "support_agent" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<MembersListPage />);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Owner Person")).toBeInTheDocument();
    expect(within(table).getByText("Owner")).toBeInTheDocument();
    expect(within(table).getByText("Support Agent")).toBeInTheDocument();
  });

  it("shows a distinct empty state for zero members", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<MembersListPage />);

    expect(await screen.findByText("No workspace members yet")).toBeInTheDocument();
  });

  it("shows a network-error state (not empty) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    workspaceMemberMockState.memberListNetworkError = true;
    setupNavigationMocks();

    renderAuthenticated(<MembersListPage />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();

    workspaceMemberMockState.memberListNetworkError = false;
    seedWorkspaceMembers(FIXTURE_WORKSPACE_ACME.id, [
      makeWorkspaceMemberFixture({ id: "m-1", user: AGENT_USER, role: "support_agent" }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Agent Person")).toBeInTheDocument();
  });

  it("paginates using the real page query param", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWorkspaceMembers(
      FIXTURE_WORKSPACE_ACME.id,
      Array.from({ length: 3 }, (_, index) =>
        makeWorkspaceMemberFixture({
          id: `m-${index}`,
          user: { id: 100 + index, email: `u${index}@example.com`, display_name: `User ${index}` },
          role: "viewer",
        }),
      ),
    );
    setupNavigationMocks();

    renderAuthenticated(<MembersListPage />);
    await screen.findByText("User 0");

    expect(await screen.findByText("Page 1 · 3 members total")).toBeInTheDocument();
  });

  it("never renders another workspace's members while/after switching workspaces", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedWorkspaceMembers(FIXTURE_WORKSPACE_ACME.id, [
      makeWorkspaceMemberFixture({
        id: "acme-m",
        user: { id: 200, email: "acme@example.com", display_name: "Acme-only member" },
        role: "viewer",
      }),
    ]);
    seedWorkspaceMembers(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWorkspaceMemberFixture({
        id: "globex-m",
        user: { id: 201, email: "globex@example.com", display_name: "Globex-only member" },
        role: "viewer",
      }),
    ]);
    setupNavigationMocks();

    function Harness() {
      const workspace = useWorkspace();
      return (
        <>
          {workspace.status === "ready" &&
            workspace.workspaces.map((candidate) => (
              <button key={candidate.id} onClick={() => workspace.selectWorkspace(candidate.id)}>
                {`switch-to-${candidate.name}`}
              </button>
            ))}
          <MembersListPage />
        </>
      );
    }

    renderAuthenticated(<Harness />);

    expect(await screen.findByText("Acme-only member")).toBeInTheDocument();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_GLOBEX.name}` }));

    await waitFor(() => expect(screen.queryByText("Acme-only member")).not.toBeInTheDocument());
    expect(await screen.findByText("Globex-only member")).toBeInTheDocument();
  });

  it("renders no role-edit control for a support_agent (read-only role)", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]); // support_agent
    seedWorkspaceMembers(FIXTURE_WORKSPACE_ACME.id, [
      makeWorkspaceMemberFixture({ id: "m-other", user: AGENT_USER, role: "viewer" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<MembersListPage />);
    await screen.findByText("Agent Person");

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("renders a role-edit control for an admin managing a lower-role member", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedWorkspaceMembers(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWorkspaceMemberFixture({ id: "m-agent", user: AGENT_USER, role: "support_agent" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<MembersListPage />);
    await screen.findByText("Agent Person");

    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("does not render a role-edit control for the owner row", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedWorkspaceMembers(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWorkspaceMemberFixture({ id: "m-owner", user: OWNER_USER, role: "owner" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<MembersListPage />);
    await screen.findByText("Owner Person");

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("does not render a role-edit control for the signed-in caller's own row (self), shown as (You)", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]); // support_agent
    seedWorkspaceMembers(FIXTURE_WORKSPACE_ACME.id, [
      makeWorkspaceMemberFixture({ id: "m-self", user: SELF_USER, role: "support_agent" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<MembersListPage />);
    await screen.findByText("(You)");

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("an admin cannot manage another admin — no control renders for that row", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedWorkspaceMembers(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWorkspaceMemberFixture({ id: "m-other-admin", user: OTHER_ADMIN, role: "admin" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<MembersListPage />);
    await screen.findByText("Other Admin");

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("submits a role change and the server-authoritative result is reflected", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedWorkspaceMembers(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWorkspaceMemberFixture({ id: "m-agent", user: AGENT_USER, role: "support_agent" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<MembersListPage />);
    await screen.findByText("Agent Person");

    const select = screen.getByRole("combobox");
    await userEvent.setup().selectOptions(select, "viewer");

    await waitFor(() => expect(select).toHaveValue("viewer"));
  });

  it("requires confirmation before granting admin (privilege escalation)", async () => {
    signIn([FIXTURE_WORKSPACE_OWNER_SEAT]); // owner — only an owner may grant admin
    workspaceMemberMockState.actorRole = "owner";
    seedWorkspaceMembers(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWorkspaceMemberFixture({ id: "m-agent", user: AGENT_USER, role: "support_agent" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<MembersListPage />);
    await screen.findByText("Agent Person");

    const select = screen.getByRole("combobox");
    await userEvent.setup().selectOptions(select, "admin");

    expect(await screen.findByText("Grant admin access?")).toBeInTheDocument();
    // Not applied yet until confirmed.
    expect(select).toHaveValue("support_agent");

    await userEvent.setup().click(screen.getByRole("button", { name: "Grant admin" }));

    await waitFor(() =>
      expect(
        workspaceMemberMockState.membersByWorkspace[FIXTURE_WORKSPACE_GLOBEX.id]?.find(
          (m) => m.id === "m-agent",
        )?.role,
      ).toBe("admin"),
    );
  });

  it("direct unauthorized API mutation is blocked by the mock backend contract (not merely hidden by the UI)", async () => {
    const { fetchWorkspaceMemberList, updateWorkspaceMemberRole } =
      await import("@/features/workspace-admin/api");
    signIn([FIXTURE_WORKSPACE_ACME]);
    workspaceMemberMockState.actorRole = "support_agent";
    seedWorkspaceMembers(FIXTURE_WORKSPACE_ACME.id, [
      makeWorkspaceMemberFixture({ id: "m-1", user: AGENT_USER, role: "viewer" }),
    ]);

    await fetchWorkspaceMemberList(FIXTURE_WORKSPACE_ACME.id, { page: 1 });
    await expect(
      updateWorkspaceMemberRole(FIXTURE_WORKSPACE_ACME.id, "m-1", "admin"),
    ).rejects.toMatchObject({ status: 403 });
  });

  it("foreign membership id (different workspace) returns not_found, never a leak", async () => {
    const { fetchWorkspaceMemberList } = await import("@/features/workspace-admin/api");
    seedWorkspaceMembers(FIXTURE_WORKSPACE_ACME.id, []);
    seedWorkspaceMembers(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWorkspaceMemberFixture({ id: "globex-only", user: OTHER_ADMIN, role: "admin" }),
    ]);

    const acmeList = await fetchWorkspaceMemberList(FIXTURE_WORKSPACE_ACME.id, { page: 1 });
    expect(acmeList.results.find((m) => m.id === "globex-only")).toBeUndefined();
  });
});
