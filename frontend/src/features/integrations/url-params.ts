/**
 * Shareable/restorable URL query-string state for the Integrations list —
 * same pattern as features/knowledge/url-params.ts. Only `page` is real
 * (see api.ts's schema-gap note: no filter/search/ordering exists for this
 * list), so this is deliberately smaller than knowledge's equivalent.
 */
import type { IntegrationConnectionListParams } from "@/features/integrations/types";
import { DEFAULT_INTEGRATION_CONNECTION_LIST_PARAMS } from "@/features/integrations/types";

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
