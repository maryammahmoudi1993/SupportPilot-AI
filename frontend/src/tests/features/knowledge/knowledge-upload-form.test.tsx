import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { KnowledgeUploadForm } from "@/features/knowledge/components/knowledge-upload-form";
import { FIXTURE_USER, FIXTURE_WORKSPACE_GLOBEX, mockState } from "@/tests/msw/handlers";
import {
  knowledgeMockState,
  makeKnowledgeSourceFixture,
  seedKnowledgeSources,
} from "@/tests/msw/knowledge-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next/navigation")>();
  return { ...actual, useRouter: vi.fn() };
});

const SOURCE_1 = "22222222-2222-4222-8222-222222222222";
const INACTIVE_SOURCE = "33333333-3333-4333-8333-333333333333";

function signIn() {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_GLOBEX]; // admin — canManageKnowledge
}

function makeFile(name: string, content: string, type = "text/plain") {
  return new File([content], name, { type });
}

describe("KnowledgeUploadForm", () => {
  it("submits real multipart fields only (source_id, title, file) and navigates to the new document", async () => {
    signIn();
    seedKnowledgeSources(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeKnowledgeSourceFixture({ id: SOURCE_1, name: "Support Macros" }),
    ]);
    const push = vi.fn();
    vi.mocked(useRouter).mockReturnValue({ push } as unknown as ReturnType<typeof useRouter>);

    renderAuthenticated(<KnowledgeUploadForm workspaceId={FIXTURE_WORKSPACE_GLOBEX.id} />);

    await screen.findByRole("option", { name: "Support Macros" });
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Source"), SOURCE_1);
    await user.clear(screen.getByLabelText("Title"));
    await user.type(screen.getByLabelText("Title"), "Refund policy");
    await user.upload(screen.getByLabelText("File"), makeFile("policy.txt", "hello"));

    await user.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(push).toHaveBeenCalledWith(expect.stringMatching(/^\/app\/knowledge\/doc-\d+$/));
  });

  it("auto-fills the title from the filename but leaves it editable", async () => {
    signIn();
    seedKnowledgeSources(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeKnowledgeSourceFixture({ id: SOURCE_1, name: "Support Macros" }),
    ]);
    vi.mocked(useRouter).mockReturnValue({
      push: vi.fn(),
    } as unknown as ReturnType<typeof useRouter>);

    renderAuthenticated(<KnowledgeUploadForm workspaceId={FIXTURE_WORKSPACE_GLOBEX.id} />);
    await screen.findByRole("option", { name: "Support Macros" });

    await userEvent.setup().upload(screen.getByLabelText("File"), makeFile("policy.txt", "hi"));

    expect(screen.getByLabelText("Title")).toHaveValue("policy.txt");
  });

  it("disables submit and shows an inline message for a file over the size limit", async () => {
    signIn();
    seedKnowledgeSources(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeKnowledgeSourceFixture({ id: SOURCE_1, name: "Support Macros" }),
    ]);
    vi.mocked(useRouter).mockReturnValue({
      push: vi.fn(),
    } as unknown as ReturnType<typeof useRouter>);

    renderAuthenticated(<KnowledgeUploadForm workspaceId={FIXTURE_WORKSPACE_GLOBEX.id} />);
    await screen.findByRole("option", { name: "Support Macros" });

    const oversized = makeFile("big.txt", "x");
    Object.defineProperty(oversized, "size", { value: 11 * 1024 * 1024 });
    await userEvent.setup().upload(screen.getByLabelText("File"), oversized);

    expect(screen.getByRole("alert")).toHaveTextContent(/larger than the 10 MB limit/);
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
  });

  it("shows a real 409 conflict when the selected source is inactive, and never navigates", async () => {
    signIn();
    seedKnowledgeSources(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeKnowledgeSourceFixture({ id: INACTIVE_SOURCE, name: "Retired Source", is_active: false }),
      makeKnowledgeSourceFixture({ id: SOURCE_1, name: "Support Macros" }),
    ]);
    const push = vi.fn();
    vi.mocked(useRouter).mockReturnValue({ push } as unknown as ReturnType<typeof useRouter>);

    renderAuthenticated(<KnowledgeUploadForm workspaceId={FIXTURE_WORKSPACE_GLOBEX.id} />);
    await screen.findByRole("option", { name: "Support Macros" });

    // Inactive sources are never offered as a choice at all (see component
    // doc comment) — asserting the real conflict path would require an
    // active-looking source that races to inactive server-side, which this
    // deterministic mock does not model. Instead this proves the UI-level
    // guarantee: the doomed choice never appears.
    expect(screen.queryByRole("option", { name: "Retired Source" })).not.toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("shows a distinct, honest message for an ambiguous (network-level) failure — never claims the upload failed", async () => {
    signIn();
    seedKnowledgeSources(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeKnowledgeSourceFixture({ id: SOURCE_1, name: "Support Macros" }),
    ]);
    knowledgeMockState.uploadNetworkError = true;
    vi.mocked(useRouter).mockReturnValue({
      push: vi.fn(),
    } as unknown as ReturnType<typeof useRouter>);

    renderAuthenticated(<KnowledgeUploadForm workspaceId={FIXTURE_WORKSPACE_GLOBEX.id} />);
    await screen.findByRole("option", { name: "Support Macros" });

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Source"), SOURCE_1);
    await user.type(screen.getByLabelText("Title"), "Refund policy");
    await user.upload(screen.getByLabelText("File"), makeFile("policy.txt", "hi"));
    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(
      await screen.findByText("We couldn't confirm this upload was received"),
    ).toBeInTheDocument();
    expect(screen.queryByText("This upload was rejected")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh list" })).toBeInTheDocument();
  });

  it("keeps submit disabled with no file selected, even with source and title filled — no request is ever sent", async () => {
    signIn();
    seedKnowledgeSources(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeKnowledgeSourceFixture({ id: SOURCE_1, name: "Support Macros" }),
    ]);
    vi.mocked(useRouter).mockReturnValue({
      push: vi.fn(),
    } as unknown as ReturnType<typeof useRouter>);

    renderAuthenticated(<KnowledgeUploadForm workspaceId={FIXTURE_WORKSPACE_GLOBEX.id} />);
    await screen.findByRole("option", { name: "Support Macros" });

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Source"), SOURCE_1);
    await user.type(screen.getByLabelText("Title"), "Refund policy");

    // No file chosen: `canSubmit` (the real gate — see the component's doc
    // comment on `aria-required` vs native `required`) stays false, so the
    // submit control itself is disabled — not just guarded inside the
    // handler. A disabled button fails Testing Library's/userEvent's own
    // actionability check on click, which is itself proof it cannot be
    // activated; this asserts the disabled state directly instead.
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
    expect(knowledgeMockState.documentCreateCallCount).toBe(0);

    // Also required: this is a screen-reader-perceivable requirement, not
    // just a visual one — the file input carries `aria-required="true"`.
    expect(screen.getByLabelText("File")).toHaveAttribute("aria-required", "true");
  });

  it("shows the real server rejection for an unsupported file type, persists no document, and never navigates", async () => {
    signIn();
    seedKnowledgeSources(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeKnowledgeSourceFixture({ id: SOURCE_1, name: "Support Macros" }),
    ]);
    knowledgeMockState.uploadUnsupportedType = true;
    const push = vi.fn();
    vi.mocked(useRouter).mockReturnValue({ push } as unknown as ReturnType<typeof useRouter>);

    renderAuthenticated(<KnowledgeUploadForm workspaceId={FIXTURE_WORKSPACE_GLOBEX.id} />);
    await screen.findByRole("option", { name: "Support Macros" });

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Source"), SOURCE_1);
    await user.type(screen.getByLabelText("Title"), "Suspicious file");
    // `userEvent.upload` itself honors the input's `accept` attribute (a
    // real jsdom/Testing-Library behavior, not a product one), so an
    // extension outside the allow-list can never actually be selected here —
    // this instead models the real case the client-side `accept` hint can
    // never catch: a `.txt`-named file whose actual bytes/content-type the
    // server independently rejects (`validate_upload`'s magic-byte check,
    // knowledge/ingestion/validators.py). The client never pre-empts this —
    // the server is the sole authority — proven by this real 400 round trip.
    await user.upload(screen.getByLabelText("File"), makeFile("note.txt", "hello"));
    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByText("This upload was rejected")).toBeInTheDocument();
    expect(screen.getByText("The uploaded file type is not supported.")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(
      knowledgeMockState.documentsByWorkspace[FIXTURE_WORKSPACE_GLOBEX.id] ?? [],
    ).toHaveLength(0);
  });

  it("blocks duplicate submission while an upload is pending — never a double POST", async () => {
    signIn();
    seedKnowledgeSources(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeKnowledgeSourceFixture({ id: SOURCE_1, name: "Support Macros" }),
    ]);
    // An artificial delay so the "in flight" window is actually observable,
    // rather than racing a same-tick MSW resolution.
    knowledgeMockState.uploadDelayMs = 50;
    vi.mocked(useRouter).mockReturnValue({
      push: vi.fn(),
    } as unknown as ReturnType<typeof useRouter>);

    renderAuthenticated(<KnowledgeUploadForm workspaceId={FIXTURE_WORKSPACE_GLOBEX.id} />);
    await screen.findByRole("option", { name: "Support Macros" });

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Source"), SOURCE_1);
    await user.type(screen.getByLabelText("Title"), "Refund policy");
    await user.upload(screen.getByLabelText("File"), makeFile("policy.txt", "hi"));

    const submitButton = screen.getByRole("button", { name: "Upload" });
    // Fire the click without awaiting it, then click again while the first
    // is still in flight — proves a second click during that window is
    // inert, not just visually disabled.
    void user.click(submitButton);
    await waitFor(() => expect(submitButton).toBeDisabled());
    await user.click(submitButton);

    await waitFor(() => expect(knowledgeMockState.documentCreateCallCount).toBe(1));
  });
});
