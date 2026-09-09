import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { HandoffsListPage } from "@/features/handoffs/components/handoff-list-page";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import { handoffMockState, makeHandoffFixture, seedHandoffs } from "@/tests/msw/handoff-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks(initialQuery = "") {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/handoffs");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(initialQuery) as unknown as ReturnType<typeof useSearchParams>,
  );
  return { replace };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const CONV_1 = "22222222-2222-4222-8222-222222222222";

describe("HandoffsListPage", () => {
  it("renders real handoff rows returned by the API", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedHandoffs(FIXTURE_WORKSPACE_ACME.id, [
      makeHandoffFixture({
        id: "h-1",
        conversation_id: CONV_1,
        status: "pending",
        reason_code: "low_confidence",
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<HandoffsListPage />);

    expect(
      await screen.findByRole("link", { name: "Low-confidence retrieval/response" }),
    ).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Pending")).toBeInTheDocument();
    expect(within(table).getByText("Unassigned")).toBeInTheDocument();
  });

  it("shows a distinct empty state for zero handoffs", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<HandoffsListPage />);

    expect(await screen.findByText("No handoffs yet")).toBeInTheDocument();
  });

  it("shows a network-error state (not empty) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    handoffMockState.listNetworkError = true;
    setupNavigationMocks();

    renderAuthenticated(<HandoffsListPage />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();

    handoffMockState.listNetworkError = false;
    seedHandoffs(FIXTURE_WORKSPACE_ACME.id, [
      makeHandoffFixture({ id: "h-1", conversation_id: CONV_1 }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(
      await screen.findByRole("link", { name: /Customer requested a human/ }),
    ).toBeInTheDocument();
  });

  it("pushes a status filter change into the URL with the page reset to 1", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    const { replace } = setupNavigationMocks("page=3");

    renderAuthenticated(<HandoffsListPage />);
    await screen.findByText("No handoffs yet");

    await userEvent.setup().selectOptions(screen.getByLabelText("Status"), "resolved");

    expect(replace).toHaveBeenCalledWith("/app/handoffs?status=resolved", { scroll: false });
  });

  it("never renders another workspace's handoffs while/after switching workspaces", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedHandoffs(FIXTURE_WORKSPACE_ACME.id, [
      makeHandoffFixture({
        id: "acme-h",
        conversation_id: CONV_1,
        reason_code: "policy_escalation",
      }),
    ]);
    seedHandoffs(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeHandoffFixture({
        id: "globex-h",
        conversation_id: CONV_1,
        reason_code: "runtime_failure",
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
          <HandoffsListPage />
        </>
      );
    }

    renderAuthenticated(<Harness />);

    expect(
      await screen.findByRole("link", { name: "Business workflow requires an operator" }),
    ).toBeInTheDocument();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_GLOBEX.name}` }));

    await waitFor(() =>
      expect(
        screen.queryByRole("link", { name: "Business workflow requires an operator" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      await screen.findByRole("link", { name: "Repeated bounded runtime failure" }),
    ).toBeInTheDocument();
  });
});
