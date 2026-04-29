import Link from "next/link";
import { STATE_NAMES } from "@/lib/constants";
import { formatDate, formatElectionType } from "@/lib/utils";
import type { State, Election } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchState(code: string): Promise<State | null> {
  try {
    const res = await fetch(`${API_BASE}/api/states/${code}`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    return res.json();
  } catch { return null; }
}

async function fetchElections(code: string): Promise<Election[]> {
  try {
    const res = await fetch(`${API_BASE}/api/${code}/elections?limit=10`, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    return res.json();
  } catch { return []; }
}

export default async function StatePage({ params }: { params: Promise<{ state: string }> }) {
  const { state } = await params;
  const code = state.toUpperCase();
  const name = STATE_NAMES[code] ?? code;
  const [stateData, elections] = await Promise.all([fetchState(code), fetchElections(code)]);

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-1" style={{ fontFamily: "var(--font-serif)", color: "var(--color-primary)" }}>
        {name}
      </h1>
      {stateData && (
        <p className="text-sm text-[var(--color-muted)] mb-6">
          {stateData.election_count} elections · {stateData.race_count?.toLocaleString() ?? 0} races
          {stateData.earliest_date && stateData.latest_date && (
            <> · {formatDate(stateData.earliest_date)} – {formatDate(stateData.latest_date)}</>
          )}
        </p>
      )}
      {!stateData && (
        <p className="text-[var(--color-muted)] mb-6">Data not yet available. Connect to the API to see results.</p>
      )}
      <h2 className="text-lg font-semibold mb-4" style={{ fontFamily: "var(--font-serif)" }}>Recent Elections</h2>
      {elections.length === 0 ? (
        <p className="text-[var(--color-muted)]">No elections loaded yet.</p>
      ) : (
        <div className="space-y-2">
          {elections.map((e) => (
            <Link key={e.election_key} href={`/${state}/elections/${e.election_key}`} className="block border border-gray-200 px-4 py-3 hover:border-[var(--color-accent)] transition-colors">
              <div className="flex items-baseline justify-between">
                <span className="font-medium">{formatElectionType(e.type)}</span>
                <span className="text-sm text-[var(--color-muted)]">{formatDate(e.date)}</span>
              </div>
              <div className="text-sm text-[var(--color-muted)]">{e.race_count} races</div>
            </Link>
          ))}
        </div>
      )}
      <div className="mt-6">
        <Link href={`/${state}/elections`} className="text-sm text-[var(--color-accent)] hover:underline">
          View all elections →
        </Link>
      </div>
    </div>
  );
}
