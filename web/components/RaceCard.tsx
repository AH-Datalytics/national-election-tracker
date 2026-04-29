import Link from "next/link";
import { Choice } from "@/lib/types";
import {
  formatNumber,
  partyColor,
  ballotMeasureColor,
  outcomeLabel,
} from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  RaceCard – matches the Louisiana Election Tracker card style       */
/*  Border-top card with party-colored accent, sorted candidates,      */
/*  vote bars (full mode), and outcome badges.                         */
/* ------------------------------------------------------------------ */

interface RaceCardProps {
  title: string;
  choices: Choice[];
  precinctsReporting?: number | null;
  precinctsTotal?: number | null;
  isOfficial?: boolean;
  isBallotMeasure?: boolean;
  compact?: boolean;
  href?: string;
}

/** Resolve color for a choice — ballot measure or party-based. */
function choiceColor(choice: Choice, isBallotMeasure: boolean): string {
  if (isBallotMeasure) return ballotMeasureColor(choice.name);
  return partyColor(choice.party);
}

/** Inline style for outcome badges. */
function outcomeBadgeStyle(label: string): React.CSSProperties {
  switch (label) {
    case "Won":
    case "Approved":
      return {
        color: "#15803d",
        backgroundColor: "#f0fdf4",
        border: "1px solid #bbf7d0",
      };
    case "Runoff":
    case "Advanced":
      return {
        color: "#b45309",
        backgroundColor: "#fffbeb",
        border: "1px solid #fde68a",
      };
    default:
      return {
        color: "#6b7280",
        backgroundColor: "#f9fafb",
        border: "1px solid #e5e7eb",
      };
  }
}

export default function RaceCard({
  title,
  choices,
  precinctsReporting,
  precinctsTotal,
  isOfficial,
  isBallotMeasure = false,
  compact = false,
  href,
}: RaceCardProps) {
  /* Sort by vote_total descending */
  const sorted = [...choices].sort((a, b) => b.vote_total - a.vote_total);
  const totalVotes = sorted.reduce((sum, c) => sum + c.vote_total, 0);

  /* Leading candidate's party color for the top border */
  const leadColor =
    sorted.length > 0 ? choiceColor(sorted[0], isBallotMeasure) : "#cccccc";

  /* Status label logic */
  let statusLabel: string | null = null;
  if (isOfficial) {
    statusLabel = "Official";
  } else if (
    precinctsReporting != null &&
    precinctsTotal != null &&
    precinctsTotal > 0
  ) {
    statusLabel =
      precinctsReporting >= precinctsTotal
        ? "Final (unofficial)"
        : `${formatNumber(precinctsReporting)} of ${formatNumber(precinctsTotal)} precincts`;
  }

  /* -- Card container -- */
  const cardStyle: React.CSSProperties = {
    background: "#ffffff",
    borderTop: `3px solid ${leadColor}`,
    border: "1px solid var(--color-border)",
    borderTopWidth: 3,
    borderTopStyle: "solid",
    borderTopColor: leadColor,
  };

  /* -- Title bar -- */
  const titleBarStyle: React.CSSProperties = {
    padding: compact ? "8px 12px" : "10px 14px",
    borderBottom: "1px solid #f3f4f6",
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: 16,
  };

  const titleStyle: React.CSSProperties = {
    fontFamily: "var(--font-serif)",
    fontSize: "0.875rem",
    fontWeight: 700,
    lineHeight: 1.3,
    color: "var(--color-foreground)",
    textDecoration: "none",
    margin: 0,
  };

  return (
    <div style={cardStyle}>
      {/* Title bar */}
      <div style={titleBarStyle}>
        {href ? (
          <Link
            href={href}
            style={{
              ...titleStyle,
              transition: "color 0.15s",
            }}
            onMouseEnter={(e) =>
              ((e.target as HTMLElement).style.color = "var(--color-accent)")
            }
            onMouseLeave={(e) =>
              ((e.target as HTMLElement).style.color =
                "var(--color-foreground)")
            }
          >
            {title}
          </Link>
        ) : (
          <h3 style={titleStyle}>{title}</h3>
        )}
        {statusLabel && (
          <span
            style={{
              fontSize: "0.6875rem",
              color: "var(--color-muted)",
              whiteSpace: "nowrap",
              letterSpacing: "0.025em",
              flexShrink: 0,
            }}
          >
            {statusLabel}
          </span>
        )}
      </div>

      {/* Candidate rows */}
      <div style={{ padding: compact ? "6px 12px" : "10px 14px" }}>
        {sorted.map((choice) => {
          const color = choiceColor(choice, isBallotMeasure);
          const pct =
            totalVotes > 0
              ? ((choice.vote_total / totalVotes) * 100).toFixed(1)
              : "0.0";
          const label = outcomeLabel(choice.outcome);

          return (
            <div
              key={choice.choice_key}
              style={{
                padding: compact ? "3px 0" : "5px 0",
              }}
            >
              {/* Main row: dot | name | party | badge | spacer | votes | pct */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: "0.875rem",
                  lineHeight: 1.25,
                }}
              >
                {/* Party color dot */}
                <span
                  style={{
                    display: "inline-block",
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    backgroundColor: color,
                    flexShrink: 0,
                  }}
                />

                {/* Candidate name */}
                <span
                  style={{
                    fontWeight: 500,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    minWidth: 0,
                  }}
                >
                  {choice.name}
                </span>

                {/* Party abbreviation */}
                {!isBallotMeasure && choice.party && (
                  <span
                    style={{
                      fontSize: "0.6875rem",
                      color: "var(--color-muted)",
                      flexShrink: 0,
                    }}
                  >
                    {choice.party}
                  </span>
                )}

                {/* Outcome badge */}
                {label && (
                  <span
                    style={{
                      fontSize: "0.625rem",
                      fontWeight: 500,
                      padding: "1px 6px",
                      borderRadius: 3,
                      lineHeight: 1.4,
                      flexShrink: 0,
                      ...outcomeBadgeStyle(label),
                    }}
                  >
                    {label}
                  </span>
                )}

                {/* Spacer */}
                <span style={{ flex: 1 }} />

                {/* Vote count */}
                <span
                  style={{
                    color: "var(--color-muted)",
                    fontSize: "0.75rem",
                    fontVariantNumeric: "tabular-nums",
                    whiteSpace: "nowrap",
                    flexShrink: 0,
                  }}
                >
                  {formatNumber(choice.vote_total)}
                </span>

                {/* Percentage */}
                <span
                  style={{
                    fontWeight: 600,
                    fontSize: "0.75rem",
                    fontVariantNumeric: "tabular-nums",
                    width: 48,
                    textAlign: "right" as const,
                    flexShrink: 0,
                  }}
                >
                  {pct}%
                </span>
              </div>

              {/* Vote bar (full mode only) */}
              {!compact && totalVotes > 0 && (
                <div
                  style={{
                    marginTop: 4,
                    height: 3,
                    backgroundColor: "#f3f4f6",
                    borderRadius: 2,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      width: `${pct}%`,
                      backgroundColor: color,
                      borderRadius: 2,
                    }}
                  />
                </div>
              )}
            </div>
          );
        })}

        {/* Total votes row (full mode only) */}
        {!compact && totalVotes > 0 && (
          <div
            style={{
              marginTop: 8,
              paddingTop: 8,
              borderTop: "1px solid #f3f4f6",
              display: "flex",
              justifyContent: "space-between",
              fontSize: "0.6875rem",
              color: "var(--color-muted)",
            }}
          >
            <span>Total votes</span>
            <span style={{ fontVariantNumeric: "tabular-nums" }}>
              {formatNumber(totalVotes)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
