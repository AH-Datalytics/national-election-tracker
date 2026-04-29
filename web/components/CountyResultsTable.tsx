import { formatNumber, partyColor } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  CountyResultsTable – parish/county breakdown table                 */
/*  Matches the LA tracker style: serif section header, party-colored  */
/*  column headers, alternating rows, winner bolded, tabular-nums.     */
/* ------------------------------------------------------------------ */

interface CountyResultsTableProps {
  counties: Array<{
    county_code: string;
    county_name: string;
    choices: Array<{
      choice_key: string;
      name: string;
      party: string | null;
      votes: number;
    }>;
    precincts_reporting: number | null;
    precincts_total: number | null;
  }>;
  countyLabel?: string;
}

export default function CountyResultsTable({
  counties,
  countyLabel = "County",
}: CountyResultsTableProps) {
  if (counties.length === 0) return null;

  /* Determine top 3 candidates across all counties by total votes. */
  const candidateTotals = new Map<
    string,
    { choice_key: string; name: string; party: string | null; totalVotes: number }
  >();

  for (const county of counties) {
    for (const c of county.choices) {
      const existing = candidateTotals.get(c.choice_key);
      if (existing) {
        existing.totalVotes += c.votes;
      } else {
        candidateTotals.set(c.choice_key, {
          choice_key: c.choice_key,
          name: c.name,
          party: c.party,
          totalVotes: c.votes,
        });
      }
    }
  }

  const topCandidates = Array.from(candidateTotals.values())
    .sort((a, b) => b.totalVotes - a.totalVotes)
    .slice(0, 3);

  /* Sort counties alphabetically. */
  const sortedCounties = [...counties].sort((a, b) =>
    a.county_name.localeCompare(b.county_name),
  );

  /* Find per-county winner (most votes) to bold the row. */
  function getCountyWinnerKey(
    choices: Array<{ choice_key: string; votes: number }>,
  ): string | null {
    if (choices.length === 0) return null;
    const sorted = [...choices].sort((a, b) => b.votes - a.votes);
    return sorted[0].choice_key;
  }

  /* Extract last name for column header display. */
  function lastName(fullName: string): string {
    const parts = fullName.trim().split(" ");
    return parts[parts.length - 1];
  }

  /* -- Styles -- */
  const headerStyle: React.CSSProperties = {
    fontFamily: "var(--font-serif)",
    fontSize: "1.125rem",
    fontWeight: 600,
    paddingBottom: 8,
    borderBottom: "2px solid #1a1a1a",
    marginBottom: 16,
  };

  const thStyle: React.CSSProperties = {
    padding: "8px 10px",
    fontWeight: 600,
    fontSize: "0.8125rem",
    borderBottom: "2px solid #e5e5e5",
    whiteSpace: "nowrap",
  };

  const tdStyle: React.CSSProperties = {
    padding: "6px 10px",
    fontSize: "0.8125rem",
    borderBottom: "1px solid #f0f0f0",
  };

  return (
    <div>
      <h3 style={headerStyle}>{countyLabel} Breakdown</h3>
      <div style={{ overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: "0.8125rem",
          }}
        >
          <thead>
            <tr>
              <th style={{ ...thStyle, textAlign: "left" }}>{countyLabel}</th>
              {topCandidates.map((c) => (
                <th
                  key={c.choice_key}
                  style={{
                    ...thStyle,
                    textAlign: "right",
                    color: partyColor(c.party),
                  }}
                >
                  {lastName(c.name)}
                </th>
              ))}
              <th style={{ ...thStyle, textAlign: "right" }}>Total</th>
              <th
                style={{
                  ...thStyle,
                  textAlign: "center",
                  width: 20,
                  padding: "8px 6px",
                }}
              >
                {/* Winner indicator column — no header text */}
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedCounties.map((county, idx) => {
              const choiceMap = new Map(
                county.choices.map((c) => [c.choice_key, c]),
              );
              const winnerKey = getCountyWinnerKey(county.choices);
              const totalVotes = county.choices.reduce(
                (sum, c) => sum + c.votes,
                0,
              );
              const isOdd = idx % 2 === 1;

              /* Find the winner's party for the indicator dot. */
              const winnerChoice = winnerKey ? choiceMap.get(winnerKey) : null;
              const winnerCandidate = winnerChoice
                ? topCandidates.find(
                    (tc) => tc.choice_key === winnerChoice.choice_key,
                  )
                : null;
              const winnerParty = winnerCandidate?.party ?? winnerChoice?.party ?? null;

              return (
                <tr
                  key={county.county_code}
                  style={{
                    backgroundColor: isOdd ? "#f9f9f9" : "#ffffff",
                  }}
                >
                  <td
                    style={{
                      ...tdStyle,
                      fontWeight: 500,
                      textAlign: "left",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {county.county_name}
                  </td>
                  {topCandidates.map((tc) => {
                    const r = choiceMap.get(tc.choice_key);
                    const isWinner =
                      winnerKey !== null && tc.choice_key === winnerKey;
                    return (
                      <td
                        key={tc.choice_key}
                        style={{
                          ...tdStyle,
                          textAlign: "right",
                          fontVariantNumeric: "tabular-nums",
                          fontWeight: isWinner ? 700 : 400,
                        }}
                      >
                        {r ? formatNumber(r.votes) : "\u2014"}
                      </td>
                    );
                  })}
                  <td
                    style={{
                      ...tdStyle,
                      textAlign: "right",
                      fontVariantNumeric: "tabular-nums",
                      color: "var(--color-muted)",
                    }}
                  >
                    {formatNumber(totalVotes)}
                  </td>
                  <td
                    style={{
                      ...tdStyle,
                      textAlign: "center",
                      padding: "6px",
                    }}
                  >
                    {winnerKey && (
                      <span
                        style={{
                          display: "inline-block",
                          width: 10,
                          height: 10,
                          borderRadius: "50%",
                          backgroundColor: partyColor(winnerParty),
                        }}
                      />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
