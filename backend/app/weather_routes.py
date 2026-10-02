"""Geographic, manually simulated weather zones and verified road detours."""
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from .operations import parse

IMPACT_MINUTES = {"snow": 110, "rain": 65, "tornado": 180}
CLEARANCE_KM = 2.0
LOCAL_BUFFER_KM = 8.0
SEARCH_BUDGET_SECONDS = 15.0


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


def _distance_km(a, b):
    lat=(a[1]+b[1])/2
    return math.hypot((b[0]-a[0])*111.32*math.cos(math.radians(lat)),(b[1]-a[1])*111.32)


def _route_length(geometry):
    return sum(_distance_km(a,b) for a,b in zip(geometry,geometry[1:]))


def _point_at(geometry, distance):
    if not geometry:
        return None
    if distance<=0:
        return list(geometry[0])
    walked=0.0
    for a,b in zip(geometry,geometry[1:]):
        segment=_distance_km(a,b)
        if walked+segment>=distance:
            ratio=max(0,min(1,(distance-walked)/(segment or 1)))
            return [a[0]+(b[0]-a[0])*ratio,a[1]+(b[1]-a[1])*ratio]
        walked+=segment
    return list(geometry[-1])


def _slice_route(geometry, start, end):
    total=_route_length(geometry)
    start=max(0,min(total,start)); end=max(start,min(total,end))
    out=[_point_at(geometry,start)]
    walked=0.0
    for a,b in zip(geometry,geometry[1:]):
        walked+=_distance_km(a,b)
        if start+1e-6<walked<end-1e-6:
            out.append(list(b))
    last=_point_at(geometry,end)
    if last and _distance_km(out[-1],last)>1e-5:
        out.append(last)
    return out


def _zone_interval(geometry, zone, radius):
    """Return the route-distance interval inside a zone plus its clearance margin."""
    center=(zone["lon"],zone["lat"])
    walked=0.0; first=math.inf; last=-math.inf
    for p1,p2 in zip(geometry,geometry[1:]):
        ax,ay=_xy(p1,center); bx,by=_xy(p2,center)
        dx,dy=bx-ax,by-ay; length=math.hypot(dx,dy)
        if length<1e-6:
            continue
        projection=-(ax*dx+ay*dy)/(length*length)
        nearest_sq=(ax+projection*dx)**2+(ay+projection*dy)**2
        road_length=_distance_km(p1,p2)
        if nearest_sq<=radius*radius:
            half=math.sqrt(max(0,radius*radius-nearest_sq))/length
            lo=max(0,projection-half); hi=min(1,projection+half)
            if lo<=hi:
                first=min(first,walked+lo*road_length)
                last=max(last,walked+hi*road_length)
        walked+=road_length
    return None if not math.isfinite(first) else (first,last)


def _candidate_waypoints(a, b, zone, side, extra):
    center=(zone["lon"],zone["lat"])
    ax,ay=_xy([a[1],a[0]],center); bx,by=_xy([b[1],b[0]],center)
    dx,dy=bx-ax,by-ay; length=math.hypot(dx,dy)
    if length<1:
        return []
    ux,uy=dx/length,dy/length
    px,py=-uy,ux
    r=zone["radius_km"]+CLEARANCE_KM+extra
    points=[]
    for along in (-r,r):
        lon,lat=_lonlat(ux*along+side*px*r,uy*along+side*py*r,center)
        points.append((lat,lon))
    return points


def _distance_to_line(point, geometry):
    center=(point[0],point[1])
    px,py=_xy([point[0],point[1]],center)
    best=math.inf
    for a,b in zip(geometry,geometry[1:]):
        ax,ay=_xy(a,center); bx,by=_xy(b,center)
        dx,dy=bx-ax,by-ay
        t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy or 1)))
        best=min(best,math.hypot(px-(ax+t*dx),py-(ay+t*dy)))
    if len(geometry)==1:
        gx,gy=_xy(geometry[0],center); best=math.hypot(px-gx,py-gy)
    return best


def _join_lines(*lines):
    result=[]
    for line in lines:
        for point in line or []:
            if not result or _distance_km(result[-1],point)>1e-5:
                result.append(list(point))
    return result


def _road_vertex(geometry, distance, after=False):
    """Use a real routed vertex for a divergence or rejoin point."""
    walked=0.0
    previous=geometry[0]
    for a,b in zip(geometry,geometry[1:]):
        next_km=walked+_distance_km(a,b)
        if next_km>=distance:
            return (list(b),next_km) if after else (list(previous),walked)
        walked=next_km
        previous=b
    return list(geometry[-1]),walked


def _corridor_waypoints(start, end, zones, side, extra):
    """Waypoints around the combined hazard envelope, not just the first storm.

    They are router inputs only. Returned road geometry must still pass every
    zone and connection check; no straight waypoint connectors are published.
    """
    center=((start[0]+end[0])/2,(start[1]+end[1])/2)
    ax,ay=_xy(start,center); bx,by=_xy(end,center)
    length=math.hypot(bx-ax,by-ay)
    if length<1:return []
    ux,uy=(bx-ax)/length,(by-ay)/length
    px,py=-uy,ux
    bounds=[]
    for z in zones:
        x,y=_xy([z["lon"],z["lat"]],center)
        along,across=x*ux+y*uy,x*px+y*py
        radius=z["radius_km"]+CLEARANCE_KM
        # Include hazards near the bypass as well as those on the original road.
        if abs(along)<=length/2+radius+extra and abs(across)<=radius+80+extra:
            bounds.append((along-radius,along+radius,across-radius,across+radius))
    if not bounds:return []
    lo=max(-length/2,min(v[0] for v in bounds)-extra)
    hi=min(length/2,max(v[1] for v in bounds)+extra)
    offset=max(v[3] for v in bounds)+extra if side>0 else min(v[2] for v in bounds)-extra
    points=[_lonlat(ux*t+px*offset,uy*t+py*offset,center) for t in (lo,hi)]
    if any(clearance_km([p],z)<z["radius_km"]+CLEARANCE_KM for p in points for z in zones):return []
    return [(p[1],p[0]) for p in points]


def closest_clear_detour(providers, a, b, original, zones, depart, truck):
    """Bounded local-to-wide road search; ALL hazards stay active in every trial."""
    geometry=original.get("geometry")
    if not geometry or len(geometry)<2 or not zones:return None
    if any(clearance_km([[p[1],p[0]]],z)<z["radius_km"]+CLEARANCE_KM
           for p in (a,b) for z in zones):return None
    intervals=[interval for z in zones
               if (interval:=_zone_interval(geometry,z,z["radius_km"]+CLEARANCE_KM))]
    if not intervals:return original
    first=min(i[0] for i in intervals); last=max(i[1] for i in intervals)
    total_km=_route_length(geometry)
    trials=0
    deadline=time.monotonic()+SEARCH_BUDGET_SECONDS
    seen=set()
    # First try a nearby divergence/rejoin. Then progressively widen, including
    # the full road leg as a last resort instead of giving up after two paths.
    for buffer,extra in ((LOCAL_BUFFER_KM,8),(30,22),(75,45),(total_km,70)):
        if time.monotonic()>=deadline:break
        start,start_km=_road_vertex(geometry,max(0,first-buffer))
        end,end_km=_road_vertex(geometry,min(total_km,last+buffer),after=True)
        if end_km-start_km<1:continue
        if any(clearance_km([p],z)<z["radius_km"]+CLEARANCE_KM+.2
               for p in (start,end) for z in zones):continue
        local_a,local_b=(start[1],start[0]),(end[1],end[0])
        local_depart=depart+timedelta(minutes=original.get("duration_minutes",0)*start_km/max(1,total_km))
        segment=_slice_route(geometry,start_km,end_km)
        # Provider traffic sections are slices of this original road. Vertex
        # membership avoids a quadratic point-to-every-road-segment scan.
        removed_vertices={(round(p[0],5),round(p[1],5)) for p in segment}
        retained_sections=[s for s in original.get("traffic_sections",[])
                           if not any((round(p[0],5),round(p[1],5)) in removed_vertices
                                      for p in s.get("geometry",[]))]
        prefix=_slice_route(geometry,0,start_km); suffix=_slice_route(geometry,end_km,total_km)
        fraction=min(1,(end_km-start_km)/max(1,total_km))
        old_km=original.get("distance_km",total_km)*fraction

        def verify(detour):
            if not detour:return None
            line=detour.get("geometry")
            if not line or len(line)<2 or crossed_zones(line,zones,CLEARANCE_KM):return None
            if _distance_km(start,line[0])>.3 or _distance_km(end,line[-1])>.3:return None
            if detour.get("distance_km",0)<=0 or detour.get("duration_minutes",0)<=0:return None
            combined=_join_lines(prefix,line,suffix)
            if crossed_zones(combined,zones,CLEARANCE_KM):return None
            extra_km=detour["distance_km"]-old_km
            sections=retained_sections+detour.get("traffic_sections",[])
            info={"original_segment":segment,"detour_segment":line,
                  "divert_at":start,"rejoin_at":end,"extra_km":round(extra_km,1)}
            return {**original,"geometry":combined,
                    "distance_km":round(original.get("distance_km",total_km)+extra_km,1),
                    "duration_minutes":max(1,round(original.get("duration_minutes",0)*(1-fraction)+detour["duration_minutes"])),
                    "traffic_minutes":round(original.get("traffic_minutes",0)*(1-fraction)+detour.get("traffic_minutes",0)),
                    "traffic_sections":sections,"weather_detour":info,"weather_detours":[info],
                    "source":detour.get("source","road route")+" · road-network weather avoidance"}

        tomtom=getattr(providers,"tomtom",None)
        window=(tuple(start),tuple(end))
        if tomtom and tomtom.key and window not in seen:
            seen.add(window);trials+=1
            verified=verify(tomtom.route_via(local_a,local_b,[],local_depart,truck,avoid_areas=zones))
            if verified:
                verified["weather_search"]={"zones_checked":len(zones),"candidates_checked":trials}
                return verified
        # An unsafe or missing provider result is NOT a successful detour.
        # Test both sides, then wider waypoints on the next pass. Prefer truck
        # routing when configured; use OSRM only when that request is unavailable.
        waypoints=[via for side in (1,-1)
                   if (via:=_corridor_waypoints(start,end,zones,side,extra))]
        def route(via):
            road=tomtom.route_via(local_a,local_b,via,local_depart,truck,avoid_areas=zones) if tomtom and tomtom.key else None
            checked=verify(road)
            return checked or verify(providers.routing.via(local_a,local_b,via))
        if not waypoints or time.monotonic()>=deadline:continue
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(route,waypoints))
        trials+=len(results)
        verified=[r for r in results if r]
        if verified:
            best=min(verified,key=lambda r:(r["duration_minutes"],r["distance_km"]))
            best["weather_search"]={"zones_checked":len(zones),"candidates_checked":trials}
            return best
    # This is a bounded search, not proof that every road in the world is shut.
    return None
