import type { CountyResult, Choice } from "@/lib/types";
import { formatNumber } from "@/lib/utils";

interface Props {
  countyResults: CountyResult[];
  choices: Choice[];
}

export default function CountyResultsTable({ countyResults, choices }: Props) {
  // Show top 4 choices in table columns
  const topChoices = [...choices].sort((a, b) => b.vote_total - a.vote_total).slice(0, 4);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-left">
            <th className="py-2 pr-4 font-semibold">County</th>
            {topChoices.map((c) => (
              <th key={c.choice_key} className="py-2 px-2 font-semibold text-right">
                {c.name.split(" ").pop()}
              </th>
            ))}
            <th className="py-2 pl-2 font-semibold text-right">Reporting</th>
          </tr>
        </thead>
        <tbody>
          {countyResults
            .sort((a, b) => a.county_name.localeCompare(b.county_name))
            .map((cr) => {
              const choiceMap = new Map(cr.choices.map((c) => [c.choice_key, c]));
              return (
                <tr key={cr.county_code} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-1.5 pr-4 font-medium">{cr.county_name}</td>
                  {topChoices.map((c) => {
                    const r = choiceMap.get(c.choice_key);
                    return (
                      <td key={c.choice_key} className="py-1.5 px-2 text-right tabular-nums">
                        {r ? formatNumber(r.votes) : "\u2014"}
                      </td>
                    );
                  })}
                  <td className="py-1.5 pl-2 text-right text-[var(--color-muted)] tabular-nums">
                    {cr.precincts_reporting != null && cr.precincts_total
                      ? `${cr.precincts_reporting}/${cr.precincts_total}`
                      : "\u2014"}
                  </td>
                </tr>
              );
            })}
        </tbody>
      </table>
    </div>
  );
}
