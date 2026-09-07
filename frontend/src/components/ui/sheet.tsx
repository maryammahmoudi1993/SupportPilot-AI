"use client";

import * as RadixDialog from "@radix-ui/react-dialog";
import { type ComponentPropsWithoutRef, forwardRef } from "react";

import { cn } from "@/lib/utils";

/**
 * A slide-in panel (used for the mobile navigation drawer) built on Radix's
 * dialog primitive: it owns focus trapping, Escape-to-close, focus return to
 * the trigger, and `aria-modal`/background-inert wiring, which is exactly
 * the "mature accessible primitive" this kind of component needs (see
 * frontend/README.md, "Design system extension" and "Mobile navigation").
 */
export const Sheet = RadixDialog.Root;
export const SheetTrigger = RadixDialog.Trigger;
export const SheetClose = RadixDialog.Close;

export const SheetOverlay = forwardRef<
  React.ElementRef<typeof RadixDialog.Overlay>,
  ComponentPropsWithoutRef<typeof RadixDialog.Overlay>
>(({ className, ...props }, ref) => (
  <RadixDialog.Overlay
    ref={ref}
    className={cn("fixed inset-0 z-40 bg-black/40", className)}
    {...props}
  />
));
SheetOverlay.displayName = "SheetOverlay";

export const SheetContent = forwardRef<
  React.ElementRef<typeof RadixDialog.Content>,
  ComponentPropsWithoutRef<typeof RadixDialog.Content>
>(({ className, children, ...props }, ref) => (
  <RadixDialog.Portal>
    <SheetOverlay />
    <RadixDialog.Content
      ref={ref}
      className={cn(
        "bg-surface-0 fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col shadow-xl",
        "focus:outline-none",
        className,
      )}
      {...props}
    >
      {children}
    </RadixDialog.Content>
  </RadixDialog.Portal>
));
SheetContent.displayName = "SheetContent";

export const SheetTitle = RadixDialog.Title;
export const SheetDescription = RadixDialog.Description;
