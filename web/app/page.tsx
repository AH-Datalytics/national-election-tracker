import Link from "next/link";
import USMap from "@/components/USMap";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface StateInfo {
  code: string;
  name: string;
  election_count: number;
  race_count: number;
  earliest: string | null;
  latest: string | null;
}

async function fetchStates(): Promise<StateInfo[]> {
  try {
    const res = await fetch(`${API_BASE}/api/states`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export default async function HomePage() {
  const states = await fetchStates();

  // Total stats across all states
  const totalElections = states.reduce((a, s) => a + s.election_count, 0);
  const totalRaces = states.reduce((a, s) => a + s.race_count, 0);

  return (
    <div>
      {/* Hero with map */}
      <section
        style={{
          background: "var(--color-hero-bg)",
          color: "#fff",
          padding: "48px 16px 24px",
        }}
      >
        <div style={{ maxWidth: 1200, margin: "0 auto", textAlign: "center" }}>
          <h1
            style={{
              fontFamily: "var(--font-serif)",
              fontSize: "clamp(2rem, 5vw, 3.5rem)",
              fontWeight: 700,
              lineHeight: 1,
              marginBottom: 12,
            }}
          >
            National Election Tracker
          </h1>
          <p
            style={{
              fontSize: "1.0625rem",
              opacity: 0.75,
              maxWidth: 560,
              margin: "0 auto 8px",
            }}
          >
            Every race, every state, every precinct — from president to school
            board.
          </p>
          {totalElections > 0 && (
            <p
              style={{
                fontSize: "0.875rem",
                opacity: 0.5,
                marginBottom: 0,
              }}
            >
              {states.length} states &middot;{" "}
              {totalElections.toLocaleString()} elections &middot;{" "}
              {totalRaces.toLocaleString()} races
            </p>
          )}
        </div>
      </section>

      {/* Map section */}
      <section
        style={{
          background: "#f5f5f3",
          padding: "32px 16px 48px",
        }}
      >
        <div style={{ maxWidth: 1200, margin: "0 auto" }}>
          <p
            style={{
              textAlign: "center",
              fontSize: "0.8125rem",
              color: "var(--color-muted)",
              marginBottom: 16,
            }}
          >
            Click a highlighted state to explore election results
          </p>
          <USMap stateStats={states} />
        </div>
      </section>

      {/* State cards below the map */}
      {states.length > 0 && (
        <section
          style={{ maxWidth: 1200, margin: "0 auto", padding: "48px 16px" }}
        >
          <h2 className="section-header">Available States</h2>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
              gap: 16,
            }}
          >
            {states.map((s) => (
              <Link
                key={s.code}
                href={`/${s.code.toLowerCase()}`}
                style={{
                  display: "block",
                  padding: "16px 20px",
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  textDecoration: "none",
                  color: "var(--color-foreground)",
                  transition: "border-color 0.15s",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    justifyContent: "space-between",
                  }}
                >
                  <h3
                    style={{
                      fontFamily: "var(--font-serif)",
                      fontSize: "1.125rem",
                      fontWeight: 600,
                    }}
                  >
                    {s.name}
                  </h3>
                  {s.earliest && s.latest && (
                    <span
                      style={{
                        fontSize: "0.75rem",
                        color: "var(--color-muted)",
                      }}
                    >
                      {new Date(s.earliest + "T00:00:00").getFullYear()}
                      &ndash;
                      {new Date(s.latest + "T00:00:00").getFullYear()}
                    </span>
                  )}
                </div>
                <p
                  style={{
                    fontSize: "0.8125rem",
                    color: "var(--color-muted)",
                    marginTop: 4,
                  }}
                >
                  {s.election_count.toLocaleString()} elections &middot;{" "}
                  {s.race_count.toLocaleString()} races
                </p>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
