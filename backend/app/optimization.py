"""Explicit optimization objectives and a normalized historical cost reference."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

def decorate(options, ctx, origin, destination, ldm, objective):
    # A route crossing a simulated exclusion zone cannot win on ETA or cost.
    safe=[o for o in options if o.get("avoidance_status") in {"NO_ZONE", "CLEAR"}]
    eligible=([o for o in safe if o["risk"]["deadline_ok"]] or safe) if safe else []
    fastest=min(eligible,key=lambda o:o["total_minutes"]) if eligible else None
    cheapest=min(eligible,key=lambda o:o["cost"]["transport_eur"]) if eligible else None
    # Explainable prototype value of time, not a hidden model.
    balanced=min(eligible,key=lambda o:o["cost"]["transport_eur"]+o["total_minutes"]*50/60) if eligible else None
    direct=next(o for o in options if len(o["path"])==2)
    for o in options:
        o["badges"]=[label for label,choice in [("Fastest",fastest),("Lowest cost",cheapest),("Balanced",balanced)] if choice is not None and o is choice]
        o["optimization"]=objective
        o["quote_id"]=uuid4().hex
        o["evaluated_at"]=datetime.now(timezone.utc).isoformat()
        o["baseline_snapshot"]={k:direct[k] for k in ("path","depart_at","eta","total_minutes","cost","revision")}
        o["comparison"]={"baseline":"Direct road option, same departure and conditions","money_saved_eur":direct["cost"]["transport_eur"]-o["cost"]["transport_eur"],"minutes_saved":direct["total_minutes"]-o["total_minutes"],"fuel_saved_l":direct["cost"]["fuel_l"]-o["cost"]["fuel_l"]}
        o["valid_until"]=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
        net=ctx["network"];edges=[net["edges"].get(a+"-"+b) for a,b in zip(o["path"],o["path"][1:])]
        exact=all(edges)
        relations=list(dict.fromkeys(e["relation"] for e in edges if e)) if exact else list(dict.fromkeys(net["nodes"][n].get("relation") for n in (origin,destination) if net["nodes"][n].get("relation")))
        histories=[(r,ctx["history"][r]) for r in relations if r in ctx["history"]]
        unit=sum(h.get("cost_per_ldm_eur",0) for _,h in histories)
        reference=round(unit*ldm,2) if histories and all(h.get("cost_per_ldm_eur") for _,h in histories) else None
        o["historical_comparison"]={"scope":"Matched dataset lanes" if exact else "Reference lanes via assumed central hub; not the selected route", "matched":exact,"relations":relations,"samples":sum(h["samples"] for _,h in histories),"normalized_cost_eur":reference,"cost_difference_eur":round(reference-o["cost"]["transport_eur"],2) if reference is not None else None,"reliability_pct":round(sum(h["reliability_pct"] for _,h in histories)/len(histories),1) if histories else None,"time_difference_minutes":None,"note":"Daily cost normalized by historical loading metres, then allocated to this shipment. Derived benchmark, not realized savings. No historical arrival timestamps supplied; time savings against history cannot be measured."}
    key={"fastest":lambda o:(o["total_minutes"],o["cost"]["transport_eur"]),"cost":lambda o:(o["cost"]["transport_eur"],o["total_minutes"]),"balanced":lambda o:(o["cost"]["transport_eur"]+o["total_minutes"]*50/60,o["total_minutes"])}[objective]
    options.sort(key=lambda o:(o.get("avoidance_status") not in {"NO_ZONE", "CLEAR"},not o["risk"]["deadline_ok"],*key(o)))
    return options
