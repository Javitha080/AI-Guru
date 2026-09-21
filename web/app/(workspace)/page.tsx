import { redirect } from "next/navigation";

/**
 * Root page — server redirect to /home.
 *
 * Previously a client component returning `null` + `router.replace("/home")`,
 * which left a blank screen until the client bundle compiled, hydrated, and
 * ran the effect (17s+ on a cold Turbopack compile). A server `redirect()`
 * resolves before any client JS loads, so `/` never paints blank.
 *
 * Backward compat: `/?session=xxx` maps to `/home/xxx`; every other query
 * param (capability, tool, agent, …) is forwarded unchanged.
 */
type SearchParams = Record<string, string | string[] | undefined>;

export default async function WorkspaceRootPage({
  searchParams,
}: {
  searchParams?: Promise<SearchParams>;
}) {
  const resolved: SearchParams = searchParams ? await searchParams : {};

  const first = (v: string | string[] | undefined) =>
    Array.isArray(v) ? v[0] : v;
  const all = (v: string | string[] | undefined): string[] =>
    Array.isArray(v) ? v : v === undefined ? [] : [v];

  const session = first(resolved.session);
  const target = session ? `/home/${encodeURIComponent(session)}` : "/home";

  const query: string[] = [];
  for (const [key, value] of Object.entries(resolved)) {
    if (key === "session") continue;
    for (const v of all(value)) {
      query.push(`${encodeURIComponent(key)}=${encodeURIComponent(v)}`);
    }
  }

  redirect(query.length ? `${target}?${query.join("&")}` : target);
}
