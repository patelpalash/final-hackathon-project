import { useState } from "react";
import { FlaskConical, Car, Factory, Ban, RotateCcw, Cone } from "lucide-react";
import { api } from "../api/client";
import type { NetNode, Operations } from "../api/types";

export function ScenarioStudio({
  nodes, origin, destination, start, ops, onChange,
}: {
  nodes: NetNode[];
  origin: string;
  destination: string;
  start: string;
  ops: Operations | null;
  onChange: () => Promise<void>;
}) {
  const [node, setNode] = useState("HN");
  const [minutes, setMinutes] = useState(180);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function apply(kind: string) {
    setBusy(true); setErr("");
    try {
      const isCorridor = kind === "traffic" || kind === "roadwork";
      const reason =
        kind === "traffic" ? `Heavy traffic congestion on direct corridor (+${minutes}m)` :
        kind === "roadwork" ? `Construction & lane restriction on direct corridor (+${minutes}m)` :
        kind === "closure" ? "Political / operational closure at selected facility (avoided)" :
        `Hub congestion: loading capacity reduced (+${minutes}m)`;

      await api.addEvent({
        kind: isCorridor ? "traffic" : kind,
        node: isCorridor ? undefined : node,
        origin: isCorridor ? origin : undefined,
        destination: isCorridor ? destination : undefined,
        start,
        end: new Date(Date.parse(start) + 7 * 86400000).toISOString(),
        minutes: kind === "closure" ? 0 : minutes,
        reason,
      });
      await onChange();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function resolve(id: string) {
    setBusy(true);
    try {
      await api.resolveEvent(id);
      await onChange();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="studio">
      <div className="studio-title">
        <span><FlaskConical size={16} /> Scenario Studio</span>
        <span className="mini mini--est">SIMULATION</span>
      </div>
      <p>Simulate operational disruptions and watch the route optimization and live map adapt in real time.</p>
      <div className="studio-controls" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
        <label>
          Target facility
          <select aria-label="Scenario target facility" value={node} onChange={(e) => setNode(e.target.value)}>
            {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
          </select>
        </label>
        <label>
          Delay duration
          <select aria-label="Scenario delay duration" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
            <option value={30}>+30 minutes</option>
            <option value={60}>+1 hour</option>
            <option value={90}>+1.5 hours</option>
            <option value={120}>+2 hours</option>
            <option value={180}>+3 hours</option>
            <option value={240}>+4 hours</option>
          </select>
        </label>
        <button disabled={busy} onClick={() => apply("traffic")}>
          <Car size={18} />
          <span>Heavy traffic<small>+{minutes}m · direct corridor</small></span>
        </button>
        <button disabled={busy} onClick={() => apply("roadwork")}>
          <Cone size={18} />
          <span>Roadwork<small>+{minutes}m · corridor bottleneck</small></span>
        </button>
        <button disabled={busy} onClick={() => apply("hub_delay")}>
          <Factory size={18} />
          <span>Hub delay<small>+{minutes}m · selected hub</small></span>
        </button>
        <button disabled={busy} onClick={() => apply("closure")}>
          <Ban size={18} />
          <span>Hub closure<small>Avoid selected hub · 7 days</small></span>
        </button>
      </div>
      {err && <div role="alert" className="notice notice--warn">{err}</div>}
      {ops?.events.map((e) => (
        <div className="scenario-event" key={e.id}>
          <span>{e.reason} <small>· until {new Date(e.end).toLocaleDateString()}</small></span>
          <button aria-label={`Resolve ${e.reason}`} disabled={busy} onClick={() => resolve(e.id)}>
            <RotateCcw size={13} /> Resolve
          </button>
        </div>
      ))}
    </section>
  );
}
