import type { RouteOption } from "../api/types";
import { dt,eur } from "../lib";
export function PlanChangeNotice({saved,proposed}:{saved?:RouteOption;proposed?:RouteOption}){
 if(!saved||!proposed)return null;
 const minutes=Math.round((Date.parse(proposed.eta)-Date.parse(saved.eta))/60000);
 const cost=proposed.cost.transport_eur-saved.cost.transport_eur;
 const route=saved.path.join()!==proposed.path.join();
 const changed=route||Math.abs(minutes)>=15||Math.abs(cost)>=Math.max(.01,saved.cost.transport_eur*.05)||saved.risk.deadline_ok!==proposed.risk.deadline_ok||saved.revision!==proposed.revision||JSON.stringify(saved.components)!==JSON.stringify(proposed.components)||saved.data_sources.transport!==proposed.data_sources.transport;
 return <div className={`plan-change notice ${changed?"notice--warn":"notice--info"}`}><div><b>{changed?"Plan changed · review required":"Compared with saved plan"}</b><p>{route?"Route changed. ":""}{saved.risk.deadline_ok!==proposed.risk.deadline_ok?"Deadline feasibility changed. ":""}{saved.revision!==proposed.revision?"Operational inputs changed. ":""}Evaluated {dt(proposed.evaluated_at)}. Saved plan remains in effect until approved.</p></div><div className="change-values"><span>Arrival<b>{dt(saved.eta)} → {dt(proposed.eta)}</b><small>{minutes>=0?"+":""}{minutes} min</small></span><span>Transport<b>{eur(saved.cost.transport_eur)} → {eur(proposed.cost.transport_eur)}</b><small>{cost>=0?"+":""}{eur(cost)}</small></span></div></div>
}
