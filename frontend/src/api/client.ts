import type { Service, Performance, NetworkDoc, Hub, Provider, Holiday, AuditEvent, RouteResp, Shipment, Dashboard, SavingsResp, RerouteResp, HighValue, RelationStat, Disruption, OperationalDelay, MapConditions, TruckProfile, Operations, WeatherInput, WeatherRecord, WeatherZoneInput, WeatherZone, ScenarioEvent, Decision, DecisionResult } from "./types";
export const BASE = import.meta.env.VITE_API_BASE ?? "/api";
export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly code?: string) { super(message); }
}
async function req<T>(p: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${p}`, { cache:"no-store", headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let detail = r.statusText, code: string | undefined;
    try { const body = await r.json(); detail = body.detail ?? detail; code = body.code; } catch { /* body may be empty */ }
    throw new ApiError(Array.isArray(detail)?detail.map(x=>x.msg??String(x)).join("; "):String(detail),r.status,code);
  }
  return r.json() as Promise<T>;
}
export const api = {
  transportCalendar:(year:number,month:number,region:string,companyHold:boolean)=>req<import("./types").TransportCalendarDoc>(`/transport-calendar?year=${year}&month=${month}&region=${encodeURIComponent(region)}&company_sunday_hold=${companyHold}`),
  proposeRoute:(id:string,body:{via_hubs:string[];depart_at?:string})=>req<Shipment>(`/shipments/${id}/route-proposal`,{method:"POST",body:JSON.stringify(body)}),
  journeyExamples:()=>req<{examples:import("./types").JourneyExample[]}>("/journey-examples"),
  driverUpdate:(id:string,body:{kind:"departed"|"delay"|"safe_stop"|"arrived";at?:string;reference?:string;minutes?:number;actual_cost_eur?:number})=>req<Shipment>(`/shipments/${id}/driver-update`,{method:"POST",body:JSON.stringify(body)}),
  capacity:()=>req<{records:import("./types").CapacityRecord[]}>("/capacity"),
  saveCapacity:(body:Omit<import("./types").CapacityRecord,"id"|"source">)=>req<import("./types").CapacityRecord>("/capacity",{method:"POST",body:JSON.stringify(body)}),
  removeCapacity:(id:string)=>req(`/capacity/${id}`,{method:"DELETE"}),
  reportPosition:(id:string,body:{lat?:number;lon?:number;progress_percent?:number;source:"MANAGER REPORTED"|"DRIVER REPORTED"|"SIMULATION"|"PLAN ESTIMATE";movement_state:"MOVING"|"STOPPED"})=>req<Shipment>(`/shipments/${id}/position`,{method:"POST",body:JSON.stringify(body)}),
  requestStop:(id:string,reason:string)=>req<Shipment>(`/shipments/${id}/stop-request`,{method:"POST",body:JSON.stringify({reason})}),
  services:()=>req<{services:Service[]}>("/services"),
  saveService:(body:Omit<Service,"id"|"source">)=>req<Service>("/services",{method:"POST",body:JSON.stringify(body)}),
  deleteService:(id:string)=>req(`/services/${id}`,{method:"DELETE"}),
  performance:()=>req<Performance>("/performance"),
  saveOutcome:(id:string,body:{actual_departure:string;actual_arrival:string;actual_cost_eur:number})=>req<Shipment>(`/shipments/${id}/outcome`,{method:"POST",body:JSON.stringify(body)}),
  startDemo:()=>req<Shipment>("/demo/start",{method:"POST"}),
  demoDisruption:(id:string)=>req<Shipment>(`/demo/${id}/disruption`,{method:"POST"}),
  mapConditions: (geometry:number[][], at:string, signal?: AbortSignal) => req<MapConditions>("/map-conditions",{method:"POST",body:JSON.stringify({geometry,at}),signal}),
  operations: () => req<Operations>("/operations"),
  controlRoom: () => req<{ shipments: Shipment[]; operations: Operations }>("/control-room"),
  addWeatherZone:(body:WeatherZoneInput)=>req<WeatherZone>("/weather-zones",{method:"POST",body:JSON.stringify(body)}),
  updateWeatherZone:(id:string,body:WeatherZoneInput)=>req<WeatherZone>(`/weather-zones/${id}`,{method:"PUT",body:JSON.stringify(body)}),
  deleteWeatherZone:(id:string)=>req<{ok:boolean}>(`/weather-zones/${id}`,{method:"DELETE"}),
  assumptions: () => req<{title: string; items: {title:string; detail:string}[]}>("/assumptions"),
  saveWeather: (body: WeatherInput, id?: string) => req<WeatherRecord>(id ? `/weather-records/${id}` : "/weather-records", {method: id ? "PUT" : "POST", body: JSON.stringify(body)}),
  deleteWeather: (id: string) => req(`/weather-records/${id}`, {method:"DELETE"}),
  addEvent: (body: Omit<ScenarioEvent,"id">) => req<ScenarioEvent>("/events", {method:"POST",body:JSON.stringify(body)}),
  resolveEvent: (id: string) => req(`/events/${id}`, {method:"DELETE"}),
  replan: (id: string) => req<Shipment>(`/shipments/${id}/replan?from_now=true`, {method:"POST"}),
  decide: (body: {shipment_id:string; action:string; option:number; revision:number; quote_id:string; reason:string; acknowledge_deadline:boolean;supersedes_decision_id?:string;supersedes_updated_at?:string;decided_by?:string;request_id?:string}) => req<DecisionResult>("/decisions", {method:"POST", body:JSON.stringify(body),signal:body.request_id?AbortSignal.timeout(30_000):undefined}),
  editDecision: (id:string,body:{reason:string;expected_updated_at:string})=>req<Decision>(`/decisions/${id}`,{method:"PATCH",body:JSON.stringify(body)}),
  network: () => req<NetworkDoc>("/network"),
  hubs: () => req<{ hubs: Hub[] }>("/hubs"),
  providers: () => req<{ providers: Provider[] }>("/providers"),
  holidays: () => req<{ source: string; upcoming: Holiday[]; count: number }>("/holidays"),
  audit: () => req<{ events: AuditEvent[] }>("/audit"),
  dashboard: () => req<Dashboard>("/dashboard"),
  savings: (scope:"estimated"|"demo"="estimated") => req<SavingsResp>(`/savings?scope=${scope}`),
  savingsScenarios: (lane: string, reserve: number, objective: import("./types").SavingsScenarioObjective) =>
    req<import("./types").SavingsScenarios>(`/savings/scenarios?${new URLSearchParams({lane, reserve: String(reserve), objective})}`),
  recalculateSavings: () => req<SavingsResp>("/savings/recalculate", { method: "POST" }),
  simulateReroute: (body: { lat: number; lon: number; destination: string; via?: string; depart_at?: string; truck?: TruckProfile; transfer_minutes?: number; avoid_weather?: boolean; avoid_points?: {lat:number;lon:number;radius_km:number}[] }) =>
    req<RerouteResp>("/simulate/reroute", { method: "POST", body: JSON.stringify(body) }),
  highValue: () => req<{ shipments: HighValue[] }>("/high-value"),
  relations: () => req<{ relations: RelationStat[] }>("/analytics/relations"),
  disruptions: () => req<{ active_operational: unknown[]; historical: Disruption[] }>("/disruptions"),
  route: (body: { origin: string; destination: string; depart_at?: string; weight_kg?: number; required_delivery?: string; value_eur?: number; optimization?:string; truck?:TruckProfile; sample_id?:string; sample_weather?:boolean;via_hubs?:string[];planning_rules?:import("./types").PlanningRules }) =>
    req<RouteResp>("/route", { method: "POST", body: JSON.stringify(body) }),
  shipments: (q = "") => req<{ shipments: Shipment[] }>(`/shipments${q}`),
  shipment: (id: string) => req<Shipment>(`/shipments/${id}`),
  createShipment: (body: Record<string, unknown>) => req<Shipment>("/shipments", { method: "POST", body: JSON.stringify(body) }),
  scheduleShipment: (id: string, option = 0, force = false) =>
    req<{ scheduled: boolean; warning?: string; shipment: Shipment }>(`/shipments/${id}/schedule?option=${option}&force=${force}`, { method: "POST" }),
  setStatus: (id: string, status: string) => req<{ ok: boolean }>(`/shipments/${id}/status?status=${status}`, { method: "POST" }),
  setDelay: (id: string, body: { minutes: number; reason: string; note?: string }) =>
    req<{ ok: boolean; delay: OperationalDelay }>(`/hubs/${id}/delay`, { method: "POST", body: JSON.stringify(body) }),
  clearDelay: (id: string) => req<{ ok: boolean }>(`/hubs/${id}/delay`, { method: "DELETE" }),
  settings: () => req<import("./types").AppSettings>("/settings"),
  setTomTomKey: (key: string) => req<{ ok: boolean; tomtom_configured: boolean; traffic_mode: string }>("/settings/tomtom", { method: "POST", body: JSON.stringify({ key }) }),
};
