/**
 * Shareable/restorable URL query-string state for the Integrations page —
 * same pattern as features/knowledge/url-params.ts. Only `page` is real for
 * the Connections list (see api.ts's schema-gap note: no filter/search/
 * ordering exists for it), so this is deliberately smaller than knowledge's
 * equivalent. Phase 22 Chunk 2 adds `tab`: one route (`/app/integrations`)
 * hosts three real tabs (Connections/Webhooks/Deliveries, master prompt
 * Part E §17) — `tab` selects between them and each tab keeps its own
 * page param so switching tabs never clobbers another tab's state in the
 * URL (see features/webhooks/url-params.ts for the other two tabs' params).
 */
import type { IntegrationConnectionListParams } from "@/features/integrations/types";
import { DEFAULT_INTEGRATION_CONNECTION_LIST_PARAMS } from "@/features/integrations/types";

export type IntegrationsTab = "connections" | "webhooks" | "deliveries";

export function parseIntegrationsTab(searchParams: URLSearchParams): IntegrationsTab {
  const raw = searchParams.get("tab");
  if (raw === "webhooks") {
    return "webhooks";
  }
  if (raw === "deliveries") {
    return "deliveries";
  }
  return "connections";
}

function parsePage(raw: string | null, fallback: number): number {
  if (!raw || !/^[1-9]\d*$/.test(raw)) {
    return fallback;
  }
  const page = Number(raw);
  return Number.isSafeInteger(page) ? page : fallback;
}

export function parseIntegrationConnectionListParams(
  searchParams: URLSearchParams,
): IntegrationConnectionListParams {
  return {
    page: parsePage(searchParams.get("page"), DEFAULT_INTEGRATION_CONNECTION_LIST_PARAMS.page),
  };
}

export function buildIntegrationConnectionListQueryString(
  params: IntegrationConnectionListParams,
): string {
  const search = new URLSearchParams();
  if (params.page > 1) {
    search.set("page", String(params.page));
  }
  const query = search.toString();
  return query.length > 0 ? `?${query}` : "";
}
