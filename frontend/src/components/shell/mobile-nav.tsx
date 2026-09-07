"use client";

import { useState } from "react";

import { NavLinks } from "@/components/shell/nav-links";
import { CloseIcon, MenuIcon } from "@/components/shell/icons";
import { Sheet, SheetClose, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

/**
 * Mobile navigation drawer. Radix's Dialog primitive supplies focus
 * trapping, Escape-to-close, focus return to the trigger on close, and an
 * inert background while open (see components/ui/sheet.tsx) — the
 * accessibility behaviors Part 28 of the Chunk 3 spec requires.
 */
export function MobileNav() {
  const [open, setOpen] = useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <button
          type="button"
          aria-label="Open navigation menu"
          className="text-text-primary hover:bg-surface-2 flex h-9 w-9 items-center justify-center rounded-md md:hidden"
        >
          <MenuIcon className="h-5 w-5" />
        </button>
      </SheetTrigger>
      <SheetContent>
        <div className="flex h-14 shrink-0 items-center justify-between px-4">
          <SheetTitle className="text-text-primary text-sm font-semibold">
            SupportPilot AI
          </SheetTitle>
          <SheetClose asChild>
            <button
              type="button"
              aria-label="Close navigation menu"
              className="text-text-secondary hover:bg-surface-2 flex h-8 w-8 items-center justify-center rounded-md"
            >
              <CloseIcon className="h-5 w-5" />
            </button>
          </SheetClose>
        </div>
        <div className="flex-1 overflow-y-auto px-3 pb-4">
          <NavLinks onNavigate={() => setOpen(false)} />
        </div>
      </SheetContent>
    </Sheet>
  );
}
