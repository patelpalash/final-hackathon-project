import "./dispatch.css";
import { useEffect, useRef, useState } from "react";
import { Truck, Route, PiggyBank, BarChart3, RefreshCw, ShieldCheck, CloudSun, ArrowUpRight, Activity } from "lucide-react";
import { api } from "./api/client";
import type { NetworkDoc, Provider, Operations, Shipment } from "./api/types";
import { statusClass } from "./lib";
import { Shipments } from "./views/Shipments";
import { Planner } from "./views/Planner";
import { Savings } from "./views/Savings";
import { Analytics } from "./views/Analytics";
import { ControlRoom } from "./views/ControlRoom";
import { DriverUpdates } from "./views/DriverUpdates";
import { DACHSER_LOGO } from "./logo";
const TABS = [
  { id:"planner", label:"Route planner", icon:Route },
  { id:"control", label:"Control room", icon:ShieldCheck }, { id:"shipments", label:"Shipments", icon:Truck },
  { id:"analytics", label:"Network intelligence", icon:BarChart3 },
  { id:"savings", label:"Savings", icon:PiggyBank }, { id:"driver",label:"Driver updates",icon:Truck }
];
const PRIMARY_TABS = ["planner", "control", "shipments", "analytics", "savings"];
export default function App() {
  const initialTab=TABS.some(t=>t.id===window.location.hash.slice(1).split("/")[0])?window.location.hash.slice(1).split("/")[0]:"planner";
  const [tab, setTab] = useState(initialTab);
  const [visited, setVisited] = useState<Set<string>>(() => new Set([initialTab]));
  const [net, setNet] = useState<NetworkDoc | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [ops, setOps] = useState<Operations | null>(null);
  const [tick, setTick] = useState(0);
  const [savedJourney,setSavedJourney]=useState<Shipment|null>(null);
  const [reviewRequest,setReviewRequest]=useState<{id:string;version:number}|null>(null);
  const saved=(shipment:Shipment)=>{setSavedJourney(shipment);setReviewRequest(prev=>({id:shipment.id,version:(prev?.version??0)+1}));setTick(value=>value+1)};
  const [err, setErr] = useState("");
  const moreMenu = useRef<HTMLDetailsElement>(null);

  const selectTab = (id: string) => {
    if (moreMenu.current) moreMenu.current.open = false;
    setTab(id);
    window.history.replaceState(null,"",`#${id}`);
    setVisited((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
    setTimeout(() => window.dispatchEvent(new Event("resize")), 50);
  };

  useEffect(()=>{const navigate=()=>{const id=window.location.hash.slice(1).split("/")[0];if(TABS.some(t=>t.id===id)){setTab(id);setVisited(prev=>prev.has(id)?prev:new Set(prev).add(id));window.dispatchEvent(new Event("resize"));}};window.addEventListener("hashchange",navigate);return()=>window.removeEventListener("hashchange",navigate)},[]);

  const refresh = () => setTick((t) => t + 1);
  const controlActive = tab === "control";
  useEffect(() => {
    let alive = true;
    api.network().then((n) => { if (alive) setNet(n); }).catch((e) => { if (alive) setErr(String(e)); });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    let alive = true;
    let pending = false;
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const [p, o] = await Promise.all([api.providers(), controlActive ? null : api.operations()]);
        if (alive) { setProviders(p.providers); if (o) setOps(o); setErr(""); }
      } catch (e) {
        if (alive) setErr(String(e));
      } finally { pending = false; }
    };
    void load();
    const refreshVisible = () => { if (!document.hidden) void load(); };
    const timer = setInterval(refreshVisible, 60000);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => { alive = false; clearInterval(timer); document.removeEventListener("visibilitychange", refreshVisible); };
  }, [tick, controlActive]);
  const nodes = net?.nodes ?? [];
  const alerts = ops?.weather.filter((w) => w.alert && Date.parse(w.end) > Date.now()) ?? [];

  return (
    <div className="app-shell">
      <header className="workspace-header">
        <a href="#" className="brand" onClick={(e) => { e.preventDefault(); selectTab("planner"); }}>
          <img src={DACHSER_LOGO} alt="DACHSER" className="brand-logo" />
          <small>LIVE TRANSIT PLANNER</small>
        </a>
        <div className="top__spacer" />
        <button className="icon-button" aria-label="Refresh workspace" onClick={refresh}><RefreshCw size={17} /></button>
        <span className="avatar" title="Traffic manager">MK</span>
      </header>
      <nav className="workspace-nav" aria-label="Workspace navigation">
        {TABS.filter((t) => PRIMARY_TABS.includes(t.id)).map((t) => (
          <button
            key={t.id}
            aria-current={tab === t.id ? "page" : undefined}
            className={tab === t.id ? "active" : ""}
            onClick={() => selectTab(t.id)}
          >
            <t.icon size={16} />
            {t.label}
          </button>
        ))}
        <details className="workspace-more" ref={moreMenu}>
          <summary className={PRIMARY_TABS.includes(tab) ? "" : "active"}>More{PRIMARY_TABS.includes(tab) ? "" : ` · ${TABS.find((t) => t.id === tab)?.label}`}</summary>
          <div className="workspace-more-menu">
            {TABS.filter((t) => !PRIMARY_TABS.includes(t.id)).map((t) => (
              <button key={t.id} className={tab === t.id ? "active" : ""} aria-current={tab === t.id ? "page" : undefined} onClick={() => selectTab(t.id)}>
                <t.icon size={16} />{t.label}
              </button>
            ))}
          </div>
        </details>
      </nav>
      <main className="wrap">
        <div className="page-meta">
          <span>{TABS.find((t) => t.id === tab)?.label}</span>
          <span><Activity size={12} /> {nodes.length} facilities</span>
        </div>
        {err && <div role="alert" className="notice notice--warn">Connection issue: {err}<button className="linkbtn" onClick={refresh}>Retry</button></div>}
        {alerts.length > 0 && tab !== "control" && (
          <button className="alert-strip" onClick={() => selectTab("control")}>
            <CloudSun size={18} />
            <span><b>{alerts.length} weather alert{alerts.length > 1 ? "s" : ""}</b> · Review active conditions in the control room.</span>
            <ArrowUpRight size={17} />
          </button>
        )}

        <div style={{ display: tab === "planner" ? "block" : "none" }}>
          {visited.has("planner") && (
            <Planner nodes={nodes} revision={ops?.revision ?? 0} operations={ops} onSaved={saved} onChange={refresh} onReview={(id) => {if(id)setReviewRequest(prev=>({id,version:(prev?.version??0)+1}));selectTab("control")}} />
          )}
        </div>
        <div style={{ display: tab === "control" ? "block" : "none" }}>
          {visited.has("control") && <ControlRoom nodes={nodes} onChange={refresh} refreshKey={tick} active={controlActive} savedJourney={savedJourney} reviewRequest={reviewRequest} onSaved={saved} onOperations={setOps} />}
        </div>
        <div style={{ display: tab === "shipments" ? "block" : "none" }}>
          {visited.has("shipments") && <Shipments nodes={nodes} ops={ops} active={tab==="shipments"} />}
        </div>
        <div style={{ display: tab === "analytics" ? "block" : "none" }}>
          {visited.has("analytics") && (
            <>
              <div className="page-heading">
                <div><h1>Network intelligence</h1></div>
              </div>
              <Analytics onData={refresh} />
            </>
          )}
        </div>
        <div style={{ display: tab === "savings" ? "block" : "none" }}>
          {visited.has("savings") && <Savings />}
        </div>

        <div style={{display:tab==="driver"?"block":"none"}}>{visited.has("driver")&&<DriverUpdates nodes={nodes}/>}</div>

        <footer className="workspace-footer">
          <span>DACHSER · Transit planner</span>
          <details className="connection-status"><summary>Connection status</summary><div className="provider-strip">
            {providers.map((p) => (
              <span key={p.key} className={statusClass(p.status)} title={`${p.name} · ${p.status}${p.error ? " · " + p.error : ""}`}>
                <span className="dot" />{p.key}: {p.status.replace(/_/g, " ")}
              </span>
            ))}
          </div></details>
        </footer>
      </main>
    </div>
  );
}
