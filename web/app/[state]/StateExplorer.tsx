"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import Link from "next/link";
import { OFFICE_CATEGORIES } from "@/lib/constants";
import { formatDate, formatElectionType } from "@/lib/utils";
import RaceCard from "@/components/RaceCard";
import ElectionMap from "@/components/ElectionMap";
import type { Race, CountyResult, Election } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ElectionDetail {
  election_key: string;
  state: string;
  date: string;
  type: string;
  is_official: boolean;
  races: Race[];
}

interface StateExplorerProps {
  stateCode: string;
  stateName: string;
  countyLabel: string;
  elections: Election[];
}

export default function StateExplorer({
  stateCode,
  stateName,
  countyLabel,
  elections,
}: StateExplorerProps) {
  const code = stateCode.toUpperCase();

  /* ---- State ---- */
  const [selectedElectionKey, setSelectedElectionKey] = useState<string>(
    elections[0]?.election_key ?? "",
  );
  const [election, setElection] = useState<ElectionDetail | null>(null);
  const [selectedRaceKey, setSelectedRaceKey] = useState<string | null>(null);
  const [countyResults, setCountyResults] = useState<CountyResult[]>([]);
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [raceSearch, setRaceSearch] = useState("");

  /* ---- Fetch election detail when selection changes ---- */
  useEffect(() => {
    if (!selectedElectionKey) return;
    setLoading(true);
    fetch(`${API_BASE}/api/${code}/elections/${selectedElectionKey}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: ElectionDetail | null) => {
        setElection(data);
        if (data?.races?.length) {
          setSelectedRaceKey(data.races[0].race_key);
        } else {
          setSelectedRaceKey(null);
        }
        setActiveCategory(null);
        setRaceSearch("");
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [code, selectedElectionKey]);

  /* ---- Fetch county results when race changes ---- */
  useEffect(() => {
    if (!selectedRaceKey) {
      setCountyResults([]);
      return;
    }
    fetch(`${API_BASE}/api/${code}/races/${selectedRaceKey}/counties`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: CountyResult[]) => setCountyResults(data))
      .catch(() => setCountyResults([]));
  }, [code, selectedRaceKey]);

  /* ---- Build map data from county results ---- */
  const countyData = useMemo(() => {
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
  }, [election, countyResults, selectedRaceKey]);

  /* ---- Race filtering ---- */
  const allRaces = election?.races || [];
  const categories = [...new Set(allRaces.map((r) => r.office_category || "Other"))];
  const sortedCats = categories.sort((a, b) => {
    const ia = OFFICE_CATEGORIES.indexOf(a as (typeof OFFICE_CATEGORIES)[number]);
    const ib = OFFICE_CATEGORIES.indexOf(b as (typeof OFFICE_CATEGORIES)[number]);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });

  const filteredRaces = useMemo(() => {
    let races = allRaces;
    if (activeCategory) {
      races = races.filter(
        (r) => (r.office_category || "Other") === activeCategory,
      );
    }
    if (raceSearch.trim()) {
      const q = raceSearch.trim().toLowerCase();
      races = races.filter(
        (r) =>
          r.office_name.toLowerCase().includes(q) ||
          (r.district && r.district.toLowerCase().includes(q)),
      );
    }
    return races;
  }, [allRaces, activeCategory, raceSearch]);

  /* ---- County click → detail link ---- */
  const handleCountyClick = useCallback(
    (_code: string, _name: string) => {
      // For now, just highlight
    },
    [],
  );

  /* ---- Selected race details ---- */
  const selectedRace = allRaces.find((r) => r.race_key === selectedRaceKey);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "calc(100vh - 49px)",
        background: "#1a1a2e",
      }}
    >
      {/* Controls bar */}
      <div
        style={{
          padding: "8px 16px",
          background: "var(--color-background)",
          borderBottom: "1px solid var(--color-border)",
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexShrink: 0,
          flexWrap: "wrap",
        }}
      >
        {/* State name */}
        <h1
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "1.125rem",
            fontWeight: 700,
            margin: 0,
            whiteSpace: "nowrap",
          }}
        >
          {stateName}
        </h1>

        {/* Election picker */}
        <select
          value={selectedElectionKey}
          onChange={(e) => setSelectedElectionKey(e.target.value)}
          style={{
            padding: "4px 8px",
            fontSize: "0.8125rem",
            border: "1px solid var(--color-border)",
            background: "var(--color-surface)",
            color: "var(--color-foreground)",
            cursor: "pointer",
            maxWidth: 320,
          }}
        >
          {elections.map((el) => (
            <option key={el.election_key} value={el.election_key}>
              {formatElectionType(el.type)} — {formatDate(el.date)} ({el.race_count} races)
            </option>
          ))}
        </select>

        {/* Race count */}
        {election && (
          <span
            style={{
              fontSize: "0.75rem",
              color: "var(--color-muted)",
              marginLeft: "auto",
            }}
          >
            {election.races.length} race{election.races.length !== 1 ? "s" : ""}
            {election.is_official && (
              <span
                style={{
                  marginLeft: 8,
                  fontSize: "0.625rem",
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
        )}
      </div>

      {/* Main: Map + Side panel */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Map panel */}
        <div
          style={{
            flex: "1 1 60%",
            position: "relative",
            minHeight: 0,
          }}
        >
          {loading ? (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                height: "100%",
                color: "rgba(255,255,255,0.5)",
                fontSize: "0.875rem",
              }}
            >
              Loading election data...
            </div>
          ) : (
            <ElectionMap
              state={stateCode}
              countyData={countyData}
              onCountyClick={handleCountyClick}
            />
          )}

          {/* Legend overlay */}
          {selectedRace && !loading && (
            <div
              style={{
                position: "absolute",
                bottom: 16,
                left: 16,
                background: "rgba(0,0,0,0.8)",
                color: "#fff",
                padding: "8px 12px",
                borderRadius: 4,
                fontSize: "0.75rem",
                lineHeight: 1.4,
                maxWidth: 280,
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: 2 }}>
                {selectedRace.district
                  ? `${selectedRace.office_name} — ${selectedRace.district}`
                  : selectedRace.office_name}
              </div>
              <div style={{ opacity: 0.7 }}>
                Click a {countyLabel.toLowerCase()} for details
              </div>
            </div>
          )}
        </div>

        {/* Side panel */}
        <div
          style={{
            width: 380,
            flexShrink: 0,
            overflowY: "auto",
            background: "var(--color-background)",
            borderLeft: "1px solid var(--color-border)",
          }}
        >
          {/* Search + filter bar */}
          <div
            style={{
              padding: "8px 12px",
              borderBottom: "1px solid var(--color-border)",
              position: "sticky",
              top: 0,
              background: "var(--color-background)",
              zIndex: 2,
            }}
          >
            {/* Search input */}
            <input
              type="text"
              placeholder="Search races..."
              value={raceSearch}
              onChange={(e) => setRaceSearch(e.target.value)}
              style={{
                width: "100%",
                padding: "6px 10px",
                fontSize: "0.8125rem",
                border: "1px solid var(--color-border)",
                background: "var(--color-surface)",
                color: "var(--color-foreground)",
                marginBottom: 8,
              }}
            />

            {/* Category tabs */}
            <div
              style={{
                display: "flex",
                gap: 4,
                flexWrap: "wrap",
              }}
            >
              <FilterChip
                label={`All (${allRaces.length})`}
                active={!activeCategory}
                onClick={() => setActiveCategory(null)}
              />
              {sortedCats.map((cat) => {
                const count = allRaces.filter(
                  (r) => (r.office_category || "Other") === cat,
                ).length;
                return (
                  <FilterChip
                    key={cat}
                    label={`${cat} (${count})`}
                    active={activeCategory === cat}
                    onClick={() => setActiveCategory(cat)}
                  />
                );
              })}
            </div>
          </div>

          {/* Race cards */}
          <div style={{ padding: 12 }}>
            {loading ? (
              <p
                style={{
                  color: "var(--color-muted)",
                  fontSize: "0.875rem",
                  textAlign: "center",
                  padding: 24,
                }}
              >
                Loading...
              </p>
            ) : filteredRaces.length === 0 ? (
              <p
                style={{
                  color: "var(--color-muted)",
                  fontSize: "0.875rem",
                  textAlign: "center",
                  padding: 24,
                }}
              >
                No races found.
              </p>
            ) : (
              filteredRaces.map((race) => (
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
                        ? `${race.office_name} — ${race.district}`
                        : race.office_name
                    }
                    choices={race.choices}
                    precinctsReporting={race.precincts_reporting}
                    precinctsTotal={race.precincts_total}
                    isOfficial={election?.is_official}
                    isBallotMeasure={race.is_ballot_measure}
                    compact
                    href={`/${stateCode}/elections/${selectedElectionKey}/${race.race_key}`}
                  />
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---- Filter chip ---- */
function FilterChip({
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
        padding: "3px 10px",
        fontSize: "0.6875rem",
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
