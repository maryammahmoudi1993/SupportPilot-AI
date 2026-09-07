import { type InputHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/utils";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Marks the input as invalid and styles it accordingly. Pair with aria-describedby on the field. */
  invalid?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, invalid = false, ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={cn(
          "bg-surface-0 text-text-primary placeholder:text-text-muted h-9 w-full rounded-md border px-3 text-sm",
          "transition-colors outline-none",
          invalid
            ? "border-danger-500 focus-visible:outline-danger-500"
            : "border-border-default focus-visible:outline-primary-500",
          "disabled:bg-surface-2 disabled:text-text-disabled disabled:cursor-not-allowed",
          className,
        )}
        aria-invalid={invalid || undefined}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";
