import Link from "next/link";
import { STATE_NAMES, STATES_WITH_DATA } from "@/lib/constants";

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
    const res = await fetch(`${API_BASE}/api/states`, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    return res.json();
  } catch { return []; }
}

export default async function HomePage() {
  const states = await fetchStates();

  return (
    <div>
      {/* Hero Section */}
      <section style={{
        background: "var(--color-hero-bg)",
        color: "#fff",
        padding: "80px 16px",
        position: "relative",
        overflow: "hidden",
      }}>
        <div style={{ maxWidth: 1200, margin: "0 auto", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 40 }}>
          <div>
            <h1 style={{
              fontFamily: "var(--font-serif)",
              fontSize: "clamp(2.5rem, 7vw, 5rem)",
              fontWeight: 700,
              lineHeight: 0.95,
              marginBottom: 16,
            }}>
              Every Race.<br />
              Every State.<br />
              Every Precinct.
            </h1>
            <p style={{ fontSize: "1.125rem", opacity: 0.8, maxWidth: 500, marginBottom: 32 }}>
              A free, open-source election results tracker — from president to school board.
            </p>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <a href="#states" style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              background: "#FDD023", color: "#1a1a1a",
              padding: "14px 28px", fontSize: "1.125rem", fontWeight: 600,
              textDecoration: "none", borderRadius: 4,
            }}>
              Explore States <span style={{ fontSize: "1.25rem" }}>→</span>
            </a>
            <Link href="/in/live" style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              background: "transparent", color: "#fff",
              padding: "14px 28px", fontSize: "1.125rem", fontWeight: 600,
              textDecoration: "none", borderRadius: 4,
              border: "2px solid rgba(255,255,255,0.4)",
            }}>
              Election Night
            </Link>
          </div>
        </div>
      </section>

      {/* States Grid */}
      <section id="states" style={{ maxWidth: 1200, margin: "0 auto", padding: "48px 16px" }}>
        <h2 className="section-header">Available States</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 16 }}>
          {(states.length > 0 ? states : STATES_WITH_DATA.map(code => ({ code, name: STATE_NAMES[code], election_count: 0, race_count: 0, earliest: null, latest: null }))).map((s: StateInfo) => (
            <Link key={s.code} href={`/${s.code.toLowerCase()}`} style={{
              display: "block", padding: 20,
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              textDecoration: "none", color: "var(--color-foreground)",
              transition: "border-color 0.15s",
            }}>
              <h3 style={{ fontFamily: "var(--font-serif)", fontSize: "1.25rem", fontWeight: 600, marginBottom: 4 }}>
                {s.name || STATE_NAMES[s.code]}
              </h3>
              <p style={{ fontSize: "0.875rem", color: "var(--color-muted)" }}>
                {s.election_count > 0 ? (
                  <>{s.election_count} elections &middot; {(s.race_count || 0).toLocaleString()} races</>
                ) : (
                  <>Data loading...</>
                )}
              </p>
              {s.earliest && s.latest && (
                <p style={{ fontSize: "0.75rem", color: "var(--color-muted)", marginTop: 4 }}>
                  {new Date(s.earliest + "T00:00:00").getFullYear()} &ndash; {new Date(s.latest + "T00:00:00").getFullYear()}
                </p>
              )}
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
