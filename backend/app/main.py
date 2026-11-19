"""
DACHSER Live Transit Planner — API.
Real network + holidays + historical analytics; dynamic restriction engine; ETA,
cost, fuel, risk, savings engines; shipment lifecycle; live providers (honest
status); manager hub delays; audit. See README for the section-by-section map.
"""
from __future__ import annotations

import os
import time
import json
from copy import copy, deepcopy
from .runtime import configure_runtime, deployment_info
configure_runtime()
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, AwareDatetime, model_validator
from typing import Literal
from functools import wraps
from fastapi.responses import JSONResponse, Response
from .operations import Operations, parse, LOCK
from .weather_rules import evaluate, THRESHOLDS

from . import analytics as an
from . import data as dataloader
from .cost import journey_cost, cost_per_kg
from .eta import compute_journey, _haversine_km
from .providers import Providers
from .restrictions import drive_with_restrictions
from .risk import assess
from .shipments import ApprovalReviewUpdated, Shipments, approval_paths, plan as plan_options, replan_input, review_options, savings_vs_baseline, shipment_visits_hub_during, shipment_traffic_exposure_minutes
from . import savings as savings_engine
from .savings_scenarios import SavingsScenarios
from .dispatch import attention, action_comparison, approvable
from .simulate import reroute as simulate_reroute
from .map_tiles import router as map_tiles_router
from . import persistence

from pathlib import Path
DATA_DIR = os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[2] / "data" / "raw"))
S = {}


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _audit(kind, detail, source="system"):
    S["audit"].insert(0, {"at": _now_iso(), "type": kind, "detail": detail, "source": source})
    S["audit"] = S["audit"][:300]


def _ctx():
    return {"network": S["network"], "holidays": S["holidays"], "transfer": S["transfer"],
            "hub_delays": S["hub_delays"], "providers": S["providers"], "history": S["history"],
            "operations": S["operations"],"capacity_shipments":list(S["ships"].data.values()) if "ships" in S else []}


def ensure_runtime_state():
    with LOCK:
        if "ships" in S:
            return
        S["operations"] = Operations()
        S["hub_delays"] = S["operations"].data.setdefault("hub_delays", {})
        ships = Shipments(_ctx())
        if os.environ.get("SEED_DEMO_SHIPMENTS", "1") == "1":
            ships.seed_if_empty()
        S["ships"] = ships


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DATA_DIR or not os.path.isdir(DATA_DIR):
        raise RuntimeError("Set DATA_DIR to the folder containing the DACHSER CSVs.")
    S["network"] = dataloader.load_network(DATA_DIR)
    S["holidays"] = dataloader.load_holidays(DATA_DIR)
    S["transfer"] = dataloader.transfer_stats(DATA_DIR)
    # relationen dict for cost/analytics
    rel = {}
    for e in S["network"]["edges"].values():
        if e["from"] == S["network"]["hub_id"]:
            rel[e["relation"]] = {"km": e["km"], "cost_line": e["cost_eur"], "cost_special": e["cost_special_eur"]}
    S["history"] = an.relation_history(DATA_DIR, rel)
    S["savings_scenarios"] = SavingsScenarios(DATA_DIR)
    S["disruptions"] = an.disruptions(DATA_DIR)
    S["providers"] = Providers(S["holidays"])
    S.pop("ships", None)
    S["audit"] = []
    if not persistence.configured():
        ensure_runtime_state()
    _audit("startup", f"{len(S['network']['nodes'])} hubs, {len(S['holidays'])} holidays, "
                      f"{len(S['history'])} lane histories")
    try:
        yield
    finally:
        if hasattr(S["providers"],"close"):S["providers"].close()


app = FastAPI(title="DACHSER Live Transit Planner", version="3.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(map_tiles_router)

STATELESS_ROUTES={
    "/api/health", "/api/network", "/api/providers", "/api/holidays", "/api/settings",
    "/api/settings/tomtom", "/api/savings/scenarios", "/api/transport-calendar",
    "/api/analytics/relations", "/api/weather", "/api/journey-examples",
    "/api/audit", "/api/assumptions", "/api/map-conditions",
}
STATELESS_PREFIXES=("/api/map-tiles/","/api/traffic-tiles/")


@app.middleware("http")
async def fresh_api_responses(request,call_next):
    # These endpoints do not read saved journeys or mutable operations data.
    stateless=request.url.path in STATELESS_ROUTES or request.url.path.startswith(STATELESS_PREFIXES)
    started=time.perf_counter();db_ms=0.0
    if persistence.configured() and request.url.path.startswith("/api/") and not stateless and request.method != "OPTIONS":
        from starlette.concurrency import run_in_threadpool
        reads_state = request.method == "GET" or request.url.path in {"/api/route", "/api/simulate/reroute"}
        refresh = refresh_shared_state if reads_state else ensure_runtime_state
        try:
            checked = await run_in_threadpool(refresh)
        except persistence.StorageUnavailable:
            # A pooled connection may have been closed by the database; retry once on a fresh one.
            persistence.reset_pool()
            try:
                checked = await run_in_threadpool(refresh)
            except persistence.StorageUnavailable as exc:
                return JSONResponse(status_code=503,content={"detail":str(exc)},headers={"Cache-Control":"no-store"})
        if checked is not None:
            persistence.refreshed.set(checked)
        db_ms=(time.perf_counter()-started)*1000
    response=await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"]="no-store"
        # Visible in the browser's network panel: shared-state refresh vs. total server time.
        response.headers["Server-Timing"]=f"db;dur={db_ms:.0f}, total;dur={(time.perf_counter()-started)*1000:.0f}"
    return response


def refresh_shared_state():
    ensure_runtime_state()
    if not persistence.configured():return frozenset()
    from .demo import _sessions
    with LOCK,persistence.session():
        # Saved journeys, operations and every demo session this worker has open: one query.
        demo_keys={f"demo/{sid}/operations.json":ops for sid,ops in list(_sessions.items())}
        fresh=persistence.load_many({"operations.json":S["operations"].data,
                                     **{key:ops.data for key,ops in demo_keys.items()}},prefix=persistence.SHIP_PREFIX)
        for key,ops_obj in demo_keys.items():
            if key in fresh:ops_obj.data=fresh[key]
        ops=fresh.get("operations.json")
        # Only journeys changed (or removed) by another server instance are replaced.
        for name,ship in fresh.items():
            if not name.startswith(persistence.SHIP_PREFIX):continue
            sid=name[len(persistence.SHIP_PREFIX):]
            if ship is None:S["ships"].data.pop(sid,None)
            else:S["ships"].data[sid]=ship
        if ops is not None:
            S["operations"].data=ops
            S["hub_delays"]=ops.setdefault("hub_delays",{})
            S["ships"].ctx["hub_delays"]=S["hub_delays"]
    return frozenset(["operations.json",*demo_keys])


def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with LOCK,persistence.session(write=True):
            refresh_shared_state()
            return fn(*args, **kwargs)
    return wrapped


def planning_snapshot(context):
    """Freeze planning inputs without copying every shipment's road geometry."""
    ops=copy(context["operations"])
    ops.data=deepcopy(ops.data)
    summaries=[]
    for ship in context["capacity_shipments"]:
        plan=ship.get("accepted_plan") or {}
        summaries.append({
            **{k:ship.get(k) for k in ("id","origin","destination","status","approved_at","data_kind","demo_session","simulation_used")},
            "vehicle_position":{"source":(ship.get("vehicle_position") or {}).get("source")},
            "actual":deepcopy(ship.get("actual")),
            "capacity_reservations":deepcopy(ship.get("capacity_reservations",[])),
            "accepted_plan":{k:plan.get(k) for k in ("quote_id","eta","remaining_only","is_demo")},
        })
    return {**context,"operations":ops,"hub_delays":deepcopy(context["hub_delays"]),"capacity_shipments":summaries}

def _json_default(value):
    if hasattr(value,"isoformat"):return value.isoformat()
    if isinstance(value,(set,frozenset,tuple)):return list(value)
    if hasattr(value,"model_dump"):return value.model_dump(mode="json")
    return str(value)


def fast_json(value):
    """Send large plan payloads with the C JSON encoder. FastAPI's default
    jsonable_encoder walks every route coordinate in Python (~0.7 s per journey)."""
    from fastapi import Response as _Response
    if isinstance(value,_Response):return value
    return _Response(json.dumps(value,separators=(",",":"),default=_json_default,allow_nan=False),media_type="application/json")


@app.exception_handler(ValueError)
async def invalid_request(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(persistence.StorageUnavailable)
async def unavailable_storage(request,exc):
    return JSONResponse(status_code=503,content={"detail":str(exc)})

class TruckReq(BaseModel):
    # Broad prototype sanity limits; these are routing-input limits, not a claim
    # that every vehicle at these dimensions is legal in every country.
    height_m: float = Field(default=4, ge=1.5, le=4.5)
    width_m: float = Field(default=2.55, ge=1.5, le=2.6)
    length_m: float = Field(default=16.5, ge=3, le=20)
    gross_weight_kg: float = Field(default=40000, ge=1000, le=50000)

class PlanningRulesReq(BaseModel):
    region: Literal["DE-BW","DE-BY","DE-BE","DE-BB","DE-HB","DE-HH","DE-HE","DE-MV","DE-NI","DE-NW","DE-RP","DE-SL","DE-SN","DE-ST","DE-SH","DE-TH"] = "DE-BW"
    company_sunday_hold: bool = True
    trailer_attached: bool = True


class RouteReq(BaseModel):
    planning_rules: PlanningRulesReq = Field(default_factory=PlanningRulesReq)
    via_hubs: list[str] = Field(default_factory=list,max_length=6)
    sample_id: Optional[str] = None
    sample_weather: bool = False
    optimization: Literal["fastest","cost","balanced"] = "fastest"
    truck: TruckReq = Field(default_factory=TruckReq)
    origin: str
    destination: str
    depart_at: Optional[AwareDatetime] = None
    weight_kg: float = Field(default=8000, ge=1, le=23800)
    required_delivery: Optional[AwareDatetime] = None
    value_eur: float = Field(default=0, ge=0, le=100_000_000)

    @model_validator(mode="after")
    def validate_planning_inputs(self):
        if self.weight_kg > self.truck.gross_weight_kg:
            raise ValueError("Gross vehicle weight must be at least the shipment weight.")
        if self.depart_at and self.required_delivery and self.required_delivery <= self.depart_at:
            raise ValueError("Delivery deadline must be later than the departure time.")
        return self


class DelayReq(BaseModel):
    minutes: int = Field(ge=0, le=10080)
    reason: str = Field(min_length=1, max_length=500)
    note: Optional[str] = ""


class ShipmentReq(BaseModel):
    planning_rules: PlanningRulesReq = Field(default_factory=PlanningRulesReq)
    demo_session: Optional[str] = None
    optimization: Literal["fastest","cost","balanced"] = "fastest"
    truck: TruckReq = Field(default_factory=TruckReq)
    selected_path: Optional[list[str]] = None
    selected_route_id: Optional[str] = None
    origin: str
    destination: str
    weight_kg: float = Field(default=8000, ge=1, le=23800)
    value_eur: float = Field(default=0, ge=0, le=100_000_000)
    planned_departure: AwareDatetime
    required_delivery: Optional[AwareDatetime] = None
    container: Optional[str] = None
    customer_segment: Optional[str] = None

    @model_validator(mode="after")
    def validate_planning_inputs(self):
        if self.weight_kg > self.truck.gross_weight_kg:
            raise ValueError("Gross vehicle weight must be at least the shipment weight.")
        if self.required_delivery and self.required_delivery <= self.planned_departure:
            raise ValueError("Delivery deadline must be later than the departure time.")
        return self


def _parse(dt):
    return parse(dt) if isinstance(dt, str) else dt.astimezone(timezone.utc)


# ---- network / reference ----
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "3.0.0-combined", "hubs": len(S["network"]["nodes"]), "time": _now_iso()}


@app.get("/api/network")
def network():
    n = S["network"]
    return {"hub_id": n["hub_id"], "nodes": list(n["nodes"].values()), "edges": list(n["edges"].values()),"deployment":deployment_info()}


@app.get("/api/hubs")
def hubs():
    out = []
    for nid, node in S["network"]["nodes"].items():
        rel = node.get("relation")
        st = S["transfer"].get(rel, {}) if rel else {}
        hist = S["history"].get(rel, {}) if rel else {}
        delay = S["hub_delays"].get(nid)
        out.append({**node, "transfer": st, "history": hist, "operational_delay": delay,
                    "expected_transfer_minutes": (st.get("avg_transfer_minutes", 120) if node["type"] == "branch" else 120) + (delay["minutes"] if delay else 0)})
    return {"hubs": out}


@app.get("/api/providers")
def providers():
    return {"providers": S["providers"].all(), "generated_at": _now_iso()}


@app.get("/api/holidays")
def holidays():
    from .transport_calendar import holidays as regional_holidays
    from .restrictions import BERLIN
    today=datetime.now(BERLIN).date()
    dates={day:row for year in (today.year,today.year+1) for day,row in regional_holidays(year,"DE-BW").items()}
    up=sorted([{"date":day,"name":row["name"],"region":"Baden-Württemberg","country":"DE",
                "transport_impact":"Truck ban 00:00–22:00" if row["truck_ban"] else "Public holiday; no additional StVO §30 truck ban"}
               for day,row in dates.items() if day>=today.isoformat()],key=lambda x:x["date"])[:12]
    return {"source":"German regional holiday calendar / StVO §30(4)","upcoming":up,"count":len(dates)}


@app.get("/api/transport-calendar")
def transport_calendar(year:int=Query(ge=1900,le=2100),month:int=Query(ge=1,le=12),region:str="DE-BW",company_sunday_hold:bool=True):
    from .transport_calendar import month_calendar
    return month_calendar(year,month,region,company_sunday_hold)


@app.get("/api/analytics/relations")
def analytics_relations():
    net = S["network"]
    rows = []
    for e in net["edges"].values():
        if e["from"] == net["hub_id"]:
            h = S["history"].get(e["relation"], {})
            rows.append({"relation": e["relation"], "destination": net["nodes"][e["to"]]["name"],
                         "km": e["km"], "cost_line_eur": e["cost_eur"], "cost_special_eur": e["cost_special_eur"], **h})
    return {"relations": sorted(rows, key=lambda r: r.get("spillover_rate", 0), reverse=True)}


@app.get("/api/disruptions")
def disruptions():
    active = [{"hub": nid, "name": S["network"]["nodes"][nid]["name"], **d, "source": "MANAGER INPUT"}
              for nid, d in S["hub_delays"].items()]
    return {"active_operational": active, "historical": S["disruptions"]}


@app.get("/api/weather")
def weather(node: str):
    n = S["network"]["nodes"].get(node)
    if not n:
        raise HTTPException(404, "unknown node")
    return {"node": node, **S["providers"].weather.fetch(n["lat"], n["lon"])}


# ---- planning ----
@app.post("/api/route")
def route(req: RouteReq):
    net = S["network"]
    if req.origin not in net["nodes"] or req.destination not in net["nodes"]:
        raise HTTPException(422, "unknown origin or destination")
    if req.origin == req.destination:
        raise HTTPException(422, "origin equals destination")
    if req.weight_kg > req.truck.gross_weight_kg: raise ValueError("Gross vehicle weight must include the cargo")
    depart = _parse(req.depart_at) if req.depart_at else datetime.now(timezone.utc)
    from .manager_routes import validate_path
    requested_path=validate_path(net,req.origin,req.destination,req.via_hubs) if req.via_hubs else None
    # Routing waits on remote providers. Keep fleet/scenario polling responsive
    # and give every candidate the same operational revision throughout a search.
    with LOCK:
        context=planning_snapshot(_ctx())
    revision=context["operations"].data["revision"]
    sample=None; zones=[]
    if req.sample_id:
        from .journey_examples import example, isolated_context
        sample=example(req.sample_id);context=isolated_context(context)
    args=(req.origin,req.destination,depart,req.weight_kg,req.required_delivery.isoformat() if req.required_delivery else None,req.value_eur,req.optimization,req.truck.model_dump())
    context["planning_rules"]=req.planning_rules.model_dump()
    options=plan_options(context,*args,required_paths=[requested_path] if requested_path else None)
    if sample and req.sample_weather:
        from .journey_examples import weather_for
        baseline=next((o for o in options if len(o["path"])==2),options[0])
        zones=weather_for(sample,baseline.get("geometry"),depart)
        context["operations"].data["weather_zones"]=zones
        options=plan_options(context,*args,required_paths=[requested_path] if requested_path else None)
    if requested_path:
        for option in options:option["manager_requested"]=option["path"]==requested_path

    savings = savings_vs_baseline(options[0], options[1]) if len(options) > 1 and options[0].get("avoidance_status") in {"NO_ZONE", "CLEAR"} else None
    wx = []  # Manual/sample records are evaluated by the same weather alert engine.
    safe_available=approvable(options[0])
    if not safe_available:savings=None
    if not sample:_audit("route_calculated", f"{req.origin} → {req.destination}: " + (f"recommended ETA {options[0]['eta']}" if safe_available else "no route clear of simulated weather zones"))
    return fast_json({"options": options, "recommended": 0 if safe_available else None, "savings": savings,
            "weather": wx, "revision": revision, "providers": S["providers"].all(), "evaluated_at": _now_iso(),
            "sample": {"id":sample["id"],"title":sample["title"],"weather_applied":req.sample_weather} if sample else None,"weather_zones":zones})


@app.get("/api/journey-examples")
def journey_examples():
    from .journey_examples import catalog
    return catalog(S["network"]["nodes"])


# ---- shipments ----
@app.get("/api/shipments")
def list_shipments(status: Optional[str] = None, origin: Optional[str] = None,
                   destination: Optional[str] = None, at_risk: Optional[bool] = None,
                   high_value: Optional[bool] = None, delayed: Optional[bool] = None):
    items = S["ships"].list()
    def keep(s):
        if status and s["status"] != status: return False
        if origin and s["origin"] != origin: return False
        if destination and s["destination"] != destination: return False
        if at_risk and s["risk_level"] not in ("MEDIUM", "HIGH"): return False
        if high_value and (s.get("value_eur", 0) < 100000): return False
        if delayed and not s.get("delay_minutes"): return False
        return True
    events=S["operations"].data["events"]
    def summary(s):
        matching=[e for e in events if e["kind"]=="hub_delay" and shipment_visits_hub_during(s,e,pending_only=True)]
        traffic=[e for e in events if e["kind"]=="traffic" and shipment_traffic_exposure_minutes(s,e,pending_only=True)]
        closures=[e for e in events if e["kind"]=="closure" and shipment_visits_hub_during(s,e,pending_only=True)]
        hub_minutes=sum(e["minutes"] for e in matching)
        traffic_minutes=sum(shipment_traffic_exposure_minutes(s,e,pending_only=True) for e in traffic)
        driver_delay=s.get("reported_delay") or {}
        driver_minutes=max(0,round((parse(driver_delay["until"])-datetime.now(timezone.utc)).total_seconds()/60)) if driver_delay and driver_delay.get("reported_at",driver_delay["at"])>(s.get("accepted_plan") or {}).get("evaluated_at","") else 0
        projected_eta=(parse(s["current_eta"])+timedelta(minutes=hub_minutes+traffic_minutes)).isoformat() if hub_minutes+traffic_minutes else None
        return {**{k:v for k,v in s.items() if k not in {"options","accepted_plan"}},
                "dispatch":attention(s,S["ships"].context_for(s)["operations"],hub_minutes+traffic_minutes+driver_minutes,closures),
                "pending_hub_delay_minutes":hub_minutes,
                "pending_hub_events":[e["id"] for e in matching],
                "pending_traffic_minutes":traffic_minutes,
                "pending_driver_minutes":driver_minutes,
                "pending_traffic_events":[e["id"] for e in traffic],
                "pending_closure_events":[e["id"] for e in closures],
                "projected_eta":projected_eta}
    return {"shipments":[summary(s) for s in items if keep(s)]}


@app.get("/api/shipments/{sid}")
def get_shipment(sid: str):
    s = S["ships"].get(sid)
    if not s:
        raise HTTPException(404, "unknown shipment")
    return fast_json({**s,"dispatch_actions":action_comparison(s)})


@app.post("/api/shipments")
@serialized
def create_shipment(req: ShipmentReq):
    net = S["network"]
    if req.origin not in net["nodes"] or req.destination not in net["nodes"] or req.origin == req.destination:
        raise HTTPException(422, "invalid origin/destination")
    if req.weight_kg > req.truck.gross_weight_kg: raise ValueError("Gross vehicle weight must include the cargo")
    s = S["ships"].create(req.model_dump(mode="json"))
    _audit("shipment_created", f"{s['id']}: {req.origin} → {req.destination}, {req.weight_kg:.0f} kg, risk {s['risk_level']}")
    return s


@app.post("/api/shipments/{sid}/schedule")
def schedule_shipment(sid: str, option: int = 0, force: bool = False, quote_id: str = "", reason: str = ""):
    if len(reason.strip())<3 or not quote_id: raise ValueError("Manager reason and reviewed quote ID are required; use the control room")
    with LOCK:
        refresh_shared_state()
        ship=S["ships"].get(sid)
        if not ship: raise HTTPException(404,"Unknown shipment")
        if not 0<=option<len(ship["options"]): raise ValueError("Invalid option")
        revision=ship["options"][option]["revision"]
    result=decision(DecisionReq(shipment_id=sid,action="accept",option=option,revision=revision,quote_id=quote_id,reason=reason,acknowledge_deadline=force))
    if isinstance(result,Response) and result.status_code>=400:return result
    return fast_json({"scheduled":True,"shipment":S["ships"].get(sid)})



@app.post("/api/shipments/{sid}/status")
@serialized
def set_status(sid: str, status: str):
    s = S["ships"].set_status(sid, status)
    if not s:
        raise HTTPException(404, "unknown shipment")
    _audit("shipment_status", f"{sid}: → {status}")
    return {"ok": True, "status": status}


# ---- dashboards ----
@app.get("/api/savings")
def savings(scope: Literal["estimated","demo"] = "estimated"):
    names = {nid: node["name"] for nid, node in S["network"]["nodes"].items()}
    return savings_engine.summary(S["ships"].list(), names, scope)


@app.get("/api/savings/scenarios")
def savings_scenarios(
    lane: str = "R01",
    reserve: int = Query(default=2, ge=0, le=4),
    objective: Literal["match_dispatch", "clear_demand"] = "match_dispatch",
):
    catalog = S["savings_scenarios"]
    if lane not in catalog.lanes:
        raise HTTPException(404, "Unknown lane")
    return catalog.compare(lane, reserve, objective)


@app.post("/api/savings/recalculate")
@serialized
def recalculate_savings():
    """Rebuild missing quote comparisons from each shipment's own stored options.

    This never re-plans and never calls a provider: it only fills in comparisons
    that older saved plans did not carry, so historical savings stop reading as
    zero. Shipments without any stored direct option stay marked as legacy.
    """
    repaired = S["ships"].repair_comparisons()
    _audit("savings_recalculated", f"{repaired} saved plan(s) given a derived baseline comparison", "MANAGER INPUT")
    names = {nid: node["name"] for nid, node in S["network"]["nodes"].items()}
    return {"repaired": repaired, **savings_engine.summary(S["ships"].list(), names)}


@app.get("/api/high-value")
def high_value():
    out = []
    for s in S["ships"].list():
        if s.get("value_eur", 0) >= 100000:
            opt = s.get("accepted_plan") or s.get("options", [{}])[0]
            out.append({"id": s["id"], "value_eur": s["value_eur"], "origin": s["origin"],
                        "destination": s["destination"], "current_location": s["current_location"],
                        "route": s["route"], "required_delivery": s.get("required_delivery"),
                        "current_eta": s["current_eta"], "risk_level": s["risk_level"],
                        "exposure_eur": opt.get("risk", {}).get("exposure_eur", 0),
                        "reasons": opt.get("risk", {}).get("reasons", []),
                        "recommended_action": "Review alternatives" if s["risk_level"] != "LOW" else "On track"})
    return {"shipments": sorted(out, key=lambda x: x["exposure_eur"], reverse=True)}


@app.get("/api/dashboard")
def dashboard():
    ships = S["ships"].list()
    by_status = {}
    for s in ships:
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
    at_risk = [s["id"] for s in ships if s["risk_level"] in ("MEDIUM", "HIGH")]
    high_val = [s["id"] for s in ships if s.get("value_eur", 0) >= 100000]
    sv = savings()
    hol = holidays()["upcoming"]
    return {"counts": by_status, "total": len(ships), "at_risk": len(at_risk),
            "high_value": len(high_val), "active_hub_delays": len(S["hub_delays"]),
            "next_holiday": hol[0] if hol else None,
            "estimated_savings_eur": sv["total"]["money_eur"],
            "providers": S["providers"].all(), "generated_at": _now_iso()}


# ---- manager ----
@app.post("/api/hubs/{node_id}/delay")
@serialized
def set_delay(node_id: str, req: DelayReq):
    if node_id not in S["network"]["nodes"]:
        raise HTTPException(404, "unknown hub")
    S["hub_delays"][node_id] = {"minutes": req.minutes, "reason": req.reason, "note": req.note,
                                "status": "ACTIVE", "at": _now_iso()}
    S["operations"].data["revision"] += 1
    S["operations"].save()
    _audit("hub_delay_set", f"{S['network']['nodes'][node_id]['name']}: +{req.minutes}m — {req.reason}", "MANAGER INPUT")
    return {"ok": True, "hub": node_id, "delay": S["hub_delays"][node_id]}


@app.delete("/api/hubs/{node_id}/delay")
@serialized
def clear_delay(node_id: str):
    if S["hub_delays"].pop(node_id, None):
        S["operations"].data["revision"] += 1
        S["operations"].save()
        _audit("hub_delay_resolved", f"{S['network']['nodes'][node_id]['name']}: operational delay resolved", "MANAGER INPUT")
    return {"ok": True}


@app.get("/api/audit")
def audit():
    return {"events": S["audit"]}


# ---- sample weather / events / manager review ----
class WindowReq(BaseModel):
    start: AwareDatetime
    end: AwareDatetime
    @model_validator(mode="after")
    def chronological(self):
        if self.end <= self.start: raise ValueError("End must be after start")
        return self

class WeatherReq(WindowReq):
    node: str
    temperature_c: float = Field(default=4, ge=-80, le=65)
    condition: str = Field(default="Heavy Snow", min_length=1, max_length=100)
    rain_mm: float = Field(default=0, ge=0, le=500)
    snow_cm: float = Field(default=5, ge=0, le=500)
    visibility_m: float = Field(default=500, ge=0, le=100000)
    wind_kmh: float = Field(default=35, ge=0, le=400)
    severity: Literal["LOW","MEDIUM","HIGH"] = "HIGH"

class EventReq(WindowReq):
    kind: Literal["traffic","hub_delay","closure"]
    node: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    minutes: int = Field(default=120, ge=0, le=10080)
    reason: str = Field(min_length=1, max_length=500)

class DecisionReq(BaseModel):
    shipment_id: str
    action: Literal["accept","keep","defer","hold"]
    option: int = Field(default=0, ge=0)
    revision: int
    quote_id: str = Field(min_length=1)
    reason: str = Field(min_length=3, max_length=1000)
    acknowledge_deadline: bool = False
    supersedes_decision_id: Optional[str] = None
    supersedes_updated_at: Optional[str] = None
    decided_by: Optional[str] = Field(default=None, max_length=80)  # name entered by the manager (no login yet)
    request_id: Optional[UUID] = None

    @model_validator(mode="after")
    def clean_name(self):
        self.decided_by = (self.decided_by or "").strip() or None
        return self

def _node(nid):
    if nid not in S["network"]["nodes"]: raise ValueError("Unknown hub")

@app.get("/api/operations")
def operations():
    result = S["operations"].snapshot()
    result["weather"] = [evaluate(r) for r in result["weather"]]
    ships=S["ships"].list() if result["events"] else []
    for event in result["events"]:
        if event["kind"] in {"hub_delay","closure"}:
            affected=[s["id"] for s in ships if shipment_visits_hub_during(s,event)]
            event["affected_count"]=len(affected)
            event["affected_shipments"]=affected
        elif event["kind"]=="traffic":
            affected=[s["id"] for s in ships if shipment_traffic_exposure_minutes(s,event,pending_only=True)]
            event["affected_count"]=len(affected)
            event["affected_shipments"]=affected
    result["thresholds"] = THRESHOLDS
    return result

@app.get("/api/control-room")
def control_room():
    with LOCK:
        return {**list_shipments(), "operations": operations()}


class WeatherZoneReq(BaseModel):
    kind: Literal["snow", "rain", "tornado"]
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=18, ge=3, le=80)
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def check_window(self):
        if self.end <= self.start: raise ValueError("Zone end must follow its start")
        return self


@app.post("/api/weather-zones")
@serialized
def add_weather_zone(req: WeatherZoneReq):
    row=S["operations"].put("weather_zones", req.model_dump(mode="json"))
    _audit("weather_zone_created",f"Simulated {row['kind']} zone · radius {row['radius_km']} km","MANUAL MAP SIMULATION")
    return row


@app.put("/api/weather-zones/{rid}")
@serialized
def edit_weather_zone(rid: str, req: WeatherZoneReq):
    if not any(z["id"]==rid for z in S["operations"].data["weather_zones"]): raise HTTPException(404,"Unknown weather zone")
    return S["operations"].put("weather_zones", req.model_dump(mode="json"), rid)


@app.delete("/api/weather-zones/{rid}")
@serialized
def delete_weather_zone(rid: str):
    if not any(z["id"]==rid for z in S["operations"].data["weather_zones"]): raise HTTPException(404,"Unknown weather zone")
    S["operations"].remove("weather_zones",rid)
    return {"ok":True}


@app.post("/api/weather-records")
@serialized
def add_weather(req: WeatherReq):
    _node(req.node)
    row=S["operations"].put("weather",req.model_dump(mode="json"))
    _audit("weather_sample",f"{req.node}: {req.condition}","MANUAL SAMPLE")
    return evaluate(row)

@app.put("/api/weather-records/{rid}")
@serialized
def edit_weather(rid: str, req: WeatherReq):
    _node(req.node)
    if not any(r["id"]==rid for r in S["operations"].data["weather"]): raise HTTPException(404,"Unknown weather record")
    return evaluate(S["operations"].put("weather",req.model_dump(mode="json"),rid))

@app.delete("/api/weather-records/{rid}")
@serialized
def delete_weather(rid: str):
    S["operations"].remove("weather",rid)
    return {"ok":True}

@app.post("/api/events")
@serialized
def add_event(req: EventReq):
    if req.kind=="traffic":
        if bool(req.origin) != bool(req.destination): raise ValueError("Provide both corridor endpoints or leave both empty for all routes")
        if req.origin:
            _node(req.origin); _node(req.destination)
            if req.origin==req.destination: raise ValueError("Choose different endpoints")
    else: _node(req.node)
    row=S["operations"].put("events",req.model_dump(mode="json"))
    _audit("scenario_event",req.reason,"SIMULATED / MANAGER INPUT")
    return row

@app.delete("/api/events/{rid}")
@serialized
def resolve_event(rid: str):
    S["operations"].remove("events",rid)
    _audit("event_resolved",rid,"MANAGER INPUT")
    return {"ok":True}

@app.post("/api/shipments/{sid}/replan")
def replan_shipment(sid: str, from_now:bool=False):
    with LOCK:
        refresh_shared_state()
        ship=S["ships"].get(sid)
        if not ship:raise HTTPException(404,"Unknown shipment")
        snapshot=deepcopy({key:value for key,value in ship.items() if key!="options"})
        quotes=[o.get("quote_id") for o in ship["options"]]
        context=planning_snapshot(S["ships"].context_for(ship))
    planned=replan_input(snapshot,from_now)
    options=review_options(context,planned)
    return _save_replan(sid,snapshot,quotes,context["operations"].data["revision"],planned["planned_departure"],options)


@serialized
def _save_replan(sid,snapshot,quotes,revision,departure,options):
    ship=S["ships"].get(sid)
    if not ship:raise HTTPException(404,"Unknown shipment")
    current_context=S["ships"].context_for(ship)
    if (revision!=current_context["operations"].data["revision"] or quotes!=[o.get("quote_id") for o in ship["options"]]
            or any(ship.get(key)!=snapshot.get(key) for key in _APPROVAL_STATE)):
        raise HTTPException(409,"Journey or conditions changed while recalculating. Try again for the latest plan.")
    s=S["ships"].save_replan(sid,departure,options)
    return fast_json({**s,"dispatch_actions":action_comparison(s)})


class ManagerRouteReq(BaseModel):
    via_hubs: list[str] = Field(default_factory=list,max_length=6)
    depart_at: Optional[AwareDatetime] = None


@app.post("/api/shipments/{sid}/route-proposal")
@serialized
def manager_route_proposal(sid:str, req:ManagerRouteReq):
    from .manager_routes import propose
    s=propose(S["ships"],sid,req.via_hubs,req.depart_at.isoformat() if req.depart_at else None)
    _audit("manager_route_proposed",f"{sid}: "+" → ".join(s["manager_route_request"]["path"]),"MANAGER INPUT")
    return fast_json({**s,"dispatch_actions":action_comparison(s)})


class PositionReq(BaseModel):
    lat: Optional[float] = Field(default=None,ge=-85,le=85,allow_inf_nan=False)
    lon: Optional[float] = Field(default=None,ge=-180,le=180,allow_inf_nan=False)
    source: Literal["DRIVER REPORTED","MANAGER REPORTED","SIMULATION","PLAN ESTIMATE"] = "MANAGER REPORTED"
    reported_at: Optional[AwareDatetime] = None
    progress_percent: Optional[float] = Field(default=None,ge=0,le=100,allow_inf_nan=False)
    movement_state: Literal["MOVING","STOPPED"] = "MOVING"
    @model_validator(mode="after")
    def coordinates(self):
        if self.source!="PLAN ESTIMATE" and self.progress_percent is None and (self.lat is None or self.lon is None):raise ValueError("Provide coordinates or a simulation percentage")
        if self.source=="SIMULATION" and self.progress_percent is None:raise ValueError("Simulation requires an explicit progress percentage")
        return self


@app.post("/api/shipments/{sid}/position")
@serialized
def update_position(sid:str,req:PositionReq):
    if not S["ships"].get(sid):raise HTTPException(404,"Unknown shipment")
    ship=S["ships"].update_position(sid,req.model_dump(mode="json"))
    _audit("vehicle_position",f"{sid}: {ship['vehicle_position']['source']}",ship["vehicle_position"]["source"])
    return {**ship,"dispatch_actions":[]}


class DriverEventReq(BaseModel):
    kind:Literal["departed","delay","safe_stop","arrived"]
    at:Optional[AwareDatetime]=None
    reference:str=Field(default="",max_length=500)
    minutes:Optional[int]=Field(default=None,ge=1,le=1440)
    actual_cost_eur:Optional[float]=Field(default=None,ge=0,allow_inf_nan=False)


@app.post("/api/shipments/{sid}/driver-update")
@serialized
def driver_update(sid:str,req:DriverEventReq):
    if not S["ships"].get(sid):raise HTTPException(404,"Unknown shipment")
    ship=S["ships"].driver_event(sid,req.model_dump(mode="json"))
    _audit("driver_update",f"{sid}: {req.kind}","USER-REPORTED DRIVER UPDATE")
    return {**ship,"dispatch_actions":action_comparison(ship)}


class StopReq(BaseModel):
    reason:str=Field(min_length=3,max_length=1000)


@app.post("/api/shipments/{sid}/stop-request")
@serialized
def request_stop(sid:str,req:StopReq):
    from .progress import dispatched
    ship=S["ships"].get(sid)
    if not ship:raise HTTPException(404,"Unknown shipment")
    if not dispatched(ship):raise ValueError("Use a departure hold for a journey that has not departed")
    S["ships"].hold(sid,0,req.reason)
    S["operations"].put("decisions",{"shipment_id":sid,"action":"stop_request","reason":req.reason.strip(),"path":ship["route"],"eta":ship["current_eta"],"data_kind":ship.get("data_kind","user")})
    return {**ship,"dispatch_actions":action_comparison(ship)}

def _decision_state(req):
    s=S["ships"].get(req.shipment_id)
    if not s:raise HTTPException(404,"Unknown shipment")
    if s["status"]=="DELIVERED":raise ValueError("Delivery is confirmed. You can edit the decision note, but cannot change this journey.")
    previous=None
    if req.supersedes_decision_id:
        previous=next((d for d in S["operations"].data["decisions"] if d["id"]==req.supersedes_decision_id),None)
        if not previous or previous["shipment_id"]!=req.shipment_id:raise HTTPException(404,"Decision does not belong to this shipment")
        if previous.get("superseded_by"):raise HTTPException(409,"This decision has already been replaced. Open its latest revision.")
        if req.supersedes_updated_at!=previous["updated_at"]:raise HTTPException(409,"Decision changed. Refresh history before revising it.")
    if len(req.reason.strip())<3:raise ValueError("Enter a decision reason of at least three characters")
    ctx=S["ships"].context_for(s)
    if req.revision!=ctx["operations"].data["revision"]:raise HTTPException(409,"Conditions changed. Recalculate before deciding.")
    if req.option>=len(s["options"]):raise ValueError("Invalid option")
    option=s["options"][req.option]
    if option.get("revision",-1)!=req.revision:raise HTTPException(409,"Recalculate shipment options first")
    if req.quote_id!=option.get("quote_id"):raise HTTPException(409,"Quote replaced. Recalculate and review again.")
    return s,option,previous,ctx


def _decision_response(row, ship):
    summary={k:ship.get(k) for k in ("id","status","route","approved_at","current_eta","plan_change","alert")}
    summary["dispatch"]=attention(ship,S["operations"])
    return {**row,"shipment_summary":summary}


def _saved_decision(req):
    if req.request_id is None:return None
    request_id=str(req.request_id)
    row=next((d for d in S["operations"].data["decisions"] if d.get("request_id")==request_id),None)
    if row is None:return None
    if any(row.get(key)!=getattr(req,key) for key in ("shipment_id","action","quote_id")):
        raise HTTPException(409,"This request already belongs to a different decision.")
    return _decision_response(row,S["ships"].get(req.shipment_id))


_APPROVAL_STATE=("status","planned_departure","scheduled_departure","movement_started_at","approved_at","vehicle_position",
                 "reported_delay","manager_route_request","hold","stop_request","required_delivery","truck","planning_rules")


@app.post("/api/decisions")
def decision(req: DecisionReq):
    if req.action!="accept":return _save_decision(req)
    with LOCK:
        refresh_shared_state()
        saved=_saved_decision(req)
        if saved:return saved
        ship,option,_,ctx=_decision_state(req)
        if option.get("avoidance_status") in {"IMPACTED","NO_CLEAR_DETOUR"}:
            raise HTTPException(409,"This route crosses an active simulated weather zone. Choose a clear route or hold the shipment.")
        if not option.get("route_feasible",True) or not option.get("capacity",{}).get("feasible",True):
            raise HTTPException(409,"This route is unavailable. Choose another option or recalculate.")
        paths=approval_paths(ship,option)
        snapshot=deepcopy({key:value for key,value in ship.items() if key!="options"})
        ctx=planning_snapshot(ctx)
    # Provider calls run outside both the process lock and the DB write transaction.
    fresh=review_options(ctx,snapshot,only_paths=paths) if paths is not None else review_options(ctx,snapshot)
    return fast_json(_save_decision(req,snapshot,fresh,paths is not None))


@serialized
def _save_decision(req, snapshot=None, fresh=None, limited=False):
    saved=_saved_decision(req)
    if saved:return saved
    s,option,previous_decision,_=_decision_state(req)
    if snapshot is not None and any(s.get(key)!=snapshot.get(key) for key in _APPROVAL_STATE):
        raise HTTPException(409,"Journey changed while checking the route. Recalculate and review it again.")
    previous_route=list(s["route"])
    if req.action=="accept":
        try:
            _,warning=S["ships"].schedule(req.shipment_id,req.option,req.acknowledge_deadline,req.quote_id,req.reason.strip(),
                                          reviewed_options=fresh,limited=limited)
        except ApprovalReviewUpdated as exc:
            # Return after committing the updated choices. Raising inside the
            # transaction would remove them and force another provider search.
            return JSONResponse(status_code=422,content={"detail":str(exc),"code":"REVIEW_UPDATED"})
        if warning:raise HTTPException(409,warning)
    elif req.action=="hold":
        S["ships"].hold(req.shipment_id,req.option,req.reason)
    row=S["operations"].put("decisions",{**req.model_dump(mode="json",exclude_none=True),"reason":req.reason.strip(),"created_at":_now_iso(),"path":s["route"],"eta":s["current_eta"],"reviewed_path":option["path"],"reviewed_eta":option["eta"],"data_kind":s.get("data_kind","user"),"previous_route":previous_route})
    if previous_decision:
        S["operations"].put("decisions",{**previous_decision,"created_at":previous_decision.get("created_at",previous_decision["updated_at"]),"superseded_by":row["id"],"superseded_at":row["updated_at"]},previous_decision["id"])
    _audit("manager_decision",f"{req.shipment_id}: {req.action} — {req.reason}","MANAGER INPUT")
    return fast_json(_decision_response(row,s))


class DecisionNoteReq(BaseModel):
    reason: str = Field(min_length=3,max_length=1000)
    expected_updated_at: str = Field(min_length=1)


@app.patch("/api/decisions/{decision_id}")
@serialized
def edit_decision_note(decision_id:str, req:DecisionNoteReq):
    original=next((d for d in S["operations"].data["decisions"] if d["id"]==decision_id),None)
    if not original: raise HTTPException(404,"Unknown decision")
    if original["updated_at"]!=req.expected_updated_at: raise HTTPException(409,"Decision changed. Refresh history before saving your edit.")
    reason=req.reason.strip()
    if len(reason)<3: raise ValueError("Enter a decision reason of at least three characters")
    if reason==original["reason"]: return original
    edits=[*original.get("reason_edits",[]),{"previous_reason":original["reason"],"reason":reason,"at":_now_iso()}]
    row=S["operations"].put("decisions",{**original,"created_at":original.get("created_at",original["updated_at"]),"reason":reason,"reason_edits":edits},decision_id)
    _audit("manager_decision_note_edited",f"{row['shipment_id']}: decision note updated","MANAGER INPUT")
    return row

@app.get("/api/assumptions")
def assumptions():
    import json
    from pathlib import Path
    return json.loads((Path(__file__).parent / "assumptions.json").read_text(encoding="utf-8"))


class MapReq(BaseModel):
    geometry: list[tuple[float,float]] = Field(min_length=2,max_length=50000)
    at: AwareDatetime
    @model_validator(mode="after")
    def bounds(self):
        if any(not (-180<=lon<=180 and -85<=lat<=85) for lon,lat in self.geometry): raise ValueError("Invalid coordinates")
        return self

@app.post("/api/map-conditions")
def map_conditions(req: MapReq):
    from .live import now
    coords=req.geometry
    samples=[coords[round((len(coords)-1)*f)] for f in [0,.25,.5,.75,1]]
    points=[(lat,lon) for lon,lat in samples]
    weather=S["providers"].forecasts.fetch(points,[req.at]*len(points))
    # Incidents and flow show current conditions only, never future predictions.
    incidents=S["providers"].tomtom.incidents(coords) if abs((req.at-now()).total_seconds())<3600 else {"status":"CURRENT_ONLY","items":[]}
    return {"weather":weather,"incidents":incidents,"traffic_configured":bool(S["providers"].tomtom.key),"at":req.at.isoformat(),"fetched_at":_now_iso(),"note":"Forecast preview does not change saved departure or ETA. Recalculate the plan to refresh arrival estimates."}

class RerouteReq(BaseModel):
    """Live re-route request from the journey simulator."""
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)
    destination: str
    via: Optional[str] = None
    depart_at: Optional[AwareDatetime] = None
    truck: TruckReq = Field(default_factory=TruckReq)
    transfer_minutes: int = Field(default=0, ge=0, le=1440)
    avoid_weather: bool = False
    avoid_points: list[dict] = Field(default_factory=list, max_length=10)  # blocked road spots: {lat, lon, radius_km}

    @model_validator(mode="after")
    def check_points(self):
        for p in self.avoid_points:
            if not (-85 <= float(p.get("lat", 999)) <= 85 and -180 <= float(p.get("lon", 999)) <= 180 and 0.5 <= float(p.get("radius_km", 2)) <= 30):
                raise ValueError("Invalid blocked road position")
        return self


@app.post("/api/simulate/reroute")
def simulate_reroute_endpoint(req: RerouteReq):
    """Road route from a vehicle's current position, optionally via a facility.

    Used by the journey simulator so an on-screen diversion follows real roads
    instead of a drawn line. Returns an explicit status when routing is
    unavailable so the client can label its fallback honestly.
    """
    if req.via and req.via == req.destination:
        raise HTTPException(422, "Intermediate facility equals destination")
    return simulate_reroute(_ctx(), req.lat, req.lon, req.destination, req.via,
                            _parse(req.depart_at) if req.depart_at else None,
                            req.truck.model_dump(), req.transfer_minutes, req.avoid_weather, req.avoid_points)


@app.get("/api/traffic-tiles/{z}/{x}/{y}.png")
def traffic_tile(z:int,x:int,y:int):
    if not (0<=z<=22 and 0<=x<2**z and 0<=y<2**z): raise HTTPException(422,"Invalid tile")
    tile=S["providers"].tomtom.tile(z,x,y)
    if tile is None:
        from .live import TRANSPARENT_PNG
        return Response(content=TRANSPARENT_PNG, media_type="image/png", headers={"Cache-Control":"public, max-age=300"})
    return Response(content=tile,media_type="image/png",headers={"Cache-Control":"private, max-age=120"})


class SettingsTomTomReq(BaseModel):
    key: str

@app.get("/api/settings")
def get_settings():
    key = S["providers"].tomtom.key
    return {
        "tomtom_configured": bool(key),
        "tomtom_masked": ("configured" if key else "") if os.environ.get("VERCEL")=="1" else f"{key[:4]}...{key[-4:]}" if len(key) > 8 else ("configured" if key else ""),
        "traffic_status": S["providers"].traffic.status(),
        "traffic_mode": "live" if key else "simulated"
    }

@app.post("/api/settings/tomtom")
def update_tomtom_key(req: SettingsTomTomReq):
    if os.environ.get("VERCEL")=="1":raise HTTPException(403,"Configure TOMTOM_API_KEY in the hosting environment; public credential editing is disabled")
    new_key = req.key.strip()
    S["providers"].tomtom.set_key(new_key)
    S["providers"].traffic.configured = bool(new_key)
    S["providers"].traffic.name = "TomTom (Live)" if new_key else "Simulated Traffic Engine"
    env_path = Path(__file__).resolve().parents[2] / ".env"
    try:
        lines = []
        found = False
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("TOMTOM_API_KEY="):
                    lines.append(f"TOMTOM_API_KEY={new_key}")
                    found = True
                else:
                    lines.append(line)
        if not found:
            lines.append(f"TOMTOM_API_KEY={new_key}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass
    _audit("settings_update", f"TomTom API key {'configured' if new_key else 'cleared'}", "USER INPUT")
    return {"ok": True, "tomtom_configured": bool(new_key), "traffic_mode": "live" if new_key else "simulated"}


class ServiceReq(BaseModel):
    origin: str
    destination: str
    weekdays: list[int] = Field(min_length=1,max_length=7)
    departure_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "Europe/Berlin"
    cutoff_minutes: int = Field(default=30,ge=0,le=1440)
    @model_validator(mode="after")
    def valid_service(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        if self.origin==self.destination or any(d not in range(7) for d in self.weekdays): raise ValueError("Invalid service endpoints or weekdays")
        try: ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError: raise ValueError("Unknown timezone")
        return self

@app.get("/api/services")
def services(): return {"services":S["operations"].snapshot()["schedules"]}

@app.post("/api/services")
@serialized
def save_service(req:ServiceReq):
    _node(req.origin); _node(req.destination)
    row=S["operations"].put("schedules",{**req.model_dump(),"source":"USER-ENTERED TIMETABLE / availability unverified"})
    _audit("service_added",f"{req.origin} → {req.destination} {req.departure_time}","MANAGER INPUT")
    return row

@app.delete("/api/services/{rid}")
@serialized
def delete_service(rid:str):
    S["operations"].remove("schedules",rid)
    return {"ok":True}


class CapacityReq(BaseModel):
    kind:Literal["hub","service"]
    node:Optional[str]=None
    service_id:Optional[str]=None
    start:AwareDatetime
    end:AwareDatetime
    available_ldm:float=Field(ge=0,le=10000,allow_inf_nan=False)
    reason:str=Field(min_length=3,max_length=500)
    @model_validator(mode="after")
    def window(self):
        if self.end<=self.start:raise ValueError("Capacity end must follow its start")
        if self.kind=="hub" and not self.node:raise ValueError("Select a hub")
        if self.kind=="service" and not self.service_id:raise ValueError("Select a departure service")
        return self


@app.get("/api/capacity")
def capacity_records():
    return {"records":S["operations"].snapshot()["capacity_records"]}


@app.post("/api/capacity")
@serialized
def save_capacity(req:CapacityReq):
    if req.kind=="hub":_node(req.node)
    elif not any(s["id"]==req.service_id for s in S["operations"].data["schedules"]):raise ValueError("Unknown departure service")
    row=S["operations"].put("capacity_records",{**req.model_dump(mode="json"),"source":"MANAGER ENTERED"})
    _audit("capacity_limit",f"{req.kind}: {req.available_ldm} loading metres — {req.reason}","MANAGER INPUT")
    return row


@app.delete("/api/capacity/{rid}")
@serialized
def remove_capacity(rid:str):
    if not any(r["id"]==rid for r in S["operations"].data["capacity_records"]):raise HTTPException(404,"Unknown capacity record")
    S["operations"].remove("capacity_records",rid)
    return {"ok":True}

class OutcomeReq(BaseModel):
    actual_departure: AwareDatetime
    actual_arrival: AwareDatetime
    actual_cost_eur: float = Field(ge=0,allow_inf_nan=False)
    @model_validator(mode="after")
    def chronology(self):
        if self.actual_arrival<self.actual_departure: raise ValueError("Actual arrival must follow departure")
        return self

@app.post("/api/shipments/{sid}/outcome")
@serialized
def outcome(sid:str,req:OutcomeReq):
    if not S["ships"].get(sid): raise HTTPException(404,"Unknown shipment")
    ship=S["ships"].record_outcome(sid,req.model_dump(mode="json"))
    _audit("actual_outcome",f"{sid}: actual delivery outcome recorded","MANAGER INPUT")
    return ship

@app.get("/api/performance")
def performance():
    from .performance import summary
    names={nid:node["name"] for nid,node in S["network"]["nodes"].items()}
    return summary(S["ships"].list(),names)


@app.post("/api/demo/start")
@serialized
def start_demo():
    import uuid
    session=uuid.uuid4().hex[:12]
    ops=Operations(Path(os.environ.get("STORE_DIR","store"))/"demo"/session)
    ops.save()
    ship=S["ships"].create({"origin":"R16","destination":"R21","planned_departure":"2026-09-22T06:00:00+00:00","required_delivery":"2026-09-24T18:00:00+00:00","weight_kg":12000,"value_eur":180000,"demo_session":session,"container":"JUDGE DEMO"})
    _audit("demo_started",ship["id"],"DEMO")
    return ship

@app.post("/api/demo/{sid}/disruption")
@serialized
def demo_disruption(sid:str):
    s=S["ships"].get(sid)
    if not s or not s.get("demo_session"): raise HTTPException(404,"Unknown demo shipment")
    ops=S["ships"].context_for(s)["operations"]
    if not any(e["id"]=="demo-traffic" for e in ops.data["events"]):
        ops.put("events",{"kind":"traffic","origin":"R16","destination":"R21","start":"2026-09-22T00:00:00+00:00","end":"2026-09-24T00:00:00+00:00","minutes":180,"reason":"DEMO: direct-connection congestion, +180 minutes"},"demo-traffic")
    return S["ships"].replan(sid)
