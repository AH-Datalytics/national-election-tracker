import Link from "next/link";
import { STATE_NAMES, OFFICE_CATEGORIES } from "@/lib/constants";
import { formatDate, formatElectionType } from "@/lib/utils";
import RaceCard from "@/components/RaceCard";
import type { Race } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ElectionDetail {
  election_key: string;
  state: string;
  date: string;
  type: string;
  is_official: boolean;
  races: Race[];
}

async function fetchElection(code: string, key: string): Promise<ElectionDetail | null> {
  try {
    const res = await fetch(`${API_BASE}/api/${code}/elections/${key}`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    return res.json();
  } catch { return null; }
}

export default async function ElectionDetailPage({
  params,
}: {
  params: Promise<{ state: string; electionKey: string }>;
}) {
  const { state, electionKey } = await params;
  const code = state.toUpperCase();
  const name = STATE_NAMES[code] ?? code;
  const election = await fetchElection(code, electionKey);

  if (!election) {
    return (
      <div className="max-w-6xl mx-auto px-4 py-8">
        <p className="text-[var(--color-muted)]">Election not found or API not available.</p>
      </div>
    );
  }

  // Group races by office category
  const grouped = new Map<string, Race[]>();
  for (const race of election.races) {
    const cat = race.office_category || "Other";
    if (!grouped.has(cat)) grouped.set(cat, []);
    grouped.get(cat)!.push(race);
  }

  // Sort categories by OFFICE_CATEGORIES order
  const sortedCategories = [...grouped.keys()].sort((a, b) => {
    const ia = OFFICE_CATEGORIES.indexOf(a as typeof OFFICE_CATEGORIES[number]);
    const ib = OFFICE_CATEGORIES.indexOf(b as typeof OFFICE_CATEGORIES[number]);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-1" style={{ fontFamily: "var(--font-serif)", color: "var(--color-primary)" }}>
        {name} {formatElectionType(election.type)}
      </h1>
      <p className="text-sm text-[var(--color-muted)] mb-6">
        {formatDate(election.date)} · {election.races.length} races
        {election.is_official && " · Official results"}
      </p>

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
                isOfficial={election.is_official}
                isBallotMeasure={race.is_ballot_measure}
                compact
                href={`/${state}/elections/${electionKey}/${race.race_key}`}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
