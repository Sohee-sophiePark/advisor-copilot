import { useEffect, useState } from "react";
import { source } from "./lib/source";
import { Client } from "./pages/Client";
import { Home } from "./pages/Home";
import { Market } from "./pages/Market";

const useHash = () => {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => { const f = () => setHash(location.hash); addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []);
  return hash;
};

export default function App() {
  const hash = useHash();
  const [mode, setMode] = useState(source.live ? "" : "DEMO");
  useEffect(() => { if (source.live) fetch("/api/health").then((r) => r.json()).then((h) => setMode(h.run_mode === "live" ? "LIVE" : "REPLAY")); }, []);
  const client = hash.match(/^#\/client\/([A-Za-z0-9_-]+)/)?.[1];
  const page = client ? <Client id={client} /> : hash === "#/market" ? <Market /> : <Home />;
  const nav = (href: string, label: string, active: boolean) => (
    <a href={href} className={`rounded-lg px-3 py-1.5 text-sm ${active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>{label}</a>
  );
  return (
    <div className="mx-auto max-w-[1400px] p-4 sm:p-6">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <span className="text-lg font-semibold tracking-tight text-slate-900">Advisor Copilot</span>
        {mode && <span className={`rounded-full px-2 py-0.5 text-xs font-semibold text-white ${mode === "LIVE" ? "bg-emerald-600" : "bg-blue-600"}`} title={mode === "LIVE" ? "Answers come from the model now" : "Answers replay recorded runs"}>{mode}</span>}
        <nav className="ml-4 flex gap-1">{nav("#/", "My book", !client && hash !== "#/market")}{nav("#/market", "Market", hash === "#/market")}</nav>
        <span className="ml-auto rounded-md bg-amber-100 px-2 py-1 text-xs text-amber-900">All clients and market data are fictional · not investment advice</span>
      </header>
      {page}
    </div>
  );
}
