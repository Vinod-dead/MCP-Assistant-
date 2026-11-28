import type { Metadata } from "next";
import { ReactNode } from "react";
import { Providers } from "@/components/providers";
import { Shell } from "@/components/shell";
import "./globals.css";

export const metadata: Metadata = { title: "MCP Assistant Studio", description: "Operate an MCP-powered AI assistant: chat, tools, database, servers, security." };
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark"><body><Providers><Shell>{children}</Shell></Providers></body></html>
  );
}
