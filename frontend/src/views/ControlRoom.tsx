import { useCallback, useEffect, useRef, useState } from "react";
import { ShieldCheck, RefreshCw, Check, Pause, Plus, ClipboardList, TriangleAlert } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { NetNode, Shipment, Operations, RouteOption, Decision } from "../api/types";
import { dt, eur } from "../lib";
import { PlanChangeNotice } from "../components/PlanChangeNotice";
import { RouteCompare } from "../components/RouteCompare";
import { ScenarioStudio } from "../components/ScenarioStudio";
import { CapacitySettings } from "../components/CapacitySettings";
import { ServiceSettings } from "../components/ServiceSettings";
import { DecisionHistory } from "../components/DecisionHistory";
import { DispatchActions } from "../components/DispatchActions";
import { ManagerRoutes } from "../components/ManagerRoutes";
import "../manager-control.css";

type QueueGroup="all"|"planned"|"review"|"active";
const routeClear=(o?:RouteOption)=>!!o&&o.route_feasible!==false&&o.capacity?.feasible!==false&&["CLEAR","NO_ZONE"].includes(o.avoidance_status??"");
const groupOf=(s:Shipment):QueueGroup=>s.status==="ON HOLD"||s.hold||s.plan_change?.material||["CRITICAL","HIGH"].includes(s.dispatch?.priority??"")?"review":!s.approved_at?"planned":s.status==="ARRIVAL EXPECTED"||s.dispatch?.priority==="REVIEW"?"review":"active";
const groupLabel=(s:Shipment)=>({planned:"Planned",review:"Review required",active:"Active",all:"All"}[groupOf(s)]);

export function ControlRoom({nodes,onChange,refreshKey=0,active=true,savedJourney,reviewRequest,onSaved,onOperations}:{nodes:NetNode[];onChange:()=>void;refreshKey?:number;active?:boolean;savedJourney?:Shipment|null;reviewRequest?:{id:string;version:number}|null;onSaved?:(s:Shipment)=>void;onOperations?:(ops:Operations)=>void}){
 const [ships,setShips]=useState<Shipment[]>([]),[ops,setOps]=useState<Operations|null>(null),[detail,setDetail]=useState<Shipment|null>(null);
 const [sel,setSel]=useState(0),[decidedBy,setDecidedBy]=useState(()=>{try{return localStorage.getItem("dachser-decided-by")??""}catch{return ""}}),[reason,setReason]=useState(""),[ack,setAck]=useState(false),[busy,setBusy]=useState(false);
 const [err,setErr]=useState(""),[msg,setMsg]=useState(""),[filter,setFilter]=useState<QueueGroup>("all"),[creating,setCreating]=useState(false);
 const [queueError,setQueueError]=useState(false);
 const [routeDraft,setRouteDraft]=useState(false);
 const [revising,setRevising]=useState<Decision|null>(null);
 const [savingDecision,setSavingDecision]=useState(false);
 const submission=useRef<{key:string;id:string}|null>(null);
 const decisionInFlight=useRef(false);
 const reviewPanel=useRef<HTMLElement|null>(null);
 const loadId=useRef(0);const openedSaved=useRef("");const alive=useRef(true);const reviewId=useRef(0);
 // Journeys saved in this browser stay listed until the server's own list contains
 // them, so a queue response that left before the save (or from a slower server
 // instance) cannot hide the journey the manager just saved.
 const pinned=useRef(new Map<string,{ship:Shipment;at:number}>());
 // On unmount, cancel the in-flight review and forget the auto-opened journey so a
 // remount (React StrictMode does this in development) opens it again instead of
 // leaving a cancelled review holding `busy` forever.
 useEffect(()=>{alive.current=true;setBusy(false);return()=>{alive.current=false;reviewId.current++;openedSaved.current=""}},[]);
 const load=useCallback(async()=>{const request=++loadId.current;try{const {shipments,operations}=await api.controlRoom();if(alive.current&&request===loadId.current){
  const listed=new Set(shipments.map(x=>x.id));const now=Date.now();const kept:Shipment[]=[];
  pinned.current.forEach((pin,id)=>{if(listed.has(id)||now-pin.at>120000)pinned.current.delete(id);else kept.push(pin.ship)});
  setShips([...kept,...shipments].filter(x=>x.status!=="DELIVERED").sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at)));setOps(operations);onOperations?.(operations);setQueueError(false)}}catch{if(alive.current&&request===loadId.current)setQueueError(true)}},[onOperations]);
 useEffect(()=>{
  if(!active)return;
  const refresh=()=>{if(!document.hidden&&!decisionInFlight.current)void load()};
  refresh();
  const timer=window.setInterval(refresh,60000);
  document.addEventListener("visibilitychange",refresh);
  return()=>{loadId.current++;clearInterval(timer);document.removeEventListener("visibilitychange",refresh)};
 },[active,refreshKey,load]);
 useEffect(()=>{if(savedJourney){pinned.current.set(savedJourney.id,{ship:savedJourney,at:Date.now()});setShips(prev=>[savedJourney,...prev.filter(s=>s.id!==savedJourney.id)])}},[savedJourney]);
 async function review(id:string,recalculate=false,decisionToRevise?:Decision){
  if(busy)return;const request=++reviewId.current;setBusy(true);setErr("");setMsg("");setCreating(false);
  try{const saved=recalculate&&detail?.id===id?detail:await api.shipment(id);const moving=!!saved.movement_started_at||["IN TRANSIT","DELAYED","ARRIVAL EXPECTED"].includes(saved.status);const stale=moving&&(!saved.vehicle_position||Date.now()-Date.parse(saved.vehicle_position.reported_at)>900000);
   const s=recalculate&&!stale?await api.replan(id):saved;if(!alive.current||reviewId.current!==request)return;
   setDetail(s);const preferred=s.options?.findIndex(o=>o.route_id===s.accepted_plan?.route_id)??-1;setSel(preferred>=0?preferred:s.selected_option??0);setAck(false);if(decisionToRevise||detail?.id!==id)setReason(decisionToRevise?.reason??"");setRevising(decisionToRevise??(detail?.id===id?revising:null));setRouteDraft(false);if(recalculate)void load();
   if(decisionToRevise)reviewPanel.current?.scrollIntoView({behavior:"smooth",block:"start"});
  }catch(e){if(alive.current)setErr(String(e));if(decisionToRevise)throw e}finally{if(alive.current&&reviewId.current===request)setBusy(false)}
 }
 const reviewLatest=useRef(review);reviewLatest.current=review;
 useEffect(()=>{const key=reviewRequest?`${reviewRequest.id}:${reviewRequest.version}`:"";if(active&&!busy&&reviewRequest&&openedSaved.current!==key){openedSaved.current=key;setFilter("all");void reviewLatest.current(reviewRequest.id,false)}},[active,reviewRequest?.id,reviewRequest?.version,busy]);
 function proposed(s:Shipment){setDetail(s);const preferred=s.options?.findIndex(o=>o.manager_requested&&routeClear(o))??-1;setSel(preferred>=0?preferred:0);setAck(false);setReason("");setRouteDraft(false);void load();onChange()}
 function created(s:Shipment){setCreating(false);setRevising(null);setDetail(s);setSel(s.selected_option??0);setShips(prev=>[s,...prev.filter(x=>x.id!==s.id)]);setFilter("all");setMsg(`${s.id} saved. Review the route and record your decision.`);onSaved?.(s);onChange()}
 async function decide(action:string){
  const option=detail?.options?.[sel];
  if(!detail||!option||busy||decisionInFlight.current)return;
  const payload={shipment_id:detail.id,action,option:sel,revision:option.revision??-1,quote_id:option.quote_id,
    reason,decided_by:decidedBy.trim(),acknowledge_deadline:ack,
    ...(revising?{supersedes_decision_id:revising.id,supersedes_updated_at:revising.updated_at}:{})};
  const key=JSON.stringify(payload);
  if(submission.current?.key!==key)submission.current={key,id:crypto.randomUUID()};
  decisionInFlight.current=true;setBusy(true);setSavingDecision(true);setErr("");setMsg("");
  try{
   const result=await api.decide({...payload,request_id:submission.current.id});
   const {shipment_summary,...receipt}=result;
   loadId.current++;submission.current=null;
   if(shipment_summary)setShips(items=>items.map(s=>s.id===shipment_summary.id?{...s,...shipment_summary,...(action==="accept"?{hold:undefined}:{})}:s));
   setOps(current=>current?{...current,decisions:[
    ...current.decisions.filter(d=>d.id!==receipt.id).map(d=>d.id===receipt.supersedes_decision_id?{...d,superseded_by:receipt.id}:d),receipt
   ]}:current);
   setMsg(revising?"Revised decision saved. The original remains in history.":action==="accept"?"Route approved and saved.":action==="hold"?"Hold or safe-stop request recorded.":action==="keep"?"Current plan retained.":"Decision deferred.");
   setDetail(null);setRevising(null);onChange();
  }catch(e){
   if(e instanceof ApiError&&e.code==="REVIEW_UPDATED"){
    setErr(e.message);
    try{
     const updated=await api.shipment(detail.id);
     setDetail(updated);
     const next=updated.options?.findIndex(o=>o.route_id===option.route_id)??-1;
     setSel(next>=0?next:0);setAck(false);
    }catch{setErr("Live conditions changed. Reopen the journey to review the updated options.")}
   }else if(!(e instanceof ApiError)||e.status>=500){
    setErr("We couldn’t confirm the save. Retry the same decision. It will only be recorded once.");
   }else setErr(e.message);
  }finally{decisionInFlight.current=false;setBusy(false);setSavingDecision(false)}
 }
 async function scenarioChanged(){await load();setDetail(null);setRevising(null);onChange()}
 const selected=detail?.options?.[sel];const moving=!!detail&&(!!detail.movement_started_at||["IN TRANSIT","DELAYED","ARRIVAL EXPECTED"].includes(detail.status));
 const positionReady=!moving||!!(selected?.remaining_only&&selected.position_id===detail?.vehicle_position?.id&&Date.now()-Date.parse(detail?.vehicle_position?.reported_at??"")<900000);
 const blocked=!routeClear(selected)||!positionReady||routeDraft;
 const name=(id:string)=>nodes.find(n=>n.id===id)?.name??"Vehicle position";
 const visibleShips=ships.filter(s=>filter==="all"||groupOf(s)===filter);
 return <>
  <div className="page-heading control-heading"><div><h1>Control room</h1></div><button className="btn" disabled={busy} onClick={()=>{setCreating(true);setDetail(null);setRevising(null);setErr("");setMsg("")}}><Plus size={16}/>New manager journey</button></div>
  {err&&<div role="alert" className="notice notice--warn">{err}</div>}{msg&&<div role="status" className="notice notice--info">{msg}</div>}
  {savingDecision&&<div role="status" className="notice notice--info">Checking the route and saving the decision…</div>}
  {queueError&&<div role="status" className="notice notice--warn">Couldn’t refresh the queue. <button className="linkbtn" onClick={()=>void load()}>Retry queue refresh</button></div>}
  <div className="control-overview">{(["planned","review","active"] as const).map(group=><button key={group} aria-pressed={filter===group} onClick={()=>setFilter(filter===group?"all":group)}><span className={`overview-icon ${group}`}>{group==="planned"?<ClipboardList size={19}/>:group==="review"?<TriangleAlert size={19}/>:<ShieldCheck size={19}/>}</span><span>{group==="planned"?"Planned journeys":group==="review"?"Review required":"Active journeys"}<b>{ships.filter(s=>groupOf(s)===group).length}</b></span></button>)}</div>
  <div className="control-layout">
   <section className="card review-queue"><div className="card__h"><h2>Journeys <span className="mini">{visibleShips.length}</span></h2><button className="icon-button" disabled={busy} onClick={()=>void load()} aria-label="Refresh attention queue"><RefreshCw size={14}/></button></div>
    <div className="queue-filter-row">{(["all","planned","review","active"] as const).map(group=><button key={group} aria-pressed={filter===group} onClick={()=>setFilter(group)}>{group==="all"?"All":group==="planned"?"Planned":group==="review"?"Review":"Active"}</button>)}</div>
    <div className="review-queue-list">{visibleShips.length===0&&<div className="empty">No journeys in this group.</div>}{visibleShips.map(s=><button key={s.id} className={`queue-item ${detail?.id===s.id?"selected":""}`} disabled={busy} onClick={()=>void review(s.id)}><span className="queue-top"><b>{s.id}</b><span className={`queue-state queue-state--${groupOf(s)}`}>{groupLabel(s)}</span></span><strong>{name(s.origin)} → {name(s.destination)}</strong><span className="queue-journey-meta">{s.weight_kg.toLocaleString()} kg · {eur(s.est_cost_eur)}</span><small>{s.hold?`Hold: ${s.hold.reason}`:`Arrival ${dt(s.current_eta)}`}</small>{s.dispatch?.reasons[0]&&<span className="queue-one-reason">{s.dispatch.reasons[0]}</span>}</button>)}</div>
   </section>
   <section className="review-main" ref={reviewPanel}>
    {busy&&!detail&&!creating&&<div className="card empty"><RefreshCw className="spin"/>Loading journey…</div>}
    {creating&&<div className="card manager-create-card"><ManagerRoutes nodes={nodes} ops={ops} onProposed={proposed} onCreated={created} onBusyChange={setBusy}/></div>}
    {!detail&&!busy&&!creating&&<div className="card review-placeholder"><ShieldCheck size={42}/><h2>Select a journey</h2><p>Review a saved route or plan a new connection.</p></div>}
    {detail&&!creating&&<div className="card manager-review-card">
     <div className="manager-review-header"><div><span className={`queue-state queue-state--${groupOf(detail)}`}>{groupLabel(detail)}</span><h2>{name(detail.origin)} → {name(detail.destination)}</h2><span>{detail.id} · {detail.weight_kg.toLocaleString()} kg · {eur(detail.value_eur)} shipment value</span></div><button className="btn btn--ghost" disabled={busy} onClick={()=>void review(detail.id,true)}><RefreshCw size={14}/>Recalculate</button></div>
     {detail.hold&&<div className="manager-state-message is-hold"><b>Shipment on hold</b><span>{detail.hold.reason}</span></div>}
     {revising&&<div className="manager-state-message is-info"><b>Revising a previous manager decision</b><span>Review the route and choose the replacement action below. The original decision stays in history.</span><button className="linkbtn" disabled={busy} onClick={()=>setRevising(null)}>Cancel revision</button></div>}
     <ManagerRoutes key={detail.id} nodes={nodes} shipment={detail} ops={ops} disabled={busy} onDraftChange={setRouteDraft} onProposed={proposed} onCreated={created} onBusyChange={setBusy}/>
     <PlanChangeNotice saved={detail.accepted_plan} proposed={selected}/>
     {!!detail.options?.length&&<RouteCompare nodes={nodes} options={detail.options} operationalEvents={detail.data_kind==="demo"?[]:ops?.events} operationalRevision={ops?.revision} selected={sel} onSelect={i=>{setSel(i);setAck(false)}} showJourneyTools={false} weatherZones={ops?.weather_zones??[]}/>}
     {selected?.unavailable_reasons?.length&&<div className="manager-state-message is-warning"><b>Why this route needs review</b>{selected.unavailable_reasons.map(r=><span key={r}>{r}</span>)}</div>}
     {positionReady&&detail.dispatch_actions&&<details className="manager-dispatch-details"><summary>Dispatch choices</summary><DispatchActions actions={detail.dispatch_actions} selected={sel} onSelect={i=>{setSel(i);setAck(false)}}/></details>}
     <form className="decision-form" onSubmit={e=>{e.preventDefault();void decide("accept")}}><div className="decision-heading"><ShieldCheck size={19}/><div><h3>Manager decision</h3><span>{routeDraft?"Calculate your hub changes before approving a route.":blocked?"Choose an available route or record a hold.":"Review the route and confirm your decision."}</span></div></div><label>Your name<input required minLength={2} maxLength={80} autoComplete="name" placeholder="Who is making this decision?" value={decidedBy} onChange={e=>{setDecidedBy(e.target.value);try{localStorage.setItem("dachser-decided-by",e.target.value)}catch{/* remembered for this visit only */}}}/></label><label>Reason<textarea required minLength={3} placeholder="Add the reason for this decision" value={reason} onChange={e=>setReason(e.target.value)}/></label>{selected&&!selected.risk.deadline_ok&&<label className="ack"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/>I acknowledge the delivery deadline will be missed.</label>}<div className="decision-buttons"><button className="btn" disabled={busy||blocked||reason.trim().length<3||decidedBy.trim().length<2||(!selected?.risk.deadline_ok&&!ack)}><Check size={15}/>{detail.hold?"Approve & release hold":"Approve selected route"}</button><button type="button" className="btn btn--hold" disabled={busy||!selected||reason.trim().length<3||decidedBy.trim().length<2} onClick={()=>void decide("hold")}><Pause size={14}/>{moving?"Request safe stop":"Place on hold"}</button><button type="button" className="btn btn--ghost" disabled={busy||!selected||reason.trim().length<3||decidedBy.trim().length<2} onClick={()=>void decide("keep")}>Keep saved plan</button><button type="button" className="btn btn--ghost" disabled={busy||!selected||reason.trim().length<3||decidedBy.trim().length<2} onClick={()=>void decide("defer")}>Defer</button></div></form>
    </div>}
   </section>
  </div>
  <ScenarioStudio nodes={nodes} ops={ops} onChange={scenarioChanged}/><ServiceSettings nodes={nodes} onChange={()=>void scenarioChanged()}/><CapacitySettings nodes={nodes} onChange={scenarioChanged}/><DecisionHistory decisions={ops?.decisions??[]} nodes={nodes} disabled={busy} onChanged={async()=>{await load();onChange()}} onRevise={d=>review(d.shipment_id,true,d)}/>
 </>;
}
