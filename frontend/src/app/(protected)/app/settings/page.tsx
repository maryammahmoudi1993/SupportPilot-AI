import { redirect } from "next/navigation";

/**
 * `/app/settings` is the one coherent Settings nav entry (master prompt
 * Part D §16-17); Chunk 1's only real sub-route is Members, so the index
 * redirects there rather than rendering a placeholder overview page. Later
 * chunks add real workspace/account/security sub-routes alongside it.
 */
export default function Page() {
  redirect("/app/settings/members");
}
