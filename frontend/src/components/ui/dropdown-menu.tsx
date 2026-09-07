"use client";

import * as RadixDropdownMenu from "@radix-ui/react-dropdown-menu";
import { type ComponentPropsWithoutRef, forwardRef } from "react";

import { cn } from "@/lib/utils";

/**
 * Thin styling wrapper around Radix's dropdown-menu primitive — chosen over
 * a hand-built menu because correct keyboard/focus/typeahead behavior
 * (arrow-key navigation, Home/End, Escape-to-close-and-return-focus,
 * click-outside dismissal, `role="menu"`/`menuitem"` wiring) is exactly the
 * kind of thing worth a mature accessible primitive rather than
 * reimplementing (see frontend/README.md, "Design system extension").
 */
export const DropdownMenu = RadixDropdownMenu.Root;
export const DropdownMenuTrigger = RadixDropdownMenu.Trigger;

export const DropdownMenuContent = forwardRef<
  React.ElementRef<typeof RadixDropdownMenu.Content>,
  ComponentPropsWithoutRef<typeof RadixDropdownMenu.Content>
>(({ className, sideOffset = 6, align = "end", ...props }, ref) => (
  <RadixDropdownMenu.Portal>
    <RadixDropdownMenu.Content
      ref={ref}
      sideOffset={sideOffset}
      align={align}
      className={cn(
        "border-border-subtle bg-surface-0 z-50 min-w-48 rounded-md border p-1 shadow-lg",
        className,
      )}
      {...props}
    />
  </RadixDropdownMenu.Portal>
));
DropdownMenuContent.displayName = "DropdownMenuContent";

export const DropdownMenuItem = forwardRef<
  React.ElementRef<typeof RadixDropdownMenu.Item>,
  ComponentPropsWithoutRef<typeof RadixDropdownMenu.Item>
>(({ className, ...props }, ref) => (
  <RadixDropdownMenu.Item
    ref={ref}
    className={cn(
      "text-text-primary flex cursor-pointer items-center gap-2 rounded-sm px-2.5 py-2 text-sm outline-none select-none",
      "focus:bg-surface-2 data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className,
    )}
    {...props}
  />
));
DropdownMenuItem.displayName = "DropdownMenuItem";

export const DropdownMenuLabel = forwardRef<
  React.ElementRef<typeof RadixDropdownMenu.Label>,
  ComponentPropsWithoutRef<typeof RadixDropdownMenu.Label>
>(({ className, ...props }, ref) => (
  <RadixDropdownMenu.Label
    ref={ref}
    className={cn("text-text-muted px-2.5 py-1.5 text-xs font-medium", className)}
    {...props}
  />
));
DropdownMenuLabel.displayName = "DropdownMenuLabel";

export const DropdownMenuSeparator = forwardRef<
  React.ElementRef<typeof RadixDropdownMenu.Separator>,
  ComponentPropsWithoutRef<typeof RadixDropdownMenu.Separator>
>(({ className, ...props }, ref) => (
  <RadixDropdownMenu.Separator
    ref={ref}
    className={cn("bg-border-subtle my-1 h-px", className)}
    {...props}
  />
));
DropdownMenuSeparator.displayName = "DropdownMenuSeparator";
