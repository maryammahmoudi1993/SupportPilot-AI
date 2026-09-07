import { type HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/** A layout-shaped loading placeholder. Use where content's real dimensions are known ahead of time. */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("bg-surface-3 animate-pulse rounded-md", className)}
      aria-hidden="true"
      {...props}
    />
  );
}
