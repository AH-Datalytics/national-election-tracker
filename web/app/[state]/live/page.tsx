"use client";

import { useEffect, useState, use } from "react";
import { STATE_NAMES, OFFICE_CATEGORIES } from "@/lib/constants";
import { formatDate } from "@/lib/utils";
import RaceCard from "@/components/RaceCard";
import type { LiveStatus, Race } from "@/lib/types";

const API_BASE = "";

export default function LivePage({
  params,
}: {
  params: Promise<{ state: string }>;
}) {
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
        /* API not available */
      }
    }

    poll();
    const interval = setInterval(poll, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [code]);

  /* Group races by category */
  const grouped = new Map<string, Race[]>();
  for (const race of races) {
    const cat = race.office_category || "Other";
    if (!grouped.has(cat)) grouped.set(cat, []);
    grouped.get(cat)!.push(race);
  }
  const sortedCategories = [...grouped.keys()].sort((a, b) => {
    const ia = OFFICE_CATEGORIES.indexOf(a as (typeof OFFICE_CATEGORIES)[number]);
    const ib = OFFICE_CATEGORIES.indexOf(b as (typeof OFFICE_CATEGORIES)[number]);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });

  return (
    <div>
      {/* Hero banner */}
      <div
        style={{
          background: "var(--color-hero-bg)",
          color: "#ffffff",
          padding: "32px 16px",
        }}
      >
        <div
          style={{
            maxWidth: 1200,
            margin: "0 auto",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 12,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {/* Pulsing red dot when live */}
            {status?.active && (
              <span
                style={{
                  display: "inline-block",
                  width: 12,
                  height: 12,
                  borderRadius: "50%",
                  backgroundColor: "#E81B23",
                  animation: "pulse-dot 1.5s ease-in-out infinite",
                  flexShrink: 0,
                }}
              />
            )}
            <h1
              style={{
                fontFamily: "var(--font-serif)",
                fontSize: "1.75rem",
                fontWeight: 700,
                margin: 0,
              }}
            >
              Election Night &mdash; {name}
            </h1>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 16,
              fontSize: "0.8125rem",
              opacity: 0.8,
            }}
          >
            {status?.election_date && (
              <span>{formatDate(status.election_date)}</span>
            )}
            {lastPoll && <span>Updated {lastPoll}</span>}
          </div>
        </div>
      </div>

      {/* Pulse animation keyframe */}
      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(1.3); }
        }
      `}</style>

      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 16px" }}>
        {/* Loading state */}
        {!status && (
          <p style={{ color: "var(--color-muted)", textAlign: "center" }}>
            Connecting to live results...
          </p>
        )}

        {/* Empty state — no active election */}
        {status && !status.active && races.length === 0 && (
          <div
            style={{
              textAlign: "center",
              padding: "64px 16px",
            }}
          >
            <div
              style={{
                width: 64,
                height: 64,
                borderRadius: "50%",
                background: "#f3f4f6",
                margin: "0 auto 16px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 28,
                color: "var(--color-muted)",
              }}
            >
              {"\u2014"}
            </div>
            <p
              style={{
                fontSize: "1.125rem",
                color: "var(--color-muted)",
                marginBottom: 4,
              }}
            >
              No active election
            </p>
            <p
              style={{
                fontSize: "0.875rem",
                color: "var(--color-muted)",
                marginBottom: 24,
              }}
            >
              Check back on election night for live results.
            </p>
            <a
              href={`/${state}/elections`}
              style={{
                fontSize: "0.875rem",
                color: "var(--color-accent)",
                textDecoration: "none",
              }}
            >
              View historical results &rarr;
            </a>
          </div>
        )}

        {/* Live results updating banner */}
        {races.length > 0 && status?.active && (
          <div
            style={{
              marginBottom: 20,
              padding: "10px 16px",
              background: "#eff6ff",
              border: "1px solid #bfdbfe",
              borderRadius: 4,
              fontSize: "0.8125rem",
              color: "#1e40af",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: "#3b82f6",
                display: "inline-block",
                flexShrink: 0,
              }}
            />
            Results are updating every 30 seconds. Results are unofficial.
          </div>
        )}

        {/* Race cards grouped by category */}
        {races.length > 0 &&
          sortedCategories.map((category) => (
            <div key={category} style={{ marginBottom: 32 }}>
              <h2 className="section-header">{category}</h2>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
                  gap: 12,
                }}
              >
                {grouped.get(category)!.map((race) => (
                  <RaceCard
                    key={race.race_key}
                    title={
                      race.district
                        ? `${race.office_name} \u2014 ${race.district}`
                        : race.office_name
                    }
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
      </div>
    </div>
  );
}
