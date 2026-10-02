import { Fragment, useEffect, useState } from "react";
import { PiggyBank, Fuel, Clock, ShieldCheck, RefreshCw, Download, Loader2 } from "lucide-react";
import { api } from "../api/client";
import type { SavingsResp, Performance } from "../api/types";
import { eur, hm, dt } from "../lib";

type Mode = "estimated" | "actual" | "demo";
const modes: {id: Mode; label: string}[] = [
  {id: "estimated", label: "Approved estimates"},
  {id: "actual", label: "Actual outcomes"},
  {id: "demo", label: "Demo scenarios"},
];
function signedHm(n: number) { return (n < 0 ? "−" : "") + hm(Math.abs(n)); }
function signedEur(n: number) { return (n < 0 ? "−" : "") + eur(Math.abs(n)); }
function csvCell(value: unknown) {
  let text = value == null ? "" : String(value);
  if (typeof value === "string" && /^\s*[=+\-@]/.test(text)) text = "'" + text;
  return '"' + text.replace(/"/g, '""') + '"';
}

export function Savings() {
  const [mode, setMode] = useState<Mode>("estimated");
  const [s, setS] = useState<SavingsResp | null>(null);
  const [actual, setActual] = useState<Performance | null>(null);
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
    Promise.all([api.savings(mode === "demo" ? "demo" : "estimated"), api.performance()])
      .then(([plans, outcomes]) => {
        if (active) { setS(plans); setActual(outcomes); setAsOf(new Date().toISOString()); }
      })
      .catch(e => { if (active) setError(String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [mode, refresh]);

  async function rebuild() {
    setBusy(true); setError("");
    try { const result = await api.recalculateSavings(); setRepaired(result.repaired ?? 0); setRefresh(v => v + 1); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  const rows = s?.per_shipment ?? [];
  const outcomes = actual?.outcomes ?? [];
  const total = s?.total;
  const demo = mode === "demo";
  function exportReport() {
    const records: unknown[][] = mode === "actual" ? [
      ["Evidence type", "Shipment", "Route", "Approved quote", "Approved ETA", "Reported arrival", "Arrival difference min", "Approved cost EUR", "Reported cost EUR", "Cost difference EUR", "On time", "Source", "Report as of"],
      ...outcomes.map(r => ["USER-REPORTED ACTUAL", r.id, r.route.join(" -> "), r.quote_id, r.approved_eta, r.actual_arrival, r.arrival_error_minutes, r.approved_cost_eur, r.actual_cost_eur, r.cost_error_eur, r.on_time == null ? "Unknown" : r.on_time ? "Yes" : "No", r.source, asOf]),
    ] : [
      ["Evidence type", "Shipment", "Route", "Included in totals", "Excluded reason", "Transport difference EUR", "Time saved min", "Fuel saved L", "Modelled time value EUR", "Modelled planning value EUR", "Separate reroute comparison EUR", "Cargo value with deadline protected EUR (not savings)", "Baseline", "Approved quote", "Approved at", "Manager reason", "Route source", "Report as of"],
      ...rows.map(r => [demo ? "DEMO" : "ESTIMATE", r.id, r.route.join(" -> "), r.comparable ? "Yes" : "No", r.excluded_reason, r.comparable ? r.money_eur : null, r.comparable ? r.time_min : null, r.comparable ? r.fuel_l : null, r.comparable ? r.time_value_eur : null, r.comparable ? r.benefit_eur : null, r.disruption_eur, r.exposure_avoided_eur, r.evidence.baseline, r.evidence.quote_id, r.evidence.approved_at, r.evidence.manager_reason, r.evidence.source, asOf]),
    ];
    const csv = "\uFEFF" + records.map(row => row.map(csvCell).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], {type: "text/csv;charset=utf-8"}));
    const a = document.createElement("a"); a.href = url; a.download = `dachser-evidence-${mode}-${new Date().toISOString().slice(0,10)}.csv`;
    a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <>
    <div className="page-heading">
      <div><span className="eyebrow">SAVINGS & DECISION EVIDENCE</span><h1>Know what is estimated.<br/>See what actually happened.</h1><p>Trace each comparison to a saved plan, a manager approval or a reported delivery.</p></div>
      <div className="evidence-actions">
        <button className="btn btn--ghost" disabled={loading || busy} onClick={() => setRefresh(v => v+1)} aria-label="Refresh decision evidence"><RefreshCw size={15}/></button>
        <button className="btn" disabled={loading || busy || !!error || (mode === "actual" ? !outcomes.length : !rows.length)} onClick={exportReport}><Download size={15}/> Export evidence</button>
      </div>
    </div>
    <div className="evidence-tabs" role="tablist" aria-label="Evidence source">
      {modes.map(m => <button key={m.id} id={`tab-${m.id}`} role="tab" aria-selected={mode===m.id} aria-controls="evidence-panel" disabled={busy} onClick={() => { setMode(m.id); setRepaired(null); }}>{m.label}</button>)}
    </div>
    {error && <div className="notice notice--warn" role="alert">{error}</div>}
    <div id="evidence-panel" role="tabpanel" aria-labelledby={`tab-${mode}`} aria-busy={loading}>
      {loading ? <div className="card empty" role="status"><Loader2 className="spin" size={20}/> Loading saved evidence…</div> : error ? <div className="card empty">Results unavailable. Refresh to try again.</div> : mode === "actual" ? <>
        <section className="card evidence-actual">
          <div className="evidence-section-heading"><div><span className="eyebrow">USER-REPORTED ACTUALS</span><h2>{actual?.status === "MEASURED" ? "Delivery performance against approved plans" : "Building an actual delivery record"}</h2></div><span className="mini">{actual?.samples ?? 0} linked outcomes</span></div>
          <p>{actual?.source}</p>
          {actual?.status !== "MEASURED" && <div className="notice notice--info">{actual?.samples ?? 0} of {actual?.minimum_samples ?? 5} records needed for aggregate performance. Individual reports are listed below; no sample figures are substituted.</div>}
          <div className="benchmark-values">
            <span>Mean absolute arrival error<b>{actual?.arrival_mae_minutes == null ? "—" : `${actual.arrival_mae_minutes} min`}</b><small>Against the approved ETA</small></span>
            <span>Average actual cost − estimate<b>{actual?.cost_error_eur == null ? "—" : signedEur(actual.cost_error_eur)}</b><small>Positive means actual cost was higher</small></span>
            <span>Reported on time<b>{actual?.on_time_pct == null ? "—" : `${actual.on_time_pct}%`}</b><small>{actual?.deadline_samples ?? 0} known deadlines; minimum 5</small></span>
          </div>
          {!!actual?.excluded_records && <p className="fineprint">{actual.excluded_records} demo, unapproved, invalid or unmatched outcome records excluded.</p>}
        </section>
        <section className="card evidence-table">
          <div className="card__h"><h2>Actual delivery records</h2><span className="fineprint">Cost variance is not realized savings</span></div>
          <div className="table-scroll"><table className="htbl"><thead><tr><th>Shipment</th><th>Approved ETA</th><th>Reported arrival</th><th>Arrival difference</th><th>Actual cost</th><th>Cost difference</th><th>On time</th></tr></thead>
          <tbody>{outcomes.map(r => <tr key={r.id}><td><b>{r.id}</b><small className="evidence-cell-note">{r.route.join(" → ")}</small><small className="evidence-cell-note" title={r.quote_id}>Approved {dt(r.approved_at)}</small></td><td>{dt(r.approved_eta)}</td><td>{dt(r.actual_arrival)}</td><td>{r.arrival_error_minutes > 0 ? "+" : ""}{signedHm(r.arrival_error_minutes)}</td><td>{eur(r.actual_cost_eur)}</td><td className={r.cost_error_eur>0?"is-late":"is-ok"}>{r.cost_error_eur>0?"+":""}{signedEur(r.cost_error_eur)}</td><td>{r.on_time == null ? "Unknown" : r.on_time ? "Yes" : "No"}</td></tr>)}</tbody></table></div>
          {!outcomes.length && <div className="empty"><ShieldCheck size={28}/><h3>No linked actual deliveries yet.</h3><p>In Shipments, open a completed shipment and record its actual departure, arrival and cost.<br/>The report must match a manager-approved quote to appear here.</p></div>}
        </section>
      </> : <>
        <div className={`notice ${demo?"notice--warn":"notice--info"}`} role="status"><b>{demo?"DEMO — saved scenarios only. ":"ESTIMATES — not realized savings. "}</b>{s?.source}</div>
        <div className="savings-headline">
          <div className="savings-headline-main"><span className="eyebrow">{demo?"SIMULATED":"MODELLED"} PLANNING VALUE</span><strong>{total?signedEur(total.economic_benefit_eur):"—"}</strong><small>{total?.optimized ?? 0} comparable {demo?"scenario":"approved plan"}{total?.optimized===1?"":"s"} · transport difference + time valued at {eur(s?.assumptions.value_of_time_eur_per_hour??50)}/hour</small></div>
          <div className="savings-breakdown"><span><small>Transport estimate difference</small><b>{total?signedEur(total.money_eur):"—"}</b></span><span><small>Modelled time value</small><b>{total?signedEur(total.time_value_eur):"—"}</b></span></div>
        </div>
        <div className="tiles">
          <div className="tile tile--accent"><div className="l"><PiggyBank size={13}/> Estimated transport saving</div><div className="v">{total?signedEur(total.money_eur):"—"}</div><div className="s">Signed difference against each plan's direct option</div></div>
          <div className="tile"><div className="l"><Clock size={13}/> Estimated time saved</div><div className="v">{total?signedHm(total.time_min):"—"}</div><div className="s">Negative means a longer journey</div></div>
          <div className="tile"><div className="l"><Fuel size={13}/> Estimated fuel saved</div><div className="v">{total?`${total.fuel_l} L`:"—"}</div><div className="s">Shown separately; not added again to planning value</div></div>
          <div className="tile"><div className="l"><ShieldCheck size={13}/> Evidence coverage</div><div className="v">{total?.optimized??0} / {rows.length}</div><div className="s">{s?.excluded_count??0} excluded · {demo?"Demo scope only":`${s?.demo_excluded_count??0} demo shipments kept separate`}</div></div>
        </div>
        {!!s?.rerouted_count && <details className="card evidence-reroute"><summary>Reroute comparisons · {s.rerouted_count} linked decisions</summary><p>Compared with the previously approved route under the conditions at reapproval. These figures overlap the main comparison and are not added to it.</p><div className="benchmark-values"><span>Time value avoided − extra transport cost<b>{signedEur(total?.disruption_eur??0)}</b></span><span>Cargo value with deadline protected<b>{eur(total?.exposure_avoided_eur)}</b><small>Cargo value, not cash saved or proven loss avoided</small></span></div></details>}
        <section className="card evidence-table">
          <div className="card__h"><div><h2>Plan-by-plan evidence</h2><div className="sub">{s?.note}</div></div>{!demo && <button className="btn btn--ghost" disabled={busy} onClick={rebuild}>{busy?<Loader2 className="spin" size={14}/>:<RefreshCw size={14}/>} Rebuild missing baselines</button>}</div>
          {repaired !== null && <p className="notice notice--info" role="status">{repaired} missing comparisons rebuilt from their own stored options. This does not approve a proposal or create an actual outcome.</p>}
          <div className="table-scroll"><table className="htbl savings-table"><thead><tr><th>Shipment / status</th><th>Route</th><th>Transport saving</th><th>Time saved</th><th>Fuel saved</th><th>Planning value</th><th>Evidence</th></tr></thead><tbody>
            {rows.map(r => <Fragment key={r.id}><tr className={r.comparable?"":"is-legacy"}>
              <td><b>{r.id}</b><small className="evidence-cell-note">{r.status}</small></td><td>{r.route.join(" → ")}</td>
              <td className={`num ${r.money_eur<0?"is-late":""}`}>{r.comparable?signedEur(r.money_eur):"—"}</td><td className="num">{r.comparable?signedHm(r.time_min):"—"}</td><td className="num">{r.comparable?`${r.fuel_l} L`:"—"}</td><td className="num"><b>{r.comparable?signedEur(r.benefit_eur):"—"}</b></td>
              <td><button className="linkbtn" aria-expanded={expanded===r.id} aria-controls={`evidence-${r.id}`} onClick={() => setExpanded(expanded===r.id?null:r.id)}>{r.comparable?"View evidence":"Why excluded?"}<span className="sr-only"> for {r.id}</span></button></td>
            </tr>{expanded===r.id && <tr id={`evidence-${r.id}`}><td colSpan={7}><div className="evidence-detail">{r.excluded_reason && <p className="notice notice--warn"><b>Excluded:</b> {r.excluded_reason}. This row contributes nothing to the totals.</p>}<dl>
              <div><dt>Baseline</dt><dd>{r.evidence.baseline??r.basis_label}</dd></div><div><dt>Approved at</dt><dd>{r.evidence.approved_at?dt(r.evidence.approved_at):"Not approved"}</dd></div><div><dt>Manager reason</dt><dd>{r.evidence.manager_reason??"Not recorded for this approval"}</dd></div><div><dt>Route data source</dt><dd>{r.evidence.source??"Not recorded"}</dd></div><div><dt>Quote reference</dt><dd>{r.evidence.quote_id??"Unavailable"}</dd></div><div><dt>Conditions revision</dt><dd>{r.evidence.revision??"Unavailable"} · evaluated {r.evidence.evaluated_at?dt(r.evidence.evaluated_at):"not recorded"}</dd></div>
            </dl><p className="fineprint">{demo?"Simulated scenario. ":"Approved plan estimate. "}Even after delivery, a modelled comparison is not proof of financial savings.</p></div></td></tr>}</Fragment>)}
          </tbody></table></div>
          {!rows.length && <div className="empty">{demo?"No saved demo scenarios. Demo figures are never invented to fill this view.":"No saved plans yet. Save a route, then approve it in the control room to start a traceable estimate."}</div>}
          <p className="fineprint evidence-footer">{s?.assumptions.note}</p>
        </section>
      </>}
    </div>
    {!loading && !error && <p className="fineprint evidence-footer">Loaded {dt(asOf)} · Export contains only the selected evidence category.</p>}
  </>;
}
