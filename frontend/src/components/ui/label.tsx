import { type LabelHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/utils";

export const Label = forwardRef<HTMLLabelElement, LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => {
    return (
      <label
        ref={ref}
        className={cn("text-text-primary mb-1.5 block text-sm font-medium", className)}
        {...props}
      />
    );
  },
);
Label.displayName = "Label";
