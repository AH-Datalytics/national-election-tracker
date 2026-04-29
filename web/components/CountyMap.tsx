"use client";

import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import * as topojson from "topojson-client";
import type { CountyResult, Choice } from "@/lib/types";
import { partyColor, formatNumber } from "@/lib/utils";

const API_BASE = "";

interface CountyMapProps {
  state: string;
  countyResults?: CountyResult[];
  choices?: Choice[];
}

export default function CountyMap({ state, countyResults, choices }: CountyMapProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || !countyResults || !choices) return;

    // Build choice lookup
    const choiceMap = new Map(choices.map((c) => [c.choice_key, c]));

    // Build county -> leading choice
    const countyLeader = new Map<string, { name: string; party: string | null; votes: number }>();
    for (const cr of countyResults) {
      const sorted = [...cr.choices].sort((a, b) => b.votes - a.votes);
      if (sorted.length > 0) {
        const leader = choiceMap.get(sorted[0].choice_key);
        if (leader) {
          countyLeader.set(cr.county_code, { name: leader.name, party: leader.party, votes: sorted[0].votes });
        }
      }
    }

    async function draw() {
      try {
        const res = await fetch(`${API_BASE}/api/maps/${state.toLowerCase()}/counties.json`);
        if (!res.ok) throw new Error("County map not available");
        const topoData = await res.json();
        const counties = topojson.feature(topoData, topoData.objects[Object.keys(topoData.objects)[0]]) as any;

        const width = 600;
        const height = 400;
        const projection = d3.geoMercator().fitSize([width, height], counties);
        const path = d3.geoPath().projection(projection);

        const sel = d3.select(svg);
        sel.selectAll("*").remove();
        sel.attr("viewBox", `0 0 ${width} ${height}`);

        sel
          .selectAll("path")
          .data(counties.features)
          .join("path")
          .attr("d", (d: any) => path(d) || "")
          .attr("fill", (d: any) => {
            const code = d.properties.county_code;
            const leader = countyLeader.get(code);
            return leader ? partyColor(leader.party) : "#e5e7eb";
          })
          .attr("stroke", "#fff")
          .attr("stroke-width", 0.5)
          .attr("opacity", 0.8)
          .append("title")
          .text((d: any) => {
            const code = d.properties.county_code;
            const leader = countyLeader.get(code);
            const name = d.properties.name;
            return leader ? `${name}: ${leader.name} (${formatNumber(leader.votes)} votes)` : name;
          });
      } catch {
        setError(true);
      }
    }

    draw();
  }, [state, countyResults, choices]);

  if (error || !countyResults || !choices) {
    return null;
  }

  return <svg ref={svgRef} className="w-full max-w-lg" />;
}
