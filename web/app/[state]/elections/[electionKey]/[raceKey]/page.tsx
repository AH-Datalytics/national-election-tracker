import { notFound } from "next/navigation";
import { STATE_NAMES } from "@/lib/constants";
import RaceCard from "@/components/RaceCard";
import CountyResultsTable from "@/components/CountyResultsTable";
import type { Race, CountyResult } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchRace(code: string, raceKey: string): Promise<Race | null> {
  try {
    const res = await fetch(`${API_BASE}/api/${code}/races/${raceKey}`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    return res.json();
  } catch { return null; }
}

async function fetchCountyResults(code: string, raceKey: string): Promise<CountyResult[]> {
  try {
    const res = await fetch(`${API_BASE}/api/${code}/races/${raceKey}/counties`, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    return res.json();
  } catch { return []; }
}

export default async function RaceDetailPage({
  params,
}: {
  params: Promise<{ state: string; electionKey: string; raceKey: string }>;
}) {
  const { state, raceKey } = await params;
  const code = state.toUpperCase();
  const [race, countyResults] = await Promise.all([
    fetchRace(code, raceKey),
    fetchCountyResults(code, raceKey),
  ]);

  if (!race) notFound();

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <div className="max-w-2xl">
        <RaceCard
          title={race.district ? `${race.office_name} \u2014 ${race.district}` : race.office_name}
          choices={race.choices}
          precinctsReporting={race.precincts_reporting}
          precinctsTotal={race.precincts_total}
          isBallotMeasure={race.is_ballot_measure}
        />
      </div>

      {countyResults.length > 0 && (
        <div className="mt-8">
          <h2 className="text-lg font-semibold mb-4" style={{ fontFamily: "var(--font-serif)" }}>
            County Results
          </h2>
          <CountyResultsTable countyResults={countyResults} choices={race.choices} />
        </div>
      )}
    </div>
  );
}
