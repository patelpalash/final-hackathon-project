import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { CloudSun, RefreshCw, Expand, LocateFixed, Car, TriangleAlert, Key, X, ExternalLink } from "lucide-react";
import { api, BASE } from "../api/client";
import type { NetNode, RouteOption, MapConditions, LiveWeather, AppSettings, Incident } from "../api/types";
import { dt, hm } from "../lib";
import type { SimView } from "./JourneySimulator";

function buildHubPopupHtml(
  n: NetNode,
  path: string[],
  alternatives: RouteOption[],
  forecasts: LiveWeather[],
  trafficSections: { geometry: number[][]; delay_minutes: number; description: string }[],
  incidents: Incident[],
  trafficConfigured: boolean
): string {
  const onPath = path.includes(n.id);
  const pathIdx = path.indexOf(n.id);
  const activeOpt = alternatives.find((o) => o.path.join("-") === path.join("-")) || alternatives[0];

  // 1. Time to reach
  let timeText = "Not on active route";
  let isHighlight = false;
  let isWarn = false;

  if (onPath) {
    isHighlight = true;
    if (pathIdx === 0) {
      timeText = "Departure Origin (0 min · Start)";
      if (activeOpt?.depart_at) {
        timeText += ` · ${dt(activeOpt.depart_at)}`;
      }
    } else if (pathIdx === path.length - 1 && activeOpt) {
      timeText = `Destination · ${hm(activeOpt.total_minutes)} (ETA: ${dt(activeOpt.eta)})`;
    } else if (activeOpt?.steps) {
      let cumulativeMinutes = 0;
      let arrivalTime = "";
      for (const step of activeOpt.steps) {
        cumulativeMinutes += step.minutes;
        if (step.location === n.id) {
          arrivalTime = step.start || step.end;
          break;
        }
      }
      if (cumulativeMinutes > 0) {
        timeText = `~${hm(cumulativeMinutes)} from origin`;
        if (arrivalTime) {
          timeText += ` · ETA: ${dt(arrivalTime)}`;
        }
      } else {
        timeText = "Active route corridor";
      }
    } else {
      timeText = "Intermediate hub on active route";
    }
  }

  // 2. Weather
  let matchedWx = forecasts.find((w) => w.id === n.id || w.name?.toLowerCase() === n.name.toLowerCase());
  if (!matchedWx && forecasts.length > 0) {
    let minD = Infinity;
    for (const w of forecasts) {
      const d = Math.hypot(w.lon - n.lon, w.lat - n.lat);
      if (d < minD && d < 1.5) {
        minD = d;
        matchedWx = w;
      }
    }
  }
  let wxText = "Fair · Normal driving visibility";
  if (matchedWx) {
    const cond = matchedWx.condition || matchedWx.status || "Clear";
    const temp = matchedWx.temperature_c != null ? `${matchedWx.temperature_c}°C` : "";
    const wind = matchedWx.wind_kmh != null ? `Wind ${matchedWx.wind_kmh} km/h` : "";
    const delay = matchedWx.delay_minutes ? ` (+${matchedWx.delay_minutes}m weather impact)` : "";
    wxText = [cond, temp, wind].filter(Boolean).join(" · ") + delay;
  }

  // 3. Traffic
  let trafficText = trafficConfigured ? "🟢 Normal traffic flow (TomTom Live)" : "🟢 Normal flow (Simulated corridor)";
  const sec = trafficSections.find((s) => s.description?.toLowerCase().includes(n.name.toLowerCase()) || s.description?.toLowerCase().includes(n.id.toLowerCase()));
  if (sec && sec.delay_minutes > 0) {
    trafficText = `⚠️ +${sec.delay_minutes}m corridor delay (${sec.description})`;
    isWarn = true;
  } else {
    const nearbyInc = incidents.find((i) => {
      const c = i.geometry?.type === "Point" ? (i.geometry.coordinates as number[]) : (i.geometry?.coordinates as number[][])?.[0];
      if (!c || !Number.isFinite(c[0]) || !Number.isFinite(c[1])) return false;
      const distKm = Math.hypot((c[0] - n.lon) * Math.cos((n.lat * Math.PI) / 180), c[1] - n.lat) * 111;
      return distKm < 35;
    });
    if (nearbyInc) {
      trafficText = `⚠️ ${nearbyInc.description} (${nearbyInc.delay_minutes}m delay)`;
      isWarn = true;
    }
  }

  return `
    <div class="hub-popup">
      <div class="hub-popup-header">
        <div class="hub-popup-title">
          <span class="hub-popup-dot"></span>
          <strong>${n.name}</strong>
        </div>
        <span class="hub-popup-badge ${n.type}">${n.type.toUpperCase()}</span>
      </div>
      <div class="hub-popup-body">
        <div class="hub-popup-row">
          <span class="hub-popup-icon">⏱️</span>
          <div>
            <div class="hub-popup-label">Time to Reach</div>
            <div class="hub-popup-val ${isHighlight ? "highlight" : ""}">${timeText}</div>
          </div>
        </div>
        <div class="hub-popup-row">
          <span class="hub-popup-icon">🚗</span>
          <div>
            <div class="hub-popup-label">Traffic Conditions</div>
            <div class="hub-popup-val ${isWarn ? "warn" : ""}">${trafficText}</div>
          </div>
        </div>
        <div class="hub-popup-row">
          <span class="hub-popup-icon">🌤️</span>
          <div>
            <div class="hub-popup-label">Local Weather</div>
            <div class="hub-popup-val">${wxText}</div>
          </div>
        </div>
      </div>
    </div>
  `;
}

export type BasemapId = "voyager" | "positron" | "osm";

export const BASEMAPS: Record<BasemapId, { name: string; spec: maplibregl.StyleSpecification }> = {
  voyager: {
    name: "CARTO Voyager",
    spec: {
      version: 8,
      sources: {
        "carto-voyager": {
          type: "raster",
          tiles: [
            "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png",
            "https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png",
            "https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png",
            "https://d.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png",
          ],
          tileSize: 256,
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        },
      },
      layers: [
        {
          id: "carto-voyager-layer",
          type: "raster",
          source: "carto-voyager",
          minzoom: 0,
          maxzoom: 20,
        },
      ],
    },
  },
  positron: {
    name: "CARTO Positron",
    spec: {
      version: 8,
      sources: {
        "carto-positron": {
          type: "raster",
          tiles: [
            "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
            "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
            "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
            "https://d.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
          ],
          tileSize: 256,
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        },
      },
      layers: [
        {
          id: "carto-positron-layer",
          type: "raster",
          source: "carto-positron",
          minzoom: 0,
          maxzoom: 20,
        },
      ],
    },
  },
  osm: {
    name: "OpenStreetMap",
    spec: {
      version: 8,
      sources: {
        "osm": {
          type: "raster",
          tiles: [
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
          ],
          tileSize: 256,
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        },
      },
      layers: [
        {
          id: "osm-layer",
          type: "raster",
          source: "osm",
          minzoom: 0,
          maxzoom: 19,
        },
      ],
    },
  },
};

const HUB = "#1a3682", BRANCH = "#66738c", ROUTE = "#17765e";

function hasWebGL() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

function popup(text: string) {
  return new maplibregl.Popup({ offset: 15, maxWidth: "280px" }).setText(text);
}

export function LiveMap({
  demo = false,
  nodes,
  path,
  geometry,
  alternatives = [],
  onSelect,
  routeWeather = [],
  trafficSections = [],
  onRefresh,
  sim,
}: {
  demo?: boolean;
  nodes: NetNode[];
  path: string[];
  geometry?: number[][] | null;
  alternatives?: RouteOption[];
  onSelect?: (i: number) => void;
  routeWeather?: LiveWeather[];
  trafficSections?: { geometry: number[][]; delay_minutes: number; description: string }[];
  onRefresh?: () => void;
  sim?: SimView;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const shell = useRef<HTMLDivElement | null>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const loadedMap = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const weatherMarkers = useRef<maplibregl.Marker[]>([]);
  const incidentMarkers = useRef<maplibregl.Marker[]>([]);
  const truckMarker = useRef<maplibregl.Marker | null>(null);
  const blockMarker = useRef<maplibregl.Marker | null>(null);
  const currentHoverPopup = useRef<maplibregl.Popup | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const [fallback, setFallback] = useState(!hasWebGL());
  const [basemap, setBasemap] = useState<BasemapId>("osm");
  const [styleVersion, setStyleVersion] = useState(0);
  const [ready, setReady] = useState(false);
  const [data, setData] = useState<MapConditions | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);

  const [wx, setWx] = useState(true);
  const [traffic, setTraffic] = useState(true);
  const [incidents, setIncidents] = useState(true);
  const [hubs, setHubs] = useState(true);
  const [offset, setOffset] = useState(-1);

  const [showKeyModal, setShowKeyModal] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [keySaving, setKeySaving] = useState(false);
  const [keyMsg, setKeyMsg] = useState("");
  const [settings, setSettings] = useState<AppSettings | null>(null);

  useEffect(() => {
    api.settings().then(setSettings).catch(() => {});
  }, []);

  const saveTomTomKey = async (k: string) => {
    setKeySaving(true);
    setKeyMsg("");
    try {
      const res = await api.setTomTomKey(k);
      const s = await api.settings();
      setSettings(s);
      setKeyMsg(res.tomtom_configured ? "TomTom API key saved and activated!" : "Key cleared. Switched to Simulated Traffic.");
      setTick((t) => t + 1);
      onRefresh?.();
    } catch (err) {
      setKeyMsg(String(err));
    } finally {
      setKeySaving(false);
    }
  };

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const planned = useMemo(
    () => (geometry?.length ? geometry : path.flatMap((id) => { const n = byId.get(id); return n ? [[n.lon, n.lat]] : []; })),
    [geometry, path, byId]
  );
  // While a simulation is engaged the vehicle's actual path is what we draw.
  const coords = useMemo(
    () => (sim?.engaged && sim.activeCoords?.length ? sim.activeCoords : planned),
    [sim?.engaged, sim?.activeCoords, planned]
  );
  const coordKey = useMemo(() => JSON.stringify(coords), [coords]);
  const conditionsKey = useMemo(() => JSON.stringify(planned), [planned]);

  const fit = useCallback(() => {
    const m = map.current;
    if (!m) return;
    const frame = planned.length > 1 ? planned : coords;
    if (frame.length < 2) return;
    const b = new maplibregl.LngLatBounds();
    frame.forEach((p) => b.extend([p[0], p[1]]));
    m.fitBounds(b, { padding: 45, maxZoom: 9, duration: 450 });
  }, [planned, coords]);

  // Fit bounds when route changes or map becomes ready, but never during simulation frame updates
  const lastFitted = useRef("");
  const pathKey = useMemo(() => path.join("-") + (geometry?.length ? `-${geometry.length}` : ""), [path, geometry]);
  useEffect(() => {
    if (!ready || !map.current) return;
    if (lastFitted.current === pathKey) return;
    lastFitted.current = pathKey;
    fit();
  }, [ready, pathKey, fit]);

  // Fetch map conditions (weather & incidents)
  useEffect(() => {
    if (demo) {
      setData(null);
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    setError("");
    setData(null);
    const at = new Date(Date.now() + Math.max(0, offset) * 3600000).toISOString();
    api.mapConditions(JSON.parse(conditionsKey), at)
      .then((r) => { if (alive) setData(r); })
      .catch((e) => { if (alive) setError(String(e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [conditionsKey, offset, tick, demo]);

  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), 120000);
    return () => clearInterval(timer);
  }, []);

  // MapLibre initialization
  useEffect(() => {
    if (fallback || !ref.current) return;
    setReady(false);
    loadedMap.current = null;
    let m: maplibregl.Map;
    try {
      m = new maplibregl.Map({
        container: ref.current,
        style: BASEMAPS[basemap].spec,
        center: [10.2, 51],
        zoom: 5,
        attributionControl: { compact: true },
      });
    } catch {
      setFallback(true);
      return;
    }
    map.current = m;

    m.on("load", () => {
      loadedMap.current = m;
      setReady(true);
    });

    m.on("error", (e) => {
      const message = String(e.error?.message ?? "");
      if (/traffic-tiles/.test(message)) {
        setError("Traffic layer unavailable. Road routes remain visible.");
      } else if (!m.isStyleLoaded() && /style|fetch|network/i.test(message)) {
        setFallback(true);
      }
    });

    m.addControl(new maplibregl.NavigationControl(), "top-right");
    m.addControl(new maplibregl.ScaleControl());

    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => {
      try { m.resize(); } catch {}
    }) : null;
    if (ref.current && ro) ro.observe(ref.current);

    return () => {
      ro?.disconnect();
      loadedMap.current = null;
      setReady(false);
      m.remove();
      map.current = null;
    };
  }, [fallback]);

  // Handle switching basemaps
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || loadedMap.current !== m) return;
    try {
      m.setStyle(BASEMAPS[basemap].spec);
      const onStyleData = () => {
        setStyleVersion((v) => v + 1);
      };
      m.once("styledata", onStyleData);
    } catch {}
  }, [basemap]);

  // Vector sources and layers setup
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || loadedMap.current !== m) return;

    if (!m.getSource("alternatives")) {
      m.addSource("alternatives", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({
        id: "alternatives-line",
        type: "line",
        source: "alternatives",
        paint: { "line-color": "#82909c", "line-width": 5, "line-opacity": 0.45 },
      });
    }

    if (!m.getSource("route")) {
      m.addSource("route", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({
        id: "route-l",
        type: "line",
        source: "route",
        paint: { "line-color": ROUTE, "line-width": 5, "line-opacity": 0.95 },
      });
    }

    if (!m.getSource("abandoned")) {
      m.addSource("abandoned", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({
        id: "abandoned-line",
        type: "line",
        source: "abandoned",
        paint: { "line-color": "#c0392b", "line-width": 4, "line-opacity": 0.55, "line-dasharray": [1.5, 1.5] },
      });
    }

    if (!m.getSource("traffic-sections")) {
      m.addSource("traffic-sections", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({
        id: "traffic-sections-line",
        type: "line",
        source: "traffic-sections",
        paint: { "line-color": "#de7043", "line-width": 7 },
      });
    }

    const click = (e: maplibregl.MapLayerMouseEvent) => {
      const i = Number(e.features?.[0]?.properties?.index);
      if (Number.isInteger(i)) onSelectRef.current?.(i);
    };

    const sectionClick = (e: maplibregl.MapLayerMouseEvent) => {
      const p = e.features?.[0]?.properties;
      popup(`${p?.description ?? "Traffic"} · ${p?.delay ?? 0} minutes provider traffic impact (included in ETA)`)
        .setLngLat(e.lngLat)
        .addTo(m);
    };

    m.on("click", "alternatives-line", click);
    m.on("click", "traffic-sections-line", sectionClick);

    return () => {
      m.off("click", "alternatives-line", click);
      m.off("click", "traffic-sections-line", sectionClick);
    };
  }, [ready, styleVersion]);

  // Update route geometry
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || loadedMap.current !== m) return;
    const src = m.getSource("route") as maplibregl.GeoJSONSource | undefined;
    if (src) {
      src.setData({
        type: "FeatureCollection",
        features: coords.length > 1 ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: coords } }] : [],
      });
    }
  }, [ready, coordKey, coords]);

  // Update alternative route geometries
  const altKey = useMemo(
    () => alternatives.map((o) => (o.quote_id || "") + (o.path?.join("-") || "")).join("|"),
    [alternatives]
  );
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || loadedMap.current !== m) return;
    const alt = m.getSource("alternatives") as maplibregl.GeoJSONSource | undefined;
    if (alt) {
      const features = alternatives
        .filter((o) => o.geometry?.length)
        .map((o) => ({
          type: "Feature" as const,
          properties: { index: alternatives.indexOf(o) },
          geometry: { type: "LineString" as const, coordinates: o.geometry! },
        }));
      alt.setData({ type: "FeatureCollection", features });
    }
  }, [ready, altKey, alternatives]);

  // Update abandoned leg geometry for simulation reroute
  const ghostKey = useMemo(() => JSON.stringify(sim?.ghostCoords ?? []), [sim?.ghostCoords]);
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || loadedMap.current !== m) return;
    const ghostSource = m.getSource("abandoned") as maplibregl.GeoJSONSource | undefined;
    if (ghostSource) {
      ghostSource.setData({
        type: "FeatureCollection",
        features: sim?.ghostCoords && sim.ghostCoords.length > 1 ? [{
          type: "Feature" as const,
          properties: {},
          geometry: { type: "LineString" as const, coordinates: sim.ghostCoords },
        }] : [],
      });
    }
  }, [ready, ghostKey, sim?.ghostCoords]);

  // Update traffic sections geometry
  const trafficKey = useMemo(() => JSON.stringify(trafficSections ?? []), [trafficSections]);
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || loadedMap.current !== m) return;
    const sectionSource = m.getSource("traffic-sections") as maplibregl.GeoJSONSource | undefined;
    if (sectionSource) {
      sectionSource.setData({
        type: "FeatureCollection",
        features: (trafficSections ?? [])
          .filter((s) => s.geometry.length > 1)
          .map((s) => ({
            type: "Feature" as const,
            properties: { delay: s.delay_minutes, description: s.description },
            geometry: { type: "LineString" as const, coordinates: s.geometry },
          })),
      });
    }
  }, [ready, trafficKey, trafficSections]);

  // Weather forecasts along the route or general map conditions
  const forecasts = offset === -1 && routeWeather.length ? routeWeather : data?.weather ?? [];
  const forecastsKey = useMemo(
    () => forecasts.map((w) => `${w.id}:${w.condition}:${w.temperature_c}`).join("|"),
    [forecasts]
  );

  // Facilities / Hub markers with interactive hover dialog
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || loadedMap.current !== m) return;
    markers.current.forEach((x) => x.remove());
    markers.current = [];
    currentHoverPopup.current?.remove();
    currentHoverPopup.current = null;
    if (!hubs) return;
    const onPath = new Set(path);
    markers.current = nodes.map((n) => {
      const el = document.createElement("button");
      el.setAttribute("aria-label", `${n.name} facility`);
      el.className = `facility-marker ${onPath.has(n.id) ? "on-route" : ""}`;

      const popupHtml = buildHubPopupHtml(
        n,
        path,
        alternatives,
        forecasts,
        trafficSections,
        data?.incidents.items ?? [],
        !!data?.traffic_configured
      );

      const pop = new maplibregl.Popup({
        offset: 14,
        maxWidth: "310px",
        closeButton: false,
        closeOnClick: false,
        className: "hub-hover-popup",
      }).setHTML(popupHtml);

      el.addEventListener("mouseenter", () => {
        currentHoverPopup.current?.remove();
        currentHoverPopup.current = pop;
        pop.setLngLat([n.lon, n.lat]).addTo(m);
      });
      el.addEventListener("mouseleave", () => {
        pop.remove();
        if (currentHoverPopup.current === pop) {
          currentHoverPopup.current = null;
        }
      });
      el.addEventListener("click", () => {
        currentHoverPopup.current?.remove();
        currentHoverPopup.current = pop;
        pop.setLngLat([n.lon, n.lat]).addTo(m);
      });

      return new maplibregl.Marker({ element: el })
        .setLngLat([n.lon, n.lat])
        .addTo(m);
    });
  }, [ready, nodes, path, hubs, alternatives, forecastsKey, trafficKey, data]);

  // Weather markers
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || loadedMap.current !== m) return;
    weatherMarkers.current.forEach((x) => x.remove());
    weatherMarkers.current = [];
    if (!wx) return;
    const unique = new Map(forecasts.map((w) => [w.id, w]));
    weatherMarkers.current = [...unique.values()].map((w) => {
      const el = document.createElement("button");
      el.className = `weather-marker wx-${w.level ?? "unknown"}`;
      el.textContent = w.condition?.includes("Snow") ? "❄" : w.condition?.includes("Rain") ? "☂" : w.condition === "Clear" ? "☀" : "☁";
      el.title = `${w.condition ?? w.status} · ${w.temperature_c ?? "—"}°C`;
      return new maplibregl.Marker({ element: el, offset: [0, -20] })
        .setLngLat([w.lon, w.lat])
        .setPopup(popup(`${w.source} · ${w.status}
${w.condition ?? "Forecast unavailable"} · ${w.temperature_c ?? "—"}°C
Wind ${w.wind_kmh ?? "—"} km/h · visibility ${w.visibility_m ?? "—"} m
Valid ${dt(w.valid_at)}
Retrieved ${dt(w.fetched_at)}
Weather impact rule: +${w.delay_minutes ?? 0}m (estimate)`))
        .addTo(m);
    });
  }, [ready, forecastsKey, wx, forecasts]);

  // Incidents & Traffic Flow
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || loadedMap.current !== m) return;
    incidentMarkers.current.forEach((x) => x.remove());
    incidentMarkers.current = [];
    if (incidents && offset <= 0) {
      incidentMarkers.current = (data?.incidents.items ?? []).map((i) => {
        const c = i.geometry.type === "Point" ? (i.geometry.coordinates as number[]) : (i.geometry.coordinates as number[][])[0];
        const el = document.createElement("button");
        el.className = "incident-marker";
        el.textContent = "!";
        el.title = i.description;
        return new maplibregl.Marker({ element: el })
          .setLngLat([c[0], c[1]])
          .setPopup(popup(`${i.description}\n${i.delay_minutes}m reported delay · ${i.source}\nCurrent incident near route; exact impact comes from routing.`))
          .addTo(m);
      });
    }
    if (data?.traffic_configured && !m.getSource("traffic-flow")) {
      m.addSource("traffic-flow", {
        type: "raster",
        tiles: [`${new URL(BASE, window.location.href).href.replace(/\/$/, "")}/traffic-tiles/{z}/{x}/{y}.png`],
        tileSize: 256,
        attribution: "Traffic © TomTom",
      });
      m.addLayer({ id: "traffic-flow-layer", type: "raster", source: "traffic-flow", paint: { "raster-opacity": 0.7 } }, "alternatives-line");
    }
    if (m.getLayer("traffic-flow-layer")) {
      m.setLayoutProperty("traffic-flow-layer", "visibility", traffic && offset <= 0 ? "visible" : "none");
    }
    if (m.getLayer("traffic-sections-line")) {
      m.setLayoutProperty("traffic-sections-line", "visibility", traffic && offset <= 0 ? "visible" : "none");
    }
  }, [ready, data, traffic, incidents, offset]);

  // Simulated vehicle marker
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || loadedMap.current !== m) return;
    if (!sim?.truck) {
      truckMarker.current?.remove();
      truckMarker.current = null;
      return;
    }
    const [lon, lat] = sim.truck.position;
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
    const bearing = Math.round(sim.truck.bearing || 0);

    if (!truckMarker.current) {
      const el = document.createElement("div");
      el.className = "truck-marker";
      el.setAttribute("aria-hidden", "false");
      el.setAttribute("title", "Simulated freight vehicle");
      el.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 L18.5 20 L12 16 L5.5 20 Z"/></svg>';
      truckMarker.current = new maplibregl.Marker({ element: el, rotationAlignment: "map" })
        .setLngLat([lon, lat])
        .setRotation(bearing)
        .addTo(m);
    } else {
      truckMarker.current.setLngLat([lon, lat]);
      truckMarker.current.setRotation(bearing);
    }
    truckMarker.current.getElement().classList.toggle("is-moving", !!sim.running);
  }, [ready, sim?.truck, sim?.running]);

  // Blockage marker
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || loadedMap.current !== m) return;
    blockMarker.current?.remove();
    blockMarker.current = null;
    if (!sim?.blockage) return;
    const [lon, lat] = sim.blockage.position;
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
    const el = document.createElement("button");
    el.className = "blockage-marker";
    el.textContent = "⛔";
    el.title = sim.blockage.reason;
    blockMarker.current = new maplibregl.Marker({ element: el })
      .setLngLat([lon, lat])
      .setPopup(popup(`${sim.blockage.reason}\nSimulated obstruction · not a provider incident`))
      .addTo(m);
  }, [ready, sim?.blockage]);

  // Follow truck camera
  const lastFollow = useRef(0);
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || loadedMap.current !== m || !sim?.followTruck || !sim?.truck || !sim?.running) return;
    const [lon, lat] = sim.truck.position;
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
    const now = performance.now();
    if (now - lastFollow.current < 120) return;
    lastFollow.current = now;
    m.easeTo({ center: [lon, lat], duration: 120, easing: (t) => t, essential: true });
  }, [ready, sim?.followTruck, sim?.truck?.position, sim?.running]);

  useEffect(() => () => {
    truckMarker.current?.remove();
    blockMarker.current?.remove();
  }, []);

  const refresh = () => {
    setTick((t) => t + 1);
    onRefresh?.();
  };

  return (
    <div className="live-map-shell" ref={shell}>
      <div className="live-controls">
        <div className="layer-toggles">
          {[
            ["Weather", wx, setWx, CloudSun],
            ["Traffic", traffic, setTraffic, Car],
            ["Incidents", incidents, setIncidents, TriangleAlert],
            ["Hubs", hubs, setHubs, LocateFixed],
          ].map(([label, enabled, setter, Icon]) => {
            const I = Icon as typeof CloudSun;
            return (
              <button
                key={String(label)}
                disabled={demo && label !== "Hubs"}
                aria-pressed={enabled as boolean}
                onClick={() => (setter as (v: boolean) => void)(!enabled)}
              >
                <I size={13} />
                {String(label)}
              </button>
            );
          })}
          <div className="basemap-selector" style={{ display: "inline-flex", alignItems: "center", gap: 4, marginLeft: 2 }}>
            <span style={{ fontSize: "11px", color: "var(--muted)", fontWeight: 600 }}>Map:</span>
            <select
              aria-label="Basemap style"
              value={basemap}
              onChange={(e) => setBasemap(e.target.value as BasemapId)}
              style={{ fontSize: "11px", padding: "3px 6px", borderRadius: 6, border: "1px solid var(--line)", background: "#fff", color: "var(--text)", fontWeight: 600 }}
            >
              <option value="osm">OpenStreetMap</option>
              <option value="voyager">CARTO Voyager (Detailed)</option>
              <option value="positron">CARTO Positron (Light)</option>
            </select>
          </div>
          <button
            className={`key-btn ${settings?.tomtom_configured ? "key-btn--active" : "key-btn--sim"}`}
            onClick={() => {
              setShowKeyModal(true);
              setKeyInput("");
              setKeyMsg("");
            }}
            title={settings?.tomtom_configured ? "TomTom Live Key Active · Click to edit" : "Simulated Traffic active · Click to add real TomTom key"}
          >
            <Key size={13} />
            {settings?.tomtom_configured ? "TomTom: Live" : "Traffic: Simulated (Add Key)"}
          </button>
        </div>
        <div className="map-actions">
          <button aria-label="Fit route" onClick={fit}><LocateFixed size={15} /></button>
          <button
            aria-label="Fullscreen map"
            onClick={() => {
              if (document.fullscreenElement) void document.exitFullscreen();
              else void shell.current?.requestFullscreen().catch(() => setError("Fullscreen is unavailable in this browser"));
            }}
          >
            <Expand size={15} />
          </button>
          <button disabled={loading || demo} aria-label="Refresh live conditions and ETA" onClick={refresh}>
            <RefreshCw size={15} className={loading ? "spin" : ""} />
          </button>
        </div>
      </div>
      {demo && <div className="map-note">DEMO · Captured road geometry and illustrative timings. Live weather and traffic overlays disabled.</div>}
      <div className="forecast-controls">
        <label>
          Weather preview
          <select aria-label="Weather forecast time" disabled={demo} value={offset} onChange={(e) => setOffset(Number(e.target.value))}>
            <option value={-1}>At planned passage</option>
            <option value={0}>Now</option>
            <option value={3}>In 3 hours</option>
            <option value={6}>In 6 hours</option>
            <option value={12}>In 12 hours</option>
          </select>
        </label>
        <span>
          {loading ? "Fetching conditions…" : `Updated ${data ? dt(data.fetched_at) : "—"}`}
          <small>{demo ? "Demo replay · live overlays disabled" : offset > 0 ? "Future weather only · current traffic layer hidden" : "Traffic: current conditions · weather: forecast"}</small>
        </span>
      </div>
      {fallback ? (
        <Fallback nodes={nodes} path={path} geometry={geometry} sim={sim} />
      ) : (
        <div ref={ref} className="maplibre" />
      )}
      <div className="map-legend">
        <span><i style={{ background: "#17765e" }} /> Selected route</span>
        <span><i style={{ background: "#82909c" }} /> Alternatives · click to compare</span>
        <span><i style={{ background: "#de7043" }} /> Traffic impact</span>
        {sim?.ghostCoords && <span><i className="legend-dash" style={{ background: "#c0392b" }} /> Abandoned leg</span>}
      </div>
      {data && !data.traffic_configured && (
        <div className="map-note">
          Traffic is running in realistic <b>SIMULATED</b> mode (A81/A6 corridors). Click "Traffic: Simulated" above to configure a live TomTom key.
        </div>
      )}
      {data?.incidents.status === "ERROR" && <div className="map-note">Traffic incidents could not be refreshed. Coverage may be incomplete.</div>}
      {error && <div role="alert" className="map-note">{error}</div>}
      <details className="weather-readout">
        <summary>Weather along the route · {forecasts.filter((w) => w.status === "FORECAST").length} forecast samples</summary>
        {forecasts.map((w, i) => (
          <div key={w.id + i}>
            <span>{w.condition ?? w.status} · {w.temperature_c ?? "—"}°C</span>
            <span>{dt(w.valid_at)} · {w.status} · wind {w.wind_kmh ?? "—"} km/h</span>
          </div>
        ))}
        <p>Previewing a time changes the overlay only. The planner refreshes ETAs every 2 minutes while active; refresh manually for an immediate update. Weather impacts are modelled, not measured delays.</p>
      </details>
      {showKeyModal && (
        <div className="key-modal-overlay" onClick={() => setShowKeyModal(false)}>
          <div className="key-modal" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <h3>TomTom Traffic Configuration</h3>
              <button className="sim-ghost" onClick={() => setShowKeyModal(false)}><X size={16} /></button>
            </div>
            <p>
              The platform uses TomTom for live truck-specific routing, raster flow tiles, and incident feeds. Without an API key, the platform operates in <b>Simulated Traffic Mode</b> (realistic congestion on A81/A6 corridors).
            </p>
            <label style={{ display: "block", fontSize: "11.5px", fontWeight: 700, marginBottom: 6 }}>TomTom API Key</label>
            <input
              type="password"
              placeholder={settings?.tomtom_configured ? `Current key: ${settings.tomtom_masked}` : "Paste your TomTom API key here..."}
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
            />
            {keyMsg && <div style={{ fontSize: "12px", marginBottom: 12, color: keyMsg.includes("!") ? "var(--ok)" : "var(--bad)" }}>{keyMsg}</div>}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
              <a href="https://developer.tomtom.com" target="_blank" rel="noreferrer" style={{ fontSize: "11px", display: "inline-flex", alignItems: "center", gap: 4, color: "var(--blue)" }}>
                Get free key at developer.tomtom.com <ExternalLink size={12} />
              </a>
              <div className="key-modal-actions">
                {settings?.tomtom_configured && (
                  <button className="btn btn--sm btn--ghost" disabled={keySaving} onClick={() => void saveTomTomKey("")}>
                    Clear Key (Use Simulation)
                  </button>
                )}
                <button className="btn btn--sm btn--mint" disabled={keySaving || !keyInput.trim()} onClick={() => void saveTomTomKey(keyInput.trim())}>
                  {keySaving ? "Saving…" : "Save & Activate"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Fallback({
  nodes,
  path,
  geometry,
  sim,
}: {
  nodes: NetNode[];
  path: string[];
  geometry?: number[][] | null;
  sim?: SimView;
}) {
  const W = 760, H = 360, P = 30;
  const lons = nodes.map((n) => n.lon), lats = nodes.map((n) => n.lat);
  const lo0 = Math.min(...lons), lo1 = Math.max(...lons), la0 = Math.min(...lats), la1 = Math.max(...lats);
  const X = (lon: number) => P + ((lon - lo0) / (lo1 - lo0 || 1)) * (W - 2 * P);
  const Y = (lat: number) => P + ((la1 - lat) / (la1 - la0 || 1)) * (H - 2 * P);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const onPath = new Set(path);

  const activePoints = sim?.engaged && sim.activeCoords?.length
    ? sim.activeCoords
    : (geometry && geometry.length > 1
      ? geometry
      : path.flatMap((id) => { const n = byId.get(id); return n ? [[n.lon, n.lat]] : []; }));

  return (
    <div className="mapwrap mapfallback">
      <div className="map-lbl">{geometry ? "Basemap offline · actual road geometry retained" : "Basemap offline · schematic connection (not a road route)"}</div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ display: "block", width: "100%" }}>
        {activePoints.length > 1 && (
          <polyline fill="none" stroke={ROUTE} strokeWidth={3} points={activePoints.map(([lon, lat]) => `${X(lon)},${Y(lat)}`).join(" ")} />
        )}
        {sim?.ghostCoords && sim.ghostCoords.length > 1 && (
          <polyline fill="none" stroke="#c0392b" strokeWidth={3} strokeDasharray="4 4" points={sim.ghostCoords.map(([lon, lat]) => `${X(lon)},${Y(lat)}`).join(" ")} />
        )}
        {nodes.map((n) => {
          const x = X(n.lon), y = Y(n.lat), isHub = n.type === "hub", hot = onPath.has(n.id);
          return isHub
            ? <rect key={n.id} x={x - 6} y={y - 6} width={12} height={12} rx={2} fill={HUB} />
            : <circle key={n.id} cx={x} cy={y} r={hot ? 5 : 3.5} fill={hot ? ROUTE : "#fff"} stroke={hot ? ROUTE : BRANCH} strokeWidth={1.8} />;
        })}
        {nodes.filter((n) => n.type === "hub" || onPath.has(n.id)).map((n) => (
          <text key={n.id + "t"} x={X(n.lon) + 8} y={Y(n.lat) + 3} fontSize={10} fontWeight={700} fill="#334">{n.name}</text>
        ))}
        {sim?.blockage && (
          <g transform={`translate(${X(sim.blockage.position[0]) - 8}, ${Y(sim.blockage.position[1]) - 8})`}>
            <circle cx={8} cy={8} r={9} fill="#c0392b" />
            <text x={8} y={12} textAnchor="middle" fill="#fff" fontSize={11} fontWeight={900}>⛔</text>
          </g>
        )}
        {sim?.engaged && sim?.truck && (
          <g transform={`translate(${X(sim.truck.position[0])}, ${Y(sim.truck.position[1])}) rotate(${Math.round(sim.truck.bearing)})`}>
            <circle cx={0} cy={0} r={10} fill="#17765e" stroke="#fff" strokeWidth={2} />
            <path d="M0 -6 L5 5 L0 2 L-5 5 Z" fill="#fff" />
          </g>
        )}
      </svg>
    </div>
  );
}
