import {useState} from "react";
import {api} from "../api/client";
import type {NetNode,Shipment} from "../api/types";
import {RouteCompare} from "./RouteCompare";
import {PlanChangeNotice} from "./PlanChangeNotice";
export function JudgeDemo({nodes,onReview,onChange}:{nodes:NetNode[];onReview:()=>void;onChange:()=>void}){
 const [ship,setShip]=useState<Shipment|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[selected,setSelected]=useState(0),[disrupted,setDisrupted]=useState(false);
 async function run(disrupt=false){setBusy(true);setError("");try{const s=disrupt&&ship?await api.demoDisruption(ship.id):await api.startDemo();setShip(s);setSelected(0);setDisrupted(disrupt);onChange()}catch(e){setError(String(e))}finally{setBusy(false)}}
 return <details className="card compact-settings demo-studio" open><summary>Judge walkthrough <span className="mini">ISOLATED DEMO</span></summary><p>Captured road geometry, illustrative travel times and a fixed Tuesday departure. No live APIs are used for these demo routes. Your other shipments and scenarios are preserved.</p><div className="demo-actions"><button className="btn btn--sm" disabled={busy} onClick={()=>run()}>1. {ship?"Start another demo":"Create baseline plan"}</button><button className="btn btn--ghost btn--sm" disabled={busy||!ship||disrupted} onClick={()=>run(true)}>2. Add 180m direct-connection delay</button><button className="btn btn--ghost btn--sm" disabled={busy||!ship} onClick={onReview}>3. Review in control room ↗</button></div>{error&&<div role="alert" className="notice notice--warn">{error}</div>}{ship?.options&&<><p><b>{ship.id}</b> · Baseline saved for review. Find this DEMO shipment in the control room to approve a proposal and record your reason.</p><PlanChangeNotice saved={ship.accepted_plan} proposed={ship.options[selected]}/><RouteCompare nodes={nodes} options={ship.options} selected={selected} onSelect={setSelected}/></>}</details>
}
