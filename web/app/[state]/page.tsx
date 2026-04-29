import { STATE_NAMES } from "@/lib/constants";
import type { Election } from "@/lib/types";
import StateExplorer from "./StateExplorer";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface StateDetail {
  code: string;
  name: string;
  county_label: string;
}

async function fetchState(code: string): Promise<StateDetail | null> {
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
    const res = await fetch(`${API_BASE}/api/${code}/elections?limit=50`, {
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

  if (!stateData || elections.length === 0) {
    return (
      <div
        style={{
          padding: 48,
          textAlign: "center",
          color: "var(--color-muted)",
        }}
      >
        <h1
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "2rem",
            fontWeight: 700,
            color: "var(--color-foreground)",
            marginBottom: 16,
          }}
        >
          {name}
        </h1>
        <p>No election data available yet.</p>
      </div>
    );
  }

  return (
    <StateExplorer
      stateCode={state.toLowerCase()}
      stateName={stateData.name || name}
      countyLabel={stateData.county_label || "County"}
      elections={elections}
    />
  );
}
