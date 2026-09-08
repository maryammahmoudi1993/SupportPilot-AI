import { type HTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/utils";

const VARIANT_CLASSES = {
  info: "bg-info-50 border-info-500/30 text-info-700",
  success: "bg-success-50 border-success-500/30 text-success-700",
  warning: "bg-warning-50 border-warning-500/30 text-warning-700",
  danger: "bg-danger-50 border-danger-500/30 text-danger-700",
} as const;

export interface AlertProps extends HTMLAttributes<HTMLDivElement> {
  variant?: keyof typeof VARIANT_CLASSES;
  title?: string;
}

/** An inline status/error message. Uses `role="alert"` for danger/warning so assistive tech announces it immediately. */
export const Alert = forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant = "info", title, children, ...props }, ref) => (
    <div
      ref={ref}
      role={variant === "danger" || variant === "warning" ? "alert" : "status"}
      className={cn("rounded-md border px-4 py-3 text-sm", VARIANT_CLASSES[variant], className)}
      {...props}
    >
      {title && <p className="font-medium">{title}</p>}
      {/* Full-opacity `text-current` — a `/90` opacity modifier here
          previously softened the body text just enough to drop the
          warning variant's contrast ratio below WCAG AA's 4.5:1 minimum
          (4.06:1, caught by an axe scan in the E2E suite's Phase 18
          Chunk 4 acceptance gate). Every variant's `-700` text color
          against its `-50` background already provides enough contrast
          on its own; the opacity was a purely stylistic softening with no
          accessibility benefit. */}
      {children && <div className={cn(title && "mt-1", "text-current")}>{children}</div>}
    </div>
  ),
);
Alert.displayName = "Alert";
