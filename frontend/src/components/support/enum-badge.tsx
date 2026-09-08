import { Badge, type BadgeProps } from "@/components/ui/badge";

/**
 * A status/category badge for a backend enum field — semantic text (never
 * color alone) with a safe fallback for a value the frontend doesn't
 * recognize yet. Backend enums evolve; a frontend build should never crash
 * or blank out a row just because a newer status value than it knows about
 * showed up (see frontend/README.md, "Status visuals").
 */
export function EnumBadge<T extends string>({
  value,
  labels,
  variants,
  fallbackVariant = "neutral",
}: {
  value: T;
  labels: Partial<Record<T, string>>;
  variants: Partial<Record<T, BadgeProps["variant"]>>;
  fallbackVariant?: BadgeProps["variant"];
}) {
  const label = labels[value] ?? value;
  const variant = variants[value] ?? fallbackVariant;
  return <Badge variant={variant}>{label}</Badge>;
}
