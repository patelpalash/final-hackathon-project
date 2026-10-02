"""Actual delivery evidence. No synthetic fallback and no inferred outcomes."""
import math
from datetime import datetime, timezone

from .operations import parse
from .savings import is_demo

MINIMUM_SAMPLES = 5


def summary(ships, names=None):
    rows=[]
    excluded=0
    for ship in ships:
        actual=ship.get("actual")
        if not actual:continue
        plan=ship.get("accepted_plan") or {}
        if (is_demo(ship) or not ship.get("approved_at") or not plan.get("quote_id") or
                actual.get("accepted_quote_id")!=plan["quote_id"]):
            excluded+=1
            continue
        try:
            departure=parse(actual["actual_departure"])
            arrival=parse(actual["actual_arrival"])
            eta=parse(plan["eta"])
            cost=float(actual["actual_cost_eur"])
            planned_cost=float(plan["cost"]["transport_eur"])
            if arrival<departure or arrival>datetime.now(timezone.utc) or cost<0 or not all(map(math.isfinite,(cost,planned_cost))):
                raise ValueError("Invalid actual outcome")
        except (KeyError,TypeError,ValueError,AttributeError):
            excluded+=1
            continue
        rows.append({"id":ship["id"],"route":[(names or {}).get(n,n) for n in ship.get("route",[])],
                     "quote_id":plan["quote_id"],"approved_at":ship["approved_at"],
                     "recorded_at":actual.get("recorded_at"),"approved_eta":plan["eta"],
                     "actual_arrival":actual["actual_arrival"],"actual_cost_eur":cost,
                     "approved_cost_eur":planned_cost,
                     "arrival_error_minutes":round((arrival-eta).total_seconds()/60),
                     "cost_error_eur":round(cost-planned_cost,2),
                     "on_time":actual.get("on_time") if type(actual.get("on_time")) is bool else None,
                     "source":"User-reported actual; linked to approved quote"})
    rows.sort(key=lambda row:row["actual_arrival"],reverse=True)
    enough=len(rows)>=MINIMUM_SAMPLES
    deadlines=[r for r in rows if r["on_time"] is not None]
    return {"samples":len(rows),"minimum_samples":MINIMUM_SAMPLES,"excluded_records":excluded,
            "status":"MEASURED" if enough else "INSUFFICIENT_DATA",
            "arrival_mae_minutes":round(sum(abs(r["arrival_error_minutes"]) for r in rows)/len(rows),1) if enough else None,
            "cost_error_eur":round(sum(r["cost_error_eur"] for r in rows)/len(rows),2) if enough else None,
            "on_time_pct":round(100*sum(r["on_time"] for r in deadlines)/len(deadlines),1) if len(deadlines)>=MINIMUM_SAMPLES else None,
            "deadline_samples":len(deadlines),"outcomes":rows,
            "source":"User-reported completed deliveries linked to approved quotes. Demo, unapproved, invalid and unmatched records are excluded. Cost variance is not realized savings."}
