"use client";

import { FEATURE_AVAILABILITY } from "@/lib/feature-availability";
import { cn } from "@/lib/utils";
import {
  Activity,
  BarChart3,
  Bell,
  BrainCircuit,
  Building2,
  ChartNoAxesCombined,
  ChevronRight,
  CircleHelp,
  Clock3,
  Database,
  FlaskConical,
  Handshake,
  House,
  Menu,
  Moon,
  Newspaper,
  PanelLeftClose,
  Search,
  ShieldCheck,
  Shuffle,
  Sigma,
  Sun,
  WalletCards,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

type NavItem = {
  href: string;
  label: string;
  shortLabel?: string;
  icon: LucideIcon;
  section: string;
};

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Intelligence",
    items: [
      { href: "/", label: "Command centre", shortLabel: "Overview", icon: House, section: "home" },
      { href: "/discover", label: "Company discovery", icon: Search, section: "discover" },
      { href: "/market", label: "India market pulse", shortLabel: "Market pulse", icon: Newspaper, section: "market" },
      { href: "/block-deals", label: "Institutional flows", shortLabel: "Block deals", icon: Handshake, section: "block-deals" },
    ],
  },
  {
    label: "Quantitative",
    items: [
      { href: "/technical", label: "Algorithmic scanner", shortLabel: "Algo scanner", icon: ChartNoAxesCombined, section: "technical" },
      { href: "/trade-suggestions", label: "Relative-value signals", shortLabel: "Pair signals", icon: Shuffle, section: "trade-suggestions" },
      { href: "/pair-portfolio", label: "Portfolio construction", shortLabel: "Pair portfolio", icon: WalletCards, section: "pair-portfolio" },
      { href: "/trade-tracker", label: "Research tracker", shortLabel: "Tracker", icon: Activity, section: "trade-tracker" },
    ],
  },
  {
    label: "Platform",
    items: [
      { href: "/admin", label: "Coverage & data", icon: Database, section: "admin" },
      { href: "/iv-model-validation", label: "Model validation", icon: ShieldCheck, section: "iv-model-validation" },
      ...(FEATURE_AVAILABILITY.customSignal
        ? [{ href: "/custom-signal", label: "Custom signal", icon: BrainCircuit, section: "custom-signal" }]
        : []),
      ...(FEATURE_AVAILABILITY.alternativeSignal
        ? [{ href: "/alternative-signal", label: "Alternative signal", icon: FlaskConical, section: "alternative-signal" }]
        : []),
      ...(FEATURE_AVAILABILITY.robustSignal
        ? [{ href: "/robust-signal", label: "Robust signal", icon: ShieldCheck, section: "robust-signal" }]
        : []),
      ...(process.env.NODE_ENV === "development"
        ? [
            { href: "/pair-method-lab", label: "Pairs method lab", icon: FlaskConical, section: "pair-method-lab" },
            { href: "/pair-method-tracker", label: "Paper method tracker", icon: Activity, section: "pair-method-tracker" },
            { href: "/copula-pair-signals", label: "Copula pair signals", icon: Sigma, section: "copula-pair-signals" },
            { href: "/intraday-copula-tracker", label: "Intraday copula", icon: Clock3, section: "intraday-copula-tracker" },
          ]
        : []),
    ],
  },
];

const ALL_NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

function isActive(pathname: string, section: string) {
  if (section === "home") return pathname === "/";
  if (section === "discover") {
    return pathname.startsWith("/discover") || pathname.startsWith("/search/") || pathname.startsWith("/company/");
  }
  return pathname.startsWith(`/${section}`);
}

function Brand() {
  return (
    <Link href="/" className="group flex min-w-0 items-center gap-2.5" aria-label="EquityLens command centre">
      <span className="brand-mark" aria-hidden="true">
        <span>EL</span>
      </span>
      <span className="min-w-0 leading-none">
        <span className="block truncate text-[14px] font-semibold tracking-[-0.025em]">EquityLens</span>
        <span className="mt-1 block truncate font-mono text-[8px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          India Intelligence
        </span>
      </span>
    </Link>
  );
}

function ThemeToggle() {
  function toggleTheme() {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    document.documentElement.style.colorScheme = next ? "dark" : "light";
    localStorage.setItem("equitylens-theme", next ? "dark" : "light");
  }

  return (
    <button type="button" onClick={toggleTheme} aria-label="Toggle colour mode" title="Toggle colour mode" className="topbar-action">
      <Moon className="size-3.5 dark:hidden" />
      <Sun className="hidden size-3.5 dark:block" />
    </button>
  );
}

function NavContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="flex-1 overflow-y-auto px-2.5 py-4" aria-label="Primary navigation">
      {NAV_GROUPS.map((group, groupIndex) => (
        <div key={group.label} className={groupIndex > 0 ? "mt-6" : ""}>
          <p className="px-2.5 pb-2 font-mono text-[8px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/75">
            {group.label}
          </p>
          <div className="space-y-0.5">
            {group.items.map((item) => {
              const active = isActive(pathname, item.section);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn("side-nav-item", active && "side-nav-item-active")}
                >
                  <Icon className="size-[14px] shrink-0" />
                  <span className="truncate">{item.label}</span>
                  {active && <ChevronRight className="ml-auto size-3 opacity-60" />}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}

export function SiteHeader() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const current = ALL_NAV_ITEMS.find((item) => isActive(pathname, item.section));

  useEffect(() => setMobileOpen(false), [pathname]);

  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-50 hidden w-[228px] flex-col border-r border-border bg-sidebar lg:flex">
        <div className="flex h-14 items-center border-b border-border px-4">
          <Brand />
          <PanelLeftClose className="ml-auto size-3.5 text-muted-foreground/50" aria-hidden="true" />
        </div>
        <NavContent />
        <div className="border-t border-border px-3 py-3">
          <div className="rounded-md border border-border bg-background/55 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span className="status-pulse" />
              <p className="text-[11px] font-semibold">Research systems online</p>
            </div>
            <p className="mt-1.5 font-mono text-[9px] text-muted-foreground">NSE MAIN BOARD · 2,386</p>
          </div>
          <div className="mt-2 flex items-center justify-between px-1 text-[9px] text-muted-foreground">
            <span>Source-linked intelligence</span>
            <Building2 className="size-3" />
          </div>
        </div>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-[70] bg-black/45 backdrop-blur-sm lg:hidden" onClick={() => setMobileOpen(false)}>
          <aside className="flex h-full w-[290px] flex-col border-r border-border bg-sidebar shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex h-14 items-center border-b border-border px-4">
              <Brand />
              <button className="topbar-action ml-auto" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X className="size-4" /></button>
            </div>
            <NavContent onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <header className="fixed inset-x-0 top-0 z-40 border-b border-border bg-background/92 backdrop-blur-xl lg:left-[228px]">
        <div className="flex h-14 items-center gap-3 px-3 sm:px-5 xl:px-6">
          <button type="button" className="topbar-action lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <Menu className="size-4" />
          </button>
          <div className="lg:hidden"><Brand /></div>
          <div className="hidden min-w-0 items-center gap-2 lg:flex">
            <span className="text-[11px] text-muted-foreground">Workspace</span>
            <span className="text-muted-foreground/35">/</span>
            <span className="truncate text-[11px] font-semibold">{current?.label ?? "EquityLens"}</span>
          </div>

          <Link href="/discover" className="command-search mx-auto hidden md:flex">
            <Search className="size-3.5 shrink-0 text-muted-foreground" />
            <span className="truncate">Search securities, sectors, filings or ask a research question</span>
            <kbd>⌘ K</kbd>
          </Link>

          <div className="ml-auto flex items-center gap-1.5">
            <span className="hidden items-center gap-1.5 border-r border-border pr-3 font-mono text-[9px] font-semibold uppercase tracking-[0.08em] text-muted-foreground sm:flex">
              <span className="status-pulse" /> NSE · Delayed
            </span>
            <button type="button" className="topbar-action" aria-label="Help"><CircleHelp className="size-3.5" /></button>
            <button type="button" className="topbar-action relative" aria-label="Notifications"><Bell className="size-3.5" /><span className="absolute right-1.5 top-1.5 size-1 rounded-full bg-primary" /></button>
            <ThemeToggle />
            <span className="ml-1 grid size-7 place-items-center rounded-sm bg-foreground font-mono text-[9px] font-bold text-background" aria-label="User profile">YS</span>
          </div>
        </div>
      </header>
    </>
  );
}
