"use client";

import * as RadixDialog from "@radix-ui/react-dialog";
import { useEffect, useRef, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

/**
 * A centered, accessible confirmation modal for destructive/sensitive
 * mutations (Phase 22 Chunk 3, master prompt Part J §38-39): disable
 * connection/endpoint, credential/secret rotation, redrive. Built on the
 * same Radix Dialog primitive as `Sheet` (components/ui/sheet.tsx) — focus
 * trap, Escape-to-close, and `aria-modal`/background-inert wiring all come
 * from Radix, not hand-rolled here (master prompt Part J §39: "No clickable
 * divs").
 *
 * Deliberately uncontrolled beyond `open`/`onOpenChange`: the caller owns
 * exactly when the dialog is visible (typically a `useState` toggled by a
 * trigger button), so a pending mutation can keep the dialog open (and its
 * confirm button disabled/loading) until the request actually resolves —
 * never closed optimistically before the server has answered.
 *
 * **Focus return to the trigger is handled explicitly here** (Phase 23
 * Chunk 4 fix — a real defect found by Evaluations' own keyboard-only E2E,
 * see frontend/README.md "Known defects"): Radix's own automatic
 * focus-restore assumes composition with `Dialog.Trigger`, but every real
 * caller of this component renders its own external trigger button and
 * only ever passes `open`/`onOpenChange` — Radix has no reference to that
 * button, so on close it fell back to `<body>`, a genuine (if narrow) loss
 * of keyboard position, not a "trap" but a real regression from the
 * doc comment's prior (incorrect) claim that Radix handled this for free.
 * Fixed by capturing `document.activeElement` when the dialog opens and
 * restoring it in `onCloseAutoFocus`.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  onConfirm,
  isConfirming = false,
  confirmVariant = "danger",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  isConfirming?: boolean;
  confirmVariant?: "danger" | "primary";
}) {
  const triggerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
  }, [open]);

  return (
    <RadixDialog.Root open={open} onOpenChange={isConfirming ? undefined : onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <RadixDialog.Content
          className="bg-surface-0 border-border-default fixed top-1/2 left-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-lg border p-5 shadow-xl focus:outline-none"
          onCloseAutoFocus={(event) => {
            if (triggerRef.current) {
              event.preventDefault();
              triggerRef.current.focus();
            }
          }}
          onEscapeKeyDown={(event) => {
            if (isConfirming) event.preventDefault();
          }}
          onInteractOutside={(event) => {
            if (isConfirming) event.preventDefault();
          }}
        >
          <RadixDialog.Title className="text-text-primary text-base font-semibold">
            {title}
          </RadixDialog.Title>
          <RadixDialog.Description className="text-text-secondary mt-2 text-sm">
            {description}
          </RadixDialog.Description>
          <div className="mt-5 flex justify-end gap-2">
            <RadixDialog.Close asChild>
              <Button variant="secondary" disabled={isConfirming}>
                {cancelLabel}
              </Button>
            </RadixDialog.Close>
            <Button variant={confirmVariant} onClick={onConfirm} isLoading={isConfirming}>
              {confirmLabel}
            </Button>
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
