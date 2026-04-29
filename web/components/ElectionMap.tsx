"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import * as topojson from "topojson-client";
import type { Topology } from "topojson-specification";
import type { FeatureCollection, Geometry } from "geojson";

/* ------------------------------------------------------------------ */
/*  ElectionMap – MapLibre GL county + precinct choropleth             */
/*  Supports drill-down: click county → show precinct boundaries.     */
/* ------------------------------------------------------------------ */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ElectionMapProps {
  state: string;
  countyData?: Record<
    string,
    { leader: string; party: string; margin: number }
  >;
  precinctData?: Record<
    string,
    { leader: string; party: string; margin: number }
  >;
  selectedCounty?: string | null;
  height?: number;
  onCountyClick?: (countyCode: string, countyName: string) => void;
  onBackToState?: () => void;
}

/** Approximate center coordinates and zoom level per state. */
const STATE_CENTERS: Record<
  string,
  { center: [number, number]; zoom: number }
> = {
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
    const r = Math.round(200 - 180 * t);
    const g = Math.round(210 - 170 * t);
    const b = Math.round(255 - 67 * t);
    return `rgb(${r},${g},${b})`;
  }

  if (party === "Republican" || party === "REP") {
    const r = Math.round(255 - 23 * t);
    const g = Math.round(200 - 170 * t);
    const b = Math.round(200 - 170 * t);
    return `rgb(${r},${g},${b})`;
  }

  return "#cccccc";
}

/** Build a MapLibre match expression from a data record. */
function buildFillColor(
  data: Record<string, { leader: string; party: string; margin: number }> | undefined,
  keyProp: string,
): unknown {
  if (!data || Object.keys(data).length === 0) return "#cccccc";
  const expr: unknown[] = ["match", ["get", keyProp]];
  for (const [code, info] of Object.entries(data)) {
    expr.push(code, marginColor(info.party, info.margin));
  }
  expr.push("#cccccc");
  return expr;
}

export default function ElectionMap({
  state,
  countyData,
  precinctData,
  selectedCounty,
  height = 500,
  onCountyClick,
  onBackToState,
}: ElectionMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const tooltipRef = useRef<maplibregl.Popup | null>(null);
  const [precinctLoading, setPrecinctLoading] = useState(false);
  const [hasPrecinctLayer, setHasPrecinctLayer] = useState(false);

  const onCountyClickRef = useRef(onCountyClick);
  onCountyClickRef.current = onCountyClick;
  const onBackToStateRef = useRef(onBackToState);
  onBackToStateRef.current = onBackToState;
  const countyDataRef = useRef(countyData);
  countyDataRef.current = countyData;
  const precinctDataRef = useRef(precinctData);
  precinctDataRef.current = precinctData;

  /** Remove precinct layers if they exist. */
  const removePrecinctLayers = useCallback((map: maplibregl.Map) => {
    for (const id of [
      "precincts-fill",
      "precincts-line",
      "precincts-highlight",
    ]) {
      if (map.getLayer(id)) map.removeLayer(id);
    }
    if (map.getSource("precincts")) map.removeSource("precincts");
    setHasPrecinctLayer(false);
  }, []);

  /** Load precinct boundaries for a county and add to map. */
  const loadPrecincts = useCallback(
    async (map: maplibregl.Map, countyCode: string) => {
      setPrecinctLoading(true);
      try {
        const res = await fetch(
          `${API_BASE}/api/maps/${state.toLowerCase()}/precincts/${countyCode}.json`,
        );
        if (!res.ok) {
          setPrecinctLoading(false);
          return;
        }
        const topoData: Topology = await res.json();
        const objectKey = Object.keys(topoData.objects)[0];
        const geojson = topojson.feature(
          topoData,
          topoData.objects[objectKey],
        ) as FeatureCollection<Geometry>;

        // Remove existing precinct layers
        removePrecinctLayers(map);

        // Add precinct source
        map.addSource("precincts", { type: "geojson", data: geojson });

        // Precinct fill layer
        const pData = precinctDataRef.current;
        map.addLayer({
          id: "precincts-fill",
          type: "fill",
          source: "precincts",
          paint: {
            "fill-color": buildFillColor(
              pData,
              "vtd_code",
            ) as maplibregl.ExpressionSpecification | string,
            "fill-opacity": 0.85,
          },
        });

        // Precinct border layer
        map.addLayer({
          id: "precincts-line",
          type: "line",
          source: "precincts",
          paint: {
            "line-color": "#ffffff",
            "line-width": 0.5,
          },
        });

        // Precinct hover highlight
        map.addLayer({
          id: "precincts-highlight",
          type: "line",
          source: "precincts",
          paint: {
            "line-color": "#FDD023",
            "line-width": 2,
          },
          filter: ["==", "vtd_code", ""],
        });

        setHasPrecinctLayer(true);
      } catch {
        /* Failed to load — just show counties */
      }
      setPrecinctLoading(false);
    },
    [state, removePrecinctLayers],
  );

  /** Initialize the map with county layers. */
  useEffect(() => {
    if (!containerRef.current) return;

    const { center, zoom } =
      STATE_CENTERS[state.toUpperCase()] || DEFAULT_CENTER;

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

        map.addSource("counties", { type: "geojson", data: geojson });

        map.addLayer({
          id: "counties-fill",
          type: "fill",
          source: "counties",
          paint: {
            "fill-color": buildFillColor(
              countyData,
              "county_code",
            ) as maplibregl.ExpressionSpecification | string,
            "fill-opacity": 0.85,
          },
        });

        map.addLayer({
          id: "counties-line",
          type: "line",
          source: "counties",
          paint: {
            "line-color": "#ffffff",
            "line-width": 1,
          },
        });

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

        /* County hover */
        map.on("mousemove", "counties-fill", (e) => {
          if (!e.features || e.features.length === 0) return;
          map.getCanvas().style.cursor = "pointer";

          const props = e.features[0].properties || {};
          const code = props.county_code as string;
          const name = (props.name as string) || code;

          map.setFilter("counties-highlight", ["==", "county_code", code]);

          let html = `<strong>${name}</strong>`;
          const cd = countyDataRef.current;
          if (cd && cd[code]) {
            const info = cd[code];
            html += `<br/>${info.leader}<br/>Margin: ${info.margin.toFixed(1)}%`;
          }
          tooltip.setLngLat(e.lngLat).setHTML(html).addTo(map);
        });

        map.on("mouseleave", "counties-fill", () => {
          map.getCanvas().style.cursor = "";
          map.setFilter("counties-highlight", ["==", "county_code", ""]);
          tooltip.remove();
        });

        /* County click → drill down to precincts */
        map.on("click", "counties-fill", (e) => {
          if (!e.features || e.features.length === 0) return;
          const feature = e.features[0];
          const props = feature.properties || {};
          const code = props.county_code as string;
          const name = (props.name as string) || code;

          // Zoom to county bounds
          if (
            feature.geometry.type === "Polygon" ||
            feature.geometry.type === "MultiPolygon"
          ) {
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
            map.fitBounds(bounds, {
              padding: 40,
              maxZoom: 10,
              duration: 800,
            });
          }

          if (onCountyClickRef.current) {
            onCountyClickRef.current(code, name);
          }
        });

        /* Precinct hover (added after precinct layer exists) */
        map.on("mousemove", "precincts-fill", (e) => {
          if (!e.features || e.features.length === 0) return;
          map.getCanvas().style.cursor = "pointer";

          const props = e.features[0].properties || {};
          const vtdCode = props.vtd_code as string;
          const name = (props.name as string) || vtdCode;

          if (map.getLayer("precincts-highlight")) {
            map.setFilter("precincts-highlight", [
              "==",
              "vtd_code",
              vtdCode,
            ]);
          }

          let html = `<strong>${name}</strong>`;
          const pd = precinctDataRef.current;
          if (pd && pd[vtdCode]) {
            const info = pd[vtdCode];
            html += `<br/>${info.leader}<br/>Margin: ${info.margin.toFixed(1)}%`;
          }
          tooltip.setLngLat(e.lngLat).setHTML(html).addTo(map);
        });

        map.on("mouseleave", "precincts-fill", () => {
          map.getCanvas().style.cursor = "";
          if (map.getLayer("precincts-highlight")) {
            map.setFilter("precincts-highlight", ["==", "vtd_code", ""]);
          }
          tooltip.remove();
        });
      } catch {
        /* map shows empty dark background */
      }
    });

    return () => {
      tooltip.remove();
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  /* Update county fill color when countyData changes. */
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const update = () => {
      if (map.getLayer("counties-fill")) {
        map.setPaintProperty(
          "counties-fill",
          "fill-color",
          buildFillColor(
            countyData,
            "county_code",
          ) as maplibregl.ExpressionSpecification | string,
        );
      }
    };
    if (map.isStyleLoaded()) update();
    else map.once("styledata", update);
  }, [countyData]);

  /* Load/remove precinct layer when selectedCounty changes. */
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const handleLoad = () => {
      if (selectedCounty) {
        // Dim county fill when drilling into precincts
        if (map.getLayer("counties-fill")) {
          map.setPaintProperty("counties-fill", "fill-opacity", 0.25);
        }
        loadPrecincts(map, selectedCounty);
      } else {
        // Reset county opacity and remove precinct layers
        if (map.getLayer("counties-fill")) {
          map.setPaintProperty("counties-fill", "fill-opacity", 0.85);
        }
        removePrecinctLayers(map);

        // Reset to state view
        const { center, zoom } =
          STATE_CENTERS[state.toUpperCase()] || DEFAULT_CENTER;
        map.flyTo({ center, zoom, duration: 800 });
      }
    };

    if (map.isStyleLoaded() && map.getSource("counties")) {
      handleLoad();
    } else {
      map.once("load", handleLoad);
    }
  }, [selectedCounty, state, loadPrecincts, removePrecinctLayers]);

  /* Update precinct fill color when precinctData changes. */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !hasPrecinctLayer) return;
    const update = () => {
      if (map.getLayer("precincts-fill")) {
        map.setPaintProperty(
          "precincts-fill",
          "fill-color",
          buildFillColor(
            precinctData,
            "vtd_code",
          ) as maplibregl.ExpressionSpecification | string,
        );
      }
    };
    if (map.isStyleLoaded()) update();
    else map.once("styledata", update);
  }, [precinctData, hasPrecinctLayer]);

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
      <div style={{ position: "relative" }}>
        <div
          ref={containerRef}
          style={{
            width: "100%",
            height: height ?? "100%",
            minHeight: height ? undefined : 300,
            overflow: "hidden",
          }}
        />

        {/* Loading overlay for precinct data */}
        {precinctLoading && (
          <div
            style={{
              position: "absolute",
              top: 12,
              left: 12,
              background: "rgba(0,0,0,0.75)",
              color: "#fff",
              padding: "6px 12px",
              borderRadius: 4,
              fontSize: "0.8125rem",
            }}
          >
            Loading precincts...
          </div>
        )}

        {/* Back button when viewing precincts */}
        {selectedCounty && !precinctLoading && (
          <button
            onClick={() => onBackToStateRef.current?.()}
            style={{
              position: "absolute",
              top: 12,
              left: 12,
              background: "rgba(0,0,0,0.75)",
              color: "#fff",
              padding: "6px 14px",
              borderRadius: 4,
              fontSize: "0.8125rem",
              border: "1px solid rgba(255,255,255,0.3)",
              cursor: "pointer",
            }}
          >
            ← Back to state view
          </button>
        )}
      </div>
    </>
  );
}
