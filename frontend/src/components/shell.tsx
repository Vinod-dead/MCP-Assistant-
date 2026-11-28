"use client";
import { useQuery } from "@tanstack/react-query";
import { Bell, ChevronDown, Cpu, Search, Sparkles, User } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { ago, short } from "@/lib/format";
import { ApprovalDialog } from "./approvals";
import { NAV } from "./nav";
import { Badge, cx } from "./ui";

function useHealth() { return useQuery({ queryKey: ["health"], queryFn: () => api.get("/api/health"), refetchInterval: 5000, retry: 0 }); }

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5" aria-label="MCP Assistant Studio home">
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-accent to-violet shadow-glow"><Sparkles className="h-4 w-4 text-white" /></span>
      <span className="leading-tight"><span className="block text-sm font-semibold tracking-tight">MCP Assistant</span><span className="block text-[10px] font-medium uppercase tracking-[0.18em] text-mute">Studio</span></span>
    </Link>
  );
}

function GlobalSearch() {
  const [q, setQ] = useState(""); const [open, setOpen] = useState(false); const router = useRouter(); const ref = useRef<HTMLInputElement>(null);
  const tools = useQuery({ queryKey: ["tools"], queryFn: () => api.get("/api/tools"), enabled: open, staleTime: 30000 });
  useEffect(() => { const h = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); ref.current?.focus(); } }; window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, []);
  const results = useMemo(() => {
    const s = q.trim().toLowerCase(); if (!s) return [];
    const pages = NAV.filter((n) => (n.label + " " + n.keywords).toLowerCase().includes(s)).map((n) => ({ key: n.href, label: n.label, sub: "Page", go: n.href }));
    const t = (tools.data?.tools ?? []).filter((x: any) => x.name.toLowerCase().includes(s) || (x.description ?? "").toLowerCase().includes(s)).slice(0, 6)
      .map((x: any) => ({ key: x.name, label: x.name, sub: short(x.description, 50), go: `/tools/?tool=${encodeURIComponent(x.name)}` }));
    return [...pages, ...t].slice(0, 9);
  }, [q, tools.data]);
  return (
    <div className="relative w-full max-w-md">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-mute" />
      <input ref={ref} className="input pl-9 pr-14" placeholder="Search pages and tools…" value={q} aria-label="Global search" onChange={(e) => setQ(e.target.value)} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => { if (e.key === "Enter" && results[0]) { router.push(results[0].go); setQ(""); } }} />
      <kbd className="absolute right-2 top-1/2 -translate-y-1/2 rounded border border-line px-1.5 py-0.5 text-[10px] text-mute">Ctrl K</kbd>
      {open && q && (
        <div className="card absolute left-0 right-0 top-11 z-40 max-h-80 overflow-auto p-1 shadow-glow">
          {results.length === 0 ? <div className="p-3 text-sm text-mute">No matches</div> : results.map((r) => (
            <button key={r.key} className="flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm hover:bg-panel2" onMouseDown={() => { router.push(r.go); setQ(""); }}>
              <span className="font-medium">{r.label}</span><span className="truncate text-xs text-mute">{r.sub}</span>
            </button>))}
        </div>
      )}
    </div>
  );
}

function Notifications() {
  const [open, setOpen] = useState(false);
  const ap = useQuery({ queryKey: ["approvals"], queryFn: () => api.get("/api/approvals"), refetchInterval: 4000 });
  const sec = useQuery({ queryKey: ["security"], queryFn: () => api.get("/api/security"), refetchInterval: 15000, enabled: open });
  const pending = ap.data?.pending ?? [];
  const failures = (sec.data?.failed_operations ?? []).slice(0, 5);
  return (
    <div className="relative">
      <button className="btn relative h-9 w-9 p-0" aria-label="Notifications" onClick={() => setOpen(!open)}><Bell className="h-4 w-4" />{pending.length > 0 && <span className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-warn px-1 text-[10px] font-bold text-black">{pending.length}</span>}</button>
      {open && (
        <div className="card absolute right-0 top-11 z-40 w-80 p-2 shadow-glow">
          <div className="label px-2 py-1">Pending approvals</div>
          {pending.length === 0 ? <div className="px-2 pb-2 text-sm text-mute">None</div> : pending.map((p: any) => <div key={p.id} className="rounded-md px-2 py-1.5 text-sm"><span className="font-mono text-accent">{p.tool}</span></div>)}
          <div className="label mt-1 border-t border-line px-2 py-1 pt-2">Recent failures</div>
          {failures.length === 0 ? <div className="px-2 pb-1 text-sm text-mute">{sec.isLoading ? "Loading…" : "None recorded"}</div> : failures.map((f: any, i: number) => <div key={i} className="px-2 py-1 text-xs"><span className="font-mono">{f.tool ?? f.event}</span> <span className="text-mute">· {ago(f.ts)}</span></div>)}
        </div>
      )}
    </div>
  );
}

function ProfileMenu({ health }: { health: any }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button className="btn h-9 gap-2 px-2" onClick={() => setOpen(!open)} aria-label="Profile menu"><span className="grid h-6 w-6 place-items-center rounded-full bg-gradient-to-br from-accent to-violet"><User className="h-3.5 w-3.5 text-white" /></span><span className="hidden text-xs sm:block">Local user</span><ChevronDown className="h-3.5 w-3.5 text-mute" /></button>
      {open && (
        <div className="card absolute right-0 top-11 z-40 w-64 p-2 shadow-glow" onMouseLeave={() => setOpen(false)}>
          <div className="px-2 py-1.5 text-sm"><div className="font-medium">Local session</div><div className="text-xs text-mute">Permission profile: <span className="font-mono text-ink">{health?.profile ?? "Unavailable"}</span></div></div>
          <Link href="/settings/" className="block rounded-md px-2 py-1.5 text-sm hover:bg-panel2" onClick={() => setOpen(false)}>Settings & profile</Link>
          <Link href="/security/" className="block rounded-md px-2 py-1.5 text-sm hover:bg-panel2" onClick={() => setOpen(false)}>Security & audit</Link>
          <a className="block rounded-md px-2 py-1.5 text-sm hover:bg-panel2" href="/api/docs" target="_blank" rel="noreferrer">API docs</a>
        </div>
      )}
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname() ?? "/";
  const { data: h, isError, isLoading } = useHealth();
  const conn = isError ? { tone: "bad" as const, text: "API offline" } : isLoading ? { tone: "mute" as const, text: "Connecting…" } : h.status === "ok" ? { tone: "ok" as const, text: "Connected" } : { tone: "warn" as const, text: h.status === "down" ? "Servers down" : "Degraded" };
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href.replace(/\/$/, "")));
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-panel/60 p-3 backdrop-blur md:flex">
        <div className="px-2 py-3"><Logo /></div>
        <nav className="mt-2 flex-1 space-y-0.5 overflow-y-auto" aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className={cx("group flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition", active(n.href) ? "bg-accent/10 text-ink ring-1 ring-accent/30" : "text-mute hover:bg-panel2 hover:text-ink")}>
              <n.icon className={cx("h-4 w-4", active(n.href) ? "text-accent" : "group-hover:text-accent")} />{n.label}
            </Link>))}
        </nav>
        <div className="rounded-lg border border-line bg-bg/60 p-3 text-xs text-mute">
          {h?.offline_demo ? <><Badge tone="warn" dot>Offline demo</Badge><p className="mt-2">Mock provider: plumbing is real, the model is not. Add NVIDIA_API_KEY to .env for real answers.</p></> : <>Provider <span className="font-mono text-ink">{h?.provider ?? "Unavailable"}</span></>}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-bg/80 px-4 py-2.5 backdrop-blur-md">
          <div className="md:hidden"><Logo /></div>
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-2">
            <Link href="/models/" className="btn hidden h-9 gap-2 lg:inline-flex" title="Current model"><Cpu className="h-3.5 w-3.5 text-violet" /><span className="max-w-[230px] truncate font-mono text-xs">{h?.model ?? "Unavailable"}</span></Link>
            <Badge tone={conn.tone} dot>{conn.text}</Badge>
            <Notifications />
            <ProfileMenu health={h} />
          </div>
        </header>
        <nav className="flex gap-1 overflow-x-auto border-b border-line px-3 py-2 md:hidden" aria-label="Mobile">{NAV.map((n) => <Link key={n.href} href={n.href} className={cx("whitespace-nowrap rounded-md px-2.5 py-1 text-xs", active(n.href) ? "bg-accent/15 text-ink" : "text-mute")}>{n.label}</Link>)}</nav>
        <main className="mx-auto w-full max-w-[1500px] flex-1 p-4 md:p-6">{children}</main>
      </div>
      <ApprovalDialog />
    </div>
  );
}
