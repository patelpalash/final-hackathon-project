/**
 * Journey simulation engine — pure functions, no React, no network.
 *
 * The vehicle is driven along the geometry the planner already returned, paced
 * by that plan's OWN step timeline. Handling, transfers, weekend holds and legal
 * rests are reproduced as stationary phases rather than animated through, so
 * what you watch is a replay of the computed plan, not a decorative animation.
 */
import type { RouteOption, JourneyStep } from "../api/types";

export type LngLat = [number, number];

/** Metres-accurate enough for corridor maths at European scale. */
export function haversineKm(a: LngLat, b: LngLat) {
  const R = 6371, rad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * rad, dLon = (b[0] - a[0]) * rad;
  const s = Math.sin(dLat / 2) ** 2 +
    Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
}

export function cumulativeKm(coords: LngLat[]) {
  const out = [0];
  for (let i = 1; i < coords.length; i++) out.push(out[i - 1] + haversineKm(coords[i - 1], coords[i]));
  return out;
}

/** Interpolated position at `km` along a polyline, plus the bearing there. */
export function pointAtKm(coords: LngLat[], cum: number[], km: number): { position: LngLat; bearing: number } {
  if (coords.length === 0) return { position: [0, 0], bearing: 0 };
  if (coords.length === 1) return { position: coords[0], bearing: 0 };
  const target = Math.max(0, Math.min(cum[cum.length - 1], km));
  let i = 1;
  while (i < cum.length - 1 && cum[i] < target) i++;
  const span = cum[i] - cum[i - 1];
  const f = span > 0 ? (target - cum[i - 1]) / span : 0;
  const a = coords[i - 1], b = coords[i];
  const position: LngLat = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
  const rawBearing = (Math.atan2(b[0] - a[0], b[1] - a[1]) * 180) / Math.PI;
  const bearing = (rawBearing + 360) % 360;
  return { position, bearing };
}

/** Index of the polyline vertex closest to `p`, with its distance. */
export function nearestVertex(coords: LngLat[], p: LngLat) {
  let index = 0, best = Infinity;
  for (let i = 0; i < coords.length; i++) {
    const d = haversineKm(coords[i], p);
    if (d < best) { best = d; index = i; }
  }
  return { index, km: best };
}

const DRIVING: JourneyStep["type"] = "drive";

export const PHASE_LABEL: Record<string, string> = {
  drive: "Driving", handling: "Handling & transfer", legal_wait: "Legal rest",
  hub_delay: "Operational delay", weekend_hold: "Weekend hold",
  weather: "Weather impact", schedule_wait: "Waiting for next service",
};

export interface Phase {
  type: string; startMin: number; endMin: number; driving: boolean;
  label: string; detail: string; locationName: string; km0: number; km1: number;
}

export interface SimPlan {
  coords: LngLat[]; cum: number[]; totalKm: number;
  phases: Phase[]; totalMinutes: number; departAt: number;
  /** Driving kilometres per driving minute, from this plan's own figures. */
  kmPerMin: number;
  approximate: boolean;
}

/**
 * Build a simulation plan from a route option. `fallbackCoords` is used when the
 * option has no road geometry, in which case the replay is flagged approximate.
 */
export function buildPlan(option: RouteOption, fallbackCoords: LngLat[]): SimPlan | null {
  const coords = (option.geometry?.length ? option.geometry : fallbackCoords) as LngLat[];
  if (!coords || coords.length < 2) return null;
  const cum = cumulativeKm(coords);
  const totalKm = cum[cum.length - 1];
  const departAt = Date.parse(option.depart_at);
  const steps = option.steps ?? [];

  const raw = steps.map((s) => ({
    type: s.type,
    startMin: Math.max(0, (Date.parse(s.start) - departAt) / 60000),
    endMin: Math.max(0, (Date.parse(s.end) - departAt) / 60000),
    detail: s.detail,
    locationName: s.location_name,
  })).filter((p) => Number.isFinite(p.startMin) && Number.isFinite(p.endMin) && p.endMin > p.startMin)
    .sort((a, b) => a.startMin - b.startMin);

  const driveMinutes = raw.filter((p) => p.type === DRIVING).reduce((n, p) => n + (p.endMin - p.startMin), 0);
  const allocMinutes = driveMinutes > 0 ? driveMinutes : raw.reduce((n, p) => n + (p.endMin - p.startMin), 0);
  const phases: Phase[] = [];
  let km = 0;
  for (const p of raw) {
    const driving = driveMinutes > 0 ? p.type === DRIVING : true;
    // Distance is shared between driving phases in proportion to their duration,
    // so the vehicle is stationary during every hold the planner computed.
    const share = allocMinutes > 0 ? (totalKm * (p.endMin - p.startMin)) / allocMinutes : 0;
    phases.push({ ...p, driving, label: PHASE_LABEL[p.type] ?? p.type, km0: km, km1: km + share });
    km += share;
  }
  if (phases.length) phases[phases.length - 1].km1 = totalKm;

  const total = Math.max(1, option.total_minutes || (phases.length ? phases[phases.length - 1].endMin : 0));
  const driveOnly = option.components?.transport || driveMinutes || total;
  return {
    coords, cum, totalKm, phases, totalMinutes: total, departAt,
    kmPerMin: totalKm / Math.max(1, driveOnly),
    approximate: !option.geometry?.length,
  };
}

export interface SimSnapshot {
  position: LngLat; bearing: number; km: number; progress: number;
  phase: Phase | null; clock: number; remainingKm: number; done: boolean;
}

/** Where the vehicle is `t` simulated minutes after departure. */
export function snapshotAt(plan: SimPlan, t: number): SimSnapshot {
  const clamped = Math.max(0, Math.min(plan.totalMinutes, t));
  let phase: Phase | null = null, km = 0;
  if (!plan.phases.length) {
    km = plan.totalKm * (plan.totalMinutes ? clamped / plan.totalMinutes : 0);
  } else {
    if (clamped < plan.phases[0].startMin) {
      phase = plan.phases[0];
      km = 0;
    } else if (clamped >= plan.phases[plan.phases.length - 1].endMin) {
      phase = plan.phases[plan.phases.length - 1];
      km = plan.totalKm;
    } else {
      phase = plan.phases[0];
      for (const p of plan.phases) { if (clamped >= p.startMin) phase = p; else break; }
      if (phase.driving) {
        const span = phase.endMin - phase.startMin;
        const fraction = span > 0 ? Math.max(0, Math.min(1, (clamped - phase.startMin) / span)) : 0;
        km = phase.km0 + (phase.km1 - phase.km0) * fraction;
      } else {
        km = phase.km0;
      }
    }
  }
  km = Math.max(0, Math.min(plan.totalKm, km));
  const { position, bearing } = pointAtKm(plan.coords, plan.cum, km);
  return {
    position, bearing, km, progress: plan.totalKm ? km / plan.totalKm : 0,
    phase, clock: plan.departAt + clamped * 60000,
    remainingKm: Math.max(0, plan.totalKm - km), done: clamped >= plan.totalMinutes,
  };
}

/** Dwell time still to be served at this option's intermediate facilities. */
export function intermediateHoldMinutes(option: RouteOption) {
  const middle = new Set(option.path.slice(1, -1));
  return (option.steps ?? [])
    .filter((s) => s.type !== DRIVING && middle.has(s.location))
    .reduce((n, s) => n + s.minutes, 0);
}

function kmPerMinute(option: RouteOption) {
  const km = option.cost?.distance_km ?? 0;
  const driving = option.components?.transport ?? 0;
  return km > 0 && driving > 0 ? km / driving : 1.05; // ~63 km/h prototype floor
}

export interface Diversion {
  index: number; option: RouteOption; joinIndex: number; connectorKm: number;
  stayMinutes: number; viaMinutes: number; minutesAvoided: number;
  costDeltaEur: number; fuelDeltaL: number; holdMinutes: number;
}

/**
 * Pick the best alternative to divert onto from the vehicle's current position.
 *
 * Staying put costs the remaining drive on the current route plus the blockage.
 * Diverting costs a connector to the alternative corridor, the rest of that
 * corridor, and any transfer dwell it still owes. Both sides use each option's
 * own distance and driving-time figures, so no speed is invented.
 * Returns null when nothing beats staying.
 */
export function chooseDiversion(
  position: LngLat, remainingKmOnRoute: number, active: RouteOption,
  options: RouteOption[], blockageMinutes: number,
  limits: { maxConnectorKm?: number; minGainMinutes?: number } = {},
): Diversion | null {
  const maxConnectorKm = limits.maxConnectorKm ?? 60;
  const minGain = limits.minGainMinutes ?? 5;
  const stayMinutes = remainingKmOnRoute / kmPerMinute(active) + blockageMinutes;

  let best: Diversion | null = null;
  options.forEach((candidate, index) => {
    if (candidate === active) return;
    const geometry = candidate.geometry as LngLat[] | null | undefined;
    if (!geometry || geometry.length < 2) return;
    const cum = cumulativeKm(geometry);
    const { index: joinIndex, km: connectorKm } = nearestVertex(geometry, position);
    if (connectorKm > maxConnectorKm) return;
    const aheadKm = cum[cum.length - 1] - cum[joinIndex];
    if (aheadKm <= 0) return;
    const speed = kmPerMinute(candidate);
    const holdMinutes = intermediateHoldMinutes(candidate);
    const viaMinutes = (connectorKm + aheadKm) / speed + holdMinutes;
    if (viaMinutes >= stayMinutes - minGain) return;
    if (!best || viaMinutes < best.viaMinutes) {
      best = {
        index, option: candidate, joinIndex, connectorKm: Math.round(connectorKm * 10) / 10,
        stayMinutes: Math.round(stayMinutes), viaMinutes: Math.round(viaMinutes),
        minutesAvoided: Math.round(stayMinutes - viaMinutes), holdMinutes: Math.round(holdMinutes),
        costDeltaEur: Math.round(candidate.cost.transport_eur - active.cost.transport_eur),
        fuelDeltaL: Math.round(candidate.cost.fuel_l - active.cost.fuel_l),
      };
    }
  });
  return best;
}

/** A point on the route ahead of the vehicle, where a blockage is placed. */
export function pointAhead(plan: SimPlan, currentKm: number, fraction = 0.45): LngLat {
  const km = currentKm + (plan.totalKm - currentKm) * fraction;
  return pointAtKm(plan.coords, plan.cum, km).position;
}

/** Build the post-diversion path: connector from here, then the new corridor. */
export function divertedCoords(position: LngLat, diversion: Diversion): LngLat[] {
  const geometry = diversion.option.geometry as LngLat[];
  return [position, ...geometry.slice(diversion.joinIndex)];
}

/** The part of the current route we are abandoning, for the ghost overlay. */
export function abandonedCoords(plan: SimPlan, currentKm: number): LngLat[] {
  const start = plan.cum.findIndex((c) => c >= currentKm);
  return plan.coords.slice(Math.max(0, start === -1 ? plan.coords.length - 1 : start));
}

/**
 * A flat, single-phase plan used after a diversion. Holds are no longer scripted
 * from the original step list, so the remainder is paced at constant speed and
 * labelled as an estimate.
 */
export function flatPlan(coords: LngLat[], minutes: number, departAt: number, label: string, approximate: boolean): SimPlan | null {
  if (coords.length < 2) return null;
  const cum = cumulativeKm(coords);
  const totalKm = cum[cum.length - 1];
  const total = Math.max(1, Math.round(minutes));
  return {
    coords, cum, totalKm, totalMinutes: total, departAt, kmPerMin: totalKm / total, approximate,
    phases: [{
      type: "drive", startMin: 0, endMin: total, driving: true, label: "Re-routed leg",
      detail: label, locationName: "En route", km0: 0, km1: totalKm,
    }],
  };
}
