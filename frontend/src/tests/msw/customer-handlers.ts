/**
 * Request-level mocks for the customers domain, mirroring the real backend
 * contract (customers/views.py, customers/selectors.py, customers/serializers.py):
 * workspace-scoped storage, `search`/`is_active` filtering, DRF
 * `PageNumberPagination`'s `{count,next,previous,results}` envelope, and the
 * `{error:{code,message}}` failure envelope (see common/exceptions.py).
 */
import { HttpResponse, delay, http } from "msw";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface CustomerFixture {
  id: string;
  external_id: string | null;
  first_name: string;
  last_name: string;
  display_name: string;
  email: string | null;
  phone: string | null;
  company: string;
  notes: string;
  metadata: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export function makeCustomerFixture(overrides: Partial<CustomerFixture> & { id: string }): CustomerFixture {
  return {
    external_id: null,
    first_name: "",
    last_name: "",
    display_name: "Unnamed customer",
    email: null,
    phone: null,
    company: "",
    notes: "",
    metadata: {},
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export const customerMockState = {
  customersByWorkspace: {} as Record<string, CustomerFixture[]>,
  listNetworkError: false,
  listHang: false,
  detailNetworkError: false,
  detailHang: false,
  /** Counts real requests made to the list endpoint — used to assert no request-per-keystroke / no duplicate fetches. */
  listCallCount: 0,
};

export function seedCustomers(workspaceId: string, customers: CustomerFixture[]): void {
  customerMockState.customersByWorkspace[workspaceId] = customers;
}

export function resetCustomerMockState(): void {
  customerMockState.customersByWorkspace = {};
  customerMockState.listNetworkError = false;
  customerMockState.listHang = false;
  customerMockState.detailNetworkError = false;
  customerMockState.detailHang = false;
  customerMockState.listCallCount = 0;
}

function matchesSearch(customer: CustomerFixture, search: string): boolean {
  const needle = search.toLowerCase();
  return (
    customer.display_name.toLowerCase().includes(needle) ||
    customer.first_name.toLowerCase().includes(needle) ||
    customer.last_name.toLowerCase().includes(needle) ||
    (customer.email ?? "").toLowerCase().includes(needle) ||
    (customer.phone ?? "").toLowerCase().includes(needle) ||
    (customer.external_id ?? "").toLowerCase().includes(needle)
  );
}

export const customerHandlers = [
  http.get(`${BASE}/api/v1/workspaces/:workspaceId/customers/`, async ({ request, params }) => {
    customerMockState.listCallCount += 1;

    if (customerMockState.listNetworkError) {
      return HttpResponse.error();
    }
    if (customerMockState.listHang) {
      await delay("infinite");
    }

    const workspaceId = params.workspaceId as string;
    const url = new URL(request.url);
    const search = url.searchParams.get("search");
    const isActiveRaw = url.searchParams.get("is_active");
    const page = Number(url.searchParams.get("page") ?? "1");
    const pageSize = Number(url.searchParams.get("page_size") ?? "50");

    let results = customerMockState.customersByWorkspace[workspaceId] ?? [];
    if (search) {
      results = results.filter((customer) => matchesSearch(customer, search));
    }
    if (isActiveRaw !== null) {
      const isActive = isActiveRaw === "true";
      results = results.filter((customer) => customer.is_active === isActive);
    }

    const count = results.length;
    const start = (page - 1) * pageSize;
    const pageResults = results.slice(start, start + pageSize);
    const hasNext = start + pageSize < count;
    const hasPrevious = page > 1;

    const nextUrl = hasNext ? `${url.origin}${url.pathname}?page=${page + 1}` : null;
    const previousUrl = hasPrevious
      ? `${url.origin}${url.pathname}${page - 1 > 1 ? `?page=${page - 1}` : ""}`
      : null;

    return HttpResponse.json({
      count,
      next: nextUrl,
      previous: previousUrl,
      results: pageResults,
    });
  }),

  http.get(`${BASE}/api/v1/workspaces/:workspaceId/customers/:customerId/`, async ({ params }) => {
    if (customerMockState.detailNetworkError) {
      return HttpResponse.error();
    }
    if (customerMockState.detailHang) {
      await delay("infinite");
    }

    const workspaceId = params.workspaceId as string;
    const customerId = params.customerId as string;
    const customer = (customerMockState.customersByWorkspace[workspaceId] ?? []).find(
      (candidate) => candidate.id === customerId,
    );

    if (!customer) {
      // A customer ID from a *different* workspace resolves exactly the
      // same way as one that never existed — see
      // customers/selectors.py `customer_get_for_workspace_or_404`.
      return HttpResponse.json(
        { error: { code: "not_found", message: "Customer not found." } },
        { status: 404 },
      );
    }

    return HttpResponse.json(customer);
  }),
];
