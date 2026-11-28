"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Json } from "./ui";

/** Global human-in-the-loop dialog: any tool the policy marks "approve" (chat, manual run, dashboard action) lands here. */
export function ApprovalDialog() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["approvals"], queryFn: () => api.get("/api/approvals"), refetchInterval: 1200 });
  const decide = useMutation({
    mutationFn: ({ id, allow }: { id: string; allow: boolean }) => api.post(`/api/approvals/${id}`, { allow }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ["approvals"] }); qc.invalidateQueries({ queryKey: ["security"] }); },
  });
  const a = data?.pending?.[0];
  return (
    <AnimatePresence>
      {a && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm" role="alertdialog" aria-label="Approval required">
          <motion.div initial={{ scale: 0.96, y: 8 }} animate={{ scale: 1, y: 0 }} className="card w-full max-w-lg border-warn/40 shadow-glow">
            <div className="flex items-center gap-3 border-b border-line p-4">
              <ShieldAlert className="h-5 w-5 text-warn" />
              <div className="flex-1"><div className="font-semibold">Approval required</div><div className="text-xs text-mute">The assistant wants to run a tool that changes state.</div></div>
              <Badge tone={a.destructive ? "bad" : "warn"}>{a.destructive ? "destructive" : "write"}</Badge>
            </div>
            <div className="space-y-3 p-4">
              <div className="flex items-center justify-between text-sm"><span className="font-mono text-accent">{a.tool}</span><Badge>{a.source === "manual" ? "manual run" : "from chat"}</Badge></div>
              {a.description && <p className="text-sm text-mute">{a.description}</p>}
              <div><div className="label mb-1">Arguments (secrets redacted)</div><Json value={a.args} max={200} /></div>
              {data.pending.length > 1 && <div className="text-xs text-mute">{data.pending.length - 1} more waiting</div>}
            </div>
            <div className="flex justify-end gap-2 border-t border-line p-3">
              <button className="btn btn-danger" disabled={decide.isPending} onClick={() => decide.mutate({ id: a.id, allow: false })}>Decline</button>
              <button className="btn btn-primary" disabled={decide.isPending} onClick={() => decide.mutate({ id: a.id, allow: true })}>Approve once</button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
