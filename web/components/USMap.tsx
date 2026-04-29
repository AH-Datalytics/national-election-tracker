"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import * as d3 from "d3";
import * as topojson from "topojson-client";
import { STATES_WITH_DATA, STATE_NAMES } from "@/lib/constants";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface StateFeature {
  type: "Feature";
  properties: { code: string; name: string; has_data: boolean };
  geometry: any;
}

export default function USMap() {
  const svgRef = useRef<SVGSVGElement>(null);
  const [error, setError] = useState(false);
  const router = useRouter();

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    async function draw() {
      try {
        const res = await fetch(`${API_BASE}/api/maps/us-states.json`);
        if (!res.ok) throw new Error("Map data not available");
        const topoData = await res.json();
        const states = topojson.feature(topoData, topoData.objects[Object.keys(topoData.objects)[0]]) as any;

        const width = 960;
        const height = 600;
        const projection = d3.geoAlbersUsa().fitSize([width, height], states);
        const path = d3.geoPath().projection(projection);

        const sel = d3.select(svg);
        sel.selectAll("*").remove();
        sel.attr("viewBox", `0 0 ${width} ${height}`);

        sel
          .selectAll("path")
          .data(states.features as StateFeature[])
          .join("path")
          .attr("d", (d: any) => path(d) || "")
          .attr("fill", (d: StateFeature) =>
            d.properties.has_data ? "#1e3a5f" : "#e5e7eb"
          )
          .attr("stroke", "#fff")
          .attr("stroke-width", 0.5)
          .attr("cursor", (d: StateFeature) =>
            d.properties.has_data ? "pointer" : "default"
          )
          .on("click", (_: any, d: StateFeature) => {
            if (d.properties.has_data) {
              router.push(`/${d.properties.code.toLowerCase()}`);
            }
          })
          .on("mouseenter", function (_: any, d: StateFeature) {
            if (d.properties.has_data) {
              d3.select(this as Element).attr("fill", "#2563eb");
            }
          })
          .on("mouseleave", function (_: any, d: StateFeature) {
            d3.select(this as Element).attr("fill", d.properties.has_data ? "#1e3a5f" : "#e5e7eb");
          })
          .append("title")
          .text((d: StateFeature) => d.properties.name);
      } catch {
        setError(true);
      }
    }

    draw();
  }, [router]);

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-[var(--color-muted)] mb-4">Map data not yet available</p>
        <div className="flex justify-center gap-4">
          {STATES_WITH_DATA.map((code) => (
            <a key={code} href={`/${code.toLowerCase()}`} className="px-4 py-2 border rounded hover:bg-gray-50">
              {STATE_NAMES[code]}
            </a>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-4xl mx-auto">
      <svg ref={svgRef} className="w-full" />
    </div>
  );
}
