"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Calendar, LineChart, Settings, User } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Plans", icon: Calendar },
  { href: "/analysis", label: "Analysis", icon: LineChart },
  { href: "/profile", label: "Profile", icon: User },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden md:flex w-60 flex-col border-r bg-card">
      <div className="px-6 py-5 flex items-center gap-2 border-b">
        <Activity className="h-5 w-5 text-primary" />
        <span className="font-semibold tracking-tight">Garmin Coach</span>
      </div>
      <nav className="p-3 space-y-1">
        {NAV.map((item) => {
          const Icon = item.icon;
          const active =
            item.href === "/"
              ? pathname === "/" || pathname.startsWith("/plans")
              : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-secondary text-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
