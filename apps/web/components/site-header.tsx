"use client";

import { cn } from "@/lib/utils";
import {
  Activity,
  BarChart3,
  BrainCircuit,
  Building2,
  ChartNoAxesCombined,
  Database,
  FlaskConical,
  Handshake,
  House,
  Moon,
  Newspaper,
  Search,
  Shuffle,
  Sun,
  WalletCards,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  section: string;
};

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Research",
    items: [
      { href: "/", label: "Overview", icon: House, section: "home" },
      { href: "/discover", label: "Company discovery", icon: Search, section: "discover" },
      { href: "/market", label: "Market pulse", icon: Newspaper, section: "market" },
      { href: "/block-deals", label: "Block deals", icon: Handshake, section: "block-deals" },
    ],
  },
  {
    label: "Trading tools",
    items: [
      { href: "/technical", label: "Algo scanner", icon: ChartNoAxesCombined, section: "technical" },
      { href: "/trade-suggestions", label: "Pair trades", icon: Shuffle, section: "trade-suggestions" },
      { href: "/trade-tracker", label: "Trade tracker", icon: WalletCards, section: "trade-tracker" },
    ],
  },
  {
    label: "System",
    items: [
      { href: "/admin", label: "Data coverage", icon: Database, section: "admin" },
      {
        href: "/iv-model-validation",
        label: "IV model validation",
        icon: Activity,
        section: "iv-model-validation",
      },
      {
        href: "/custom-signal",
        label: "Custom signal",
        icon: BrainCircuit,
        section: "custom-signal",
      },
      {
        href: "/alternative-signal",
        label: "Alternative signal",
        icon: FlaskConical,
        section: "alternative-signal",
      },
      ...(process.env.NODE_ENV === "development"
        ? [
            {
              href: "/pair-method-lab",
              label: "Pairs method lab",
              icon: FlaskConical,
              section: "pair-method-lab",
            },
            {
              href: "/pair-method-tracker",
              label: "Paper method tracker",
              icon: Activity,
              section: "pair-method-tracker",
            },
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
    <Link href="/" className="group flex items-center gap-2.5" aria-label="EquityLens overview">
      <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-[#2257b8] to-[#17315f] text-white shadow-sm dark:from-emerald-400 dark:to-emerald-600 dark:text-[#111512]">
        <BarChart3 className="size-4" />
      </span>
      <span className="leading-none">
        <span className="block text-[15px] font-semibold tracking-[-0.025em]">EquityLens</span>
        <span className="mt-1 block text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          India Research
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
    <button
      type="button"
      onClick={toggleTheme}
      aria-label="Toggle color mode"
      title="Toggle color mode"
      className="grid size-9 shrink-0 place-items-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:border-input hover:bg-muted hover:text-foreground"
    >
      <Moon className="size-4 dark:hidden" />
      <Sun className="hidden size-4 dark:block" />
    </button>
  );
}

export function SiteHeader() {
  const pathname = usePathname();

  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-50 hidden w-56 flex-col border-r border-border bg-card/98 md:flex">
        <div className="flex h-[60px] items-center border-b border-border px-5">
          <Brand />
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4">
          {NAV_GROUPS.map((group, groupIndex) => (
            <div key={group.label} className={groupIndex > 0 ? "mt-6" : ""}>
              <p className="px-2 pb-2 text-[9px] font-semibold uppercase tracking-[0.13em] text-muted-foreground/80">
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
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "relative flex h-9 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium transition-colors",
                        active
                          ? "bg-accent/80 text-primary"
                          : "text-muted-foreground hover:bg-muted/70 hover:text-foreground"
                      )}
                    >
                      {active && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-primary" />}
                      <Icon className="size-[15px]" />
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t border-border px-4 py-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[11px] font-semibold">NSE main board</p>
              <p className="mt-1 text-[10px] text-muted-foreground">2,386 equities tracked</p>
            </div>
            <span className="size-2 rounded-full bg-emerald-500 ring-4 ring-emerald-500/10" />
          </div>
          <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-[10px] text-muted-foreground">
            <span>Primary-source research</span>
            <Building2 className="size-3.5" />
          </div>
        </div>
      </aside>

      <header className="fixed inset-x-0 top-0 z-40 border-b border-border bg-card/90 shadow-[0_1px_12px_rgba(15,23,42,0.025)] backdrop-blur-xl dark:shadow-[0_1px_12px_rgba(0,0,0,0.18)] md:left-56">
        <div className="flex h-[60px] items-center gap-3 px-4 sm:px-6 xl:px-8">
          <div className="md:hidden"><Brand /></div>

          <Link
            href="/discover"
            className="mx-auto hidden h-9 w-full max-w-2xl items-center gap-2.5 rounded-md border border-border bg-muted/55 px-3 text-[13px] text-muted-foreground transition-colors hover:border-input hover:bg-card hover:text-foreground md:flex"
          >
            <Search className="size-3.5" />
            <span className="truncate">Search companies, sectors, exposures or financial conditions</span>
            <kbd className="ml-auto rounded-sm border border-border bg-card px-1.5 py-0.5 font-mono text-[9px] text-muted-foreground">/</kbd>
          </Link>

          <div className="ml-auto flex items-center gap-2">
            <div className="hidden items-center gap-2 sm:flex">
              <span className="rounded-sm bg-accent px-2 py-1 font-mono text-[10px] font-semibold text-primary">NSE</span>
              <span className="text-[11px] text-muted-foreground">Market data may be delayed</span>
            </div>
            <ThemeToggle />
          </div>
        </div>

        <nav className="flex h-10 items-center gap-1 overflow-x-auto border-t border-border px-3 md:hidden">
          {ALL_NAV_ITEMS.map((item) => {
            const active = isActive(pathname, item.section);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium",
                  active ? "bg-accent text-primary" : "text-muted-foreground"
                )}
              >
                <Icon className="size-3.5" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>
    </>
  );
}
