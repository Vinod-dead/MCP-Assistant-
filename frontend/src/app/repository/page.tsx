"use client";
import { useQuery } from "@tanstack/react-query";
import { FileText, Folder, GitCommit, Search } from "lucide-react";
import { useState } from "react";
import { Badge, Card, Empty, ErrorBox, PageHeader, Tabs, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, bytes } from "@/lib/format";

type Tab = "git" | "files" | "tree" | "search";
function Diff({ text }: { text: string }) {
  return <pre className="max-h-[420px] overflow-auto rounded-lg border border-line bg-bg p-3 font-mono text-xs leading-relaxed">{text.split("\n").map((l, i) => <div key={i} className={l.startsWith("+") && !l.startsWith("+++") ? "bg-ok/10 text-ok" : l.startsWith("-") && !l.startsWith("---") ? "bg-bad/10 text-bad" : l.startsWith("@@") ? "text-violet" : "text-mute"}>{l || " "}</div>)}</pre>;
}
function TreeNode({ n, depth, onOpen }: { n: any; depth: number; onOpen: (p: string) => void }) {
  const [open, setOpen] = useState(depth < 1);
  return <div><button className="flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left text-sm hover:bg-panel2" style={{ paddingLeft: depth * 14 + 4 }} onClick={() => (n.type === "dir" ? setOpen(!open) : onOpen(n.path))}>{n.type === "dir" ? <Folder className="h-3.5 w-3.5 text-accent" /> : <FileText className="h-3.5 w-3.5 text-mute" />}<span className="font-mono text-[12.5px]">{n.name}</span></button>{open && n.children?.map((c: any) => <TreeNode key={c.path} n={c} depth={depth + 1} onOpen={onOpen} />)}</div>;
}

export default function Repo() {
  const [tab, setTab] = useState<Tab>("git");
  const status = useQuery({ queryKey: ["repo-status"], queryFn: () => api.get("/api/repo/status"), refetchInterval: 10000 });
  return (
    <div className="space-y-5">
      <PageHeader title="Repository & Files" sub="Read-only views over the repo and workspace folder, fetched through the real repo and files MCP servers." actions={<Tabs value={tab} onChange={setTab} items={[{ id: "git", label: "Git" }, { id: "tree", label: "Code tree" }, { id: "files", label: "Workspace files" }, { id: "search", label: "Search" }]} />} />
      {tab === "git" && <Git status={status} />}
      {tab === "tree" && <CodeTree />}
      {tab === "files" && <Files />}
      {tab === "search" && <SearchTab />}
    </div>
  );
}

function Git({ status }: { status: any }) {
  const log = useQuery({ queryKey: ["repo-log"], queryFn: () => api.get("/api/repo/log?n=20") });
  const [file, setFile] = useState<string>("");
  const diff = useQuery({ queryKey: ["repo-diff", file], queryFn: () => api.get(`/api/repo/diff?ref=HEAD&path=${encodeURIComponent(file)}`) });
  const s = status.data;
  if (status.isLoading) return <div className="sk h-40" />;
  if (status.isError) return <ErrorBox error={status.error} />;
  if (!s?.available) return <Card><Empty title="No git repository available" hint={<>{s?.error} — point <span className="font-mono">REPO_ROOT</span> in .env at a git repository.</>} /></Card>;
  const groups: [string, any[], any][] = [["Staged", s.staged, "ok"], ["Modified", s.modified, "warn"], ["Untracked", s.untracked, "info"]];
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card title="Working tree" right={<><Badge tone="violet">{s.branch}</Badge>{s.upstream && <Badge>{s.upstream}</Badge>}{s.ahead > 0 && <Badge tone="ok">↑{s.ahead}</Badge>}{s.behind > 0 && <Badge tone="warn">↓{s.behind}</Badge>}</>}>
        {s.clean ? <Empty title="Working tree clean" /> : groups.map(([label, items, tone]) => items.length > 0 && <div key={label} className="mb-3"><div className="label mb-1">{label} ({items.length})</div>{items.map((f: any) => <button key={label + f.path} onClick={() => setFile(f.path)} className={cx("flex w-full items-center gap-2 rounded px-2 py-1 text-left hover:bg-panel2", file === f.path && "bg-accent/10")}><Badge tone={tone}>{f.code}</Badge><span className="truncate font-mono text-xs">{f.path}</span></button>)}</div>)}
      </Card>
      <Card title="Recent commits" pad={false}>
        {log.isLoading ? <div className="p-4"><div className="sk h-24" /></div> : log.data?.commits.length ? <ul className="divide-y divide-line">{log.data.commits.map((c: any) => <li key={c.hash} className="flex items-start gap-3 px-4 py-2.5"><GitCommit className="mt-0.5 h-4 w-4 text-accent" /><div className="min-w-0"><div className="truncate text-sm">{c.subject}</div><div className="text-[11px] text-mute"><span className="font-mono text-violet">{c.hash}</span> · {c.author} · {c.date}</div></div></li>)}</ul> : <Empty title="No commits" />}
      </Card>
      <Card title={`Diff vs HEAD${file ? ` — ${file}` : ""}`} className="lg:col-span-2" right={file && <button className="btn h-7" onClick={() => setFile("")}>All files</button>}>
        {diff.isLoading ? <div className="sk h-24" /> : diff.data?.diff ? <Diff text={diff.data.diff} /> : <Empty title="No differences" />}
      </Card>
    </div>
  );
}

function CodeTree() {
  const tree = useQuery({ queryKey: ["repo-tree"], queryFn: () => api.get("/api/repo/tree?depth=3") });
  const [path, setPath] = useState<string | null>(null);
  const file = useQuery({ queryKey: ["repo-file", path], queryFn: () => api.get(`/api/repo/file?path=${encodeURIComponent(path!)}&start=1&end=250`), enabled: !!path });
  return (
    <div className="grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
      <Card title="Tree" pad={false}>{tree.isLoading ? <div className="p-4"><div className="sk h-32" /></div> : tree.isError ? <div className="p-3"><ErrorBox error={tree.error} /></div> : <div className="max-h-[600px] overflow-auto p-2">{tree.data.tree.map((n: any) => <TreeNode key={n.path} n={n} depth={0} onOpen={setPath} />)}</div>}</Card>
      <Card title={path ?? "Preview"} pad={!!path}>{!path ? <Empty title="Select a file" /> : file.isLoading ? <div className="sk h-40" /> : file.isError ? <ErrorBox error={file.error} /> : <pre className="max-h-[600px] overflow-auto font-mono text-xs leading-relaxed">{file.data.content}</pre>}</Card>
    </div>
  );
}

function Files() {
  const [dir, setDir] = useState(".");
  const list = useQuery({ queryKey: ["files", dir], queryFn: () => api.get(`/api/files?path=${encodeURIComponent(dir)}`) });
  const [path, setPath] = useState<string | null>(null);
  const file = useQuery({ queryKey: ["file", path], queryFn: () => api.get(`/api/files/read?path=${encodeURIComponent(path!)}`), enabled: !!path });
  const up = dir === "." ? null : dir.split("/").slice(0, -1).join("/") || ".";
  return (
    <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
      <Card title={<span className="font-mono text-xs">{dir === "." ? "workspace /" : dir}</span>} pad={false}>
        {list.isLoading ? <div className="p-4"><div className="sk h-24" /></div> : list.isError ? <div className="p-3"><ErrorBox error={list.error} /></div> : <ul className="max-h-[600px] overflow-auto p-1.5">
          {up && <li><button className="w-full rounded px-2 py-1 text-left text-sm text-mute hover:bg-panel2" onClick={() => setDir(up)}>↰ ..</button></li>}
          {list.data.entries.map((e: any) => <li key={e.path}><button className="flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left hover:bg-panel2" onClick={() => (e.type === "dir" ? setDir(e.path) : setPath(e.path))}><span className="flex items-center gap-2 truncate">{e.type === "dir" ? <Folder className="h-3.5 w-3.5 text-accent" /> : <FileText className="h-3.5 w-3.5 text-mute" />}<span className="font-mono text-[12.5px]">{e.name}</span></span><span className="text-[11px] text-mute">{e.size != null ? bytes(e.size) : ""}</span></button></li>)}
          {list.data.entries.length === 0 && <Empty title="Empty folder" />}</ul>}
      </Card>
      <Card title={path ?? "Preview"} right={file.data?.info && <span className="text-[11px] text-mute">{String(file.data.info).split("\n")[0]}</span>}>
        {!path ? <Empty title="Select a file" hint="Reads go through files__read_file, which is sandboxed to the workspace folder." /> : file.isLoading ? <div className="sk h-40" /> : file.isError ? <ErrorBox error={file.error} /> : <pre className="max-h-[600px] overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed">{file.data.content}</pre>}
      </Card>
    </div>
  );
}

function SearchTab() {
  const [q, setQ] = useState(""); const [applied, setApplied] = useState(""); const [scope, setScope] = useState<"code" | "files">("code");
  const r = useQuery({ queryKey: ["rsearch", scope, applied], queryFn: () => api.get(scope === "code" ? `/api/repo/search?pattern=${encodeURIComponent(applied)}` : `/api/files/search?q=${encodeURIComponent(applied)}`), enabled: !!applied });
  return (
    <Card title="Search" right={<Tabs value={scope} onChange={setScope} items={[{ id: "code", label: "Code" }, { id: "files", label: "Workspace" }]} />}>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setApplied(q.trim()); }}><div className="relative flex-1"><Search className="absolute left-3 top-2.5 h-4 w-4 text-mute" /><input className="input pl-9 font-mono" placeholder={scope === "code" ? "regex, e.g. def .*llm" : "text to find"} value={q} onChange={(e) => setQ(e.target.value)} /></div><button className="btn btn-primary">Search</button></form>
      <div className="mt-4">{r.isFetching ? <div className="sk h-24" /> : r.isError ? <ErrorBox error={r.error} /> : r.data ? (r.data.hits.length === 0 ? <Empty title="No matches" /> : <ul className="divide-y divide-line rounded-lg border border-line">{r.data.hits.map((h: any, i: number) => <li key={i} className="px-3 py-2"><div className="font-mono text-xs text-accent">{h.path}{h.line ? `:${h.line}` : ""}</div>{h.text && <div className="truncate font-mono text-xs text-mute">{h.text}</div>}</li>)}</ul>) : <p className="text-sm text-mute">Enter a query.</p>}</div>
    </Card>
  );
}
