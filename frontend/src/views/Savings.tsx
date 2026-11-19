import { Fragment, useEffect, useState } from "react";
import { PiggyBank, Fuel, Clock, ShieldCheck, RefreshCw, Download, Loader2 } from "lucide-react";
import { api } from "../api/client";
import type { SavingsResp } from "../api/types";
import { eur, hm, dt } from "../lib";
import sample from "./savings-sample.json";

function signedHm(n: number) { return (n < 0 ? "−" : "") + hm(Math.abs(n)); }
function signedEur(n: number) { return (n < 0 ? "−" : "") + eur(Math.abs(n)); }

function SampleShipmentEvidence() {
  const { example } = sample;
  const origin = example.route[0];
  const destination = example.route[example.route.length - 1];
  return <section className="card evidence-actual" aria-labelledby="sample-evidence">
    <p className="eyebrow">Sample SQL export</p>
    <h2 id="sample-evidence">Shipment comparison · {example.shipment}</h2>
    <p>{sample.comparable} comparable sample plans · {sample.deliveryOutcomes} sample delivery outcomes</p>
    <div className="table-scroll">
      <table className="htbl">
        <thead><tr><th scope="col">Route</th><th scope="col">Transport estimate</th><th scope="col">Transit time</th><th scope="col">Estimated fuel</th></tr></thead>
        <tbody>
          <tr><th scope="row">Direct · {origin} → {destination}</th><td>{eur(example.direct.transportEur)}</td><td>{hm(example.direct.minutes)}</td><td>{example.direct.fuelL} L</td></tr>
          <tr><th scope="row">Via hub · {example.route.join(" → ")}</th><td>{eur(example.approved.transportEur)}</td><td>{hm(example.approved.minutes)}</td><td>{example.approved.fuelL} L</td></tr>
        </tbody>
      </table>
    </div>
    <p><b>{hm(example.minutesSaved)} saved for {eur(Math.abs(example.transportSavingEur))} extra transport cost.</b> {eur(example.planningValueEur)} modelled planning value at {eur(sample.valueOfTimeEurPerHour)}/hour.</p>
    <p className="fineprint">Generated shipment records. Figures apply to this sample and are excluded from the approved-plan totals below.</p>
  </section>;
}

function csvCell(value: unknown) {
  let text = value == null ? "" : String(value);
  if (typeof value === "string" && /^\s*[=+\-@]/.test(text)) text = "'" + text;
  return '"' + text.replace(/"/g, '""') + '"';
}

export function Savings() {
  // Only manager-approved plan estimates are shown on this page.
  const [s, setS] = useState<SavingsResp | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [repaired, setRepaired] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [asOf, setAsOf] = useState("");
  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setExpanded(null);
    const request = api.savings("estimated").then(data => { if (active) setS(data); });
    request
      .then(() => { if (active) setAsOf(new Date().toISOString()); })
      .catch(e => { if (active) setError(String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [refresh]);

  async function rebuild() {
    setBusy(true); setError("");
    try { const result = await api.recalculateSavings(); setRepaired(result.repaired ?? 0); setRefresh(v => v + 1); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  const rows = s?.per_shipment ?? [];
  const total = s?.total;
  function exportReport() {
    const records: unknown[][] = [
      ["Evidence type", "Shipment", "Route", "Included in totals", "Excluded reason", "Transport difference EUR", "Time saved min", "Fuel saved L", "Modelled time value EUR", "Modelled planning value EUR", "Separate reroute comparison EUR", "Cargo value with deadline protected EUR (not savings)", "Baseline", "Approved quote", "Approved at", "Manager reason", "Route source", "Report as of"],
      ...rows.map(r => ["ESTIMATE", r.id, r.route.join(" -> "), r.comparable ? "Yes" : "No", r.excluded_reason, r.comparable ? r.money_eur : null, r.comparable ? r.time_min : null, r.comparable ? r.fuel_l : null, r.comparable ? r.time_value_eur : null, r.comparable ? r.benefit_eur : null, r.disruption_eur, r.exposure_avoided_eur, r.evidence.baseline, r.evidence.quote_id, r.evidence.approved_at, r.evidence.manager_reason, r.evidence.source, asOf]),
    ];
    const csv = "\uFEFF" + records.map(row => row.map(csvCell).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], {type: "text/csv;charset=utf-8"}));
    const a = document.createElement("a"); a.href = url; a.download = `dachser-approved-estimates-${new Date().toISOString().slice(0,10)}.csv`;
    a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <>
    <div className="page-heading">
      <div><h1>Savings</h1></div>
      <div className="evidence-actions">
        <button className="btn btn--ghost" disabled={loading || busy} onClick={() => setRefresh(v => v+1)} aria-label="Refresh decision evidence"><RefreshCw size={15}/></button>
        <button className="btn" disabled={loading || busy || !!error || !rows.length} onClick={exportReport}><Download size={15}/> Export estimates</button>
      </div>
    </div>
    <SampleShipmentEvidence />
    <details className="card savings-explainer">
      <summary><b>How these numbers are calculated</b> <span className="fineprint">Click to open</span></summary>
      <ol>
        <li><b>What is compared.</b> Each manager-approved shipment is compared with the <b>direct road option</b> calculated in the same planning run, so both use the same departure time, conditions and load.</li>
        <li><b>Transport saving</b> = direct option's transport estimate − approved route's transport estimate. Transport estimates come from the DACHSER lane tariffs in <i>relationen.csv</i>, shared by the shipment's loading metres (at least 15% of a trailer); where no tariff exists the tool uses €2.60 per km.</li>
        <li><b>Time saved</b> = direct option's total journey time − approved route's total journey time (driving, hub handling, waits and holds). A negative value means the approved route takes longer.</li>
        <li><b>Fuel saved</b> = the difference in estimated fuel at 30 L per 100 km. It is shown on its own and is not added to the planning value, so nothing is counted twice.</li>
        <li><b>Planning value</b> = transport saving + time saved × €{s?.assumptions.value_of_time_eur_per_hour ?? 50} per hour. The hourly rate is a planning valuation of transit time, not a cost anyone pays.</li>
        <li><b>Reroutes.</b> When a manager approves a different route because conditions changed, that decision is compared with the previously approved route recalculated under the new conditions, and listed separately.</li>
        <li><b>Left out.</b> Plans that are not approved, are on hold, have no comparable direct option, or are demo scenarios.</li>
      </ol>
      <p className="fineprint">All figures are estimates from the tool's own calculations. They are not invoiced or realised savings.</p>
    </details>
    {error && <div className="notice notice--warn" role="alert">{error}</div>}
    <div id="evidence-panel" aria-busy={loading}>
      {loading ? <div className="card empty" role="status"><Loader2 className="spin" size={20}/> Loading saved evidence…</div> : error ? <div className="card empty">Results unavailable. Refresh to try again.</div> : <>
        <div className={`notice ${"notice--info"}`} role="status"><b>{"ESTIMATES — not realized savings. "}</b>{s?.source}</div>
        <div className="savings-headline">
          <div className="savings-headline-main"><span className="eyebrow">{"MODELLED"} PLANNING VALUE</span><strong>{total?signedEur(total.economic_benefit_eur):"—"}</strong><small>{total?.optimized ?? 0} comparable {"approved plan"}{total?.optimized===1?"":"s"} · transport difference + time valued at {eur(s?.assumptions.value_of_time_eur_per_hour??50)}/hour</small></div>
          <div className="savings-breakdown"><span><small>Transport estimate difference</small><b>{total?signedEur(total.money_eur):"—"}</b></span><span><small>Modelled time value</small><b>{total?signedEur(total.time_value_eur):"—"}</b></span></div>
        </div>
        <div className="tiles">
          <div className="tile tile--accent"><div className="l"><PiggyBank size={13}/> Estimated transport saving</div><div className="v">{total?signedEur(total.money_eur):"—"}</div><div className="s">Signed difference against each plan's direct option</div></div>
          <div className="tile"><div className="l"><Clock size={13}/> Estimated time saved</div><div className="v">{total?signedHm(total.time_min):"—"}</div><div className="s">Negative means a longer journey</div></div>
          <div className="tile"><div className="l"><Fuel size={13}/> Estimated fuel saved</div><div className="v">{total?`${total.fuel_l} L`:"—"}</div><div className="s">Shown separately; not added again to planning value</div></div>
          <div className="tile"><div className="l"><ShieldCheck size={13}/> Evidence coverage</div><div className="v">{total?.optimized??0} / {rows.length}</div><div className="s">{s?.excluded_count??0} excluded · {s?.demo_excluded_count??0} demo shipments left out</div></div>
        </div>
        {!!s?.rerouted_count && <details className="card evidence-reroute" open><summary>Reroute comparisons · {s.rerouted_count} linked decisions</summary><p>Compared with the previously approved route under the conditions at reapproval. These figures overlap the main comparison and are not added to it.</p><div className="benchmark-values"><span>Time value avoided − extra transport cost<b>{signedEur(total?.disruption_eur??0)}</b></span><span>Cargo value with deadline protected<b>{eur(total?.exposure_avoided_eur)}</b><small>Cargo value, not cash saved or proven loss avoided</small></span></div></details>}
        <section className="card evidence-table">
          <div className="card__h"><div><h2>Plan-by-plan evidence</h2><div className="sub">{s?.note}</div></div>{<button className="btn btn--ghost" disabled={busy} onClick={rebuild}>{busy?<Loader2 className="spin" size={14}/>:<RefreshCw size={14}/>} Rebuild missing baselines</button>}</div>
          {repaired !== null && <p className="notice notice--info" role="status">{repaired} missing comparisons rebuilt from their own stored options. This does not approve a proposal or create an actual outcome.</p>}
          <div className="table-scroll"><table className="htbl savings-table"><thead><tr><th>Shipment / status</th><th>Route</th><th>Transport saving</th><th>Time saved</th><th>Fuel saved</th><th>Planning value</th><th>Evidence</th></tr></thead><tbody>
            {rows.map(r => <Fragment key={r.id}><tr className={r.comparable?"":"is-legacy"}>
              <td><b>{r.id}</b><small className="evidence-cell-note">{r.status}</small></td><td>{r.route.join(" → ")}</td>
              <td className={`num ${r.money_eur<0?"is-late":""}`}>{r.comparable?signedEur(r.money_eur):"—"}</td><td className="num">{r.comparable?signedHm(r.time_min):"—"}</td><td className="num">{r.comparable?`${r.fuel_l} L`:"—"}</td><td className="num"><b>{r.comparable?signedEur(r.benefit_eur):"—"}</b></td>
              <td><button className="linkbtn" aria-expanded={expanded===r.id} aria-controls={`evidence-${r.id}`} onClick={() => setExpanded(expanded===r.id?null:r.id)}>{r.comparable?"View evidence":"Why excluded?"}<span className="sr-only"> for {r.id}</span></button></td>
            </tr>{expanded===r.id && <tr id={`evidence-${r.id}`}><td colSpan={7}><div className="evidence-detail">{r.excluded_reason && <p className="notice notice--warn"><b>Excluded:</b> {r.excluded_reason}. This row contributes nothing to the totals.</p>}<dl>
              <div><dt>Baseline</dt><dd>{r.evidence.baseline??r.basis_label}</dd></div><div><dt>Approved at</dt><dd>{r.evidence.approved_at?dt(r.evidence.approved_at):"Not approved"}</dd></div><div><dt>Manager reason</dt><dd>{r.evidence.manager_reason??"Not recorded for this approval"}</dd></div><div><dt>Route data source</dt><dd>{r.evidence.source??"Not recorded"}</dd></div><div><dt>Quote reference</dt><dd>{r.evidence.quote_id??"Unavailable"}</dd></div><div><dt>Conditions revision</dt><dd>{r.evidence.revision??"Unavailable"} · evaluated {r.evidence.evaluated_at?dt(r.evidence.evaluated_at):"not recorded"}</dd></div>
            </dl><p className="fineprint">Approved plan estimate. Even after delivery, a modelled comparison is not proof of financial savings.</p></div></td></tr>}</Fragment>)}
          </tbody></table></div>
          {!rows.length && <div className="empty">{"No saved plans yet. Save a route, then approve it in the control room to start a traceable estimate."}</div>}
          <p className="fineprint evidence-footer">{s?.assumptions.note}</p>
        </section>
      </>}
    </div>
    {!loading && !error && <p className="fineprint evidence-footer">Loaded {dt(asOf)} · Export contains only the selected evidence category.</p>}
  </>;
}
