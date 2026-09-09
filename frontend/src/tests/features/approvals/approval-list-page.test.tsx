import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { ApprovalsListPage } from "@/features/approvals/components/approval-list-page";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";
import {
  approvalMockState,
  makeApprovalFixture,
  seedApprovals,
} from "@/tests/msw/approval-handlers";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks(initialQuery = "") {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/approvals");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(initialQuery) as unknown as ReturnType<typeof useSearchParams>,
  );
  return { replace };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("ApprovalsListPage", () => {
  it("defaults to the pending queue and renders real approval rows", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedApprovals(FIXTURE_WORKSPACE_ACME.id, [
      makeApprovalFixture({
        id: "appr-1",
        summary: "payment.refund: amount=100",
        status: "pending",
      }),
      makeApprovalFixture({ id: "appr-2", summary: "already approved one", status: "approved" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<ApprovalsListPage />);

    expect(
      await screen.findByRole("link", { name: "payment.refund: amount=100" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("already approved one")).not.toBeInTheDocument();
  });

  it("shows a distinct empty state for the pending queue", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<ApprovalsListPage />);

    expect(await screen.findByText("No pending approvals")).toBeInTheDocument();
  });

  it("shows a network-error state (not empty) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    approvalMockState.listNetworkError = true;
    setupNavigationMocks();

    renderAuthenticated(<ApprovalsListPage />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("No pending approvals")).not.toBeInTheDocument();

    approvalMockState.listNetworkError = false;
    seedApprovals(FIXTURE_WORKSPACE_ACME.id, [
      makeApprovalFixture({ id: "appr-1", summary: "recovered" }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("link", { name: "recovered" })).toBeInTheDocument();
  });

  it("pushes a status filter change into the URL, omitting the pending default", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    const { replace } = setupNavigationMocks();

    renderAuthenticated(<ApprovalsListPage />);
    await screen.findByText("No pending approvals");

    await userEvent.setup().selectOptions(screen.getByLabelText("Status"), "approved");

    expect(replace).toHaveBeenCalledWith("/app/approvals?status=approved", { scroll: false });
  });

  it("never renders another workspace's approvals while/after switching workspaces", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedApprovals(FIXTURE_WORKSPACE_ACME.id, [
      makeApprovalFixture({ id: "acme-appr", summary: "Acme approval" }),
    ]);
    seedApprovals(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeApprovalFixture({ id: "globex-appr", summary: "Globex approval" }),
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
          <ApprovalsListPage />
        </>
      );
    }

    renderAuthenticated(<Harness />);

    expect(await screen.findByRole("link", { name: "Acme approval" })).toBeInTheDocument();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_GLOBEX.name}` }));

    await waitFor(() => expect(screen.queryByText("Acme approval")).not.toBeInTheDocument());
    expect(await screen.findByRole("link", { name: "Globex approval" })).toBeInTheDocument();
  });

  it("renders an unrecognized future status value safely instead of crashing", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedApprovals(FIXTURE_WORKSPACE_ACME.id, [
      makeApprovalFixture({ id: "appr-1", summary: "x", status: "mystery_status" as never }),
    ]);
    setupNavigationMocks("status=all");

    renderAuthenticated(<ApprovalsListPage />);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("mystery_status")).toBeInTheDocument();
  });
});
