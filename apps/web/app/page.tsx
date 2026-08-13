import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Building2,
  ChartNoAxesCombined,
  Check,
  ChevronRight,
  Clock3,
  Database,
  FileSearch2,
  Handshake,
  Layers3,
  Newspaper,
  Search,
  ShieldCheck,
  Shuffle,
  Sparkles,
  WalletCards,
} from "lucide-react";
import Link from "next/link";

const MARKET_TAPE = [
  ["NIFTY 50", "India large cap", "NSE"],
  ["NIFTY BANK", "Financials", "NSE"],
  ["INDIA VIX", "Volatility", "NSE"],
  ["USD / INR", "Spot reference", "FX"],
] as const;

const WORKSPACES = [
  {
    href: "/discover",
    code: "DSCV",
    title: "Company discovery",
    description: "Screen operating models, exposures and financial conditions against verified filings.",
    icon: FileSearch2,
    meta: "2,386 NSE equities",
  },
  {
    href: "/technical",
    code: "SCAN",
    title: "Algorithmic scanner",
    description: "Combine semantic business context with deterministic price and options conditions.",
    icon: ChartNoAxesCombined,
    meta: "Multi-timeframe",
  },
  {
    href: "/trade-suggestions",
    code: "PAIR",
    title: "Relative-value signals",
    description: "Review statistically related futures pairs and their spread diagnostics.",
    icon: Shuffle,
    meta: "NSE F&O universe",
  },
  {
    href: "/pair-portfolio",
    code: "PORT",
    title: "Portfolio construction",
    description: "Build a low-overlap paper portfolio from active relative-value signals.",
    icon: WalletCards,
    meta: "Risk-aware selection",
  },
  {
    href: "/block-deals",
    code: "FLOW",
    title: "Institutional flows",
    description: "Inspect disclosed block transactions, named clients, prices and notional value.",
    icon: Handshake,
    meta: "NSE disclosures",
  },
  {
    href: "/market",
    code: "NEWS",
    title: "India market pulse",
    description: "Translate policy, macro and geopolitical developments into an India-market lens.",
    icon: Newspaper,
    meta: "Source-linked brief",
  },
] as const;

const RESEARCH_STEPS = [
  ["01", "Interpret", "Natural language becomes a transparent, editable research plan."],
  ["02", "Verify", "Financial conditions are computed; filing evidence remains linked."],
  ["03", "Rank", "Results are ordered by query fit, never by investment recommendation."],
] as const;

const RECENT = [
  ["Power transmission & grid equipment", "Company screen", "12 candidates"],
  ["F&O pairs with stable long-run spread", "Relative value", "8 signals"],
  ["Institutional activity — 30 day window", "Block deals", "Flow monitor"],
] as const;

function MiniChart({ variant }: { variant: number }) {
  return (
    <div className={`mini-chart mini-chart-${variant}`} aria-hidden="true">
      {Array.from({ length: 12 }).map((_, index) => <i key={index} />)}
    </div>
  );
}

export default function HomePage() {
  return (
    <div className="space-y-4 pb-4">
      <section className="terminal-strip fade-in-up" aria-label="Market reference tape">
        <div className="flex min-w-max items-stretch">
          <div className="flex w-32 shrink-0 flex-col justify-center border-r border-border bg-foreground px-3 text-background">
            <span className="font-mono text-[8px] font-bold uppercase tracking-[0.14em] opacity-55">Market monitor</span>
            <span className="mt-1 text-[10px] font-semibold">Reference tape</span>
          </div>
          {MARKET_TAPE.map(([name, detail, exchange], index) => (
            <div key={name} className="grid min-w-[205px] grid-cols-[1fr_78px] items-center border-r border-border px-3 py-2.5 last:border-r-0">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] font-semibold">{name}</span>
                  <span className="font-mono text-[8px] text-muted-foreground">{exchange}</span>
                </div>
                <p className="mt-1 text-[9px] text-muted-foreground">{detail}</p>
              </div>
              <MiniChart variant={index + 1} />
            </div>
          ))}
        </div>
      </section>

      <section className="fade-in-up grid overflow-hidden border border-border bg-card [animation-delay:35ms] xl:grid-cols-[minmax(0,1.7fr)_370px]">
        <div className="relative overflow-hidden px-5 py-7 sm:px-8 sm:py-9 lg:px-10">
          <div className="terminal-grid absolute inset-0 opacity-35" />
          <div className="relative max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <span className="product-kicker"><Sparkles className="size-3" /> Institutional research workspace</span>
              <span className="font-mono text-[9px] uppercase tracking-[0.08em] text-muted-foreground">India · NSE main board</span>
            </div>
            <h1 className="mt-6 max-w-2xl text-[2.35rem] font-semibold leading-[1.02] tracking-[-0.052em] sm:text-[3.35rem]">
              Move from market question to <span className="text-primary">defensible evidence.</span>
            </h1>
            <p className="mt-5 max-w-2xl text-[13px] leading-6 text-muted-foreground sm:text-sm">
              Search what a company actually does, verify the numbers behind the narrative, and monitor quantitative signals—all in one India-first research system.
            </p>

            <Link href="/discover" className="research-command group mt-7">
              <span className="grid size-9 shrink-0 place-items-center bg-primary text-primary-foreground"><Search className="size-4" /></span>
              <span className="min-w-0 flex-1">
                <span className="block text-[12px] font-semibold">Ask EquityLens</span>
                <span className="mt-0.5 block truncate text-[10px] text-muted-foreground">Try “power infrastructure companies with improving quarterly revenue”</span>
              </span>
              <span className="hidden items-center gap-1 font-mono text-[9px] font-semibold uppercase tracking-[0.08em] text-primary sm:flex">Open research <ArrowRight className="size-3 transition-transform group-hover:translate-x-0.5" /></span>
            </Link>
          </div>
        </div>

        <div className="border-t border-border bg-terminal px-5 py-6 text-terminal-foreground xl:border-l xl:border-t-0">
          <div className="flex items-center justify-between border-b border-white/10 pb-3">
            <div>
              <p className="font-mono text-[8px] font-semibold uppercase tracking-[0.16em] text-white/45">System coverage</p>
              <p className="mt-1 text-[12px] font-semibold">Research infrastructure</p>
            </div>
            <span className="flex items-center gap-1.5 font-mono text-[8px] uppercase tracking-[0.1em] text-emerald-300"><span className="size-1.5 rounded-full bg-emerald-400" /> Operational</span>
          </div>
          <div className="mt-5 grid grid-cols-2 gap-px border border-white/10 bg-white/10">
            {[
              ["2,386", "NSE companies"],
              ["210+", "F&O underlyings"],
              ["Primary", "Evidence standard"],
              ["India", "Market focus"],
            ].map(([value, label]) => (
              <div key={label} className="bg-terminal p-3.5">
                <p className="font-mono text-[17px] font-semibold tracking-[-0.04em] text-white">{value}</p>
                <p className="mt-1 font-mono text-[8px] uppercase tracking-[0.1em] text-white/45">{label}</p>
              </div>
            ))}
          </div>
          <div className="mt-5 space-y-3">
            {["Annual reports & exchange filings", "Deterministic financial checks", "Source-grounded research chat"].map((item) => (
              <div key={item} className="flex items-center gap-2 text-[10px] text-white/70"><Check className="size-3 text-emerald-300" /> {item}</div>
            ))}
          </div>
          <Link href="/admin" className="mt-5 flex items-center justify-between border-t border-white/10 pt-3 font-mono text-[8px] uppercase tracking-[0.1em] text-white/45 hover:text-white">
            Inspect data coverage <ArrowUpRight className="size-3" />
          </Link>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_390px]">
        <div className="finance-surface fade-in-up [animation-delay:70ms]">
          <div className="panel-heading">
            <div>
              <p className="terminal-label">Research applications</p>
              <h2 className="mt-1 text-[15px] font-semibold tracking-[-0.02em]">Core workspaces</h2>
            </div>
            <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground">06 modules</span>
          </div>
          <div className="grid md:grid-cols-2">
            {WORKSPACES.map((workspace, index) => {
              const Icon = workspace.icon;
              return (
                <Link key={workspace.href} href={workspace.href} className={cnWorkspace(index)}>
                  <div className="flex items-start gap-3">
                    <span className="workspace-code">{workspace.code}</span>
                    <span className="ml-auto grid size-7 place-items-center border border-border bg-muted/50 text-muted-foreground transition-colors group-hover:border-primary/30 group-hover:text-primary"><Icon className="size-3.5" /></span>
                  </div>
                  <h3 className="mt-5 text-[13px] font-semibold">{workspace.title}</h3>
                  <p className="mt-2 min-h-10 text-[10px] leading-5 text-muted-foreground">{workspace.description}</p>
                  <div className="mt-4 flex items-center justify-between border-t border-border/75 pt-3">
                    <span className="font-mono text-[8px] uppercase tracking-[0.08em] text-muted-foreground">{workspace.meta}</span>
                    <ArrowRight className="size-3 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                  </div>
                </Link>
              );
            })}
          </div>
        </div>

        <div className="space-y-4">
          <div className="finance-surface fade-in-up [animation-delay:105ms]">
            <div className="panel-heading">
              <div><p className="terminal-label">Workflow</p><h2 className="mt-1 text-[15px] font-semibold">Built for auditable research</h2></div>
              <Layers3 className="size-4 text-muted-foreground" />
            </div>
            <div className="divide-y divide-border">
              {RESEARCH_STEPS.map(([number, title, description]) => (
                <div key={number} className="grid grid-cols-[28px_1fr] gap-3 px-4 py-4">
                  <span className="font-mono text-[9px] font-semibold text-primary">{number}</span>
                  <div><p className="text-[11px] font-semibold">{title}</p><p className="mt-1 text-[10px] leading-4.5 text-muted-foreground">{description}</p></div>
                </div>
              ))}
            </div>
          </div>

          <div className="finance-surface fade-in-up [animation-delay:140ms]">
            <div className="panel-heading"><div><p className="terminal-label">Resume</p><h2 className="mt-1 text-[15px] font-semibold">Recent workflows</h2></div><Clock3 className="size-4 text-muted-foreground" /></div>
            <div className="divide-y divide-border">
              {RECENT.map(([title, type, meta], index) => (
                <Link key={title} href={index === 0 ? "/discover" : index === 1 ? "/trade-suggestions" : "/block-deals"} className="group flex items-center gap-3 px-4 py-3.5 hover:bg-muted/45">
                  <span className="grid size-7 place-items-center border border-border bg-background font-mono text-[8px] font-semibold text-muted-foreground">0{index + 1}</span>
                  <span className="min-w-0 flex-1"><span className="block truncate text-[10px] font-semibold">{title}</span><span className="mt-1 block font-mono text-[8px] uppercase tracking-[0.08em] text-muted-foreground">{type} · {meta}</span></span>
                  <ChevronRight className="size-3 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                </Link>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-px overflow-hidden border border-border bg-border sm:grid-cols-3">
        {[
          [ShieldCheck, "Evidence first", "Semantic results trace back to annual reports and exchange filings."],
          [Database, "Math outside the model", "Growth, filters and scores are computed deterministically."],
          [Activity, "Research, not advice", "Scenarios and rankings are clearly bounded and never framed as calls."],
        ].map(([Icon, title, description]) => {
          const ItemIcon = Icon as typeof BarChart3;
          return <div key={String(title)} className="flex gap-3 bg-card p-4"><ItemIcon className="mt-0.5 size-3.5 shrink-0 text-primary" /><div><p className="text-[10px] font-semibold">{String(title)}</p><p className="mt-1 text-[9px] leading-4 text-muted-foreground">{String(description)}</p></div></div>;
        })}
      </section>
    </div>
  );
}

function cnWorkspace(index: number) {
  return `group block p-4 transition-colors hover:bg-accent/45 sm:p-5 ${index < 4 ? "border-b border-border" : ""} ${index % 2 === 0 ? "md:border-r md:border-border" : ""}`;
}
