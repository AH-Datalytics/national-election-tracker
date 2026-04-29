"use client";

import { useEffect, useState, use, useMemo } from "react";
import Link from "next/link";
import { STATE_NAMES } from "@/lib/constants";
import { formatDate, formatElectionType } from "@/lib/utils";
import RaceCard from "@/components/RaceCard";
import CountyResultsTable from "@/components/CountyResultsTable";
import ElectionMap from "@/components/ElectionMap";
import type { Race, CountyResult, Choice } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ElectionSummary {
  election_key: string;
  state: string;
  date: string;
  type: string;
  is_official: boolean;
}

export default function RaceDetailPage({
  params,
}: {
  params: Promise<{ state: string; electionKey: string; raceKey: string }>;
}) {
  const { state, electionKey, raceKey } = use(params);
  const code = state.toUpperCase();
  const name = STATE_NAMES[code] ?? code;

  const [race, setRace] = useState<Race | null>(null);
  const [countyResults, setCountyResults] = useState<CountyResult[]>([]);
  const [election, setElection] = useState<ElectionSummary | null>(null);
  const [loading, setLoading] = useState(true);

  /* Fetch race, county results, and election summary in parallel */
  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/${code}/races/${raceKey}`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
      fetch(`${API_BASE}/api/${code}/races/${raceKey}/counties`)
        .then((r) => (r.ok ? r.json() : []))
        .catch(() => []),
      fetch(`${API_BASE}/api/${code}/elections/${electionKey}`)
        .then((r) => {
          if (!r.ok) return null;
          return r.json().then(
            (d: { election_key: string; state: string; date: string; type: string; is_official: boolean }) => ({
              election_key: d.election_key,
              state: d.state,
              date: d.date,
              type: d.type,
              is_official: d.is_official,
            }),
          );
        })
        .catch(() => null),
    ]).then(([raceData, counties, elecData]) => {
      setRace(raceData as Race | null);
      setCountyResults(counties as CountyResult[]);
      setElection(elecData as ElectionSummary | null);
      setLoading(false);
    });
  }, [code, raceKey, electionKey]);

  /* Compute map data from county results */
  const countyData = useMemo(() => {
    if (!race || countyResults.length === 0) return {};

    return countyResults.reduce(
      (acc, cr) => {
        if (cr.choices.length === 0) return acc;
        const sorted = [...cr.choices].sort((a, b) => b.votes - a.votes);
        const leader = sorted[0];
        const total = sorted.reduce((s, c) => s + c.votes, 0);
        const margin =
          total > 0 ? ((leader.votes / total) * 100 - 50) * 2 : 0;
        const fullChoice = race.choices.find(
          (c) => c.choice_key === leader.choice_key,
        );
        acc[cr.county_code] = {
          leader: fullChoice?.name || leader.choice_key,
          party: fullChoice?.party || "",
          margin: Math.abs(margin),
        };
        return acc;
      },
      {} as Record<string, { leader: string; party: string; margin: number }>,
    );
  }, [race, countyResults]);

  /* Build county table data */
  const countyTableData = useMemo(() => {
    if (!race) return [];
    const choiceLookup = new Map<string, Choice>(
      race.choices.map((c) => [c.choice_key, c]),
    );
    return countyResults.map((cr) => ({
      county_code: cr.county_code,
      county_name: cr.county_name,
      choices: cr.choices.map((cc) => {
        const full = choiceLookup.get(cc.choice_key);
        return {
          choice_key: cc.choice_key,
          name: full?.name ?? cc.choice_key,
          party: full?.party ?? null,
          votes: cc.votes,
        };
      }),
      precincts_reporting: cr.precincts_reporting,
      precincts_total: cr.precincts_total,
    }));
  }, [race, countyResults]);

  if (loading) {
    return (
      <div
        style={{
          padding: 48,
          textAlign: "center",
          color: "var(--color-muted)",
        }}
      >
        Loading race data...
      </div>
    );
  }

  if (!race) {
    return (
      <div
        style={{
          maxWidth: 1200,
          margin: "0 auto",
          padding: "32px 16px",
        }}
      >
        <p style={{ color: "var(--color-muted)" }}>
          Race not found or API not available.
        </p>
      </div>
    );
  }

  const raceTitle = race.district
    ? `${race.office_name} \u2014 ${race.district}`
    : race.office_name;

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 16px" }}>
      {/* Breadcrumb */}
      <div
        style={{
          fontSize: "0.8125rem",
          color: "var(--color-muted)",
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 20,
          flexWrap: "wrap",
        }}
      >
        <Link
          href="/"
          style={{ color: "var(--color-muted)", textDecoration: "none" }}
        >
          Home
        </Link>
        <span style={{ color: "#ccc" }}>/</span>
        <Link
          href={`/${state}`}
          style={{ color: "var(--color-muted)", textDecoration: "none" }}
        >
          {name}
        </Link>
        <span style={{ color: "#ccc" }}>/</span>
        <Link
          href={`/${state}/elections/${electionKey}`}
          style={{ color: "var(--color-muted)", textDecoration: "none" }}
        >
          {election ? formatElectionType(election.type) : electionKey}
        </Link>
        <span style={{ color: "#ccc" }}>/</span>
        <span style={{ color: "var(--color-foreground)", fontWeight: 500 }}>
          {raceTitle}
        </span>
      </div>

      {/* Official/Unofficial badge */}
      {election && (
        <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 12 }}>
          <span
            style={{
              fontSize: "0.8125rem",
              color: "var(--color-muted)",
            }}
          >
            {formatDate(election.date)}
          </span>
          {election.is_official ? (
            <span
              style={{
                fontSize: "0.6875rem",
                fontWeight: 500,
                padding: "2px 8px",
                borderRadius: 3,
                backgroundColor: "#f0fdf4",
                color: "#15803d",
                border: "1px solid #bbf7d0",
              }}
            >
              Official
            </span>
          ) : (
            <span
              style={{
                fontSize: "0.6875rem",
                fontWeight: 500,
                padding: "2px 8px",
                borderRadius: 3,
                backgroundColor: "#fffbeb",
                color: "#b45309",
                border: "1px solid #fde68a",
              }}
            >
              Unofficial
            </span>
          )}
        </div>
      )}

      {/* Full RaceCard */}
      <div style={{ maxWidth: 600, marginBottom: 32 }}>
        <RaceCard
          title={raceTitle}
          choices={race.choices}
          precinctsReporting={race.precincts_reporting}
          precinctsTotal={race.precincts_total}
          isOfficial={election?.is_official}
          isBallotMeasure={race.is_ballot_measure}
        />
      </div>

      {/* Election Map for this race */}
      {Object.keys(countyData).length > 0 && (
        <div style={{ marginBottom: 32 }}>
          <h3 className="section-header">County Map</h3>
          <ElectionMap
            state={state}
            countyData={countyData}
            height={450}
            onCountyClick={() => {}}
          />
        </div>
      )}

      {/* County results table */}
      {countyTableData.length > 0 && (
        <div style={{ marginTop: 32 }}>
          <CountyResultsTable counties={countyTableData} />
        </div>
      )}
    </div>
  );
}
