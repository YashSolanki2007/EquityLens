import { Button } from "@/components/ui/button";
import {
  ArrowRight,
  BarChart3,
  Building2,
  CandlestickChart,
  ChartNoAxesCombined,
  CheckCircle2,
  Database,
  FileSearch2,
  Handshake,
  Newspaper,
  Search,
  ShieldCheck,
  Shuffle,
  Sparkles,
  TrendingUp,
  WalletCards,
} from "lucide-react";
import Link from "next/link";

const WORKSPACES = [
  {
    href: "/discover",
    label: "Research",
    title: "Company discovery",
    description: "Find NSE businesses by operating model, exposure and financial criteria.",
    icon: FileSearch2,
    tone: "bg-blue-500/10 text-blue-600 dark:bg-emerald-400/10 dark:text-emerald-400",
  },
  {
    href: "/technical",
    label: "Screen",
    title: "Algo scanner",
    description: "Combine RSI, momentum, volume and price conditions across F&O stocks.",
    icon: ChartNoAxesCombined,
    tone: "bg-violet-500/10 text-violet-600 dark:bg-violet-400/10 dark:text-violet-400",
  },
  {
    href: "/trade-suggestions",
    label: "Relative value",
    title: "Pair trades",
    description: "Review statistically related futures pairs with spread diagnostics.",
    icon: Shuffle,
    tone: "bg-amber-500/10 text-amber-700 dark:bg-amber-400/10 dark:text-amber-400",
  },
  {
    href: "/trade-tracker",
    label: "Monitor",
    title: "Trade tracker",
    description: "Track active research ideas, entry context and subsequent performance.",
    icon: WalletCards,
    tone: "bg-emerald-500/10 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-400",
  },
  {
    href: "/block-deals",
    label: "Flows",
    title: "Block deals",
    description: "Inspect recent institutional transactions, prices, buyers and sellers.",
    icon: Handshake,
    tone: "bg-rose-500/10 text-rose-700 dark:bg-rose-400/10 dark:text-rose-400",
  },
  {
    href: "/market",
    label: "Macro",
    title: "India market pulse",
    description: "Read source-linked developments affecting Indian equity markets.",
    icon: Newspaper,
    tone: "bg-cyan-500/10 text-cyan-700 dark:bg-cyan-400/10 dark:text-cyan-400",
  },
] as const;

const CAPABILITIES = [
  ["Company universe", "2,386", "NSE main-board equities"],
  ["Derivatives universe", "210+", "F&O underlyings"],
  ["Evidence", "Primary", "Annual reports and filings"],
  ["Market scope", "India", "NSE-focused research"],
] as const;

const COMPANY_TOOLS = [
  { title: "Market & valuation", icon: BarChart3 },
  { title: "Financial statements", icon: Database },
  { title: "Options & volatility", icon: CandlestickChart },
  { title: "Filings & evidence", icon: ShieldCheck },
] as const;

function MarketVisual() {
  return (
    <div className="soft-grid relative min-h-[290px] overflow-hidden border-t border-white/10 lg:min-h-0 lg:border-l lg:border-t-0">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_62%_44%,rgba(52,211,153,0.18),transparent_31%),radial-gradient(circle_at_24%_72%,rgba(59,130,246,0.16),transparent_26%)]" />
      <div className="absolute left-[9%] top-[12%] rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-[10px] font-medium text-white/70 backdrop-blur">
        Filing-grounded discovery
      </div>
      <div className="absolute right-[8%] top-[13%] flex items-center gap-2 rounded-lg border border-white/15 bg-black/25 px-3 py-2 backdrop-blur-md">
        <span className="size-1.5 rounded-full bg-emerald-400" />
        <span className="font-mono text-[10px] text-white/70">NSE UNIVERSE</span>
      </div>

      <svg viewBox="0 0 520 300" className="absolute inset-x-0 bottom-0 h-[88%] w-full" aria-hidden="true">
        <defs>
          <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#34d399" stopOpacity="0.26" />
            <stop offset="100%" stopColor="#34d399" stopOpacity="0" />
          </linearGradient>
          <filter id="glow"><feGaussianBlur stdDeviation="4" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>
        <path d="M0 252 C42 245 49 222 83 228 C112 232 126 204 158 211 C195 219 205 177 239 186 C276 196 287 145 323 157 C354 167 372 120 402 129 C438 139 454 82 520 54 L520 300 L0 300Z" fill="url(#area)" />
        <path d="M0 252 C42 245 49 222 83 228 C112 232 126 204 158 211 C195 219 205 177 239 186 C276 196 287 145 323 157 C354 167 372 120 402 129 C438 139 454 82 520 54" fill="none" stroke="#6ee7b7" strokeWidth="2.5" strokeLinecap="round" filter="url(#glow)" />
        {[96, 150, 204, 258, 312, 366, 420].map((x, i) => {
          const tops = [178, 205, 155, 165, 119, 101, 65];
          const bottoms = [238, 244, 220, 210, 180, 158, 142];
          const open = tops[i] + 17;
          const close = bottoms[i] - 13;
          return <g key={x} opacity="0.75"><line x1={x} y1={tops[i]} x2={x} y2={bottoms[i]} stroke={i === 1 || i === 4 ? "#fb7185" : "#6ee7b7"} /><rect x={x - 4} y={Math.min(open, close)} width="8" height={Math.abs(close - open)} rx="1" fill={i === 1 || i === 4 ? "#fb7185" : "#6ee7b7"} /></g>;
        })}
        <circle cx="454" cy="82" r="5" fill="#6ee7b7" filter="url(#glow)" />
      </svg>

      <div className="absolute bottom-[10%] left-[9%] rounded-xl border border-white/15 bg-[#101215]/75 p-3.5 shadow-2xl backdrop-blur-md">
        <p className="font-mono text-[9px] uppercase tracking-widest text-white/45">Semantic match</p>
        <div className="mt-2 flex items-end gap-4">
          <div><p className="text-sm font-semibold text-white">Power infrastructure</p><p className="mt-1 text-[10px] text-white/50">18 companies · evidence verified</p></div>
          <span className="font-mono text-sm font-semibold text-emerald-400">94%</span>
        </div>
      </div>
    </div>
  );
}

export default function HomePage() {
  return (
    <div className="space-y-6 pb-5">
      <section className="fade-in-up overflow-hidden rounded-2xl bg-[#101828] text-white shadow-[0_24px_70px_rgba(15,23,42,0.16)] dark:bg-[#191a1d] dark:shadow-[0_24px_70px_rgba(0,0,0,0.34)]">
        <div className="grid lg:grid-cols-[1.05fr_0.95fr]">
          <div className="relative z-10 flex min-h-[330px] flex-col justify-center p-6 sm:p-9 lg:p-11">
            <div className="mb-5 flex w-fit items-center gap-2 rounded-full border border-white/10 bg-white/[0.06] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.13em] text-emerald-300">
              <Sparkles className="size-3" /> India equity intelligence
            </div>
            <h1 className="max-w-xl text-4xl font-semibold leading-[1.03] tracking-[-0.05em] sm:text-5xl">
              Know the business.<br /><span className="text-emerald-300">See the signal.</span>
            </h1>
            <p className="mt-5 max-w-lg text-sm leading-6 text-slate-300">
              Search companies by what they actually do, connect financial data to primary evidence, and turn market complexity into a clear research workflow.
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-3">
              <Button asChild size="lg" className="bg-white text-slate-950 hover:bg-emerald-100">
                <Link href="/discover">Explore companies <ArrowRight className="size-4" /></Link>
              </Button>
              <Link href="/market" className="inline-flex h-10 items-center gap-2 px-2 text-xs font-semibold text-white/75 transition-colors hover:text-white">
                View market pulse <TrendingUp className="size-3.5" />
              </Link>
            </div>
          </div>
          <MarketVisual />
        </div>
      </section>

      <Link href="/discover" className="fade-in-up group flex min-h-16 items-center gap-4 rounded-xl border border-border bg-card px-4 shadow-[0_8px_28px_rgba(15,23,42,0.045)] transition-all hover:-translate-y-0.5 hover:border-primary/35 hover:shadow-[0_14px_36px_rgba(15,23,42,0.08)] dark:shadow-[0_10px_28px_rgba(0,0,0,0.18)] sm:px-5">
        <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground shadow-sm"><Search className="size-4" /></span>
        <div className="min-w-0 flex-1"><p className="text-sm font-semibold">Search the NSE company universe</p><p className="mt-0.5 truncate text-xs text-muted-foreground">Try “power transmission companies above ₹50,000 crore market cap”</p></div>
        <span className="hidden items-center gap-2 text-xs font-semibold text-primary sm:flex">Open discovery <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" /></span>
      </Link>

      <section className="fade-in-up grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border shadow-[0_8px_30px_rgba(15,23,42,0.04)] [animation-delay:40ms] xl:grid-cols-4">
        {CAPABILITIES.map(([label, value, detail]) => <div key={label} className="bg-card px-4 py-4 transition-colors hover:bg-accent/30 sm:px-5"><p className="terminal-label">{label}</p><p className="metric-value mt-2">{value}</p><p className="mt-1 text-[11px] text-muted-foreground">{detail}</p></div>)}
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.65fr)_350px]">
        <div className="dashboard-panel">
          <div className="finance-panel-header"><div><h2 className="text-sm font-semibold">Research workspaces</h2><p className="mt-1 text-xs text-muted-foreground">One place for fundamental, quantitative and market research.</p></div><span className="font-mono text-[10px] text-muted-foreground">06 modules</span></div>
          <div className="grid md:grid-cols-2">
            {WORKSPACES.map((workspace, index) => {
              const Icon = workspace.icon;
              return <Link key={workspace.title} href={workspace.href} className={`group flex min-h-32 gap-3.5 p-5 transition-all hover:bg-accent/25 ${index < WORKSPACES.length - 2 ? "border-b border-border" : ""} ${index % 2 === 0 ? "md:border-r" : ""}`}>
                <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${workspace.tone}`}><Icon className="size-[18px]" /></span>
                <div className="min-w-0 flex-1"><p className="terminal-label">{workspace.label}</p><h3 className="mt-1.5 text-sm font-semibold">{workspace.title}</h3><p className="mt-2 text-xs leading-5 text-muted-foreground">{workspace.description}</p></div>
                <ArrowRight className="mt-1 size-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
              </Link>;
            })}
          </div>
        </div>

        <div className="space-y-5">
          <div className="dashboard-panel">
            <div className="finance-panel-header"><h2 className="text-sm font-semibold">Company workspace</h2><Building2 className="size-4 text-muted-foreground" /></div>
            <div className="divide-y divide-border">{COMPANY_TOOLS.map((tool) => { const Icon = tool.icon; return <div key={tool.title} className="flex items-center gap-3 px-5 py-4 text-xs"><span className="grid size-7 place-items-center rounded-lg bg-accent text-primary"><Icon className="size-3.5" /></span><span className="font-medium">{tool.title}</span><CheckCircle2 className="ml-auto size-3.5 text-emerald-600 dark:text-emerald-400" /></div>; })}</div>
            <div className="border-t border-border p-4"><Button asChild className="w-full" size="sm"><Link href="/discover">Find a company <ArrowRight className="size-3.5" /></Link></Button></div>
          </div>
          <div className="rounded-xl border border-emerald-600/15 bg-gradient-to-br from-emerald-50 to-white p-5 dark:border-white/10 dark:from-[#20221f] dark:to-[#191a1d]">
            <div className="flex items-start gap-3"><ShieldCheck className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" /><div><p className="text-xs font-semibold">Research standard</p><p className="mt-1.5 text-[11px] leading-5 text-muted-foreground">Semantic matches are filing-grounded. Market data is labeled when delayed or unverified. Scenarios are not price targets.</p><Link href="/admin" className="mt-3 inline-flex items-center gap-1 text-[11px] font-semibold text-primary hover:underline">Review data coverage <ArrowRight className="size-3" /></Link></div></div>
          </div>
        </div>
      </section>
    </div>
  );
}
