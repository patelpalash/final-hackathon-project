import { useEffect, useRef, useState } from "react";
import { Truck, Route, PiggyBank, BarChart3, RefreshCw, ShieldCheck, CloudSun, BookOpen, ArrowUpRight, Activity } from "lucide-react";
import { api } from "./api/client";
import type { NetworkDoc, Provider, Operations } from "./api/types";
import { statusClass } from "./lib";
import { Shipments } from "./views/Shipments";
import { Planner } from "./views/Planner";
import { Savings } from "./views/Savings";
import { Analytics } from "./views/Analytics";
import { ControlRoom } from "./views/ControlRoom";
import { Assumptions } from "./views/Assumptions";
import { DACHSER_LOGO } from "./logo";
const TABS = [
  { id:"planner", label:"Route planner", icon:Route },
  { id:"control", label:"Control room", icon:ShieldCheck }, { id:"shipments", label:"Shipments", icon:Truck },
  { id:"analytics", label:"Network intelligence", icon:BarChart3 },
  { id:"savings", label:"Savings", icon:PiggyBank }, { id:"assumptions", label:"Assumptions", icon:BookOpen }
];
const PRIMARY_TABS = ["planner", "control", "shipments", "analytics", "savings"];
export default function App() {
  const [tab, setTab] = useState("planner");
  const [visited, setVisited] = useState<Set<string>>(() => new Set(["planner"]));
  const [net, setNet] = useState<NetworkDoc | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [ops, setOps] = useState<Operations | null>(null);
  const [tick, setTick] = useState(0);
  const [err, setErr] = useState("");
  const moreMenu = useRef<HTMLDetailsElement>(null);

  const selectTab = (id: string) => {
    if (moreMenu.current) moreMenu.current.open = false;
    setTab(id);
    setVisited((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
    setTimeout(() => window.dispatchEvent(new Event("resize")), 50);
  };

  const refresh = () => setTick((t) => t + 1);
  useEffect(() => {
    let alive = true;
    api.network().then((n) => { if (alive) setNet(n); }).catch((e) => { if (alive) setErr(String(e)); });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    let alive = true;
    const load = () => Promise.all([api.providers(), api.operations()]).then(([p, o]) => {
      if (alive) { setProviders(p.providers); setOps(o); setErr(""); }
    }).catch((e) => { if (alive) setErr(String(e)); });
    void load();
    const timer = setInterval(load, 15000);
    return () => { alive = false; clearInterval(timer); };
  }, [tick]);
  const nodes = net?.nodes ?? [];
  const alerts = ops?.weather.filter((w) => w.alert && Date.parse(w.end) > Date.now()) ?? [];

  return (
    <div className="app-shell">
      <header className="workspace-header">
        <a href="#" className="brand" onClick={(e) => { e.preventDefault(); selectTab("planner"); }}>
          <img src={DACHSER_LOGO} alt="DACHSER" className="brand-logo" />
          <small>LIVE TRANSIT PLANNER</small>
        </a>
        <span className="workspace-label">CHALLENGE 03</span>
        <div className="top__spacer" />
        <span className="prototype-tag">HACKATHON PROTOTYPE</span>
        <button className="icon-button" aria-label="Refresh workspace" onClick={refresh}><RefreshCw size={17} /></button>
        <span className="avatar" title="Demo manager">MK</span>
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
          <span>WORKSPACE <span>/</span> {TABS.find((t) => t.id === tab)?.label.toUpperCase()}</span>
          <span><Activity size={12} /> {nodes.length} facilities · {ops?.events.length ?? 0} scenario events</span>
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
            <Planner nodes={nodes} revision={ops?.revision ?? 0} onChange={refresh} onReview={() => selectTab("control")} />
          )}
        </div>
        <div style={{ display: tab === "control" ? "block" : "none" }}>
          {visited.has("control") && <ControlRoom nodes={nodes} onChange={refresh} />}
        </div>
        <div style={{ display: tab === "shipments" ? "block" : "none" }}>
          {visited.has("shipments") && <Shipments nodes={nodes} />}
        </div>
        <div style={{ display: tab === "analytics" ? "block" : "none" }}>
          {visited.has("analytics") && (
            <>
              <div className="page-heading">
                <div><span className="eyebrow">NETWORK INTELLIGENCE</span><h1>Learn from every lane.</h1><p>Historical operations and hub performance from the supplied data.</p></div>
              </div>
              <Analytics onData={refresh} />
            </>
          )}
        </div>
        <div style={{ display: tab === "savings" ? "block" : "none" }}>
          {visited.has("savings") && <Savings />}
        </div>
        <div style={{ display: tab === "assumptions" ? "block" : "none" }}>
          {visited.has("assumptions") && <Assumptions />}
        </div>

        <footer className="workspace-footer">
          <span>Transit / Decision support, with people in control.</span>
          <div className="provider-strip">
            {providers.map((p) => (
              <span key={p.key} className={statusClass(p.status)} title={`${p.name} · ${p.status}${p.error ? " · " + p.error : ""}`}>
                <span className="dot" />{p.key}: {p.status.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        </footer>
      </main>
    </div>
  );
}
