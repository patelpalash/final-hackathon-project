"""
Re-route from a live position.

The journey simulator drives a vehicle along the geometry the planner already
returned. When a blockage appears ahead, the frontend asks this module for a
REAL road route from wherever the vehicle currently is — optionally via an
intermediate facility — instead of drawing an invented detour.

Routing comes from the same providers the planner uses (TomTom truck routing
when a key is configured, OSRM otherwise). If neither answers, the caller is
told so explicitly and falls back to a clearly-labelled straight connector.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from .eta import _haversine_km
from .live import DEFAULT_TRUCK

# Conservative prototype floor, identical to the planner's OSRM handling.
FLOOR_KMH = 65.0


def _leg(providers, a, b, depart, truck):
    """One road leg with geometry. Returns a dict with a status we can be honest about."""
    road = None
    if getattr(providers, "tomtom", None) is not None and getattr(providers.tomtom, "key", ""):
        road = providers.tomtom.route(a, b, depart, truck or DEFAULT_TRUCK)
    road = road or providers.routing.leg(a, b)
    if not road or not road.get("geometry"):
        km = round(_haversine_km(a, b) * 1.25, 1)
        return {"geometry": None, "distance_km": km,
                "duration_minutes": max(1, math.ceil(km / FLOOR_KMH * 60)),
                "source": "Straight-line fallback — routing unavailable", "routed": False}
    km = road.get("distance_km") or round(_haversine_km(a, b) * 1.25, 1)
    drive = road.get("duration_minutes", 0)
    if "traffic_minutes" in road:
        drive = drive - road.get("traffic_minutes", 0)
    minutes = max(drive, math.ceil(km / FLOOR_KMH * 60))
    return {"geometry": road["geometry"], "distance_km": round(km, 1),
            "duration_minutes": max(1, round(minutes)),
            "traffic_minutes": road.get("traffic_minutes", 0),
            "traffic_sections": road.get("traffic_sections", []),
            "source": road.get("source", "road estimate"), "routed": True}


def reroute(ctx, lat, lon, destination, via=None, depart=None, truck=None, transfer_minutes=0):
    """
    Road route from (lat, lon) to `destination`, optionally through facility `via`.

    Returns geometry stitched across the legs plus the driving time, so the
    simulator can continue the animation on genuine road geometry.
    """
    net = ctx["network"]
    if destination not in net["nodes"]:
        raise ValueError("Unknown destination facility")
    if via is not None and via not in net["nodes"]:
        raise ValueError("Unknown intermediate facility")
    if not (-85 <= lat <= 85 and -180 <= lon <= 180):
        raise ValueError("Invalid current position")

    depart = depart or datetime.now(timezone.utc)
    here = (lat, lon)
    waypoints = [here]
    if via:
        waypoints.append((net["nodes"][via]["lat"], net["nodes"][via]["lon"]))
    waypoints.append((net["nodes"][destination]["lat"], net["nodes"][destination]["lon"]))

    geometry, legs, minutes, km, clock = [], [], 0, 0.0, depart
    for a, b in zip(waypoints, waypoints[1:]):
        leg = _leg(ctx["providers"], a, b, clock, truck)
        legs.append({k: leg[k] for k in ("distance_km", "duration_minutes", "source", "routed")})
        if leg["geometry"]:
            # Avoid duplicating the shared waypoint between consecutive legs.
            geometry.extend(leg["geometry"][1:] if geometry else leg["geometry"])
        minutes += leg["duration_minutes"]
        km += leg["distance_km"]
        clock = clock + timedelta(minutes=leg["duration_minutes"])

    # A transfer at the intermediate facility is real dwell time, not driving.
    hold = round(transfer_minutes) if via else 0
    routed = all(l["routed"] for l in legs)
    return {
        "status": "ROUTED" if routed else "PARTIAL" if any(l["routed"] for l in legs) else "UNAVAILABLE",
        "geometry": geometry or None,
        "distance_km": round(km, 1),
        "drive_minutes": round(minutes),
        "hold_minutes": hold,
        "total_minutes": round(minutes) + hold,
        "eta": (depart + timedelta(minutes=round(minutes) + hold)).isoformat(),
        "via": via,
        "legs": legs,
        "source": " + ".join(sorted({l["source"] for l in legs})),
        "note": "Live re-route computed from the vehicle's current position using the same routing providers as the "
                "planner. Holds, weekend rules and calendar restrictions beyond the intermediate transfer are not "
                "re-applied here; approve the shipment in the control room for a full re-plan.",
    }
