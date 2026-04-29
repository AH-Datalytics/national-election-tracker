"use client";

import { useEffect, useRef, useCallback } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import * as topojson from "topojson-client";
import type { Topology } from "topojson-specification";
import type { FeatureCollection, Geometry } from "geojson";

/* ------------------------------------------------------------------ */
/*  ElectionMap – MapLibre GL county choropleth for election results   */
/*  Dark background, party-colored fill, hover tooltip, click zoom.    */
/* ------------------------------------------------------------------ */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ElectionMapProps {
  state: string;
  countyData?: Record<
    string,
    { leader: string; party: string; margin: number }
  >;
  height?: number;
  onCountyClick?: (countyCode: string, countyName: string) => void;
}

/** Approximate center coordinates and zoom level per state. */
const STATE_CENTERS: Record<string, { center: [number, number]; zoom: number }> = {
  LA: { center: [-91.8, 30.95], zoom: 6.3 },
  IN: { center: [-86.15, 39.77], zoom: 6.5 },
  OH: { center: [-82.7, 40.4], zoom: 6.5 },
};

const DEFAULT_CENTER: { center: [number, number]; zoom: number } = {
  center: [-98.5, 39.5],
  zoom: 4,
};

/** Empty map style — no tile server, just a dark background. */
const EMPTY_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "background",
      type: "background",
      paint: { "background-color": "#1a1a2e" },
    },
  ],
};

/**
 * Diverging color function for margin mode.
 * DEM → blue scale, REP → red scale, other → gray.
 * Margin is 0-100 (percentage points of lead).
 */
function marginColor(party: string, margin: number): string {
  const t = Math.min(margin / 80, 1); // 0 at 0%, 1 at 80%+

  if (party === "Democrat" || party === "Democratic" || party === "DEM") {
    // Light blue → dark blue
    const r = Math.round(200 - 180 * t);
    const g = Math.round(210 - 170 * t);
    const b = Math.round(255 - 67 * t);
    return `rgb(${r},${g},${b})`;
  }

  if (party === "Republican" || party === "REP") {
    // Light red → dark red
    const r = Math.round(255 - 23 * t);
    const g = Math.round(200 - 170 * t);
    const b = Math.round(200 - 170 * t);
    return `rgb(${r},${g},${b})`;
  }

  return "#cccccc";
}

export default function ElectionMap({
  state,
  countyData,
  height = 500,
  onCountyClick,
}: ElectionMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const tooltipRef = useRef<maplibregl.Popup | null>(null);

  /** Stable callback ref for county click. */
  const onCountyClickRef = useRef(onCountyClick);
  onCountyClickRef.current = onCountyClick;

  /** Build the fill-color expression from countyData. */
  const buildFillColor = useCallback(
    (
      data: Record<string, { leader: string; party: string; margin: number }> | undefined,
    ): unknown => {
      if (!data || Object.keys(data).length === 0) return "#cccccc";

      // Build a MapLibre "match" expression: ["match", ["get", "county_code"], code1, color1, ..., fallback]
      const expr: unknown[] = ["match", ["get", "county_code"]];
      for (const [code, info] of Object.entries(data)) {
        expr.push(code, marginColor(info.party, info.margin));
      }
      expr.push("#cccccc"); // fallback
      return expr;
    },
    [],
  );

  useEffect(() => {
    if (!containerRef.current) return;

    const { center, zoom } = STATE_CENTERS[state.toUpperCase()] || DEFAULT_CENTER;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: EMPTY_STYLE,
      center,
      zoom,
      attributionControl: false,
    });

    mapRef.current = map;

    const tooltip = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      className: "election-map-tooltip",
    });
    tooltipRef.current = tooltip;

    map.on("load", async () => {
      /* Fetch TopoJSON and convert to GeoJSON */
      try {
        const res = await fetch(
          `${API_BASE}/api/maps/${state.toLowerCase()}/counties.json`,
        );
        if (!res.ok) return;
        const topoData: Topology = await res.json();
        const objectKey = Object.keys(topoData.objects)[0];
        const geojson = topojson.feature(
          topoData,
          topoData.objects[objectKey],
        ) as FeatureCollection<Geometry>;

        /* Add source */
        map.addSource("counties", {
          type: "geojson",
          data: geojson,
        });

        /* County fill layer */
        map.addLayer({
          id: "counties-fill",
          type: "fill",
          source: "counties",
          paint: {
            "fill-color": buildFillColor(countyData) as maplibregl.ExpressionSpecification | string,
            "fill-opacity": 0.85,
          },
        });

        /* County border layer */
        map.addLayer({
          id: "counties-line",
          type: "line",
          source: "counties",
          paint: {
            "line-color": "#ffffff",
            "line-width": 1,
          },
        });

        /* Hover highlight layer */
        map.addLayer({
          id: "counties-highlight",
          type: "line",
          source: "counties",
          paint: {
            "line-color": "#000000",
            "line-width": 2.5,
          },
          filter: ["==", "county_code", ""],
        });

        /* Hover events */
        map.on("mousemove", "counties-fill", (e) => {
          if (!e.features || e.features.length === 0) return;
          map.getCanvas().style.cursor = "pointer";

          const feature = e.features[0];
          const props = feature.properties || {};
          const code = props.county_code as string;
          const name = (props.name as string) || code;

          /* Highlight border */
          map.setFilter("counties-highlight", [
            "==",
            "county_code",
            code,
          ]);

          /* Tooltip content */
          let html = `<strong>${name}</strong>`;
          if (countyData && countyData[code]) {
            const info = countyData[code];
            html += `<br/>${info.leader}<br/>Margin: ${info.margin.toFixed(1)}%`;
          }

          tooltip.setLngLat(e.lngLat).setHTML(html).addTo(map);
        });

        map.on("mouseleave", "counties-fill", () => {
          map.getCanvas().style.cursor = "";
          map.setFilter("counties-highlight", [
            "==",
            "county_code",
            "",
          ]);
          tooltip.remove();
        });

        /* Click events */
        map.on("click", "counties-fill", (e) => {
          if (!e.features || e.features.length === 0) return;
          const feature = e.features[0];
          const props = feature.properties || {};
          const code = props.county_code as string;
          const name = (props.name as string) || code;

          /* Fly to fit clicked county */
          if (feature.geometry.type === "Polygon" || feature.geometry.type === "MultiPolygon") {
            const bounds = new maplibregl.LngLatBounds();
            const coords =
              feature.geometry.type === "Polygon"
                ? feature.geometry.coordinates
                : feature.geometry.coordinates.flat();

            for (const ring of coords) {
              for (const pt of ring as [number, number][]) {
                bounds.extend(pt);
              }
            }

            map.fitBounds(bounds, { padding: 40, maxZoom: 10, duration: 800 });
          }

          if (onCountyClickRef.current) {
            onCountyClickRef.current(code, name);
          }
        });
      } catch {
        /* Silently fail — map just shows empty dark background */
      }
    });

    return () => {
      tooltip.remove();
      map.remove();
      mapRef.current = null;
    };
    // We only want to re-create the map when state changes.
    // countyData changes are handled by the second effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  /* Update fill color when countyData changes without re-creating map. */
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const updatePaint = () => {
      if (map.getLayer("counties-fill")) {
        map.setPaintProperty(
          "counties-fill",
          "fill-color",
          buildFillColor(countyData) as maplibregl.ExpressionSpecification | string,
        );
      }
    };

    if (map.isStyleLoaded()) {
      updatePaint();
    } else {
      map.once("styledata", updatePaint);
    }
  }, [countyData, buildFillColor]);

  return (
    <>
      <style>{`
        .election-map-tooltip .maplibregl-popup-content {
          background: rgba(0, 0, 0, 0.85);
          color: #fff;
          padding: 8px 12px;
          font-size: 0.8125rem;
          line-height: 1.4;
          border-radius: 4px;
          border: none;
          box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }
        .election-map-tooltip .maplibregl-popup-tip {
          border-top-color: rgba(0, 0, 0, 0.85);
        }
      `}</style>
      <div
        ref={containerRef}
        style={{
          width: "100%",
          height,
          borderRadius: 4,
          overflow: "hidden",
        }}
      />
    </>
  );
}
