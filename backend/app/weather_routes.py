"""Geographic, manually simulated weather zones and verified road detours."""
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from .operations import parse

IMPACT_MINUTES = {"snow": 110, "rain": 65, "tornado": 180}
CLEARANCE_KM = 2.0


def active_zones(operations, start, end):
    if not operations:
        return []
    return [z for z in operations.data.get("weather_zones", [])
            if parse(z["start"]) < end and parse(z["end"]) > start]


def _xy(point, center):
    lon, lat = point
    return ((lon-center[0])*111.32*math.cos(math.radians(center[1])),
            (lat-center[1])*111.32)


def _lonlat(x, y, center):
    return [center[0]+x/(111.32*max(.1, math.cos(math.radians(center[1])))),
            center[1]+y/111.32]


def clearance_km(geometry, zone):
    """Minimum center-to-road-segment distance, in the zone's local km plane."""
    if not geometry:
        return -1
    center=(zone["lon"],zone["lat"])
    pts=[_xy(p,center) for p in geometry]
    nearest=math.inf
    for (ax,ay),(bx,by) in zip(pts,pts[1:]):
        dx,dy=bx-ax,by-ay
        t=max(0,min(1,-(ax*dx+ay*dy)/(dx*dx+dy*dy))) if dx*dx+dy*dy else 0
        nearest=min(nearest, math.hypot(ax+t*dx,ay+t*dy))
    return nearest if len(pts)>1 else math.hypot(*pts[0])


def crossed_zones(geometry, zones, margin=0):
    return [z for z in zones if clearance_km(geometry,z)<z["radius_km"]+margin]


def _candidates(a, b, zone):
    center=(zone["lon"],zone["lat"])
    ax,ay=_xy([a[1],a[0]],center); bx,by=_xy([b[1],b[0]],center)
    dx,dy=bx-ax,by-ay; length=math.hypot(dx,dy)
    if length<1:
        return []
    ux,uy=dx/length,dy/length
    px,py=-uy,ux
    # Two waypoint arcs on either side, with a near and wider clearance.
    for side in (1,-1):
        for extra in (9,22):
            r=zone["radius_km"]+extra
            points=[]
            for along in (-r,r):
                lon,lat=_lonlat(ux*along+side*px*r,uy*along+side*py*r,center)
                points.append((lat,lon))
            yield points


def closest_clear_detour(providers, a, b, original, zones, depart, truck):
    """Try nearby waypoint arcs; only return provider road geometry clear of ALL zones."""
    if not original.get("geometry") or not zones:
        return None
    if any(clearance_km([[a[1],a[0]]],z)<z["radius_km"]+CLEARANCE_KM or
           clearance_km([[b[1],b[0]]],z)<z["radius_km"]+CLEARANCE_KM for z in zones):
        return None
    crossed=crossed_zones(original["geometry"],zones,CLEARANCE_KM)
    if not crossed:
        return None
    target=max(crossed,key=lambda z:z["radius_km"]+CLEARANCE_KM-clearance_km(original["geometry"],z))
    candidates=list(_candidates(a,b,target))
    def route(via):
        result=providers.tomtom.route_via(a,b,via,depart,truck) if providers.tomtom.key else None
        result=result or providers.routing.via(a,b,via)
        return result if result and result.get("geometry") and not crossed_zones(result["geometry"],zones,CLEARANCE_KM) else None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(route,candidates))
    verified=[r for r in results if r]
    if not verified:
        return None
    best=min(verified,key=lambda r:(r["distance_km"],r["duration_minutes"]))
    return {**best,"source":best["source"]+" · verified simulated-weather detour"}
