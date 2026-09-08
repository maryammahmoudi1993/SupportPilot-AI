import { Badge } from "@/components/ui/badge";

/** Semantic text + color — never color alone (see frontend/README.md, "Status visuals"). */
export function CustomerStatusBadge({ isActive }: { isActive: boolean }) {
  return <Badge variant={isActive ? "success" : "neutral"}>{isActive ? "Active" : "Inactive"}</Badge>;
}
