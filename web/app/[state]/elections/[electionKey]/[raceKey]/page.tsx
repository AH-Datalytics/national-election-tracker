"use client";

import { useEffect, useState, use, useMemo, useCallback } from "react";
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

interface PrecinctChoiceResult {
  name: string;
  party: string | null;
  choice_key: string;
  vote_total: number;
}

interface PrecinctResult {
  precinct_id: string;
  choices: PrecinctChoiceResult[];
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

  // Precinct drill-down state
  const [selectedCounty, setSelectedCounty] = useState<string | null>(null);
  const [selectedCountyName, setSelectedCountyName] = useState<string>("");
  const [precinctResults, setPrecinctResults] = useState<PrecinctResult[]>([]);
  const [precinctLoading, setPrecinctLoading] = useState(false);
  const [hasPrecinct, setHasPrecinct] = useState(false);

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
            (d: {
              election_key: string;
              state: string;
              date: string;
              type: string;
              is_official: boolean;
            }) => ({
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
      const r = raceData as Race | null;
      setRace(r);
      setCountyResults(counties as CountyResult[]);
      setElection(elecData as ElectionSummary | null);
      setHasPrecinct(
        !!(r && "has_precinct_data" in r && (r as Record<string, unknown>).has_precinct_data),
      );
      setLoading(false);
    });
  }, [code, raceKey, electionKey]);

  /* Fetch precinct results when a county is selected */
  const handleCountyClick = useCallback(
    (countyCode: string, countyName: string) => {
      setSelectedCounty(countyCode);
      setSelectedCountyName(countyName);
      setPrecinctLoading(true);

      fetch(
        `${API_BASE}/api/${code}/races/${raceKey}/precincts/${countyCode}`,
      )
        .then((r) => (r.ok ? r.json() : []))
        .then((data: PrecinctResult[]) => {
          setPrecinctResults(data);
          setPrecinctLoading(false);
        })
        .catch(() => {
          setPrecinctResults([]);
          setPrecinctLoading(false);
        });
    },
    [code, raceKey],
  );

  const handleBackToState = useCallback(() => {
    setSelectedCounty(null);
    setSelectedCountyName("");
    setPrecinctResults([]);
  }, []);

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
      {} as Record<
        string,
        { leader: string; party: string; margin: number }
      >,
    );
  }, [race, countyResults]);

  /* Compute precinct map data from precinct results */
  const precinctData = useMemo(() => {
    if (precinctResults.length === 0) return undefined;

    return precinctResults.reduce(
      (acc, pr) => {
        if (pr.choices.length === 0) return acc;
        const sorted = [...pr.choices].sort(
          (a, b) => b.vote_total - a.vote_total,
        );
        const leader = sorted[0];
        const total = sorted.reduce((s, c) => s + c.vote_total, 0);
        const margin =
          total > 0 ? ((leader.vote_total / total) * 100 - 50) * 2 : 0;
        acc[pr.precinct_id] = {
          leader: leader.name,
          party: leader.party || "",
          margin: Math.abs(margin),
        };
        return acc;
      },
      {} as Record<
        string,
        { leader: string; party: string; margin: number }
      >,
    );
  }, [precinctResults]);

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
        <div
          style={{
            marginBottom: 16,
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
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

      {/* Election Map with precinct drill-down */}
      {Object.keys(countyData).length > 0 && (
        <div style={{ marginBottom: 32 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 8,
            }}
          >
            <h3 className="section-header" style={{ margin: 0 }}>
              {selectedCounty
                ? `${selectedCountyName} — Precinct Map`
                : "County Map"}
            </h3>
            {hasPrecinct && !selectedCounty && (
              <span
                style={{
                  fontSize: "0.75rem",
                  color: "var(--color-muted)",
                  fontStyle: "italic",
                }}
              >
                Click a county to see precinct results
              </span>
            )}
          </div>
          <ElectionMap
            state={state}
            countyData={countyData}
            precinctData={precinctData}
            selectedCounty={selectedCounty}
            height={450}
            onCountyClick={handleCountyClick}
            onBackToState={handleBackToState}
          />
        </div>
      )}

      {/* Precinct results table (when drilled down) */}
      {selectedCounty && precinctResults.length > 0 && (
        <div style={{ marginBottom: 32 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 8,
            }}
          >
            <h3 className="section-header" style={{ margin: 0 }}>
              {selectedCountyName} — Precinct Results
            </h3>
            <button
              onClick={handleBackToState}
              style={{
                fontSize: "0.8125rem",
                color: "var(--color-accent)",
                background: "none",
                border: "none",
                cursor: "pointer",
                textDecoration: "underline",
              }}
            >
              Back to county results
            </button>
          </div>
          <PrecinctResultsTable precincts={precinctResults} />
        </div>
      )}

      {selectedCounty && precinctLoading && (
        <div
          style={{
            padding: 24,
            textAlign: "center",
            color: "var(--color-muted)",
          }}
        >
          Loading precinct data...
        </div>
      )}

      {selectedCounty &&
        !precinctLoading &&
        precinctResults.length === 0 && (
          <div
            style={{
              padding: 24,
              textAlign: "center",
              color: "var(--color-muted)",
              fontSize: "0.875rem",
            }}
          >
            No precinct-level data available for this county.
          </div>
        )}

      {/* County results table (show when not drilled down) */}
      {!selectedCounty && countyTableData.length > 0 && (
        <div style={{ marginTop: 32 }}>
          <CountyResultsTable counties={countyTableData} />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Precinct Results Table                                            */
/* ------------------------------------------------------------------ */

function PrecinctResultsTable({
  precincts,
}: {
  precincts: PrecinctResult[];
}) {
  // Get top 3 candidates by total votes across all precincts
  const candidateTotals = new Map<
    string,
    { name: string; party: string | null; total: number }
  >();
  for (const p of precincts) {
    for (const c of p.choices) {
      const existing = candidateTotals.get(c.choice_key);
      if (existing) {
        existing.total += c.vote_total;
      } else {
        candidateTotals.set(c.choice_key, {
          name: c.name,
          party: c.party,
          total: c.vote_total,
        });
      }
    }
  }
  const topCandidates = [...candidateTotals.entries()]
    .sort((a, b) => b[1].total - a[1].total)
    .slice(0, 3);

  const partyColor = (party: string | null) => {
    if (!party) return "#666";
    const p = party.toUpperCase();
    if (p.includes("DEM")) return "#0015BC";
    if (p.includes("REP")) return "#E81B23";
    if (p.includes("LIB") || p.includes("LBT")) return "#FED105";
    return "#666";
  };

  // Sort precincts by name
  const sorted = [...precincts].sort((a, b) =>
    a.precinct_id.localeCompare(b.precinct_id, undefined, { numeric: true }),
  );

  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: "0.8125rem",
        }}
      >
        <thead>
          <tr
            style={{
              borderBottom: "2px solid var(--color-border)",
              textAlign: "left",
            }}
          >
            <th style={{ padding: "8px 12px", fontWeight: 600 }}>Precinct</th>
            {topCandidates.map(([key, info]) => (
              <th
                key={key}
                style={{
                  padding: "8px 12px",
                  fontWeight: 600,
                  textAlign: "right",
                  borderBottom: `3px solid ${partyColor(info.party)}`,
                }}
              >
                {info.name}
              </th>
            ))}
            <th
              style={{
                padding: "8px 12px",
                fontWeight: 600,
                textAlign: "right",
              }}
            >
              Total
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((p, i) => {
            const choiceMap = new Map(
              p.choices.map((c) => [c.choice_key, c.vote_total]),
            );
            const total = p.choices.reduce(
              (s, c) => s + c.vote_total,
              0,
            );
            const winner = [...p.choices].sort(
              (a, b) => b.vote_total - a.vote_total,
            )[0];

            return (
              <tr
                key={p.precinct_id}
                style={{
                  borderBottom: "1px solid var(--color-border)",
                  backgroundColor:
                    i % 2 === 0
                      ? "transparent"
                      : "rgba(0,0,0,0.02)",
                }}
              >
                <td
                  style={{
                    padding: "6px 12px",
                    fontWeight: 500,
                  }}
                >
                  {p.precinct_id}
                </td>
                {topCandidates.map(([key]) => {
                  const votes = choiceMap.get(key) || 0;
                  const isWinner = winner?.choice_key === key;
                  return (
                    <td
                      key={key}
                      style={{
                        padding: "6px 12px",
                        textAlign: "right",
                        fontWeight: isWinner ? 700 : 400,
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {votes.toLocaleString()}
                    </td>
                  );
                })}
                <td
                  style={{
                    padding: "6px 12px",
                    textAlign: "right",
                    fontVariantNumeric: "tabular-nums",
                    color: "var(--color-muted)",
                  }}
                >
                  {total.toLocaleString()}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
