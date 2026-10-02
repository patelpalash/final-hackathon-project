import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, DragEvent, MouseEvent, ReactNode, RefObject } from "react";
import maplibregl from "maplibre-gl";
import type { RouteOption, WeatherZone, WeatherZoneInput } from "../api/types";
import "../weather-simulation.css";

type Kind = WeatherZoneInput["kind"];
const HAZARDS: { kind: Kind; icon: string; label: string }[] = [
  { kind: "snow", icon: "❄", label: "Heavy snow" },
  { kind: "rain", icon: "☔", label: "Heavy rain" },
  { kind: "tornado", icon: "🌪", label: "Tornado" },
];

type Props = {
  children: ReactNode;
  mapRef: RefObject<maplibregl.Map | null>;
  mapContainerRef: RefObject<HTMLDivElement | null>;
  ready: boolean;
  styleVersion: number;
  fallback: boolean;
  demo: boolean;
  routeCoords: number[][];
  weatherZones: WeatherZone[];
  plannedStart?: string;
  plannedEnd?: string;
  avoidanceStatus?: RouteOption["avoidance_status"];
  onAddWeatherZone?: (zone: WeatherZoneInput) => Promise<void>;
  onUpdateWeatherZone?: (id: string, zone: WeatherZoneInput) => Promise<void>;
  onDeleteWeatherZone?: (id: string) => Promise<void>;
  onCancelWeatherZones?: (ids: string[]) => Promise<void>;
};

function circle(zone: WeatherZone): number[][] {
  const lonKm = 111.32 * Math.max(0.1, Math.cos(zone.lat * Math.PI / 180));
  return Array.from({ length: 65 }, (_, i) => {
    const angle = 2 * Math.PI * i / 64;
    return [zone.lon + Math.cos(angle) * zone.radius_km / lonKm,
      zone.lat + Math.sin(angle) * zone.radius_km / 111.32];
  });
}

export function MapWeatherSimulation({
  children, mapRef, mapContainerRef, ready, styleVersion, fallback, demo,
  routeCoords, weatherZones, plannedStart, plannedEnd, avoidanceStatus,
  onAddWeatherZone, onUpdateWeatherZone, onDeleteWeatherZone,
  onCancelWeatherZones,
}: Props) {
  const markers = useRef<maplibregl.Marker[]>([]);
  const [kind, setKind] = useState<Kind | null>(null);
  const [radius, setRadius] = useState(18);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pixels, setPixels] = useState<Record<string, { left: number; top: number; size: number }>>({});

  const active = useMemo(() => weatherZones.filter(z =>
    !plannedStart || !plannedEnd ||
    (Date.parse(z.start) < Date.parse(plannedEnd) && Date.parse(z.end) > Date.parse(plannedStart))
  ), [weatherZones, plannedStart, plannedEnd]);

  async function save(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try { await work(); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }

  function cancelWeatherSimulation() {
    if (busy) return;
    setSelected(null);
    setKind(null);
    if (!onCancelWeatherZones || !active.length) return;
    void save(() => onCancelWeatherZones(active.map(zone => zone.id)));
  }

  function place(hazard: Kind, lon: number, lat: number) {
    if (!onAddWeatherZone || demo || busy) return;
    const start = plannedStart ?? new Date().toISOString();
    const finish = Math.max(Date.parse(plannedEnd ?? start) + 24 * 3600000, Date.parse(start) + 24 * 3600000);
    void save(() => onAddWeatherZone({ kind: hazard, lon, lat, radius_km: radius, start, end: new Date(finish).toISOString() }));
    setKind(null);
  }

  function pointFromEvent(e: { clientX: number; clientY: number }) {
    const map = mapRef.current;
    const box = mapContainerRef.current?.getBoundingClientRect();
    if (!map || !box || !ready) return null;
    return map.unproject([e.clientX - box.left, e.clientY - box.top]);
  }

  function drop(e: DragEvent<HTMLDivElement>) {
    const hazard = e.dataTransfer.getData("application/x-weather-kind") as Kind;
    if (!HAZARDS.some(h => h.kind === hazard)) return;
    e.preventDefault();
    const point = pointFromEvent(e);
    if (point) place(hazard, point.lng, point.lat);
  }

  function clickPlace(e: MouseEvent<HTMLButtonElement>) {
    if (!kind) return;
    const point = pointFromEvent(e);
    if (point) place(kind, point.lng, point.lat);
  }

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || fallback) return;
    const sync = () => {
      if (!map.isStyleLoaded()) return;
      const geo = { type: "FeatureCollection" as const, features: active.map(z => ({
        type: "Feature" as const,
        properties: { id: z.id, kind: z.kind },
        geometry: { type: "Polygon" as const, coordinates: [circle(z)] },
      })) };
      const source = map.getSource("sim-weather-zones") as maplibregl.GeoJSONSource | undefined;
      if (source) source.setData(geo);
      else {
        map.addSource("sim-weather-zones", { type: "geojson", data: geo });
        const before = map.getLayer("alternatives-line") ? "alternatives-line" : undefined;
        map.addLayer({ id: "sim-weather-fill", type: "fill", source: "sim-weather-zones",
          paint: { "fill-color": ["match", ["get", "kind"], "snow", "#5daee8", "rain", "#4462b0", "tornado", "#d15e7d", "#8da3ae"], "fill-opacity": 0.25 } }, before);
        map.addLayer({ id: "sim-weather-edge", type: "line", source: "sim-weather-zones",
          paint: { "line-color": ["match", ["get", "kind"], "snow", "#3888ca", "rain", "#294c9d", "tornado", "#c23563", "#80909b"], "line-width": 2.5, "line-dasharray": [2, 1] } }, before);
      }
    };
    sync();
    map.on("style.load", sync);
    return () => { map.off("style.load", sync); };
  }, [active, ready, fallback, styleVersion, mapRef]);

  useEffect(() => {
    const map = mapRef.current;
    markers.current.forEach(marker => marker.remove());
    markers.current = [];
    if (!map || !ready || fallback) return;
    markers.current = active.map(zone => {
      const button = document.createElement("button");
      button.className = `sim-zone-marker sim-zone-marker--${zone.kind}`;
      button.textContent = HAZARDS.find(h => h.kind === zone.kind)?.icon ?? "!";
      button.title = `Simulated ${zone.kind} · drag to move · ${zone.radius_km} km radius`;
      button.setAttribute("aria-label", button.title);
      button.addEventListener("click", () => { setSelected(zone.id); setRadius(zone.radius_km); });
      const marker = new maplibregl.Marker({ element: button, draggable: !!onUpdateWeatherZone })
        .setLngLat([zone.lon, zone.lat]).addTo(map);
      marker.on("dragend", () => {
        const point = marker.getLngLat();
        if (onUpdateWeatherZone) void save(() => onUpdateWeatherZone(zone.id, {
          kind: zone.kind, lon: point.lng, lat: point.lat, radius_km: zone.radius_km,
          start: zone.start, end: zone.end,
        }));
      });
      return marker;
    });
    return () => { markers.current.forEach(marker => marker.remove()); markers.current = []; };
  }, [active, ready, fallback, onUpdateWeatherZone, mapRef]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || fallback) { setPixels({}); return; }
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const next: Record<string, { left: number; top: number; size: number }> = {};
        for (const zone of active) {
          const center = map.project([zone.lon, zone.lat]);
          const lonKm = 111.32 * Math.max(0.1, Math.cos(zone.lat * Math.PI / 180));
          const edge = map.project([zone.lon + zone.radius_km / lonKm, zone.lat]);
          const r = Math.max(1, Math.abs(edge.x - center.x));
          next[zone.id] = { left: center.x - r, top: center.y - r, size: 2 * r };
        }
        setPixels(next);
      });
    };
    update();
    map.on("move", update);
    map.on("resize", update);
    return () => { cancelAnimationFrame(frame); map.off("move", update); map.off("resize", update); };
  }, [active, ready, fallback, mapRef]);

  const enabled = !demo && !!onAddWeatherZone;

  return <>
    {enabled && <details className="weather-simulator" open={active.length > 0 || !!kind}>
      <summary className="weather-simulator-heading"><strong>Weather simulation {active.length > 0 ? `· ${active.length} active` : ""}</strong><span>Drop snow, rain or tornado on the route</span>
        {(active.length > 0 || kind) && <button type="button" className="sim-cancel-weather" disabled={busy} onClick={(e) => { e.preventDefault(); void cancelWeatherSimulation(); }}>× Cancel weather simulation</button>}
      </summary>
      <div className="weather-simulator-tools">
        <div className="hazard-palette">{HAZARDS.map(h => <button key={h.kind} type="button" draggable={!busy && !fallback} disabled={busy}
          aria-pressed={kind === h.kind}
          onDragStart={e => { e.dataTransfer.setData("application/x-weather-kind", h.kind); e.dataTransfer.effectAllowed = "copy"; }}
          onClick={() => { setKind(kind === h.kind ? null : h.kind); setSelected(null); }}>
          <span aria-hidden="true">{h.icon}</span>{h.label}</button>)}</div>
        <label className="sim-radius">Radius <b>{radius} km</b><input aria-label="Weather zone radius" type="range" min="5" max="60"
          value={radius} onChange={e => setRadius(Number(e.target.value))}/></label>
        <button type="button" className="sim-midpoint" disabled={!kind || busy || routeCoords.length < 2}
          onClick={() => { const point = routeCoords[Math.floor(routeCoords.length / 2)]; place(kind!, point[0], point[1]); }}>Place on route</button>
      </div>
      <small>{fallback ? "Map interaction is unavailable here; choose a weather type and use Place on route." :
        "Choose a weather type, then click the map or drag it to a road section. Drag its pin to move it."}</small>
    </details>}
    <div className="map-viewport" onDragOver={e => { if (e.dataTransfer.types.includes("application/x-weather-kind")) e.preventDefault(); }} onDrop={drop}>
      {children}
      {enabled && !fallback && active.map(zone => {
        const p = pixels[zone.id];
        return p ? <div key={zone.id} className={`sim-weather-effect sim-weather-effect--${zone.kind}`}
          style={{ left: p.left, top: p.top, width: p.size, height: p.size, "--zone-diameter": `${p.size}px` } as CSSProperties} aria-hidden="true">
          {Array.from({ length: zone.kind === "tornado" ? 9 : 16 }, (_, i) => <span key={i} className="sim-weather-particle"
            style={{ left: `${(i * 37) % 100}%`, animationDelay: `-${(i % 7) * .43}s` }}>
            {zone.kind === "snow" ? "❄" : zone.kind === "rain" ? "╱" : "·"}</span>)}
          {zone.kind === "tornado" && <i className="sim-tornado-core"/>}
        </div> : null;
      })}
      {enabled && kind && !fallback && <button className="sim-place-layer" aria-label={`Place ${kind} weather zone on map`} onClick={clickPlace}>
        <span>Click to place {kind} zone</span></button>}
    </div>
    {enabled && active.length > 0 && <div className="sim-zone-status"><strong>{busy ? "Recalculating road options…" :
      avoidanceStatus === "CLEAR" ? "Verified clear road detour" :
      avoidanceStatus === "NO_CLEAR_DETOUR" ? "No clear road detour found" :
      avoidanceStatus === "IMPACTED" ? "Selected road crosses a simulated zone" :
      active.length ? "Zone misses this selected road" : "No map weather zone active"}</strong>
      <span>{avoidanceStatus === "CLEAR" ? "Road geometry checked against every active zone with 2 km clearance." :
        "Weather zones are a manual what-if simulation; live forecast markers remain separate."}</span></div>}
    {enabled && active.length > 0 && <div className="sim-zone-list">{active.map(zone => <div key={zone.id} className={selected === zone.id ? "is-selected" : ""}>
      <button type="button" onClick={() => { setSelected(zone.id); setRadius(zone.radius_km); mapRef.current?.flyTo({ center: [zone.lon, zone.lat], zoom: Math.max(mapRef.current.getZoom(), 7) }); }}>
        {HAZARDS.find(h => h.kind === zone.kind)?.icon} {zone.kind} · {zone.radius_km} km</button>
      <span>{active.some(a => a.id === zone.id) ? "This trip" : "Other time"}</span>
      {selected === zone.id && onUpdateWeatherZone && <button type="button" disabled={busy || radius === zone.radius_km}
        onClick={() => void save(() => onUpdateWeatherZone(zone.id, { kind: zone.kind, lon: zone.lon, lat: zone.lat,
          radius_km: radius, start: zone.start, end: zone.end }))}>Apply radius</button>}
      <button type="button" disabled={busy} aria-label={`Remove ${zone.kind} zone`}
        onClick={() => { setSelected(null); if (onDeleteWeatherZone) void save(() => onDeleteWeatherZone(zone.id)); }}>×</button>
    </div>)}</div>}
    {enabled && error && <div role="alert" className="map-note">{error}</div>}
  </>;
}
