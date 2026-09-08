import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { usePathname } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { MobileNav } from "@/components/shell/mobile-nav";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/app"),
}));

describe("MobileNav", () => {
  it("opens the drawer, moves focus in, and Escape closes it and returns focus to the trigger", async () => {
    vi.mocked(usePathname).mockReturnValue("/app");
    const user = userEvent.setup();
    render(<MobileNav />);

    const trigger = screen.getByRole("button", { name: "Open navigation menu" });
    await user.click(trigger);

    const dialog = await screen.findByRole("dialog", { name: "SupportPilot AI" });
    expect(dialog).toBeInTheDocument();
    // The primary nav link inside is reachable.
    expect(screen.getByRole("link", { name: "Overview" })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("closes when a nav link is activated", async () => {
    const user = userEvent.setup();
    render(<MobileNav />);

    await user.click(screen.getByRole("button", { name: "Open navigation menu" }));
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("link", { name: "Overview" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
