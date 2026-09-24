import { ArrowRight, Eye, EyeOff, ShieldCheck } from "lucide-react";
import type { RouteOption } from "../api/types";
import { dt, eur, hm } from "../lib";
import "../reroute-impact.css";

type Props = {
  affected: RouteOption;
  clear: RouteOption;
  selectedClear: boolean;
  showAffectedRoad: boolean;
  onToggleAffectedRoad: () => void;
  onSelectOther: () => void;
};

function change(value: number, unit: string) {
  const rounded = Math.round(Math.abs(value) * 10) / 10;
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${rounded}${unit}`;
}

export function RerouteImpact({ affected, clear, selectedClear, showAffectedRoad, onToggleAffectedRoad, onSelectOther }: Props) {
  const distance = clear.cost.distance_km - affected.cost.distance_km;
  const minutes = clear.total_minutes - affected.total_minutes;
  const fuel = clear.cost.fuel_l - affected.cost.fuel_l;
  const cost = clear.cost.transport_eur - affected.cost.transport_eur;
  const condition = [...new Set((affected.zone_impacts ?? []).map(z => z.kind))].join(" + ") || "weather";
  const simulatedDelay = Math.max(0, ...(affected.zone_impacts ?? []).map(z => z.delay_minutes));
  const metrics = [
    { label: "Road distance", value: change(distance, " km"), detail: `${affected.cost.distance_km} → ${clear.cost.distance_km} km` },
    { label: "Arrival time", value: minutes === 0 ? "No change" : `${hm(Math.abs(minutes))} ${minutes < 0 ? "earlier" : "later"}`, detail: `${dt(affected.eta)} → ${dt(clear.eta)}` },
    { label: "Fuel estimate", value: change(fuel, " L"), detail: `${affected.cost.fuel_l} → ${clear.cost.fuel_l} L` },
    { label: "Transport cost", value: `${cost > 0 ? "+" : cost < 0 ? "−" : ""}${eur(Math.abs(cost))}`, detail: `${eur(affected.cost.transport_eur)} → ${eur(clear.cost.transport_eur)}` },
  ];

  return <section className="reroute-impact" aria-label="Weather reroute impact">
    <div className="reroute-impact__intro">
      <span className="eyebrow">WEATHER REROUTE · DECISION IMPACT</span>
      <h3>What changes if we avoid the {condition} zone?</h3>
      <p>Compared with the same shipment driving through the simulated weather. {simulatedDelay > 0 && `The affected road includes a +${hm(simulatedDelay)} manual weather-delay assumption. `}The clear road geometry is checked against every active zone with a 2 km margin.</p>
    </div>
    <div className="reroute-impact__journeys">
      <div><span className="reroute-impact__dot reroute-impact__dot--affected"/><span>Through weather</span><strong>{dt(affected.eta)}</strong></div>
      <ArrowRight size={16} aria-hidden="true"/>
      <div><span className="reroute-impact__dot reroute-impact__dot--clear"/><span>Verified clear</span><strong>{dt(clear.eta)}</strong></div>
    </div>
    <div className="reroute-impact__metrics">{metrics.map(m => <div key={m.label}><small>{m.label}</small><strong>{m.value}</strong><span>{m.detail}</span></div>)}</div>
    <div className="reroute-impact__actions">
      <span><ShieldCheck size={14}/> Estimated trade-off · no dispatch until manager approval</span>
      <button type="button" onClick={onSelectOther}>{selectedClear ? "Inspect weather-hit route" : "Inspect clear detour"}</button>
      {selectedClear && <button type="button" onClick={onToggleAffectedRoad}>
        {showAffectedRoad ? <EyeOff size={14}/> : <Eye size={14}/>}{showAffectedRoad ? "Hide" : "Show"} affected road
      </button>}
    </div>
  </section>;
}
