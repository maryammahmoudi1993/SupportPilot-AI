import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// A valid API base URL so src/lib/config.ts's fail-fast validation passes
// during tests without every test file needing to stub process.env itself.
process.env.NEXT_PUBLIC_API_BASE_URL ??= "http://localhost:8000/api/v1";

// `globals: false` in vitest.config.ts means @testing-library/react's
// automatic afterEach cleanup never registers itself — do it explicitly so
// one test's rendered DOM doesn't leak into the next.
afterEach(() => {
  cleanup();
});
