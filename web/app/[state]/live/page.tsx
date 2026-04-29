"use client";

import { useEffect, useState, use } from "react";
import { STATE_NAMES, OFFICE_CATEGORIES } from "@/lib/constants";
import RaceCard from "@/components/RaceCard";
import type { LiveStatus, Race } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function LivePage({ params }: { params: Promise<{ state: string }> }) {
  const { state } = use(params);
  const code = state.toUpperCase();
  const name = STATE_NAMES[code] ?? code;

  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [races, setRaces] = useState<Race[]>([]);
  const [lastPoll, setLastPoll] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const sRes = await fetch(`${API_BASE}/api/${code}/live/status`);
        if (sRes.ok) {
          const s: LiveStatus = await sRes.json();
          if (!cancelled) setStatus(s);

          if (s.active || s.election_key) {
            const rRes = await fetch(`${API_BASE}/api/${code}/live/races`);
            if (rRes.ok && !cancelled) {
              setRaces(await rRes.json());
            }
          }
        }
        if (!cancelled) setLastPoll(new Date().toLocaleTimeString());
      } catch {
        // API not available
      }
    }

    poll();
    const interval = setInterval(poll, 30_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [code]);

  // Group races by category
  const grouped = new Map<string, Race[]>();
  for (const race of races) {
    const cat = race.office_category || "Other";
    if (!grouped.has(cat)) grouped.set(cat, []);
    grouped.get(cat)!.push(race);
  }
  const sortedCategories = [...grouped.keys()].sort((a, b) => {
    const ia = OFFICE_CATEGORIES.indexOf(a as typeof OFFICE_CATEGORIES[number]);
    const ib = OFFICE_CATEGORIES.indexOf(b as typeof OFFICE_CATEGORIES[number]);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <div className="flex items-baseline justify-between mb-6">
        <h1 className="text-2xl font-bold" style={{ fontFamily: "var(--font-serif)", color: "var(--color-primary)" }}>
          Election Night \u2014 {name}
        </h1>
        {lastPoll && (
          <span className="text-xs text-[var(--color-muted)]">Updated {lastPoll}</span>
        )}
      </div>

      {!status && (
        <p className="text-[var(--color-muted)]">Connecting to live results...</p>
      )}

      {status && !status.active && races.length === 0 && (
        <div className="text-center py-12">
          <p className="text-lg text-[var(--color-muted)] mb-2">No active election</p>
          <p className="text-sm text-[var(--color-muted)]">
            Check back on election night for live results.
          </p>
          <a href={`/${state}/elections`} className="inline-block mt-4 text-sm text-[var(--color-accent)] hover:underline">
            View historical results \u2192
          </a>
        </div>
      )}

      {races.length > 0 && (
        <>
          {status?.active && (
            <div className="mb-4 px-3 py-2 bg-blue-50 border border-blue-200 rounded text-sm">
              Results are updating every 30 seconds. Results are unofficial.
            </div>
          )}
          {sortedCategories.map((category) => (
            <div key={category} className="mb-8">
              <h2 className="text-lg font-semibold mb-3 pb-1 border-b border-gray-200" style={{ fontFamily: "var(--font-serif)" }}>
                {category}
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {grouped.get(category)!.map((race) => (
                  <RaceCard
                    key={race.race_key}
                    title={race.district ? `${race.office_name} \u2014 ${race.district}` : race.office_name}
                    choices={race.choices}
                    precinctsReporting={race.precincts_reporting}
                    precinctsTotal={race.precincts_total}
                    isBallotMeasure={race.is_ballot_measure}
                    compact
                  />
                ))}
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
