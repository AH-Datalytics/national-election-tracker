import Link from "next/link";
import { STATE_NAMES } from "@/lib/constants";
import { formatDate, formatElectionType, formatNumber } from "@/lib/utils";
import type { State, Election } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchState(code: string): Promise<State | null> {
  try {
    const res = await fetch(`${API_BASE}/api/states/${code}`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

async function fetchElections(code: string): Promise<Election[]> {
  try {
    const res = await fetch(`${API_BASE}/api/${code}/elections?limit=10`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export default async function StatePage({
  params,
}: {
  params: Promise<{ state: string }>;
}) {
  const { state } = await params;
  const code = state.toUpperCase();
  const name = STATE_NAMES[code] ?? code;
  const [stateData, elections] = await Promise.all([
    fetchState(code),
    fetchElections(code),
  ]);

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 16px" }}>
      {/* Large serif heading */}
      <h1
        style={{
          fontFamily: "var(--font-serif)",
          fontSize: "2rem",
          fontWeight: 700,
          color: "var(--color-foreground)",
          margin: 0,
          lineHeight: 1.2,
        }}
      >
        {name}
      </h1>

      {/* Stats line */}
      {stateData && (
        <p
          style={{
            fontSize: "0.875rem",
            color: "var(--color-muted)",
            marginTop: 6,
            marginBottom: 32,
          }}
        >
          {formatNumber(stateData.election_count)} elections
          {" \u00B7 "}
          {formatNumber(stateData.race_count)} races
          {stateData.earliest && stateData.latest && (
            <>
              {" \u00B7 "}
              {formatDate(stateData.earliest)} &ndash;{" "}
              {formatDate(stateData.latest)}
            </>
          )}
        </p>
      )}

      {!stateData && (
        <p
          style={{
            color: "var(--color-muted)",
            marginTop: 6,
            marginBottom: 32,
            fontSize: "0.875rem",
          }}
        >
          Data not yet available. Connect to the API to see results.
        </p>
      )}

      {/* Recent elections heading */}
      <h2 className="section-header">Recent Elections</h2>

      {elections.length === 0 ? (
        <p style={{ color: "var(--color-muted)" }}>No elections loaded yet.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {elections.map((e) => (
            <Link
              key={e.election_key}
              href={`/${state}/elections/${e.election_key}`}
              style={{
                display: "block",
                border: "1px solid var(--color-border)",
                background: "var(--color-surface)",
                padding: "14px 16px",
                textDecoration: "none",
                color: "inherit",
                transition: "border-color 0.15s, box-shadow 0.15s",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--font-serif)",
                    fontWeight: 600,
                    fontSize: "0.9375rem",
                  }}
                >
                  {formatElectionType(e.type)}
                </span>
                <span
                  style={{
                    fontSize: "0.8125rem",
                    color: "var(--color-muted)",
                  }}
                >
                  {formatDate(e.date)}
                </span>
              </div>
              <div
                style={{
                  fontSize: "0.8125rem",
                  color: "var(--color-muted)",
                  marginTop: 4,
                }}
              >
                {e.race_count} race{e.race_count !== 1 ? "s" : ""}
                {e.is_official && (
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
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* View all link */}
      <div style={{ marginTop: 24 }}>
        <Link
          href={`/${state}/elections`}
          style={{
            fontSize: "0.875rem",
            color: "var(--color-accent)",
            textDecoration: "none",
          }}
        >
          View all elections &rarr;
        </Link>
      </div>
    </div>
  );
}
