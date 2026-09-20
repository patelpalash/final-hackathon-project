import { useCallback, useEffect, useState } from "react";
import { PiggyBank, Fuel, Clock, TrendingDown, ShieldAlert, RefreshCw, Route, Loader2 } from "lucide-react";
import { api } from "../api/client";
import type { SavingsResp, Performance } from "../api/types";
import { eur, hm, dt } from "../lib";

function signedHm(m: number) { return (m < 0 ? "\u2212" : "") + hm(Math.abs(m)); }
function signedEur(n: number) { return (n < 0 ? "\u2212" : "") + eur(Math.abs(n)); }

export function Savings() {
  const [s, setS] = useState<SavingsResp | null>(null);
  const [actual, setActual] = useState<Performance | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [repaired, setRepaired] = useState<number | null>(null);

  const load = useCallback(() => {
    let alive = true;
    Promise.all([api.savings(), api.performance()])
      .then(([a, b]) => { if (alive) { setS(a); setActual(b); setError(""); } })
      .catch((e) => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, []);
  useEffect(() => load(), [load]);

  async function recalculate() {
    setBusy(true); setError("");
    try { const r = await api.recalculateSavings(); setS(r); setRepaired(r.repaired ?? 0); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  const total = s?.total;
  const rate = s?.assumptions.value_of_time_eur_per_hour ?? 50;
  const rows = s?.per_shipment ?? [];
  const counted = rows.filter((r) => r.comparable);

  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">WHAT THE PLANNING ACTUALLY SAVED</span>
          <h1>Every euro, traced<br />to a saved plan.</h1>
          <p>Three separate sources of value, each measured against a stated baseline. Nothing is extrapolated.</p>
        </div>
        <button className="btn btn--ghost" disabled={busy} onClick={recalculate}>
          {busy ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />} Rebuild missing baselines
        </button>
      </div>

      {error && <div role="alert" className="notice notice--warn">{error}</div>}
      {repaired !== null && (
        <div role="status" className="notice notice--info">
          {repaired === 0
            ? "No saved plan could be repaired from its own stored options. Re-approve those shipments in the control room to start measuring them."
            : `${repaired} saved plan${repaired > 1 ? "s" : ""} given a baseline from ${repaired > 1 ? "their" : "its"} own stored option set. Nothing was re-planned, so approved numbers are unchanged.`}
        </div>
      )}

      <div className="savings-headline">
        <div className="savings-headline-main">
          <span className="eyebrow">TOTAL ECONOMIC BENEFIT</span>
          <strong>{eur(total?.economic_benefit_eur)}</strong>
          <small>
            across {total?.optimized ?? 0} measured shipment{total?.optimized === 1 ? "" : "s"}
            {s?.rerouted_count ? ` \u00b7 ${s.rerouted_count} re-routed around a disruption` : ""}
            {" \u00b7 "}avg {eur(s?.avg_per_shipment_eur)} each
          </small>
        </div>
        <div className="savings-breakdown">
          <span><small>Transport cost</small><b className={(total?.money_eur ?? 0) >= 0 ? "is-ok" : "is-late"}>{total ? signedEur(total.money_eur) : "\u2014"}</b></span>
          <span><small>Transit time valued</small><b>{total ? signedEur(total.time_value_eur) : "\u2014"}</b></span>
          <span><small>Disruption avoided</small><b>{total ? signedEur(total.disruption_eur) : "\u2014"}</b></span>
          <span><small>Exposure avoided</small><b>{total ? eur(total.exposure_avoided_eur) : "\u2014"}</b></span>
        </div>
      </div>

      <div className="tiles">
        <div className="tile tile--accent">
          <div className="l"><PiggyBank size={13} /> Transport cost saved</div>
          <div className="v">{total ? signedEur(total.money_eur) : "\u2014"}</div>
          <div className="s">vs each shipment's own direct road option</div>
        </div>
        <div className="tile">
          <div className="l"><Clock size={13} /> Transit time saved</div>
          <div className="v">{total ? signedHm(total.time_min) : "\u2014"}</div>
          <div className="s">valued at {eur(rate)}/hour \u00b7 {total ? signedEur(total.time_value_eur) : "\u2014"}</div>
        </div>
        <div className="tile">
          <div className="l"><Fuel size={13} /> Fuel saved</div>
          <div className="v">{total ? `${total.fuel_l} L` : "\u2014"}</div>
          <div className="s">\u2248 {total ? signedEur(total.fuel_eur) : "\u2014"} at the estimated diesel price</div>
        </div>
        <div className="tile">
          <div className="l"><ShieldAlert size={13} /> Disruption avoided</div>
          <div className="v">{total ? signedEur(total.disruption_eur) : "\u2014"}</div>
          <div className="s">delay avoided by approved re-routes, net of added cost</div>
        </div>
      </div>

      <section className="card actual-outcome" style={{ marginTop: 16 }}>
        <span className="eyebrow">MEASURED DELIVERY PERFORMANCE</span>
        <h2>{actual?.status === "MEASURED" ? "Actual outcomes vs approved plans" : "Insufficient actual delivery data"}</h2>
        <p>{actual?.samples ?? 0} completed deliveries \u00b7 minimum {actual?.minimum_samples ?? 5} for aggregate metrics. Demo outcomes are excluded.</p>
        {actual?.status === "MEASURED" && (
          <div className="benchmark-values">
            <span>Mean absolute arrival error<b>{actual.arrival_mae_minutes} min</b></span>
            <span>Average cost difference<b>{eur(actual.cost_error_eur)}</b></span>
            <span>On time<b>{actual.on_time_pct == null ? "Insufficient deadlines" : `${actual.on_time_pct}%`}</b><small>{actual.deadline_samples} promised deadlines</small></span>
          </div>
        )}
      </section>

      {!!s?.legacy_count && (
        <div className="notice notice--warn" style={{ marginTop: 16 }}>
          <b>{s.legacy_count} saved plan{s.legacy_count > 1 ? "s" : ""} cannot be measured.</b> They were approved before savings
          tracking existed, and their stored options come from a later planning pass under different conditions \u2014 comparing the two
          would invent a number. Open them in the control room, recalculate and approve again to start measuring them.
        </div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card__h">
          <div>
            <h2><TrendingDown size={15} className="h-ic" /> Savings by shipment</h2>
            <div className="sub">{s?.note}</div>
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="htbl savings-table">
            <thead>
              <tr>
                <th>Shipment</th><th>Route</th><th>Transport</th><th>Time</th><th>Fuel</th>
                <th>Disruption</th><th>Total benefit</th><th>Basis</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={r.comparable ? "" : "is-legacy"}>
                  <td><b>{r.id}</b>{r.container && <small style={{ display: "block", color: "var(--muted)" }}>{r.container}</small>}</td>
                  <td style={{ color: "var(--muted)" }}>{r.route.join(" \u2192 ") || "\u2014"}</td>
                  <td className="num" style={{ color: r.money_eur >= 0 ? "var(--ok)" : "var(--bad)", fontWeight: 700 }}>
                    {r.comparable ? signedEur(r.money_eur) : "\u2014"}
                  </td>
                  <td className="num">{r.comparable ? signedHm(r.time_min) : "\u2014"}</td>
                  <td className="num">{r.comparable ? `${r.fuel_l} L` : "\u2014"}</td>
                  <td className="num">
                    {r.disruption ? (
                      <span title={`${r.disruption.basis}. Counterfactual arrival ${dt(r.disruption.counterfactual_eta)}, approved ${dt(r.disruption.approved_eta)}.`}>
                        {signedEur(r.disruption_eur)}
                        <small style={{ display: "block", color: "var(--muted)" }}>{signedHm(r.disruption.minutes_avoided)} avoided</small>
                      </span>
                    ) : "\u2014"}
                  </td>
                  <td className="num" style={{ fontWeight: 800 }}>{r.comparable ? signedEur(r.benefit_eur) : "\u2014"}</td>
                  <td><span className={`basis-tag basis-${r.basis}`} title={r.basis_label}>{r.basis}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <div className="empty">No saved journeys yet. Plan a route and save it for review.</div>}
          {rows.length > 0 && counted.length === 0 && (
            <div className="empty">No shipment has a usable baseline yet. Approve a plan in the control room to start measuring.</div>
          )}
        </div>
        <div className="savings-legend">
          <span><Route size={12} /> <b>quote</b> \u00b7 comparison stored on the approved quote</span>
          <span><b>snapshot</b> \u00b7 rebuilt from that quote's own baseline</span>
          <span><b>derived</b> \u00b7 rebuilt from the same planning pass's direct option</span>
          <span><b>legacy</b> \u00b7 no trustworthy baseline; contributes nothing</span>
        </div>
        <p className="fineprint" style={{ padding: "0 16px 16px" }}>
          {s?.assumptions.note} {s?.source}.
        </p>
      </div>
    </>
  );
}
