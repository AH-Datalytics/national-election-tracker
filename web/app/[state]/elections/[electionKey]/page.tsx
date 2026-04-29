"use client";

import { useEffect, useState, use, useCallback } from "react";
import { STATE_NAMES, OFFICE_CATEGORIES } from "@/lib/constants";
import { formatDate, formatElectionType } from "@/lib/utils";
import RaceCard from "@/components/RaceCard";
import ElectionMap from "@/components/ElectionMap";
import type { Race, CountyResult } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ElectionDetail {
  election_key: string;
  state: string;
  date: string;
  type: string;
  is_official: boolean;
  races: Race[];
}

export default function ElectionExplorerPage({
  params,
}: {
  params: Promise<{ state: string; electionKey: string }>;
}) {
  const { state, electionKey } = use(params);
  const code = state.toUpperCase();
  const name = STATE_NAMES[code] ?? code;

  const [election, setElection] = useState<ElectionDetail | null>(null);
  const [selectedRaceKey, setSelectedRaceKey] = useState<string | null>(null);
  const [countyResults, setCountyResults] = useState<CountyResult[]>([]);
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  /* Fetch election on mount */
  useEffect(() => {
    fetch(`${API_BASE}/api/${code}/elections/${electionKey}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: ElectionDetail | null) => {
        setElection(data);
        if (data?.races?.length) {
          setSelectedRaceKey(data.races[0].race_key);
        }
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [code, electionKey]);

  /* Fetch county results when selected race changes */
  useEffect(() => {
    if (!selectedRaceKey) return;
    fetch(`${API_BASE}/api/${code}/races/${selectedRaceKey}/counties`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: CountyResult[]) => setCountyResults(data))
      .catch(() => setCountyResults([]));
  }, [code, selectedRaceKey]);

  /* Compute map data from county results */
  const countyData = useCallback(() => {
    if (!election || countyResults.length === 0) return {};

    const raceChoices =
      election.races.find((r) => r.race_key === selectedRaceKey)?.choices || [];

    return countyResults.reduce(
      (acc, cr) => {
        if (cr.choices.length === 0) return acc;
        const sorted = [...cr.choices].sort((a, b) => b.votes - a.votes);
        const leader = sorted[0];
        const total = sorted.reduce((s, c) => s + c.votes, 0);
        const margin =
          total > 0 ? ((leader.votes / total) * 100 - 50) * 2 : 0;
        const fullChoice = raceChoices.find(
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
  }, [election, countyResults, selectedRaceKey])();

  /* Group races by category */
  const allRaces = election?.races || [];
  const categories = [...new Set(allRaces.map((r) => r.office_category || "Other"))];
  const sortedCats = categories.sort((a, b) => {
    const ia = OFFICE_CATEGORIES.indexOf(a as (typeof OFFICE_CATEGORIES)[number]);
    const ib = OFFICE_CATEGORIES.indexOf(b as (typeof OFFICE_CATEGORIES)[number]);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });

  const filteredRaces = activeCategory
    ? allRaces.filter((r) => (r.office_category || "Other") === activeCategory)
    : allRaces;

  if (loading) {
    return (
      <div
        style={{ padding: 48, textAlign: "center", color: "var(--color-muted)" }}
      >
        Loading election data...
      </div>
    );
  }

  if (!election) {
    return (
      <div
        style={{ padding: 48, textAlign: "center", color: "var(--color-muted)" }}
      >
        Election not found.
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "calc(100vh - 110px)",
      }}
    >
      {/* Header bar */}
      <div
        style={{
          padding: "12px 16px",
          borderBottom: "1px solid var(--color-border)",
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          flexShrink: 0,
        }}
      >
        <h1
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "1.25rem",
            fontWeight: 700,
            margin: 0,
          }}
        >
          {name} {formatElectionType(election.type)}
        </h1>
        <span
          style={{
            fontSize: "0.8125rem",
            color: "var(--color-muted)",
            whiteSpace: "nowrap",
          }}
        >
          {formatDate(election.date)} &middot; {election.races.length} race
          {election.races.length !== 1 ? "s" : ""}
          {election.is_official && (
            <span
              style={{
                marginLeft: 8,
                fontSize: "0.6875rem",
                padding: "1px 6px",
                borderRadius: 3,
                backgroundColor: "#f0fdf4",
                color: "#15803d",
                border: "1px solid #bbf7d0",
              }}
            >
              Official
            </span>
          )}
        </span>
      </div>

      {/* Main content: Map + Race list */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Map panel */}
        <div
          style={{
            flex: "1 1 60%",
            position: "relative",
            minHeight: 0,
          }}
        >
          <ElectionMap
            state={state}
            countyData={countyData}
            height={undefined}
            onCountyClick={() => {}}
          />
        </div>

        {/* Race list panel */}
        <div
          style={{
            flex: "1 1 40%",
            overflowY: "auto",
            borderLeft: "1px solid var(--color-border)",
            background: "var(--color-background)",
            minHeight: 0,
          }}
        >
          {/* Category filter tabs */}
          <div
            style={{
              padding: "8px 12px",
              borderBottom: "1px solid var(--color-border)",
              display: "flex",
              gap: 4,
              flexWrap: "wrap",
              position: "sticky",
              top: 0,
              background: "var(--color-background)",
              zIndex: 1,
            }}
          >
            <CategoryButton
              label={`All (${allRaces.length})`}
              active={!activeCategory}
              onClick={() => setActiveCategory(null)}
            />
            {sortedCats.map((cat) => {
              const count = allRaces.filter(
                (r) => (r.office_category || "Other") === cat,
              ).length;
              return (
                <CategoryButton
                  key={cat}
                  label={`${cat} (${count})`}
                  active={activeCategory === cat}
                  onClick={() => setActiveCategory(cat)}
                />
              );
            })}
          </div>

          {/* Race cards */}
          <div style={{ padding: 12 }}>
            {filteredRaces.map((race) => (
              <div
                key={race.race_key}
                onClick={() => setSelectedRaceKey(race.race_key)}
                style={{
                  marginBottom: 8,
                  cursor: "pointer",
                  borderLeft:
                    selectedRaceKey === race.race_key
                      ? "3px solid var(--color-accent)"
                      : "3px solid transparent",
                  paddingLeft: 4,
                  transition: "border-color 0.15s",
                }}
              >
                <RaceCard
                  title={
                    race.district
                      ? `${race.office_name} \u2014 ${race.district}`
                      : race.office_name
                  }
                  choices={race.choices}
                  precinctsReporting={race.precincts_reporting}
                  precinctsTotal={race.precincts_total}
                  isOfficial={election.is_official}
                  isBallotMeasure={race.is_ballot_measure}
                  compact
                  href={`/${state}/elections/${electionKey}/${race.race_key}`}
                />
              </div>
            ))}
            {filteredRaces.length === 0 && (
              <p
                style={{
                  color: "var(--color-muted)",
                  fontSize: "0.875rem",
                  textAlign: "center",
                  padding: 24,
                }}
              >
                No races in this category.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* Inline category button used by the filter tabs */
function CategoryButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "4px 12px",
        fontSize: "0.75rem",
        fontWeight: 600,
        border: "1px solid var(--color-border)",
        borderRadius: 3,
        background: active ? "var(--color-foreground)" : "transparent",
        color: active ? "#fff" : "var(--color-muted)",
        cursor: "pointer",
        transition: "all 0.15s",
      }}
    >
      {label}
    </button>
  );
}
