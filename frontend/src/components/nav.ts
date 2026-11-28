import { BarChart3, BookOpen, Boxes, Brain, Cpu, Database, GitBranch, LayoutDashboard, MessagesSquare, Settings, ShieldCheck, Wrench, LucideIcon } from "lucide-react";
export const NAV: { href: string; label: string; icon: LucideIcon; keywords: string }[] = [
  { href: "/", label: "Overview", icon: LayoutDashboard, keywords: "home dashboard health" },
  { href: "/workspace/", label: "AI Workspace", icon: MessagesSquare, keywords: "chat assistant conversation" },
  { href: "/models/", label: "Model Lab", icon: Cpu, keywords: "nvidia nemotron llm playground latency" },
  { href: "/database/", label: "Database Explorer", icon: Database, keywords: "sql tables schema query" },
  { href: "/tools/", label: "MCP Tools", icon: Wrench, keywords: "tools execute registry" },
  { href: "/servers/", label: "Server Monitor", icon: Boxes, keywords: "mcp servers health restart" },
  { href: "/memory/", label: "Memory Center", icon: Brain, keywords: "remember recall facts" },
  { href: "/knowledge/", label: "Knowledge Base", icon: BookOpen, keywords: "documents rag search index" },
  { href: "/repository/", label: "Repository & Files", icon: GitBranch, keywords: "git files code diff commits" },
  { href: "/analytics/", label: "Analytics", icon: BarChart3, keywords: "tokens cost latency charts" },
  { href: "/security/", label: "Security & Audit", icon: ShieldCheck, keywords: "policy approvals audit redaction" },
  { href: "/settings/", label: "Settings", icon: Settings, keywords: "profile environment config" },
];
