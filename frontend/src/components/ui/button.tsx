import { type ButtonHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/utils";

const VARIANT_CLASSES = {
  primary: "bg-primary-500 text-text-inverse hover:bg-primary-600 active:bg-primary-700",
  secondary:
    "bg-surface-0 text-text-primary border border-border-default hover:bg-surface-2 active:bg-surface-3",
  ghost: "bg-transparent text-text-primary hover:bg-surface-2 active:bg-surface-3",
  danger: "bg-danger-500 text-text-inverse hover:bg-danger-700 active:bg-danger-700",
} as const;

const SIZE_CLASSES = {
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-9 px-4 text-sm gap-2",
  lg: "h-10 px-5 text-base gap-2",
} as const;

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof VARIANT_CLASSES;
  size?: keyof typeof SIZE_CLASSES;
  /** Shows a spinner and disables the button, without shifting its layout. */
  isLoading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "primary",
      size = "md",
      isLoading = false,
      disabled,
      children,
      type = "button",
      ...props
    },
    ref,
  ) => {
    return (
      <button
        ref={ref}
        type={type}
        className={cn(
          "inline-flex items-center justify-center rounded-md font-medium whitespace-nowrap transition-colors",
          "disabled:pointer-events-none disabled:opacity-50",
          VARIANT_CLASSES[variant],
          SIZE_CLASSES[size],
          className,
        )}
        disabled={disabled || isLoading}
        aria-busy={isLoading || undefined}
        {...props}
      >
        {isLoading && (
          <span
            className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent"
            aria-hidden="true"
          />
        )}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
