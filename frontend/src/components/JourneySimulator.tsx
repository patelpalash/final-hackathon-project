import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Play, Pause, RotateCcw, TriangleAlert, Route as RouteIcon, ShieldCheck, Gauge, Loader2, Share2, Navigation, FastForward } from "lucide-react";
import { api } from "../api/client";
import type { NetNode, RouteOption, TruckProfile } from "../api/types";
import { dt, eur, hm } from "../lib";
import {
  buildPlan, snapshotAt, chooseDiversion, pointAhead, divertedCoords, abandonedCoords,
  flatPlan, intermediateHoldMinutes,
} from "./simulation";
import type { LngLat, SimPlan, SimSnapshot, Diversion } from "./simulation";

/** Simulated minutes per real second at 1x. A 10-hour journey replays in ~13s. */
const MINUTES_PER_SECOND = 45;
const SPEEDS = [1, 2, 4] as const;
/** Fraction of the journey after which an automatic blockage appears. */
const AUTO_TRIGGER_AT = 0.3;

export interface RerouteInfo {
  diverted: boolean;
  minutesAvoided: number;
  costDeltaEur: number;
  fuelDeltaL: number;
  etaIfStayed: number;
  etaNow: number;
  viaName: string | null;
  source: string;
  approximate: boolean;
  connectorKm: number;
}

export interface SimView {
  activeCoords: LngLat[] | null;
  ghostCoords: LngLat[] | null;
  truck: { position: LngLat; bearing: number } | null;
  blockage: { position: LngLat; minutes: number; reason: string } | null;
  running: boolean;
  engaged: boolean;
  followTruck: boolean;
}

export interface Simulation {
  view: SimView;
  ready: boolean;
  running: boolean;
  finished: boolean;
  speed: number;
  progress: number;
  snapshot: SimSnapshot | null;
  elapsedMinutes: number;
  plannedMinutes: number;
  projectedMinutes: number;
  etaMs: number | null;
  plannedEtaMs: number | null;
  reroute: RerouteInfo | null;
  blocked: boolean;
  busy: boolean;
  error: string;
  committed: boolean;
  approximate: boolean;
  deadlineMs: number | null;
  autoDisrupt: boolean;
  setAutoDisrupt: (v: boolean) => void;
  followTruck: boolean;
  setFollowTruck: (v: boolean) => void;
  disruptMinutes: number;
  setDisruptMinutes: (n: number) => void;
  disruptReason: string;
  setDisruptReason: (s: string) => void;
  seek: (fraction: number) => void;
  start: () => void;
  pause: () => void;
  reset: () => void;
  skipHold: () => void;
  setSpeed: (n: number) => void;
  inject: (minutes?: number, reason?: string) => void;
  commit: () => void;
}

interface Args {
  option: RouteOption | undefined;
  options: RouteOption[];
  nodes: NetNode[];
  deadline?: string | null;
  truck?: TruckProfile;
  onCommitted?: () => void;
}

export function useJourneySimulation({ option, options, nodes, deadline, truck, onCommitted }: Args): Simulation {
  const [running, setRunning] = useState(false);
  const [speed, setSpeed] = useState(2);
  const [t, setT] = useState(0);
  const [override, setOverride] = useState<SimPlan | null>(null);
  const [offset, setOffset] = useState(0); // minutes already driven before a diversion
  const [blockage, setBlockage] = useState<SimView["blockage"]>(null);
  const [ghost, setGhost] = useState<LngLat[] | null>(null);
  const [reroute, setReroute] = useState<RerouteInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [committed, setCommitted] = useState(false);
  const [blockedEvent, setBlockedEvent] = useState<{ origin: string; destination: string } | null>(null);
  const [autoDisrupt, setAutoDisrupt] = useState(false);
  const [followTruck, setFollowTruck] = useState(false);
  const [disruptMinutes, setDisruptMinutes] = useState(180);
  const [disruptReason, setDisruptReason] = useState("Corridor congestion · slow freight flow");

  const tRef = useRef(0);
  const injecting = useRef(false);

  const fallback = useMemo<LngLat[]>(() => {
    if (!option) return [];
    const byId = new Map(nodes.map((n) => [n.id, n]));
    return option.path.flatMap((id) => { const n = byId.get(id); return n ? [[n.lon, n.lat] as LngLat] : []; });
  }, [option, nodes]);

  const basePlan = useMemo(() => (option ? buildPlan(option, fallback) : null), [option, fallback]);
  const plan = override ?? basePlan;

  const reset = useCallback(() => {
    setRunning(false); tRef.current = 0; setT(0); setOverride(null); setOffset(0);
    setBlockage(null); setGhost(null); setReroute(null); setError("");
    setCommitted(false); setBlockedEvent(null); injecting.current = false;
  }, []);

  const seek = useCallback((fraction: number) => {
    if (!plan) return;
    const targetMin = Math.max(0, Math.min(plan.totalMinutes, fraction * plan.totalMinutes));
    tRef.current = targetMin;
    setT(targetMin);
  }, [plan]);

  // A different route option is a different journey — never keep stale state.
  const optionKey = option ? option.quote_id + option.path.join(">") : "";
  useEffect(() => { reset(); }, [optionKey, reset]);

  // Animation loop.
  useEffect(() => {
    if (!running || !plan) return;
    let frame = 0, last = performance.now(), since = 0;
    const tick = (now: number) => {
      const delta = Math.min(0.2, (now - last) / 1000);
      last = now;
      since += delta;
      tRef.current = Math.min(plan.totalMinutes, tRef.current + delta * MINUTES_PER_SECOND * speed);
      if (since >= 0.045) { since = 0; setT(tRef.current); }
      if (tRef.current >= plan.totalMinutes) { setT(plan.totalMinutes); setRunning(false); return; }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [running, speed, plan]);

  const snapshot = useMemo(() => (plan ? snapshotAt(plan, t) : null), [plan, t]);

  const inject = useCallback(async (customMinutes?: number, customReason?: string) => {
    if (!plan || !option || injecting.current || override) return;
    injecting.current = true;
    setBusy(true); setError("");
    const mins = customMinutes ?? disruptMinutes;
    const reason = customReason ?? disruptReason;
    const here = snapshotAt(plan, tRef.current);
    const position = here.position;
    setBlockage({
      position: pointAhead(plan, here.km),
      minutes: mins,
      reason: `${reason} (+${mins}m)`,
    });
    try {
      const diversion: Diversion | null = chooseDiversion(
        position, here.remainingKm, option, options, mins);
      const etaIfStayed = here.clock + (here.remainingKm / plan.kmPerMin + mins) * 60000;

      if (!diversion) {
        const remaining = abandonedCoords(plan, here.km);
        const minutes = here.remainingKm / plan.kmPerMin + mins;
        const held = flatPlan([position, ...remaining.slice(1)], minutes, here.clock,
          `Holding on the planned corridor · +${mins}m congestion absorbed`, plan.approximate);
        if (held) {
          setOffset(tRef.current); tRef.current = 0; setT(0); setOverride(held);
        }
        setReroute({
          diverted: false, minutesAvoided: 0, costDeltaEur: 0, fuelDeltaL: 0,
          etaIfStayed, etaNow: etaIfStayed, viaName: null, connectorKm: 0,
          source: "No alternative corridor improves on the planned route",
          approximate: plan.approximate,
        });
        return;
      }

      const via = diversion.option.path.length > 2 ? diversion.option.path[1] : null;
      let coords = divertedCoords(position, diversion);
      let minutes = diversion.viaMinutes;
      let source = "Approximate connector to the alternative corridor";
      let approximate = true;

      try {
        const live = await api.simulateReroute({
          lat: position[1], lon: position[0],
          destination: option.destination, via: via ?? undefined,
          depart_at: new Date(here.clock).toISOString(), truck,
          transfer_minutes: via ? Math.round(intermediateHoldMinutes(diversion.option)) : 0,
        });
        if (live.status !== "UNAVAILABLE" && live.geometry && live.geometry.length > 1) {
          coords = live.geometry as LngLat[];
          minutes = live.total_minutes;
          source = live.source;
          approximate = live.status !== "ROUTED";
        }
      } catch (e) {
        setError(`Live re-route unavailable (${String(e)}). Showing an approximate diversion.`);
      }

      const next = flatPlan(coords, minutes, here.clock,
        via
          ? `Re-routed via ${nodes.find((n) => n.id === via)?.name ?? via} · includes transfer dwell at that facility`
          : "Re-routed around the blockage",
        approximate);
      if (!next) { setError("Could not build a diversion from this position."); return; }

      setGhost(abandonedCoords(plan, here.km));
      setOffset(tRef.current); tRef.current = 0; setT(0); setOverride(next);
      setBlockedEvent({ origin: option.path[0], destination: option.path[option.path.length - 1] });
      setReroute({
        diverted: true,
        minutesAvoided: Math.round((etaIfStayed - (here.clock + minutes * 60000)) / 60000),
        costDeltaEur: diversion.costDeltaEur, fuelDeltaL: diversion.fuelDeltaL,
        etaIfStayed, etaNow: here.clock + minutes * 60000,
        viaName: via ? nodes.find((n) => n.id === via)?.name ?? via : null,
        source, approximate, connectorKm: diversion.connectorKm,
      });
    } finally {
      setBusy(false); injecting.current = false;
    }
  }, [plan, option, options, override, nodes, truck, disruptMinutes, disruptReason]);

  // Automatic blockage only if enabled
  useEffect(() => {
    if (!autoDisrupt || !running || override || !plan || injecting.current) return;
    if (plan.totalMinutes && t / plan.totalMinutes >= AUTO_TRIGGER_AT) void inject();
  }, [t, running, override, plan, inject, autoDisrupt]);

  const commit = useCallback(async () => {
    if (!blockedEvent || committed) return;
    setBusy(true); setError("");
    try {
      const start = new Date(Date.now() - 60000).toISOString();
      await api.addEvent({
        kind: "traffic", origin: blockedEvent.origin, destination: blockedEvent.destination,
        start, end: new Date(Date.now() + 2 * 86400000).toISOString(),
        minutes: blockage?.minutes ?? disruptMinutes,
        reason: `${blockage?.reason ?? "Simulated corridor congestion"} promoted to operations`,
      });
      setCommitted(true); onCommitted?.();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }, [blockedEvent, committed, onCommitted, blockage, disruptMinutes]);

  const elapsed = offset + t;
  const projected = override ? offset + override.totalMinutes : basePlan?.totalMinutes ?? 0;

  return {
    view: {
      activeCoords: plan?.coords ?? null,
      ghostCoords: ghost,
      truck: snapshot ? { position: snapshot.position, bearing: snapshot.bearing } : null,
      blockage, running,
      engaged: running || t > 0 || !!override,
      followTruck,
    },
    ready: !!plan, running, finished: !!plan && t >= plan.totalMinutes && t > 0,
    speed, progress: projected ? Math.min(1, elapsed / projected) : 0,
    snapshot, elapsedMinutes: elapsed,
    plannedMinutes: basePlan?.totalMinutes ?? 0, projectedMinutes: projected,
    etaMs: basePlan ? basePlan.departAt + projected * 60000 : null,
    plannedEtaMs: option ? Date.parse(option.eta) : null,
    reroute, blocked: !!blockage, busy, error, committed,
    approximate: !!plan?.approximate,
    deadlineMs: deadline ? Date.parse(deadline) : null,
    autoDisrupt, setAutoDisrupt,
    followTruck, setFollowTruck,
    disruptMinutes, setDisruptMinutes,
    disruptReason, setDisruptReason,
    seek,
    skipHold: () => {
      if (!plan) return;
      const currentT = tRef.current;
      const currentPhase = plan.phases.find((p) => currentT >= p.startMin && currentT < p.endMin);
      if (currentPhase && !currentPhase.driving) {
        const nextT = Math.min(plan.totalMinutes, currentPhase.endMin);
        tRef.current = nextT;
        setT(nextT);
      } else {
        const nextDrive = plan.phases.find((p) => p.startMin > currentT && p.driving);
        if (nextDrive) {
          tRef.current = nextDrive.startMin;
          setT(nextDrive.startMin);
        }
      }
    },
    start: () => {
      if (plan && tRef.current >= plan.totalMinutes) {
        tRef.current = 0;
        setT(0);
      }
      setRunning(true);
    },
    pause: () => setRunning(false), reset,
    setSpeed: (n: number) => setSpeed(n),
    inject: (m?: number, r?: string) => { void inject(m, r); },
    commit: () => { void commit(); },
  };
}

export function JourneySimulator({ sim, showCommit = true }: { sim: Simulation; showCommit?: boolean }) {
  if (!sim.ready) {
    return <div className="sim-bar sim-bar--empty">Journey simulation needs road geometry for this option.</div>;
  }
  const phase = sim.snapshot?.phase;
  const late = sim.deadlineMs != null && sim.etaMs != null && sim.etaMs > sim.deadlineMs;
  const delta = sim.projectedMinutes - sim.plannedMinutes;

  return (
    <div className="sim">
      <div className="sim-bar">
        <div className="sim-transport">
          <button className="sim-play" onClick={() => (sim.running ? sim.pause() : sim.start())}
            aria-label={sim.running ? "Pause simulation" : "Start simulation"}>
            {sim.running ? <Pause size={17} /> : <Play size={17} />}
            {sim.running ? "Pause" : sim.finished ? "Replay" : sim.progress > 0 ? "Resume" : "Simulate journey"}
          </button>
          <button className="sim-ghost" onClick={sim.reset} aria-label="Reset simulation"><RotateCcw size={14} /></button>
          <div className="sim-speeds" role="group" aria-label="Simulation speed">
            <Gauge size={13} />
            {SPEEDS.map((s) => (
              <button key={s} aria-pressed={sim.speed === s} onClick={() => sim.setSpeed(s)}>{s}×</button>
            ))}
          </div>

          <button
            type="button"
            className={`sim-follow-btn ${sim.followTruck ? "active" : ""}`}
            onClick={() => sim.setFollowTruck(!sim.followTruck)}
            title="Keep map camera centered on truck"
          >
            <Navigation size={13} /> Follow truck
          </button>

          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <select
              className="sim-disrupt-select"
              aria-label="Disruption duration"
              value={sim.disruptMinutes}
              onChange={(e) => sim.setDisruptMinutes(Number(e.target.value))}
            >
              <option value={30}>+30m delay</option>
              <option value={60}>+60m delay</option>
              <option value={120}>+2h delay</option>
              <option value={180}>+3h delay</option>
            </select>
            <select
              className="sim-disrupt-select"
              aria-label="Disruption reason"
              value={sim.disruptReason}
              onChange={(e) => sim.setDisruptReason(e.target.value)}
            >
              <option value="Corridor congestion · slow freight flow">Heavy traffic</option>
              <option value="Autobahn construction · single lane restriction">Roadwork</option>
              <option value="Severe weather · icy conditions">Severe weather</option>
              <option value="Vehicle breakdown / accident ahead">Accident</option>
            </select>
            <button className="sim-disrupt" disabled={sim.busy || sim.blocked} onClick={() => sim.inject()}>
              {sim.busy ? <Loader2 size={14} className="spin" /> : <TriangleAlert size={14} />} Block road ahead
            </button>
          </div>
        </div>

        <div className="sim-track-wrap">
          <div className="sim-track" role="progressbar" aria-valuemin={0} aria-valuemax={100}
            aria-valuenow={Math.round(sim.progress * 100)} aria-label="Journey progress">
            <span style={{ width: `${sim.progress * 100}%` }} className={sim.reroute?.diverted ? "diverted" : ""} />
          </div>
          <input
            type="range"
            className="sim-scrubber"
            min={0}
            max={100}
            step={0.5}
            value={Math.round(sim.progress * 100)}
            onChange={(e) => sim.seek(Number(e.target.value) / 100)}
            aria-label="Seek journey progress"
          />
        </div>

        <div className="sim-readout">
          <div><small>Simulated clock</small><b>{sim.snapshot ? dt(new Date(sim.snapshot.clock).toISOString()) : "—"}</b></div>
          <div>
            <small>Status</small>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <b className={phase?.driving ? "is-driving" : "is-holding"}>{phase?.label ?? "At origin"}</b>
              {phase && !phase.driving && !sim.finished && (
                <button
                  type="button"
                  className="btn btn--xs btn--ghost sim-skip-hold"
                  onClick={sim.skipHold}
                  title="Skip stationary phase and advance directly to next drive"
                  style={{ padding: "2px 7px", fontSize: "10.5px", height: "auto", display: "inline-flex", alignItems: "center", gap: 3 }}
                >
                  <FastForward size={11} /> Skip hold
                </button>
              )}
            </div>
          </div>
          <div><small>Distance covered</small><b>{Math.round(sim.snapshot?.km ?? 0)} km<span> · {Math.round(sim.snapshot?.remainingKm ?? 0)} km to go</span></b></div>
          <div><small>Projected arrival</small><b className={late ? "is-late" : ""}>{sim.etaMs ? dt(new Date(sim.etaMs).toISOString()) : "—"}
            {delta !== 0 && <span>{delta > 0 ? "+" : "−"}{hm(Math.abs(delta))} vs plan</span>}</b></div>
        </div>
        {phase && <p className="sim-detail">{phase.locationName} · {phase.detail}</p>}

        <div className="sim-options-bar">
          <label className="sim-checkbox-label">
            <input
              type="checkbox"
              checked={sim.autoDisrupt}
              onChange={(e) => sim.setAutoDisrupt(e.target.checked)}
            />
            Auto-disrupt at 30% progress
          </label>
          <span style={{ color: "var(--muted)", fontSize: "10.5px" }}>
            Drag the progress line to scrub anywhere in the journey.
          </span>
        </div>
      </div>

      {sim.reroute && (
        <div className={`sim-reroute ${sim.reroute.diverted ? "" : "sim-reroute--held"}`}>
          <div className="sim-reroute-head">
            {sim.reroute.diverted ? <RouteIcon size={18} /> : <TriangleAlert size={18} />}
            <b>{sim.reroute.diverted
              ? `Re-routed${sim.reroute.viaName ? ` via ${sim.reroute.viaName}` : ""} — ${hm(Math.abs(sim.reroute.minutesAvoided))} of delay avoided`
              : "Holding on the planned corridor — no alternative improves on it"}</b>
          </div>
          <div className="sim-reroute-values">
            <span><small>If we had stayed</small><b>{dt(new Date(sim.reroute.etaIfStayed).toISOString())}</b></span>
            <span><small>Arrival now</small><b>{dt(new Date(sim.reroute.etaNow).toISOString())}</b></span>
            <span><small>Transport cost</small><b>{sim.reroute.costDeltaEur === 0 ? "unchanged" : `${sim.reroute.costDeltaEur > 0 ? "+" : "−"}${eur(Math.abs(sim.reroute.costDeltaEur))}`}</b></span>
            <span><small>Fuel</small><b>{sim.reroute.fuelDeltaL > 0 ? "+" : "−"}{Math.abs(sim.reroute.fuelDeltaL)} L</b></span>
            {sim.deadlineMs != null && (
              <span><small>Delivery promise</small><b className={late ? "is-late" : "is-ok"}>{late ? "At risk" : "Still met"}</b></span>
            )}
          </div>
          <p className="fineprint">
            {sim.reroute.source}{sim.reroute.connectorKm ? ` · ${sim.reroute.connectorKm} km to join the alternative corridor` : ""}.
            {sim.reroute.approximate && " Diversion geometry is approximate — routing did not return a road path from this position."}
            {" "}Nothing is saved by simulating: the shipment plan changes only when a manager approves it.
          </p>
          {showCommit && sim.reroute.diverted && (
            <button className="btn btn--sm btn--ghost" disabled={sim.busy || sim.committed} onClick={sim.commit}>
              <Share2 size={14} /> {sim.committed ? "Added to operations — recalculate to see it" : "Add this blockage to live operations"}
            </button>
          )}
        </div>
      )}

      {sim.error && <div role="alert" className="notice notice--warn">{sim.error}</div>}
      <p className="sim-foot">
        <ShieldCheck size={13} /> Replay of the computed plan at {MINUTES_PER_SECOND * sim.speed} simulated minutes per second.
        Holds, transfers and legal rests are reproduced, not skipped. No live vehicle tracking exists in this prototype.
        {sim.approximate && " This option has no road geometry, so the path shown is a straight connection."}
      </p>
    </div>
  );
}
