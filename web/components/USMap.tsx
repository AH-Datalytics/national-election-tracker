"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import * as d3 from "d3";
import * as topojson from "topojson-client";
import { STATE_NAMES } from "@/lib/constants";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const ACTIVE_FILL = "#1e3a5f";
const ACTIVE_HOVER = "#2563eb";
const INACTIVE_FILL = "#d1d5db";
const INACTIVE_STROKE = "#fff";

interface StateStats {
  code: string;
  name: string;
  election_count: number;
  race_count: number;
  earliest: string | null;
  latest: string | null;
}

interface USMapProps {
  stateStats?: StateStats[];
}

export default function USMap({ stateStats = [] }: USMapProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState(false);
  const router = useRouter();

  const statsMap = useCallback(() => {
    const m: Record<string, StateStats> = {};
    for (const s of stateStats) m[s.code] = s;
    return m;
  }, [stateStats]);

  useEffect(() => {
    const svg = svgRef.current;
    const tooltip = tooltipRef.current;
    if (!svg || !tooltip) return;

    async function draw() {
      try {
        const res = await fetch(`${API_BASE}/api/maps/us-states.json`);
        if (!res.ok) throw new Error("Map data not available");
        const topoData = await res.json();
        const objKey = Object.keys(topoData.objects)[0];
        const states = topojson.feature(topoData, topoData.objects[objKey]) as any;

        const width = 960;
        const height = 600;
        const projection = d3.geoAlbersUsa().fitSize([width, height], states);
        const path = d3.geoPath().projection(projection);

        const sel = d3.select(svg);
        sel.selectAll("*").remove();
        sel.attr("viewBox", `0 0 ${width} ${height}`);

        const sm = statsMap();

        sel
          .selectAll("path")
          .data(states.features)
          .join("path")
          .attr("d", (d: any) => path(d) || "")
          .attr("fill", (d: any) =>
            d.properties.has_data ? ACTIVE_FILL : INACTIVE_FILL
          )
          .attr("stroke", INACTIVE_STROKE)
          .attr("stroke-width", 0.5)
          .attr("cursor", (d: any) =>
            d.properties.has_data ? "pointer" : "default"
          )
          .on("click", (_: any, d: any) => {
            if (d.properties.has_data) {
              router.push(`/${d.properties.code.toLowerCase()}`);
            }
          })
          .on("mouseenter", function (event: any, d: any) {
            const el = d3.select(this as Element);
            if (d.properties.has_data) {
              el.attr("fill", ACTIVE_HOVER);
            } else {
              el.attr("fill", "#bfc5cc");
            }
            // Show tooltip
            const code = d.properties.code;
            const name = d.properties.name || STATE_NAMES[code] || code;
            const stats = sm[code];
            let html = `<strong>${name}</strong>`;
            if (stats && stats.election_count > 0) {
              html += `<br/>${stats.election_count.toLocaleString()} elections`;
              html += `<br/>${stats.race_count.toLocaleString()} races`;
              if (stats.earliest && stats.latest) {
                const from = new Date(stats.earliest + "T00:00:00").getFullYear();
                const to = new Date(stats.latest + "T00:00:00").getFullYear();
                html += `<br/>${from}\u2013${to}`;
              }
            } else if (d.properties.has_data) {
              html += `<br/>Data available`;
            } else {
              html += `<br/><span style="opacity:0.6">Coming soon</span>`;
            }
            tooltip!.innerHTML = html;
            tooltip!.style.opacity = "1";
          })
          .on("mousemove", function (event: any) {
            const svgRect = svg!.getBoundingClientRect();
            const x = event.clientX - svgRect.left;
            const y = event.clientY - svgRect.top;
            tooltip!.style.left = `${x + 12}px`;
            tooltip!.style.top = `${y - 10}px`;
          })
          .on("mouseleave", function (_: any, d: any) {
            d3.select(this as Element).attr(
              "fill",
              d.properties.has_data ? ACTIVE_FILL : INACTIVE_FILL
            );
            tooltip!.style.opacity = "0";
          });
      } catch {
        setError(true);
      }
    }

    draw();
  }, [router, statsMap]);

  if (error) {
    return (
      <div style={{ textAlign: "center", padding: "32px 16px" }}>
        <p style={{ color: "var(--color-muted)", marginBottom: 16 }}>
          Map data loading...
        </p>
        <div style={{ display: "flex", justifyContent: "center", gap: 12, flexWrap: "wrap" }}>
          {stateStats.map((s) => (
            <a
              key={s.code}
              href={`/${s.code.toLowerCase()}`}
              style={{
                padding: "8px 16px",
                border: "1px solid var(--color-border)",
                background: "var(--color-surface)",
                textDecoration: "none",
                color: "var(--color-foreground)",
                fontSize: "0.875rem",
              }}
            >
              {s.name}
            </a>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: "relative", width: "100%", maxWidth: 800, margin: "0 auto" }}>
      <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />
      <div
        ref={tooltipRef}
        style={{
          position: "absolute",
          pointerEvents: "none",
          background: "rgba(0,0,0,0.85)",
          color: "#fff",
          padding: "8px 12px",
          borderRadius: 4,
          fontSize: "0.8125rem",
          lineHeight: 1.4,
          opacity: 0,
          transition: "opacity 0.15s",
          whiteSpace: "nowrap",
          zIndex: 10,
        }}
      />
    </div>
  );
}
