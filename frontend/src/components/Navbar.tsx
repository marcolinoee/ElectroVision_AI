"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Cpu, FolderPlus, LayoutDashboard, PenTool, Zap } from "lucide-react";
import { cn } from "@/lib/api";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/projects/new", label: "Novo Projeto", icon: FolderPlus },
  { href: "/editor", label: "Editor Digital Twin", icon: PenTool },
  { href: "/ml", label: "Treinamento ML", icon: Cpu },
];

export function Navbar() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2 font-bold text-slate-900">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-white">
            <Zap className="h-4 w-4" />
          </span>
          <span>ElectroVision AI</span>
          <span className="hidden rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 sm:inline">
            Local-First
          </span>
        </Link>

        <nav className="flex items-center gap-1">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  active
                    ? "bg-blue-50 text-blue-700"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                )}
              >
                <Icon className="h-4 w-4" />
                <span className="hidden md:inline">{label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
