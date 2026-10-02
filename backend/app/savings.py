"""
Savings engine.

Three separate, separately-labelled sources of value. Nothing is invented: every
number is derived from a stored plan or a stored option set, and each row carries
the basis it was computed from.

  1. ROUTE OPTIMIZATION  chosen route vs the direct road option for the same
                         departure and conditions (money, fuel, time).
  2. DISRUPTION AVOIDANCE when a manager approves a different route because
                         conditions changed, the counterfactual is the previously
                         approved path re-evaluated under the NEW conditions.
                         Recorded at approval time in shipments.schedule().
  3. EXPOSURE AVOIDED    shipment value that would have been at risk if the
                         counterfactual missed the delivery window.

Transit time is converted to money at an explicit, documented rate — the same
EUR 50 per transit hour already used by the "balanced" ranking objective. It is a
planning valuation, not a billed cost, and is reported on its own line.
"""
from __future__ import annotations

from .analytics import DIESEL_EUR_PER_L

VALUE_OF_TIME_EUR_PER_HOUR = 50.0

# Basis labels, strongest first.
BASIS_QUOTE = "quote"        # comparison stored on the approved quote
BASIS_SNAPSHOT = "snapshot"  # rebuilt from the quote's baseline_snapshot
BASIS_DERIVED = "derived"    # rebuilt from the shipment's own stored option set
BASIS_LEGACY = "legacy"      # no baseline available — contributes nothing

BASIS_LABEL = {
    BASIS_QUOTE: "Approved quote comparison",
    BASIS_SNAPSHOT: "Rebuilt from quote baseline snapshot",
    BASIS_DERIVED: "Derived from this shipment's stored direct option",
    BASIS_LEGACY: "Approved before savings tracking — re-approve in the control room to measure it",
}


def _direct_option(options):
    """The direct road option (origin → destination, no intermediate hub)."""
    return next((o for o in options or [] if len(o.get("path") or []) == 2 and o.get("avoidance_status")!="CLEAR"), None)


def _same_planning_pass(plan, options):
    """True only if `plan` provably came from this stored option set.

    A baseline is meaningless unless it was computed in the same pass as the
    plan it is compared against: a different pass means a different departure,
    a different operational revision, or different live conditions. We require
    the plan to appear in the option set with an identical journey length and
    revision before we trust the set's direct option as its baseline.
    """
    for option in options or []:
        if plan.get("quote_id") and option.get("quote_id")!=plan["quote_id"]:
            continue
        if (option.get("path") == plan.get("path")
                and option.get("total_minutes") == plan.get("total_minutes")
                and option.get("revision") == plan.get("revision")
                and option.get("depart_at") == plan.get("depart_at")):
            return True
    return False


def _diff(baseline, plan):
    return {
        "baseline": "Direct road option, same departure and conditions",
        "money_saved_eur": round(baseline["cost"]["transport_eur"] - plan["cost"]["transport_eur"], 2),
        "fuel_saved_l": round(baseline["cost"]["fuel_l"] - plan["cost"]["fuel_l"], 1),
        "minutes_saved": round(baseline["total_minutes"] - plan["total_minutes"]),
    }


def comparison_for(ship):
    """-> (comparison dict | None, basis). Never plans; only reads what is stored."""
    plan = ship.get("accepted_plan")
    if not plan:
        return None, BASIS_LEGACY
    if plan.get("comparison"):
        return plan["comparison"], BASIS_QUOTE
    snapshot = plan.get("baseline_snapshot")
    if snapshot and snapshot.get("cost") and snapshot.get("total_minutes") is not None:
        return _diff(snapshot, plan), BASIS_SNAPSHOT
    options = ship.get("options")
    direct = _direct_option(options)
    if direct and _same_planning_pass(plan, options):
        return _diff(direct, plan), BASIS_DERIVED
    # The approved plan predates this option set, so there is no honest
    # baseline for it. Re-approving it in the control room creates one.
    return None, BASIS_LEGACY


def _time_value(minutes):
    return round(minutes / 60.0 * VALUE_OF_TIME_EUR_PER_HOUR, 2)


def is_demo(ship):
    return bool(ship.get("data_kind")=="demo" or ship.get("demo_session") or (ship.get("accepted_plan") or {}).get("is_demo"))


def shipment_row(ship, names=None, demo=False):
    """A traceable estimate, never proof of realized financial savings."""
    plan=ship.get("accepted_plan") or {}
    comparison,basis=comparison_for(ship)
    excluded=None
    if not demo and not ship.get("approved_at"):
        excluded="Awaiting manager approval"
    elif ship.get("hold") or ship.get("status")=="ON HOLD":
        excluded="Shipment is on hold"
    elif not comparison:
        excluded="No matching baseline for this approved plan"
    comparable=excluded is None
    comparison=comparison if comparable else None
    disruption=ship.get("disruption_savings") or {}
    # A previous reroute's benefit cannot be attributed to a later approval.
    if (not comparable or not plan.get("quote_id") or
            disruption.get("approved_quote_id")!=plan["quote_id"]):
        disruption={}
    money=round(comparison["money_saved_eur"],2) if comparison else 0.0
    fuel=round(comparison["fuel_saved_l"],1) if comparison else 0.0
    minutes=round(comparison["minutes_saved"]) if comparison else 0
    time_value=_time_value(minutes)
    avoided_minutes=round(disruption.get("minutes_avoided",0))
    disruption_value=round(_time_value(avoided_minutes)-disruption.get("cost_delta_eur",0),2) if disruption else 0.0
    return {
        "id":ship["id"],"container":ship.get("container"),
        "route":[(names or {}).get(n,n) for n in ship.get("route",[])],
        "status":ship.get("status"),"data_kind":"demo" if demo else "estimated",
        "basis":basis,"basis_label":"Simulated plan comparison" if demo and comparable else BASIS_LABEL[basis],
        "money_eur":money,"fuel_l":fuel,"time_min":minutes,"time_value_eur":time_value,
        "disruption_eur":disruption_value,"exposure_avoided_eur":round(disruption.get("exposure_avoided_eur",0),2),
        # One baseline only. Reroute comparisons and cargo value are NOT added.
        "benefit_eur":round(money+time_value,2),"comparable":comparable,"excluded_reason":excluded,
        "disruption":{**disruption,"value_eur":disruption_value,"minutes_avoided":avoided_minutes} if disruption else None,
        "evidence":{"quote_id":plan.get("quote_id"),"approved_at":ship.get("approved_at"),
                    "manager_reason":ship.get("approval_reason"),"evaluated_at":plan.get("evaluated_at"),
                    "baseline":(comparison or {}).get("baseline"),"source":plan.get("data_sources",{}).get("transport"),
                    "revision":plan.get("revision"),"arrival":plan.get("eta"),
                    "outcome_recorded":bool(ship.get("actual"))},
    }


def summary(ships, names=None, scope="estimated"):
    if scope not in {"estimated","demo"}:raise ValueError("Unknown savings scope")
    demo=scope=="demo"
    selected=[s for s in ships if is_demo(s)==demo]
    rows=[shipment_row(s,names,demo) for s in selected]
    counted=[r for r in rows if r["comparable"]]
    keys=("money_eur","fuel_l","time_min","time_value_eur","disruption_eur","exposure_avoided_eur")
    total={k:round(sum(r[k] for r in counted),2) for k in keys}
    total["optimized"]=len(counted)
    total["economic_benefit_eur"]=round(total["money_eur"]+total["time_value_eur"],2)
    total["fuel_eur"]=round(total["fuel_l"]*DIESEL_EUR_PER_L,2)
    return {
        "scope":scope,"total":total,"avg_per_shipment_eur":round(total["economic_benefit_eur"]/len(counted),2) if counted else 0,
        "per_shipment":sorted(rows,key=lambda r:(not r["comparable"],-r["benefit_eur"],r["id"])),
        "legacy_count":sum(r["excluded_reason"]=="No matching baseline for this approved plan" for r in rows),
        "excluded_count":len(rows)-len(counted),"unapproved_count":sum(not s.get("approved_at") for s in selected),
        "demo_excluded_count":sum(is_demo(s) for s in ships) if not demo else 0,
        "rerouted_count":sum(bool(r["disruption"]) for r in counted),
        "assumptions":{"value_of_time_eur_per_hour":VALUE_OF_TIME_EUR_PER_HOUR,
                       "note":"Planning value = transport estimate difference + transit hours saved x EUR 50/hour. "
                              "Fuel value, reroute comparisons and cargo value are shown separately and are not added to that total."},
        "note":"Signed planning estimates, not realized savings. Negative values mean additional cost, time or fuel.",
        "source":"Saved demo scenarios only; excluded from operational results" if demo else
                 "Manager-approved, non-demo plans and their own stored baselines. Held and unapproved plans are excluded from totals.",
    }
