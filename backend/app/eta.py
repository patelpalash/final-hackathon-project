"""One ETA engine shared by route search, saved shipments and manager replanning."""
import math
from datetime import timedelta
from .restrictions import drive_with_restrictions
from .weekend import hub_release
from .weather_rules import at_hub
from .operations import parse
from .live import DEFAULT_TRUCK
from .schedules import next_departure
from .weather_routes import active_zones, crossed_zones, closest_clear_detour, IMPACT_MINUTES, CLEARANCE_KM

def _haversine_km(a,b):
    dlat=math.radians(b[0]-a[0]); dlon=math.radians(b[1]-a[1])
    x=math.sin(dlat/2)**2+math.cos(math.radians(a[0]))*math.cos(math.radians(b[0]))*math.sin(dlon/2)**2
    return 12742*math.asin(min(1,math.sqrt(x)))

def compute_journey(network, holidays, transfer, hub_delays, providers, origin, dest, depart_utc, path=None, operations=None, truck=None, avoid_zones=False):
    path = path or [origin,dest]
    applied_global_traffic=set()
    rows=[]; cur=depart_utc; geometry=[]; all_geometry=True; leg_data=[]; alerts=[]; forecasts=[]; traffic_sections=[]; services=[]; zone_impacts=[]; weather_detours=[]; detour_km=0
    comp={k:0 for k in ("transport","transfer","hub_delay","traffic","legal_wait","weekend_hold","weather","schedule_wait")}
    def add(kind,loc,start,end,detail,source):
        rows.append({"type":kind,"location":loc,"location_name":network["nodes"][loc]["name"],"start":start.isoformat(),"end":end.isoformat(),"minutes":round((end-start).total_seconds()/60),"detail":detail,"source":source})
    for i,(a,b) in enumerate(zip(path,path[1:])):
        na,nb=network["nodes"][a],network["nodes"][b]
        arrival=cur
        h=transfer.get(na.get("relation"),{}).get("avg_transfer_minutes",120)
        add("handling",a,cur,cur+timedelta(minutes=h),"Loading & handling" if i==0 else "Intermediate hub transfer","Historical proxy / 120-minute baseline")
        comp["transfer"]+=h; cur+=timedelta(minutes=h)
        release=hub_release(arrival,cur,intermediate=i>0)
        if release>cur:
            add("weekend_hold",a,cur,release,"Weekend Hold · Sunday — no movement. Next eligible movement: Monday; calendar restrictions still apply.","BUSINESS POLICY")
            comp["weekend_hold"]+=round((release-cur).total_seconds()/60); cur=release
        hd=hub_delays.get(a)
        if hd and hd.get("minutes",0)>0:
            end=cur+timedelta(minutes=hd["minutes"]); add("hub_delay",a,cur,end,hd.get("reason","Hub congestion"),"MANAGER INPUT"); comp["hub_delay"]+=hd["minutes"]; cur=end
        schedules=operations.data.get("schedules",[]) if operations else []
        events=operations.data["events"] if operations else []
        # A timed hub delay applies to every visit overlapping its effective
        # window, including trucks already handling or waiting for a service.
        planned_departure,_=next_departure(cur,a,b,schedules,holidays,events)
        visit_end=max(cur+timedelta(minutes=1),planned_departure)
        if operations:
            for ev in events:
                if ev["kind"]!="hub_delay" or ev.get("node")!=a or not operations.overlaps(ev,arrival,visit_end): continue
                end=cur+timedelta(minutes=ev["minutes"])
                add("hub_delay",a,cur,end,ev["reason"],"MANAGER HUB EVENT")
                comp["hub_delay"]+=ev["minutes"]; cur=end
        # Forecast at the expected service departure; readiness includes the cutoff buffer.
        expected,service=next_departure(cur,a,b,schedules,holidays,events)
        routing_start=expected
        road=providers.tomtom.route((na["lat"],na["lon"]),(nb["lat"],nb["lon"]),routing_start,truck or DEFAULT_TRUCK) if hasattr(providers,"tomtom") else None
        road=dict(road or providers.routing.leg((na["lat"],na["lon"]),(nb["lat"],nb["lon"])))
        original_road=road
        estimated_minutes=max(1,road.get("duration_minutes",60),math.ceil(road.get("distance_km",0)/65*60))
        estimated_arrival=drive_with_restrictions(routing_start,estimated_minutes,holidays)["arrival"]
        zones=active_zones(operations,routing_start,estimated_arrival)
        hit=crossed_zones(road.get("geometry"),zones,CLEARANCE_KM)
        if avoid_zones and hit:
            # Longer detours can overlap a second storm's effective window.
            # Add those constraints and search again, without forgetting old ones.
            while True:
                road=closest_clear_detour(providers,(na["lat"],na["lon"]),(nb["lat"],nb["lon"]),original_road,zones,routing_start,truck or DEFAULT_TRUCK)
                if not road: raise ValueError("No verified road detour clears the simulated weather zones")
                end=drive_with_restrictions(routing_start,max(road["duration_minutes"],math.ceil(road["distance_km"]/65*60)),holidays)["arrival"]
                added=[z for z in active_zones(operations,routing_start,end) if z["id"] not in {v["id"] for v in zones}]
                if not added:break
                zones.extend(added)
            detour_km+=max(0,road["distance_km"]-original_road["distance_km"])
            for detour in road.get("weather_detours",[road["weather_detour"]] if road.get("weather_detour") else []):
                weather_detours.append({"from":a,"to":b,**detour})
        elif avoid_zones and not road.get("geometry"):
            raise ValueError("Road geometry unavailable; a clear detour cannot be verified")
        elif hit:
            zone_impacts.extend({"id":z["id"],"kind":z["kind"],"radius_km":z["radius_km"],"delay_minutes":IMPACT_MINUTES[z["kind"]]} for z in hit)
        km=road.get("distance_km") or round(_haversine_km((na["lat"],na["lon"]),(nb["lat"],nb["lon"]))*1.25,1)
        if hasattr(providers, "tomtom") and not getattr(providers.tomtom, "key", "") and road.get("geometry") and not road.get("traffic_sections"):
            sim_sec, sim_del = providers.tomtom.simulate_sections(road["geometry"], km)
            if sim_sec:
                road["traffic_sections"] = sim_sec
                road["traffic_minutes"] = sim_del
        # OSRM is a car-profile estimate; conservative 65 km/h prototype floor.
        drive=road["duration_minutes"]-road.get("traffic_minutes",0) if "traffic_minutes" in road else max(road.get("duration_minutes",0),math.ceil(km/65*60))
        geometry_start=len(geometry); section_start=len(traffic_sections)
        traffic_sections.extend(road.get("traffic_sections",[]))
        src=road.get("source","estimated fallback")
        if road.get("geometry"): geometry.extend(road["geometry"])
        else: all_geometry=False
        leg_data.append({"from":a,"to":b,"km":km,"source":src})
        live=[]
        if hasattr(providers,"forecasts") and road.get("geometry"):
            coords=road["geometry"]
            fractions=[0,.5,1]
            points=[tuple(reversed(coords[round((len(coords)-1)*f)])) for f in fractions]
            times=[drive_with_restrictions(routing_start,max(1,round((drive+road.get("traffic_minutes",0))*f)),holidays)["arrival"] for f in fractions]
            live=providers.forecasts.fetch(points,times)
            forecasts.extend(live)
        if operations:
            observations=at_hub(operations,a,routing_start)
            observations += at_hub(operations,b,routing_start,routing_start+timedelta(minutes=drive))
            active=[r for r in observations if r["alert"]]+[r for r in live if r.get("alert") and r["status"]=="FORECAST"]
            if active:
                # Use the worst observation per leg, not the sum of duplicate records.
                worst=max(active,key=lambda r:r["delay_minutes"]); delay=worst["delay_minutes"]
                end=cur+timedelta(minutes=delay); add("weather",a,cur,end,worst["message"],worst["source"]+" · estimated weather impact"); comp["weather"]+=delay; cur=end
                alerts.extend(active)
        if hit and not avoid_zones:
            delay=max(IMPACT_MINUTES[z["kind"]] for z in hit)
            end=cur+timedelta(minutes=delay)
            kinds=", ".join(sorted({z["kind"] for z in hit}))
            add("weather",a,cur,end,f"Simulated {kinds} zone crosses this road leg · +{delay}m assumed", "MANUAL MAP SIMULATION")
            comp["weather"]+=delay;cur=end
        for _ in range(len(events)+1):
            closures=[e for e in events if e["kind"]=="closure" and e.get("node")==a and parse(e["start"])<=cur<parse(e["end"])]
            if not closures: break
            end=max(parse(e["end"]) for e in closures)
            add("hub_delay",a,cur,end,"Departure facility closed: "+"; ".join(e["reason"] for e in closures),"MANAGER CLOSURE")
            comp["hub_delay"]+=round((end-cur).total_seconds()/60); cur=end
        departure,service=next_departure(cur,a,b,schedules,holidays,events)
        if service:
            services.append({"service_id":service.get("id"),"from":a,"to":b,"departure":departure.isoformat(),"source":service["source"]})
            if departure>cur:
                add("schedule_wait",a,cur,departure,f"Next service {service['departure_time']} {service['timezone']} · cutoff {service['cutoff_minutes']}m",service["source"])
                comp["schedule_wait"]+=round((departure-cur).total_seconds()/60)
            cur=departure
        # If weather preparation missed the service, use the new departure's traffic estimate.
        if cur!=routing_start and not hit and not avoid_zones and hasattr(providers,"tomtom") and providers.tomtom.key:
            fresh=providers.tomtom.route((na["lat"],na["lon"]),(nb["lat"],nb["lon"]),cur,truck or DEFAULT_TRUCK)
            if fresh:
                road=fresh; drive=fresh["duration_minutes"]-fresh.get("traffic_minutes",0)
                km=fresh["distance_km"]; src=fresh["source"]
                geometry[geometry_start:]=fresh.get("geometry",[])
                traffic_sections[section_start:]=fresh.get("traffic_sections",[])
                leg_data[-1]={"from":a,"to":b,"km":km,"source":src}
                all_geometry=all_geometry and bool(fresh.get("geometry"))
        traffic=road.get("traffic_minutes",0)  # already separated from provider total; count once
        if operations:
            for ev in operations.data["events"]:
                if ev["kind"]!="traffic" or not operations.overlaps(ev,cur,cur+timedelta(minutes=drive)): continue
                is_global=not ev.get("origin") and not ev.get("destination")
                matches_corridor=ev.get("origin")==a and ev.get("destination")==b
                if is_global and ev.get("id") in applied_global_traffic: continue
                if is_global or matches_corridor:
                    traffic+=ev["minutes"]
                    if is_global: applied_global_traffic.add(ev.get("id"))
                    if road.get("geometry"):
                        g = road["geometry"]
                        g0 = max(0, int(len(g) * 0.15))
                        g1 = min(len(g), int(len(g) * 0.85))
                        if g1 > g0:
                            traffic_sections.append({
                                "geometry": g[g0:g1],
                                "delay_minutes": ev["minutes"],
                                "description": ev.get("reason", "Corridor congestion (Scenario Studio)"),
                                "source": "Scenario Studio (simulated)"
                            })
        comp["traffic"]+=traffic
        leg=drive_with_restrictions(cur,drive+traffic,holidays)
        final_hits=crossed_zones(road.get("geometry"),active_zones(operations,cur,leg["arrival"]),CLEARANCE_KM)
        if final_hits:
            if avoid_zones:
                raise ValueError("A weather zone overlaps the updated passage time; no clear itinerary can be verified")
            zone_impacts.extend({"id":z["id"],"kind":z["kind"],"radius_km":z["radius_km"],"delay_minutes":IMPACT_MINUTES[z["kind"]]} for z in final_hits)
        t=cur
        for pause in leg["pauses"]:
            if pause["start"]>t: add("drive",a,t,pause["start"],f"{na['name']} → {nb['name']} · {km} km"+(f" · +{traffic}m traffic" if traffic else ""),src)
            kind="weekend_hold" if "Weekend Hold" in pause["reason"] else "legal_wait"
            # A pause after driving is roadside, not falsely shown as still at the hub.
            add(kind,a,pause["start"],pause["end"],pause["reason"]+(" · safe stopping point en route" if pause["start"]>cur else " · at departure station"),"BUSINESS POLICY" if kind=="weekend_hold" else "CALENDAR RULE (prototype)")
            comp[kind]+=pause["minutes"]; t=pause["end"]
        if leg["arrival"]>t: add("drive",a,t,leg["arrival"],f"{na['name']} → {nb['name']} · {km} km"+(f" · +{traffic}m traffic" if traffic else ""),src)
        cur=leg["arrival"]; comp["transport"]+=drive
        # A closed destination cannot receive the shipment; wait outside the facility.
        for _ in range(len(events)+1):
            closures=[e for e in events if e["kind"]=="closure" and e.get("node")==b and parse(e["start"])<=cur<parse(e["end"])]
            if not closures: break
            end=max(parse(e["end"]) for e in closures)
            add("hub_delay",b,cur,end,"Facility closed · safe waiting outside destination: "+"; ".join(e["reason"] for e in closures),"MANAGER CLOSURE")
            comp["hub_delay"]+=round((end-cur).total_seconds()/60); cur=end
        # Completion at the final facility includes an active receiving delay.
        if operations and b==dest:
            for ev in events:
                if ev["kind"]!="hub_delay" or ev.get("node")!=b or not operations.overlaps(ev,cur,cur+timedelta(minutes=1)): continue
                end=cur+timedelta(minutes=ev["minutes"])
                add("hub_delay",b,cur,end,ev["reason"],"MANAGER HUB EVENT")
                comp["hub_delay"]+=ev["minutes"]; cur=end
    return {"origin":origin,"destination":dest,"path":path,"depart_at":depart_utc.isoformat(),"eta":cur.isoformat(),
            "zone_impacts":list({z["id"]:z for z in zone_impacts}.values()),"weather_detours":weather_detours,"avoidance_status":"CLEAR" if avoid_zones else "IMPACTED" if zone_impacts else "NO_ZONE", "detour_km":round(detour_km,1),
            "scheduled_services":services,"total_minutes":round((cur-depart_utc).total_seconds()/60),"components":comp,"steps":rows,
            "geometry":geometry if all_geometry else None,"road_legs":leg_data,"weather_alerts":list({r["id"]:r for r in alerts}.values()),"live_weather":forecasts,"traffic_sections":traffic_sections,"traffic_status":"LIVE_OR_PREDICTED" if any("TomTom" in l["source"] for l in leg_data) else ("SIMULATED" if traffic_sections or any(l.get("traffic_sections") for l in [road]) else ("NOT_CONFIGURED" if not getattr(getattr(providers,"tomtom",None),"key",None) else "UNAVAILABLE")),
            "data_sources":{"transport":" + ".join(sorted({l["source"] for l in leg_data})),"transfer":"disposition.csv derived proxy","weather":"Open-Meteo forecasts + manual samples; impact is a prototype rule","weekend":"Full Sunday business hold","traffic":providers.traffic.status()}}
