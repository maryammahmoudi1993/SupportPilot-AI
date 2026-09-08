import { cn } from "@/lib/utils";

export interface SpinnerProps {
  className?: string;
  /** Accessible label announced to screen readers. */
  label?: string;
}

/** An inline loading indicator. For a full section/page loading state, use it inside a labeled live region. */
export function Spinner({ className, label = "Loading" }: SpinnerProps) {
  return (
    <span role="status" className="inline-flex items-center gap-2">
      <span
        className={cn(
          "border-border-default border-t-primary-500 h-4 w-4 shrink-0 animate-spin rounded-full border-2",
          className,
        )}
        aria-hidden="true"
      />
      <span className="sr-only">{label}</span>
    </span>
  );
}
