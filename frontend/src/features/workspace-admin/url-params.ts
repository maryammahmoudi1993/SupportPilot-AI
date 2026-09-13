/**
 * Shareable/restorable URL query-string state for the workspace Members
 * page — same pattern as features/integrations/url-params.ts. Only `page`
 * is real (see api.ts's schema-gap note: no filter/search/ordering exists
 * for this list).
 */
import type { WorkspaceMemberListParams } from "@/features/workspace-admin/types";
import { DEFAULT_WORKSPACE_MEMBER_LIST_PARAMS } from "@/features/workspace-admin/types";

function parsePage(raw: string | null, fallback: number): number {
  if (!raw || !/^[1-9]\d*$/.test(raw)) {
    return fallback;
  }
  const page = Number(raw);
  return Number.isSafeInteger(page) ? page : fallback;
}

export function parseWorkspaceMemberListParams(
  searchParams: URLSearchParams,
): WorkspaceMemberListParams {
  return {
    page: parsePage(searchParams.get("page"), DEFAULT_WORKSPACE_MEMBER_LIST_PARAMS.page),
  };
}

export function buildWorkspaceMemberListQueryString(
  params: WorkspaceMemberListParams,
): string {
  const search = new URLSearchParams();
  if (params.page > 1) {
    search.set("page", String(params.page));
  }
  const query = search.toString();
  return query.length > 0 ? `?${query}` : "";
}
