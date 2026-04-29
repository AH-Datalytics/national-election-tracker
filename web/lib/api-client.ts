/* ------------------------------------------------------------------ */
/*  Typed fetch client for the National Election Tracker API           */
/*  Backend: FastAPI on Hetzner                                        */
/* ------------------------------------------------------------------ */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Fetch JSON from the backend API with optional ISR revalidation.
 *
 * @param path  - API path after /api (e.g. "/states" or "/IN/elections")
 * @param revalidate - seconds to cache (default 3600 = 1 hour)
 */
export async function fetchApi<T>(
  path: string,
  revalidate?: number,
): Promise<T> {
  const url = `${API_BASE}/api${path}`;
  const res = await fetch(url, {
    next: { revalidate: revalidate ?? 3600 },
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${url}`);
  }
  return res.json() as Promise<T>;
}

/**
 * Client-side fetch (no Next.js cache options).
 * Used in 'use client' components like the live dashboard.
 */
export async function fetchApiClient<T>(path: string): Promise<T> {
  const url = `${API_BASE}/api${path}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${url}`);
  }
  return res.json() as Promise<T>;
}
