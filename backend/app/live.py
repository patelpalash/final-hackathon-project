"""Cached live forecast and TomTom integrations; credentials never leave backend."""
import math
import os
import time
from datetime import datetime, timedelta, timezone
import httpx
from .weather_rules import evaluate

UTC=timezone.utc

def now(): return datetime.now(UTC)

def condition(code):
    if code in (71,73,75,77,85,86): return "Heavy Snow" if code in (75,86) else "Snow"
    if code in (95,96,99): return "Thunderstorm"
    if code in (45,48): return "Fog"
    if code in (65,67,82): return "Heavy Rain"
    if code in (51,53,55,61,63,66,80,81): return "Rain"
    return "Clear" if code==0 else "Cloudy"

class Forecasts:
    def __init__(self):
        self.cache={}; self.last_success=None; self.error=None; self.retry_after=0
        self.client=httpx.Client(timeout=5)
    def fetch(self, points, times):
        keys=[(round(p[0],3),round(p[1],3)) for p in points]
        missing=list(dict.fromkeys(k for k in keys if k not in self.cache or time.time()-self.cache[k][0]>900))
        if missing and time.time()>=self.retry_after:
            try:
                r=self.client.get("https://api.open-meteo.com/v1/forecast",params={"latitude":",".join(str(k[0]) for k in missing),"longitude":",".join(str(k[1]) for k in missing),"hourly":"temperature_2m,precipitation,snowfall,visibility,wind_speed_10m,weather_code","forecast_days":16,"past_days":1,"timezone":"UTC","timeformat":"unixtime"},timeout=5)
                r.raise_for_status(); payload=r.json(); payload=payload if isinstance(payload,list) else [payload]
                if len(payload)!=len(missing): raise ValueError("Incomplete forecast response")
                for k,item in zip(missing,payload):
                    if not item.get("hourly",{}).get("time"): raise ValueError("Empty forecast")
                    self.cache[k]=(time.time(),item["hourly"])
                self.last_success=now().isoformat(); self.error=None
            except Exception as e: self.error=type(e).__name__; self.retry_after=time.time()+60
        rows=[]
        for index,(key,at) in enumerate(zip(keys,times)):
            cached=self.cache.get(key)
            row={"id":f"wx-{key[0]}-{key[1]}","lat":key[0],"lon":key[1],"source":"Open-Meteo forecast","valid_at":at.isoformat(),"node":"route","name":f"Route sample {index+1}"}
            if not cached: rows.append({**row,"status":"UNAVAILABLE","error":self.error}); continue
            fetched,hourly=cached; ts=at.timestamp(); hour=min(range(len(hourly["time"])),key=lambda i:abs(hourly["time"][i]-ts))
            if abs(hourly["time"][hour]-ts)>3600: rows.append({**row,"status":"OUT_OF_RANGE"});continue
            values={k:v[hour] for k,v in hourly.items() if k!="time"}
            if any(v is None for v in values.values()): rows.append({**row,"status":"UNAVAILABLE"});continue
            valid=datetime.fromtimestamp(hourly["time"][hour],UTC)
            record={**row,"start":valid.isoformat(),"end":(valid+timedelta(hours=1)).isoformat(),"temperature_c":values["temperature_2m"],"condition":condition(values["weather_code"]),"rain_mm":values["precipitation"],"snow_cm":values["snowfall"],"visibility_m":values["visibility"],"wind_kmh":values["wind_speed_10m"],"severity":"LOW"}
            row={**evaluate(record),"source":"Open-Meteo forecast","status":"FORECAST" if time.time()-fetched<=900 else "STALE","fetched_at":datetime.fromtimestamp(fetched,UTC).isoformat(),"valid_at":valid.isoformat()}
            rows.append(row)
        return rows

from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:
    pass

TRANSPARENT_PNG = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82'

class TomTom:
    def __init__(self):
        self.key=os.environ.get("TOMTOM_API_KEY",""); self.cache={}; self.last_success=None; self.error=None; self.retry_after={}
        self.client=httpx.Client(timeout=3.5)
    def set_key(self, new_key: str):
        self.key = (new_key or "").strip()
        self.cache.clear()
        self.error = None
        self.retry_after.clear()
        if self.key:
            os.environ["TOMTOM_API_KEY"] = self.key
        else:
            os.environ.pop("TOMTOM_API_KEY", None)
    def simulate_sections(self, geometry, distance_km):
        if not geometry or len(geometry) < 10 or distance_km < 30:
            return [], 0
        n = len(geometry)
        i0 = int(n * 0.35)
        i1 = min(n, int(n * 0.60))
        if i1 <= i0:
            return [], 0
        delay = min(45, max(12, round(distance_km * 0.08)))
        return [{
            "geometry": geometry[i0:i1+1],
            "delay_minutes": delay,
            "description": "Simulated Autobahn corridor congestion · slow freight movement",
            "source": "Traffic simulation (no TomTom key)"
        }], delay
    def simulate_incidents(self, coords):
        if not coords or len(coords) < 6:
            return []
        n = len(coords)
        pt1 = coords[int(n * 0.38)]
        items = [{
            "id": "sim-inc-1",
            "geometry": {"type": "Point", "coordinates": [pt1[0], pt1[1]]},
            "description": "A81/A6 corridor: Lane reduction & roadwork. Freight queue.",
            "delay_minutes": 18.0,
            "source": "Simulated traffic incident",
            "from": "Km 110",
            "to": "Km 124",
            "end": (now() + timedelta(hours=3)).isoformat()
        }]
        if n > 20:
            pt2 = coords[int(n * 0.72)]
            items.append({
                "id": "sim-inc-2",
                "geometry": {"type": "Point", "coordinates": [pt2[0], pt2[1]]},
                "description": "Interchange node: Slow-moving traffic due to heavy volume.",
                "delay_minutes": 12.0,
                "source": "Simulated traffic incident",
                "from": "Km 215",
                "to": "Km 226",
                "end": (now() + timedelta(hours=2)).isoformat()
            })
        return items
    def get(self, url, params, ttl=120):
        if not self.key or time.time()<self.retry_after.get(url,0): return None
        ck=(url,str(sorted(params.items())))
        if ck in self.cache and time.time()-self.cache[ck][0]<ttl:return self.cache[ck][1]
        if "/routing/" in url and time.time()<self.retry_after.get("routing",0):return None
        try:
            r=self.client.get(url,params={**params,"key":self.key},timeout=3.5 if "/routing/" in url else 5);r.raise_for_status()
            payload=r.json()
            if len(self.cache)>1200: self.cache.clear()
            self.retry_after.pop(url,None)
            self.cache[ck]=(time.time(),payload);self.last_success=now().isoformat();self.error=None
            return payload
        except Exception as e:
            self.error=type(e).__name__;self.retry_after[url]=time.time()+30
            if "/routing/" in url:self._routing_failure(e)
            return None
    def _routing_failure(self, error):
        # Avoid paying the same timeout for every candidate during an outage.
        # A route-specific "no route" response must not disable other searches.
        status=getattr(getattr(error,"response",None),"status_code",None)
        if isinstance(error,(httpx.TimeoutException,httpx.NetworkError)) or status in {401,403,429}:
            self.retry_after["routing"]=time.time()+30
    def route(self,a,b,depart,truck):
        return self.route_via(a,b,[],depart,truck)
    def route_via(self,a,b,via,depart,truck,avoid_areas=None):
        if not self.key:return None
        if depart<now()-timedelta(minutes=5):return None
        params={"traffic":"true","travelMode":"truck","routeType":"fastest","computeTravelTimeFor":"all","sectionType":"traffic","departAt":depart.replace(second=0,microsecond=0).isoformat(),"vehicleHeight":truck["height_m"],"vehicleWidth":truck["width_m"],"vehicleLength":truck["length_m"],"vehicleWeight":truck["gross_weight_kg"],"vehicleMaxSpeed":80}
        stops=":".join(f"{lat},{lon}" for lat,lon in [a,*via,b])
        url=f"https://api.tomtom.com/routing/1/calculateRoute/{stops}/json"
        if avoid_areas:
            rectangles=[]
            for zone in avoid_areas:
                radius=zone["radius_km"]+2.0
                lat_span=radius/111.32
                lon_span=radius/(111.32*max(.1,math.cos(math.radians(zone["lat"]))))
                south,north=zone["lat"]-lat_span,zone["lat"]+lat_span
                west,east=zone["lon"]-lon_span,zone["lon"]+lon_span
                # TomTom limits each rectangle to roughly 160 x 160 km.
                lat_edges=[south,zone["lat"],north] if radius*2>150 else [south,north]
                lon_edges=[west,zone["lon"],east] if radius*2>150 else [west,east]
                for low_lat,high_lat in zip(lat_edges,lat_edges[1:]):
                    for low_lon,high_lon in zip(lon_edges,lon_edges[1:]):
                        rectangles.append({"southWestCorner":{"latitude":low_lat,"longitude":low_lon},
                                           "northEastCorner":{"latitude":high_lat,"longitude":high_lon}})
            if len(rectangles)>10:return None
            body={"avoidAreas":{"rectangles":rectangles}}
            cache_key=(url,str(sorted(params.items())),str(body))
            cached=self.cache.get(cache_key)
            if cached and time.time()-cached[0]<120:doc=cached[1]
            elif time.time()<self.retry_after.get(cache_key,0) or time.time()<self.retry_after.get("routing",0):return None
            else:
                try:
                    response=self.client.post(url,params={**params,"key":self.key},json=body,timeout=3.5)
                    response.raise_for_status();doc=response.json()
                    self.cache[cache_key]=(time.time(),doc);self.last_success=now().isoformat();self.error=None
                except Exception as e:
                    self.error=type(e).__name__;self.retry_after[cache_key]=time.time()+30
                    self._routing_failure(e)
                    return None
        else:
            doc=self.get(url,params)
        if not doc or not doc.get("routes"):return None
        route=doc["routes"][0];summary=route["summary"]
        points=[[p["longitude"],p["latitude"]] for leg in route["legs"] for p in leg["points"]]
        total=math.ceil(summary["travelTimeInSeconds"]/60);delay=min(total,math.ceil(summary.get("trafficDelayInSeconds",0)/60))
        sections=[]
        for s in route.get("sections",[]):
            if s.get("sectionType")=="TRAFFIC":
                sections.append({"geometry":points[s["startPointIndex"]:s["endPointIndex"]+1],"delay_minutes":round(s.get("delayInSeconds",0)/60,1),"description":s.get("simpleCategory","Traffic"),"source":"TomTom"})
        return {"geometry":points,"distance_km":round(summary["lengthInMeters"]/1000,1),"duration_minutes":total,"traffic_minutes":delay,"traffic_sections":sections,"source":"TomTom traffic-aware truck route","fetched_at":self.last_success}
    def incidents(self,coords):
        if not self.key:
            return {"status":"SIMULATED","items":self.simulate_incidents(coords),"fetched_at":now().isoformat()}
        # Request compact tiles of the route corridor, within provider bounding-box limits.
        selected=coords[::max(1,len(coords)//5)][:6]; items={}; failed=False
        for lon,lat in selected:
            bbox=f"{lon-.15},{lat-.1},{lon+.15},{lat+.1}"
            fields="{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,events{description,code},startTime,endTime,from,to,delay}}}"
            doc=self.get("https://api.tomtom.com/traffic/services/5/incidentDetails",{"bbox":bbox,"fields":fields,"language":"en-GB","timeValidityFilter":"present"})
            if doc is None: failed=True
            for item in (doc or {}).get("incidents",[]):
                props=item["properties"];items[props["id"]]={"id":props["id"],"geometry":item["geometry"],"description":"; ".join(e["description"] for e in props.get("events",[])),"delay_minutes":round((props.get("delay") or 0)/60,1),"source":"TomTom","from":props.get("from"),"to":props.get("to"),"end":props.get("endTime")}
        return {"status":"ERROR" if failed else "LIVE","items":list(items.values()),"fetched_at":self.last_success}
    def tile(self,z,x,y):
        if not self.key:
            return TRANSPARENT_PNG
        if time.time()<self.retry_after.get("tiles",0): return None
        ck=("tile",z,x,y);cached=self.cache.get(ck)
        if cached and time.time()-cached[0]<120:return cached[1]
        try:
            r=httpx.get(f"https://api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png",params={"key":self.key,"tileSize":256},timeout=5);r.raise_for_status()
            self.cache[ck]=(time.time(),r.content)
            if len(self.cache)>1200:self.cache={ck:self.cache[ck]}
            return r.content
        except Exception as e:self.error=type(e).__name__;self.retry_after["tiles"]=time.time()+30;return None

DEFAULT_TRUCK={"height_m":4.0,"width_m":2.55,"length_m":16.5,"gross_weight_kg":40000}
