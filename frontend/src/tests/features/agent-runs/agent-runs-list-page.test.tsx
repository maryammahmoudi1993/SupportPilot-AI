import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { AgentRunsListPage } from "@/features/agent-runs/components/agent-runs-list-page";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";
import {
  agentRunMockState,
  makeAgentRunFixture,
  seedAgentRuns,
} from "@/tests/msw/agent-run-handlers";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks(initialQuery = "") {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/agent-runs");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(initialQuery) as unknown as ReturnType<typeof useSearchParams>,
  );
  return { replace };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const VERSION_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

describe("AgentRunsListPage", () => {
  it("renders real agent run rows returned by the API", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedAgentRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeAgentRunFixture({
        id: "run-1",
        agent_version_id: VERSION_1,
        status: "succeeded",
        trigger: "conversation",
        step_count: 4,
        tool_call_count: 1,
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<AgentRunsListPage />);

    expect(await screen.findByRole("link", { name: "Run #run-1" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Succeeded")).toBeInTheDocument();
    expect(within(table).getByText("conversation")).toBeInTheDocument();
  });

  it("shows a distinct empty state for zero runs", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<AgentRunsListPage />);

    expect(await screen.findByText("No agent runs yet")).toBeInTheDocument();
  });

  it("shows a network-error state (not empty) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    agentRunMockState.listNetworkError = true;
    setupNavigationMocks();

    renderAuthenticated(<AgentRunsListPage />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("No agent runs yet")).not.toBeInTheDocument();

    agentRunMockState.listNetworkError = false;
    seedAgentRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeAgentRunFixture({ id: "run-1", agent_version_id: VERSION_1 }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("link", { name: /Run #/ })).toBeInTheDocument();
  });

  it("pushes a status filter change into the URL with the page reset to 1", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    const { replace } = setupNavigationMocks("page=3");

    renderAuthenticated(<AgentRunsListPage />);
    await screen.findByText("No agent runs yet");

    await userEvent.setup().selectOptions(screen.getByLabelText("Status"), "running");

    expect(replace).toHaveBeenCalledWith("/app/agent-runs?status=running", { scroll: false });
  });

  it("paginates using the backend's next/previous contract and preserves filters", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedAgentRuns(
      FIXTURE_WORKSPACE_ACME.id,
      Array.from({ length: 55 }, (_, index) =>
        makeAgentRunFixture({
          id: `run-${index}`,
          agent_version_id: VERSION_1,
          status: "running",
        }),
      ),
    );
    const { replace } = setupNavigationMocks("status=running");

    renderAuthenticated(<AgentRunsListPage />);

    const nextButton = await screen.findByRole("button", { name: "Next page" });
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(nextButton).toBeEnabled();

    await userEvent.setup().click(nextButton);

    expect(replace).toHaveBeenCalledWith("/app/agent-runs?page=2&status=running", {
      scroll: false,
    });
  });

  it("renders an unrecognized future status value safely instead of crashing", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedAgentRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeAgentRunFixture({
        id: "run-1",
        agent_version_id: VERSION_1,
        status: "queued_for_review" as never,
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<AgentRunsListPage />);

    expect(await screen.findByRole("link", { name: /Run #/ })).toBeInTheDocument();
    expect(screen.getByText("queued_for_review")).toBeInTheDocument();
  });

  it("never renders another workspace's agent runs while/after switching workspaces", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedAgentRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeAgentRunFixture({ id: "acme-run", agent_version_id: VERSION_1 }),
    ]);
    seedAgentRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeAgentRunFixture({ id: "globex-run", agent_version_id: VERSION_1 }),
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
          <AgentRunsListPage />
        </>
      );
    }

    renderAuthenticated(<Harness />);

    expect(await screen.findByRole("link", { name: "Run #acme-run" })).toBeInTheDocument();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_GLOBEX.name}` }));

    await waitFor(() => expect(screen.queryByText("Run #acme-run")).not.toBeInTheDocument());
    expect(await screen.findByRole("link", { name: "Run #globex-r" })).toBeInTheDocument();
  });
});
