import type { ClientSummary } from "../lib/types";

export function ClientList({ clients, selected, onSelect }: { clients: ClientSummary[]; selected: string; onSelect: (id: string) => void }) {
  return (
    <div className="space-y-2">
      {clients.map((c) => (
        <button key={c.client_id} onClick={() => onSelect(c.client_id)}
          className={`w-full rounded-lg border p-3 text-left transition ${selected === c.client_id ? "border-teal-600 bg-teal-50" : "border-slate-200 bg-white hover:border-slate-300"}`}>
          <div className="flex items-center justify-between">
            <span className="font-medium">{c.name}</span>
            <span className="text-xs text-slate-500">{c.client_id}</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-xs text-slate-600">
            <span>{c.age} y</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 capitalize">{c.risk_profile ?? "KYC incomplete"}</span>
            <span className="ml-auto">${c.total_cad.toLocaleString("en-CA")}</span>
          </div>
          {c.flag_count !== null && c.flag_count > 0 && (
            <div className="mt-1 text-xs text-amber-700">{c.flag_count} flag{c.flag_count > 1 ? "s" : ""} to review</div>
          )}
        </button>
      ))}
    </div>
  );
}
