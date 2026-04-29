/* ------------------------------------------------------------------ */
/*  Formatting helpers for the National Election Tracker               */
/* ------------------------------------------------------------------ */

import { PARTY_COLORS, BALLOT_MEASURE_COLORS } from "./constants";

/** Format a number with commas: 1234567 -> "1,234,567" */
export function formatNumber(n: number): string {
  return n.toLocaleString("en-US");
}

/** Format a decimal as percentage with 1 decimal: 0.5432 -> "54.3%" */
export function formatPercent(n: number): string {
  return n.toFixed(1) + "%";
}

/**
 * Format a raw vote share (0-100) or fractional (0-1) to a display string.
 * Handles both conventions:
 *   formatVotePercent(54.3)   -> "54.3%"
 *   formatVotePercent(0.543)  -> "54.3%"
 */
export function formatVotePercent(n: number): string {
  // If the value looks fractional (< 1), multiply by 100
  const pct = n < 1 && n > 0 ? n * 100 : n;
  return pct.toFixed(1) + "%";
}

/** Format an ISO date string to human-readable: "2024-11-05" -> "Nov 5, 2024" */
export function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** Format ISO date to long form: "2024-11-05" -> "November 5, 2024" */
export function formatDateLong(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

/** Look up party color from PARTY_COLORS. Falls back to gray. */
export function partyColor(party: string | null): string {
  if (!party) return "#888888";
  return PARTY_COLORS[party] || "#888888";
}

/** Look up ballot measure choice color. Falls back to gray. */
export function ballotMeasureColor(name: string): string {
  return BALLOT_MEASURE_COLORS[name] || "#888888";
}

/** Map outcome codes to human-readable labels. */
export function outcomeLabel(outcome: string | null): string {
  if (!outcome) return "";
  switch (outcome) {
    case "Elected":
    case "Won":
      return "Won";
    case "Defeated":
    case "Lost":
      return "Lost";
    case "Runoff":
      return "Runoff";
    case "Approved":
      return "Approved";
    case "Rejected":
      return "Rejected";
    case "Advanced":
      return "Advanced";
    default:
      return outcome;
  }
}

/** Capitalize first letter of each word. */
export function titleCase(s: string): string {
  return s
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Pretty-print election type: "general" -> "General Election" */
export function formatElectionType(type: string): string {
  const base = titleCase(type.replace(/_/g, " ").replace(/-/g, " "));
  // Append "Election" if not already present
  if (base.toLowerCase().includes("election")) return base;
  return `${base} Election`;
}
