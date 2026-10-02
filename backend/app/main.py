"""
DACHSER Live Transit Planner — API.
Real network + holidays + historical analytics; dynamic restriction engine; ETA,
cost, fuel, risk, savings engines; shipment lifecycle; live providers (honest
status); manager hub delays; audit. See README for the section-by-section map.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
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
from .shipments import Shipments, plan as plan_options, savings_vs_baseline, shipment_visits_hub_during, shipment_traffic_exposure_minutes
from . import savings as savings_engine
from .simulate import reroute as simulate_reroute
from .map_tiles import router as map_tiles_router

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
            "operations": S["operations"]}


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
    S["disruptions"] = an.disruptions(DATA_DIR)
    S["providers"] = Providers(S["holidays"])
    S["operations"] = Operations()
    S["hub_delays"] = S["operations"].data.setdefault("hub_delays", {})
    S["audit"] = []
    S["ships"] = Shipments(_ctx())
    S["ships"].seed_if_empty()
    _audit("startup", f"{len(S['network']['nodes'])} hubs, {len(S['holidays'])} holidays, "
                      f"{len(S['history'])} lane histories, {len(S['ships'].list())} shipments")
    try:
        yield
    finally:
        if hasattr(S["providers"],"close"):S["providers"].close()


app = FastAPI(title="DACHSER Live Transit Planner", version="3.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(map_tiles_router)


def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with LOCK:
            return fn(*args, **kwargs)
    return wrapped

@app.exception_handler(ValueError)
async def invalid_request(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})

class TruckReq(BaseModel):
    # Broad prototype sanity limits; these are routing-input limits, not a claim
    # that every vehicle at these dimensions is legal in every country.
    height_m: float = Field(default=4, ge=1.5, le=4.5)
    width_m: float = Field(default=2.55, ge=1.5, le=2.6)
    length_m: float = Field(default=16.5, ge=3, le=20)
    gross_weight_kg: float = Field(default=40000, ge=1000, le=50000)

class RouteReq(BaseModel):
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
    return {"hub_id": n["hub_id"], "nodes": list(n["nodes"].values()), "edges": list(n["edges"].values())}


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
    today = datetime.now(timezone.utc).date().isoformat()
    up = sorted([{"date": d, "name": n, "region": "Baden-Württemberg", "country": "DE",
                  "transport_impact": "Prototype holiday window 00:00–22:00; Sunday business hold until Monday"}
                 for d, n in S["holidays"].items() if d >= today], key=lambda x: x["date"])[:12]
    return {"source": "kalender.csv (Baden-Württemberg)", "upcoming": up, "count": len(S["holidays"])}


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
@serialized
def route(req: RouteReq):
    net = S["network"]
    if req.origin not in net["nodes"] or req.destination not in net["nodes"]:
        raise HTTPException(422, "unknown origin or destination")
    if req.origin == req.destination:
        raise HTTPException(422, "origin equals destination")
    if req.weight_kg > req.truck.gross_weight_kg: raise ValueError("Gross vehicle weight must include the cargo")
    depart = _parse(req.depart_at) if req.depart_at else datetime.now(timezone.utc)
    options = plan_options(_ctx(), req.origin, req.destination, depart,
                           req.weight_kg, req.required_delivery.isoformat() if req.required_delivery else None, req.value_eur, req.optimization, req.truck.model_dump())

    savings = savings_vs_baseline(options[0], options[1]) if len(options) > 1 and options[0].get("avoidance_status") in {"NO_ZONE", "CLEAR"} else None
    wx = []  # Manual/sample records are evaluated by the same weather alert engine.
    safe_available=options[0].get("avoidance_status") in {"NO_ZONE", "CLEAR"}
    _audit("route_calculated", f"{req.origin} → {req.destination}: " + (f"recommended ETA {options[0]['eta']}" if safe_available else "no route clear of simulated weather zones"))
    return {"options": options, "recommended": 0 if safe_available else None, "savings": savings,
            "weather": wx, "revision": S["operations"].data["revision"], "providers": S["providers"].all(), "evaluated_at": _now_iso()}


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
        projected_eta=(parse(s["current_eta"])+timedelta(minutes=hub_minutes+traffic_minutes)).isoformat() if hub_minutes+traffic_minutes else None
        return {**{k:v for k,v in s.items() if k not in {"options","accepted_plan"}},
                "pending_hub_delay_minutes":hub_minutes,
                "pending_hub_events":[e["id"] for e in matching],
                "pending_traffic_minutes":traffic_minutes,
                "pending_traffic_events":[e["id"] for e in traffic],
                "pending_closure_events":[e["id"] for e in closures],
                "projected_eta":projected_eta}
    return {"shipments":[summary(s) for s in items if keep(s)]}


@app.get("/api/shipments/{sid}")
def get_shipment(sid: str):
    s = S["ships"].get(sid)
    if not s:
        raise HTTPException(404, "unknown shipment")
    return s


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
@serialized
def schedule_shipment(sid: str, option: int = 0, force: bool = False, quote_id: str = "", reason: str = ""):
    if len(reason.strip())<3 or not quote_id: raise ValueError("Manager reason and reviewed quote ID are required; use the control room")
    ship=S["ships"].get(sid)
    if not ship: raise HTTPException(404,"Unknown shipment")
    if not 0<=option<len(ship["options"]): raise ValueError("Invalid option")
    decision(DecisionReq(shipment_id=sid,action="accept",option=option,revision=ship["options"][option]["revision"],quote_id=quote_id,reason=reason,acknowledge_deadline=force))
    return {"scheduled":True,"shipment":S["ships"].get(sid)}



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

def _node(nid):
    if nid not in S["network"]["nodes"]: raise ValueError("Unknown hub")

@app.get("/api/operations")
def operations():
    result = S["operations"].snapshot()
    result["weather"] = [evaluate(r) for r in result["weather"]]
    for event in result["events"]:
        if event["kind"] in {"hub_delay","closure"}:
            affected=[s["id"] for s in S["ships"].list() if shipment_visits_hub_during(s,event)]
            event["affected_count"]=len(affected)
            event["affected_shipments"]=affected
        elif event["kind"]=="traffic":
            affected=[s["id"] for s in S["ships"].list() if shipment_traffic_exposure_minutes(s,event,pending_only=True)]
            event["affected_count"]=len(affected)
            event["affected_shipments"]=affected
    result["thresholds"] = THRESHOLDS
    return result

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
@serialized
def replan_shipment(sid: str):
    if not S["ships"].get(sid): raise HTTPException(404,"Unknown shipment")
    with LOCK:
        return S["ships"].replan(sid)

@app.post("/api/decisions")
@serialized
def decision(req: DecisionReq):
    with LOCK:
        s=S["ships"].get(req.shipment_id)
        if not s: raise HTTPException(404,"Unknown shipment")
        ops=S["ships"].context_for(s)["operations"]
        if req.revision!=ops.data["revision"]: raise HTTPException(409,"Conditions changed. Recalculate before deciding.")
        if req.option>=len(s["options"]): raise ValueError("Invalid option")
        option=s["options"][req.option]
        if option.get("revision",-1)!=req.revision: raise HTTPException(409,"Recalculate shipment options first")
        if req.quote_id!=option.get("quote_id"): raise HTTPException(409,"Quote replaced. Recalculate and review again.")
        previous_route=list(s["route"])
        if req.action=="accept":
            if option.get("avoidance_status") in {"IMPACTED", "NO_CLEAR_DETOUR"}:
                raise HTTPException(409,"This route crosses an active simulated weather zone. Hold or defer the shipment, or choose a verified clear route.")
            _, warning=S["ships"].schedule(req.shipment_id,req.option,req.acknowledge_deadline,req.quote_id,req.reason.strip())
            if warning: raise HTTPException(409,warning)
        elif req.action=="hold":
            S["ships"].hold(req.shipment_id,req.option,req.reason)
        row=S["operations"].put("decisions",{**req.model_dump(),"path":s["route"],"eta":s["current_eta"],"reviewed_path":option["path"],"reviewed_eta":option["eta"],"data_kind":s.get("data_kind","user"),"previous_route":previous_route})
        _audit("manager_decision",f"{req.shipment_id}: {req.action} — {req.reason}","MANAGER INPUT")
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
                            req.truck.model_dump(), req.transfer_minutes, req.avoid_weather)


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
        "tomtom_masked": f"{key[:4]}...{key[-4:]}" if len(key) > 8 else ("configured" if key else ""),
        "traffic_status": S["providers"].traffic.status(),
        "traffic_mode": "live" if key else "simulated"
    }

@app.post("/api/settings/tomtom")
def update_tomtom_key(req: SettingsTomTomReq):
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
