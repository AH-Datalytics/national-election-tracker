import Link from "next/link";
import { STATE_NAMES } from "@/lib/constants";
import { formatDate, formatElectionType } from "@/lib/utils";
import type { Election } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchElections(code: string): Promise<Election[]> {
  try {
    const res = await fetch(`${API_BASE}/api/${code}/elections`, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    return res.json();
  } catch { return []; }
}

export default async function ElectionsPage({ params }: { params: Promise<{ state: string }> }) {
  const { state } = await params;
  const code = state.toUpperCase();
  const name = STATE_NAMES[code] ?? code;
  const elections = await fetchElections(code);

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-6" style={{ fontFamily: "var(--font-serif)", color: "var(--color-primary)" }}>
        {name} Elections
      </h1>
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
    </div>
  );
}
