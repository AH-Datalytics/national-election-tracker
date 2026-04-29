import Link from "next/link";
import { Choice } from "@/lib/types";
import { formatNumber, partyColor, ballotMeasureColor, outcomeLabel } from "@/lib/utils";

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

function choiceColor(choice: Choice, isBallotMeasure: boolean): string {
  if (isBallotMeasure) return ballotMeasureColor(choice.name);
  return partyColor(choice.party);
}

function outcomeBadgeClasses(label: string): string {
  switch (label) {
    case "Won":
    case "Approved":
      return "text-emerald-700 bg-emerald-50 border-emerald-200";
    case "Runoff":
    case "Advanced":
      return "text-amber-700 bg-amber-50 border-amber-200";
    default:
      return "text-gray-500 bg-gray-50 border-gray-200";
  }
}

export default function RaceCard({ title, choices, precinctsReporting, precinctsTotal, isOfficial, isBallotMeasure = false, compact = false, href }: RaceCardProps) {
  const sorted = [...choices].sort((a, b) => b.vote_total - a.vote_total);
  const totalVotes = sorted.reduce((sum, c) => sum + c.vote_total, 0);

  let statusLabel: string | null = null;
  if (isOfficial) {
    statusLabel = "Official";
  } else if (precinctsReporting != null && precinctsTotal != null && precinctsTotal > 0) {
    statusLabel = precinctsReporting >= precinctsTotal
      ? "Final (unofficial)"
      : `${formatNumber(precinctsReporting)} of ${formatNumber(precinctsTotal)} precincts`;
  }

  return (
    <div className="border border-gray-200 bg-white">
      <div className="px-4 py-3 border-b border-gray-100 flex items-baseline justify-between gap-4">
        {href ? (
          <Link href={href} className="text-sm font-semibold leading-snug hover:text-[var(--color-accent)] transition-colors" style={{ fontFamily: "var(--font-serif)" }}>
            {title}
          </Link>
        ) : (
          <h3 className="text-sm font-semibold leading-snug" style={{ fontFamily: "var(--font-serif)" }}>{title}</h3>
        )}
        {statusLabel && (
          <span className="text-[11px] text-[var(--color-muted)] whitespace-nowrap tracking-wide">{statusLabel}</span>
        )}
      </div>
      <div className={compact ? "px-4 py-2" : "px-4 py-3"}>
        {sorted.map((choice) => {
          const color = choiceColor(choice, isBallotMeasure);
          const pct = totalVotes > 0 ? ((choice.vote_total / totalVotes) * 100).toFixed(1) : "0.0";
          const label = outcomeLabel(choice.outcome);

          return (
            <div key={choice.choice_key} className={compact ? "py-1" : "py-1.5 first:pt-0 last:pb-0"}>
              <div className="flex items-center gap-2 text-sm leading-tight">
                <span className="inline-block w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
                <span className="font-medium truncate">{choice.name}</span>
                {!isBallotMeasure && choice.party && (
                  <span className="text-[11px] text-[var(--color-muted)]">{choice.party}</span>
                )}
                {label && (
                  <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border leading-none ${outcomeBadgeClasses(label)}`}>
                    {label}
                  </span>
                )}
                <span className="flex-1" />
                <span className="text-[var(--color-muted)] text-xs tabular-nums whitespace-nowrap">{formatNumber(choice.vote_total)}</span>
                <span className="font-medium text-xs tabular-nums w-12 text-right">{pct}%</span>
              </div>
              {!compact && totalVotes > 0 && (
                <div className="mt-1 h-1 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
                </div>
              )}
            </div>
          );
        })}
        {!compact && totalVotes > 0 && (
          <div className="mt-2 pt-2 border-t border-gray-100 flex justify-between text-[11px] text-[var(--color-muted)]">
            <span>Total votes</span>
            <span className="tabular-nums">{formatNumber(totalVotes)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
