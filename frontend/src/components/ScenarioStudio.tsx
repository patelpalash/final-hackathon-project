import { useState } from "react";
import { FlaskConical, Car, Factory, Ban, RotateCcw, Cone } from "lucide-react";
import { api } from "../api/client";
import type { NetNode, Operations } from "../api/types";
import { dt, localInput } from "../lib";

export function ScenarioStudio({ nodes, ops, onChange }: {
  nodes: NetNode[]; ops: Operations | null; onChange: () => Promise<void>;
}) {
  const [node, setNode] = useState("HN");
  const [minutes, setMinutes] = useState(120);
  const [start, setStart] = useState(() => localInput(new Date()));
  const [end, setEnd] = useState(() => localInput(new Date(Date.now() + 24 * 3600000)));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function apply(kind: "traffic" | "roadwork" | "hub_delay" | "closure") {
    if (!start || !end || Date.parse(end) <= Date.parse(start)) {
      setErr("Choose an effective end after the start."); return;
    }
    setBusy(true); setErr("");
    try {
      const defaultReason =
        kind === "traffic" ? "Heavy traffic · all routes" :
        kind === "roadwork" ? "Roadwork · all routes" :
        kind === "closure" ? "Manager-reported facility closure" :
        "Manager-reported hub congestion";
      await api.addEvent({
        kind: kind === "roadwork" ? "traffic" : kind,
        node: kind === "hub_delay" || kind === "closure" ? node : undefined,
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        minutes: kind === "closure" ? 0 : minutes,
        reason: reason.trim() || defaultReason,
      });
      await onChange();
      setReason("");
    } catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  }

  async function resolve(id: string) {
    setBusy(true); setErr("");
    try { await api.resolveEvent(id); await onChange(); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  }

  return <section className="card control-scenarios"><details className="studio studio-collapsible" open>
    <summary className="studio-title"><span><FlaskConical size={16} /> Scenario Studio</span><span className="mini mini--est">{ops?.events.length ? `${ops.events.length} RECORDED` : "TRAFFIC · HUBS"}</span></summary>
    <p>Traffic and roadwork affect each journey whose drive overlaps the selected window. Scheduled and in-transit journeys show a scenario ETA in the review queue; approved plans stay unchanged until a manager acts. Hub events apply to journeys visiting the selected facility.</p>
    <div className="studio-controls">
      <label>Target hub · hub events<select aria-label="Scenario target facility" value={node} onChange={e => setNode(e.target.value)}>{nodes.map(n => <option key={n.id} value={n.id}>{n.name}</option>)}</select></label>
      <label>Delay per affected trip<select aria-label="Scenario delay duration" value={minutes} onChange={e => setMinutes(Number(e.target.value))}>{[30,60,90,120,180,240].map(n => <option key={n} value={n}>+{n} minutes</option>)}</select></label>
      <label>Effective from · local time<input aria-label="Scenario effective from" type="datetime-local" value={start} onChange={e => setStart(e.target.value)} /></label>
      <label>Effective until · local time<input aria-label="Scenario effective until" type="datetime-local" value={end} onChange={e => setEnd(e.target.value)} /></label>
      <label className="scenario-reason">Manager reason · optional<input aria-label="Scenario manager reason" maxLength={500} placeholder="e.g. Heilbronn loading backlog" value={reason} onChange={e => setReason(e.target.value)} /></label>
    </div>
    <div className="scenario-actions">
      <button disabled={busy || !nodes.length} onClick={() => void apply("hub_delay")}><Factory size={18} /><span>Hub delay<small>+{minutes}m for every overlapping visit</small></span></button>
      <button disabled={busy || !nodes.length} onClick={() => void apply("closure")}><Ban size={18} /><span>Hub closure<small>Block the hub during this window</small></span></button>
      <button disabled={busy || !nodes.length} onClick={() => void apply("traffic")}><Car size={18} /><span>Heavy traffic<small>+{minutes}m per affected trip</small></span></button>
      <button disabled={busy || !nodes.length} onClick={() => void apply("roadwork")}><Cone size={18} /><span>Roadwork<small>+{minutes}m per affected trip</small></span></button>
    </div>
    {err && <div role="alert" className="notice notice--warn">{err}</div>}
    {ops?.events.map(e => <div className="scenario-event" key={e.id}><span><b>{e.node ? nodes.find(n => n.id === e.node)?.name ?? e.node : e.origin && e.destination ? `${nodes.find(n => n.id === e.origin)?.name ?? e.origin} → ${nodes.find(n => n.id === e.destination)?.name ?? e.destination}` : "All routes"}</b> · {e.reason}<small> · {dt(e.start)} to {dt(e.end)} · {e.affected_count ?? 0} journeys exposed</small></span><button aria-label={`Resolve ${e.reason}`} disabled={busy} onClick={() => void resolve(e.id)}><RotateCcw size={13} /> Resolve</button></div>)}
  </details></section>;
}
