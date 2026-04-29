import Link from "next/link";
import { STATE_NAMES } from "@/lib/constants";
import { formatDate, formatElectionType } from "@/lib/utils";
import type { Election } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchElections(code: string): Promise<Election[]> {
  try {
    const res = await fetch(`${API_BASE}/api/${code}/elections`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export default async function ElectionsPage({
  params,
}: {
  params: Promise<{ state: string }>;
}) {
  const { state } = await params;
  const code = state.toUpperCase();
  const name = STATE_NAMES[code] ?? code;
  const elections = await fetchElections(code);

  /* Group elections by year */
  const byYear = new Map<string, Election[]>();
  for (const e of elections) {
    const year = e.date.substring(0, 4);
    if (!byYear.has(year)) byYear.set(year, []);
    byYear.get(year)!.push(e);
  }
  const sortedYears = [...byYear.keys()].sort((a, b) => b.localeCompare(a));

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 16px" }}>
      <h1
        style={{
          fontFamily: "var(--font-serif)",
          fontSize: "2rem",
          fontWeight: 700,
          color: "var(--color-foreground)",
          margin: 0,
          marginBottom: 32,
        }}
      >
        {name} Elections
      </h1>

      {elections.length === 0 ? (
        <p style={{ color: "var(--color-muted)" }}>No elections loaded yet.</p>
      ) : (
        sortedYears.map((year) => (
          <div key={year} style={{ marginBottom: 32 }}>
            {/* Year header */}
            <h2
              style={{
                fontFamily: "var(--font-serif)",
                fontSize: "1.25rem",
                fontWeight: 600,
                paddingBottom: 8,
                borderBottom: "2px solid #1a1a1a",
                marginBottom: 12,
              }}
            >
              {year}
            </h2>

            <div
              style={{ display: "flex", flexDirection: "column", gap: 8 }}
            >
              {byYear.get(year)!.map((e) => (
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
          </div>
        ))
      )}
    </div>
  );
}
