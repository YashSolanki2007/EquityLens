"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  FlaskConical,
  Gauge,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Metrics = {
  fast_span?: number;
  slow_span?: number;
  cagr: number | null;
  annualized_volatility: number | null;
  sharpe_zero_cash: number | null;
  sortino_zero_cash: number | null;
  annualized_downside_deviation: number | null;
  max_drawdown: number | null;
  total_return: number | null;
  market_beta: number | null;
  benchmark_cagr: number | null;
  benchmark_annualized_volatility: number | null;
  benchmark_sharpe_zero_cash: number | null;
  benchmark_sortino_zero_cash: number | null;
  benchmark_max_drawdown: number | null;
  benchmark_total_return: number | null;
  time_in_market: number | null;
  entries: number;
  exits: number;
  turnover_cost_sum?: number | null;
};

type CrossMarketRow = {
  symbol: string;
  name: string;
  latest_position: string;
  trend_score: number | null;
  cagr: number | null;
  original_cagr: number | null;
  benchmark_cagr: number | null;
  cagr_delta_original: number | null;
  sharpe: number | null;
  original_sharpe: number | null;
  benchmark_sharpe: number | null;
  sharpe_delta_original: number | null;
  sortino: number | null;
  original_sortino: number | null;
  benchmark_sortino: number | null;
  sortino_delta_original: number | null;
  max_drawdown: number | null;
  original_max_drawdown: number | null;
  benchmark_max_drawdown: number | null;
  drawdown_delta_original: number | null;
  market_beta: number | null;
  time_in_market: number | null;
  entries: number;
};

type AlternativeSignalReport = {
  generated_at: string;
  source: string;
  evaluation_start: string;
  evaluation_end: string;
  name: string;
  formula: string;
  assumptions: {
    fast_span: number;
    slow_span: number;
    volatility_span: number;
    score_horizon_gap: number;
    entry_threshold: number;
    one_way_cost: number;
    execution: string;
    positioning: string;
    cash_return: number;
    dividends: string;
    parameter_policy: string;
  };
  primary_metrics: Metrics;
  original_metrics: Metrics;
  latest_signal: {
    date: string;
    position: string;
    trend_score: number | null;
    ema_spread: number | null;
    fast_ema: number | null;
    slow_ema: number | null;
    daily_sd: number | null;
    annualized_sd: number | null;
  };
  comparison: {
    cagr_delta_original: number | null;
    sharpe_delta_original: number | null;
    sortino_delta_original: number | null;
    drawdown_delta_original: number | null;
    total_return_delta_original: number | null;
  };
  chart: Array<{
    date: string;
    candidate_equity: number | null;
    original_equity: number | null;
    benchmark_equity: number | null;
    candidate_drawdown: number | null;
    original_drawdown: number | null;
    benchmark_drawdown: number | null;
    trend_score: number | null;
    ema_spread: number | null;
    fast_ema: number | null;
    slow_ema: number | null;
    position: number | null;
    annualized_sd: number | null;
  }>;
  yearly_returns: Array<{
    year: number;
    candidate: number | null;
    original: number | null;
    benchmark: number | null;
    time_in_market: number | null;
    switches: number;
  }>;
  subperiods: Array<{
    period: string;
    start: string;
    end: string;
    cagr: number | null;
    benchmark_cagr: number | null;
    sharpe: number | null;
    benchmark_sharpe: number | null;
    sortino: number | null;
    benchmark_sortino: number | null;
    max_drawdown: number | null;
    benchmark_max_drawdown: number | null;
  }>;
  sensitivity: Metrics[];
  cross_market: {
    frozen_parameters: string;
    large_cap_selection: string;
    groups: Array<{
      name: string;
      summary: {
        count: number;
        cagr_wins_vs_original: number;
        sharpe_wins_vs_original: number;
        sortino_wins_vs_original: number;
        drawdown_wins_vs_original: number;
        median_cagr_delta_original: number | null;
        median_sharpe_delta_original: number | null;
        median_sortino_delta_original: number | null;
        median_drawdown_delta_original: number | null;
        cagr_wins_vs_benchmark: number;
        sharpe_wins_vs_benchmark: number;
      };
      rows: CrossMarketRow[];
    }>;
  } | null;
  design_rationale: string[];
  limitations: string[];
};

const CANDIDATE = "#059669";
const ORIGINAL = "#9333ea";
const BENCHMARK = "#2563eb";

function percent(value: number | null | undefined, digits = 1) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
}

function probability(value: number | null | undefined, digits = 1) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

function number(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat("en-IN", { month: "short", year: "2-digit" }).format(new Date(`${value}T00:00:00`));
}

function fullDate(value: string) {
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" }).format(new Date(`${value}T00:00:00`));
}

function Metric({ label, value, old, benchmark, detail }: { label: string; value: string; old?: string; benchmark?: string; detail: string }) {
  return (
    <div className="bg-card px-4 py-4 sm:px-5">
      <p className="terminal-label">{label}</p>
      <p className="mt-3 font-mono text-2xl font-semibold tracking-[-0.04em] tabular-nums">{value}</p>
      <p className="mt-2 font-mono text-[10px] text-muted-foreground">
        {old ? `Original ${old}` : ""}{old && benchmark ? " · " : ""}{benchmark ? `B&H ${benchmark}` : ""}
      </p>
      <p className="mt-1 text-[10px] leading-4 text-muted-foreground">{detail}</p>
    </div>
  );
}

type TooltipItem = { name?: string; value?: number; color?: string };

function ChartTooltip({ active, payload, label, format = "percent" }: { active?: boolean; payload?: TooltipItem[]; label?: string | number; format?: "percent" | "equity" | "number" }) {
  if (!active || !payload?.length) return null;
  const text = typeof label === "string" && label.includes("-") ? fullDate(label) : String(label ?? "");
  const formatValue = (value: number | undefined) => {
    if (format === "equity") return `${number(value, 2)}×`;
    if (format === "number") return number(value, 3);
    return percent(value, 1);
  };
  return (
    <div className="min-w-44 rounded-md border border-border bg-card/95 p-3 text-xs shadow-xl backdrop-blur">
      <p className="mb-2 font-medium">{text}</p>
      <div className="space-y-1.5">
        {payload.map((item) => (
          <div key={item.name} className="flex items-center justify-between gap-5">
            <span className="flex items-center gap-1.5 text-muted-foreground"><span className="size-2 rounded-full" style={{ background: item.color }} />{item.name}</span>
            <span className="font-mono font-semibold">{formatValue(item.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AlternativeSignalView({ report }: { report: AlternativeSignalReport }) {
  const metrics = report.primary_metrics;
  const original = report.original_metrics;
  const latest = report.latest_signal;
  const isLong = latest.position === "long";
  const crossRows = report.cross_market?.groups.flatMap((group) => group.rows) ?? [];

  return (
    <div className="space-y-5 py-6">
      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="grid xl:grid-cols-[minmax(0,1fr)_430px]">
          <div className="px-5 py-6 sm:px-7 sm:py-7">
            <div className="flex flex-wrap items-center gap-2">
              <p className="page-eyebrow">System · candidate branch</p>
              <Badge variant="outline"><FlaskConical className="mr-1 size-3" /> Frozen 21/63 rule</Badge>
            </div>
            <h1 className="mt-3 text-3xl font-semibold tracking-[-0.045em] sm:text-[2.5rem]">Alternative signal</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
              A month-versus-quarter EMA regime filter. It stays long while the 21-session trend is above the 63-session trend and otherwise holds cash. Volatility scales the diagnostic score only; it is not another entry hurdle.
            </p>
            <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-[11px] text-muted-foreground">
              <span>{fullDate(report.evaluation_start)} – {fullDate(report.evaluation_end)}</span>
              <span>{metrics.entries} entries · {metrics.exits} exits</span>
              <span>10 bps one-way cost</span>
              <Link href="/custom-signal" className="inline-flex items-center gap-1 font-semibold text-primary hover:underline"><ArrowLeft className="size-3" /> Original model</Link>
            </div>
          </div>
          <div className="border-t border-border bg-[#202720] px-5 py-6 text-white xl:border-l xl:border-t-0 sm:px-7">
            <div className="flex items-center justify-between gap-3">
              <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-300">Latest · {fullDate(latest.date)}</p>
              <Badge className={isLong ? "bg-emerald-400 text-emerald-950" : "bg-white/10 text-white"}>{isLong ? "LONG" : "CASH"}</Badge>
            </div>
            <p className="mt-4 font-mono text-4xl font-semibold tracking-[-0.05em]">{number(latest.trend_score, 2)}</p>
            <p className="mt-1 text-xs text-white/55">Volatility-normalized EMA distance; zero is the only threshold</p>
            <div className="mt-5 grid grid-cols-3 gap-px overflow-hidden rounded-md bg-white/10">
              <div className="bg-white/[0.04] p-3"><p className="text-[9px] uppercase tracking-[0.1em] text-white/45">EMA spread</p><p className="mt-1 font-mono text-sm font-semibold text-emerald-300">{percent(latest.ema_spread, 2)}</p></div>
              <div className="bg-white/[0.04] p-3"><p className="text-[9px] uppercase tracking-[0.1em] text-white/45">Daily SD</p><p className="mt-1 font-mono text-sm font-semibold">{probability(latest.daily_sd, 2)}</p></div>
              <div className="bg-white/[0.04] p-3"><p className="text-[9px] uppercase tracking-[0.1em] text-white/45">Annual SD</p><p className="mt-1 font-mono text-sm font-semibold">{probability(latest.annualized_sd)}</p></div>
            </div>
            <p className="mt-3 text-[11px] text-white/55">EMA 21 {number(latest.fast_ema, 0)} · EMA 63 {number(latest.slow_ema, 0)}</p>
          </div>
        </div>
        <div className="grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-6">
          <Metric label="Annualized return" value={percent(metrics.cagr)} old={percent(original.cagr)} benchmark={percent(metrics.benchmark_cagr)} detail={`Improvement ${percent(report.comparison.cagr_delta_original)}`} />
          <Metric label="Sharpe · 0% cash" value={number(metrics.sharpe_zero_cash)} old={number(original.sharpe_zero_cash)} benchmark={number(metrics.benchmark_sharpe_zero_cash)} detail={`Change ${number(report.comparison.sharpe_delta_original)}`} />
          <Metric label="Sortino · 0% MAR" value={number(metrics.sortino_zero_cash)} old={number(original.sortino_zero_cash)} benchmark={number(metrics.benchmark_sortino_zero_cash)} detail={`Change ${number(report.comparison.sortino_delta_original)}`} />
          <Metric label="Maximum drawdown" value={percent(metrics.max_drawdown)} old={percent(original.max_drawdown)} benchmark={percent(metrics.benchmark_max_drawdown)} detail={`Improvement ${percent(report.comparison.drawdown_delta_original)}`} />
          <Metric label="Total return" value={percent(metrics.total_return, 0)} old={percent(original.total_return, 0)} benchmark={percent(metrics.benchmark_total_return, 0)} detail={`₹1 became ₹${number(1 + (metrics.total_return ?? 0), 2)}`} />
          <Metric label="Market beta" value={number(metrics.market_beta)} old={number(original.market_beta)} benchmark="1.00" detail={`${probability(metrics.time_in_market)} time invested`} />
        </div>
      </section>

      <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/7 px-5 py-4 text-xs leading-5 text-muted-foreground">
        <span className="font-semibold text-foreground">Primary result:</span> on the identical NIFTY 50 window, the candidate improved CAGR by {percent(report.comparison.cagr_delta_original)}, Sharpe by {number(report.comparison.sharpe_delta_original)}, Sortino by {number(report.comparison.sortino_delta_original)}, and maximum drawdown by {percent(report.comparison.drawdown_delta_original)} versus the original signal. It still trails buy-and-hold CAGR, so this is better downside control—not demonstrated alpha.
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(340px,0.85fr)]">
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><Activity className="size-4 text-emerald-600" /> Growth of ₹1</CardTitle></CardHeader>
          <CardContent className="pt-5">
            <div className="h-[350px]"><ResponsiveContainer width="100%" height="100%"><AreaChart data={report.chart}><defs><linearGradient id="alternativeFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={CANDIDATE} stopOpacity={0.2} /><stop offset="100%" stopColor={CANDIDATE} stopOpacity={0} /></linearGradient></defs><CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" /><XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={48} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tickFormatter={(value) => `${value.toFixed(1)}×`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip content={<ChartTooltip format="equity" />} /><Legend wrapperStyle={{ fontSize: 11 }} /><Area type="monotone" dataKey="candidate_equity" name="Alternative" stroke={CANDIDATE} fill="url(#alternativeFill)" strokeWidth={2.3} dot={false} /><Line type="monotone" dataKey="original_equity" name="Original" stroke={ORIGINAL} strokeWidth={1.5} dot={false} /><Line type="monotone" dataKey="benchmark_equity" name="NIFTY 50" stroke={BENCHMARK} strokeWidth={1.5} dot={false} /></AreaChart></ResponsiveContainer></div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><Gauge className="size-4 text-blue-600" /> What changed</CardTitle></CardHeader>
          <CardContent className="space-y-3 pt-5">
            {report.design_rationale.map((item) => <div key={item} className="flex gap-2.5 text-xs leading-5 text-muted-foreground"><CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /><p>{item}</p></div>)}
            <div className="border-t border-border pt-4"><p className="terminal-label">Exact rule</p><p className="mt-2 font-mono text-[10px] leading-5 text-muted-foreground">{report.formula}</p></div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Trend score and position</CardTitle></CardHeader>
          <CardContent className="pt-5"><div className="h-[300px]"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={report.chart}><CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" /><XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={48} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis domain={["auto", "auto"]} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip content={<ChartTooltip format="number" />} /><ReferenceLine y={0} stroke="var(--foreground)" strokeOpacity={0.5} /><Area type="stepAfter" dataKey="position" name="Position" fill={CANDIDATE} fillOpacity={0.08} stroke="none" /><Line type="monotone" dataKey="trend_score" name="Normalized trend" stroke={CANDIDATE} strokeWidth={1.7} dot={false} /></ComposedChart></ResponsiveContainer></div><p className="mt-3 text-[10px] leading-4 text-muted-foreground">Positive score: the fast EMA is above the slow EMA. The volatility denominator changes scale but cannot change the sign or trade decision.</p></CardContent>
        </Card>
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="size-4 text-emerald-600" /> Drawdown comparison</CardTitle></CardHeader>
          <CardContent className="pt-5"><div className="h-[300px]"><ResponsiveContainer width="100%" height="100%"><AreaChart data={report.chart}><CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" /><XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={48} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tickFormatter={(value) => `${Math.round(value * 100)}%`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip content={<ChartTooltip />} /><Area type="monotone" dataKey="benchmark_drawdown" name="NIFTY 50" stroke={BENCHMARK} fill={BENCHMARK} fillOpacity={0.04} dot={false} /><Area type="monotone" dataKey="original_drawdown" name="Original" stroke={ORIGINAL} fill={ORIGINAL} fillOpacity={0.05} dot={false} /><Area type="monotone" dataKey="candidate_drawdown" name="Alternative" stroke={CANDIDATE} fill={CANDIDATE} fillOpacity={0.12} dot={false} /></AreaChart></ResponsiveContainer></div></CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="border-b border-border/70"><div><CardTitle className="text-base">Calendar-year returns</CardTitle><p className="mt-1 text-[11px] text-muted-foreground">Candidate, original probability model, and buy-and-hold over identical dates.</p></div></CardHeader>
        <CardContent className="pt-5"><div className="h-[330px]"><ResponsiveContainer width="100%" height="100%"><BarChart data={report.yearly_returns}><CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" /><XAxis dataKey="year" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tickFormatter={(value) => `${Math.round(value * 100)}%`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip content={<ChartTooltip />} /><Legend wrapperStyle={{ fontSize: 11 }} /><Bar dataKey="candidate" name="Alternative" fill={CANDIDATE} radius={[2, 2, 0, 0]} /><Bar dataKey="original" name="Original" fill={ORIGINAL} radius={[2, 2, 0, 0]} /><Bar dataKey="benchmark" name="NIFTY 50" fill={BENCHMARK} radius={[2, 2, 0, 0]} /></BarChart></ResponsiveContainer></div></CardContent>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Subperiod stability</CardTitle></CardHeader>
          <CardContent className="pt-5"><div className="overflow-x-auto"><table className="data-table min-w-[650px]"><thead><tr><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Sortino</th><th>Max drawdown</th></tr></thead><tbody>{report.subperiods.map((row) => <tr key={row.period}><td className="font-mono font-semibold">{row.period}</td><td><p className="font-mono font-semibold">{percent(row.cagr)}</p><p className="text-[9px] text-muted-foreground">B&H {percent(row.benchmark_cagr)}</p></td><td><p className="font-mono font-semibold">{number(row.sharpe)}</p><p className="text-[9px] text-muted-foreground">B&H {number(row.benchmark_sharpe)}</p></td><td><p className="font-mono font-semibold">{number(row.sortino)}</p><p className="text-[9px] text-muted-foreground">B&H {number(row.benchmark_sortino)}</p></td><td><p className="font-mono font-semibold">{percent(row.max_drawdown)}</p><p className="text-[9px] text-muted-foreground">B&H {percent(row.benchmark_max_drawdown)}</p></td></tr>)}</tbody></table></div></CardContent>
        </Card>
        <Card>
          <CardHeader className="border-b border-border/70"><div><CardTitle className="text-base">Neighboring-window sensitivity</CardTitle><p className="mt-1 text-[11px] text-muted-foreground">The default is not replaced by the best-looking row.</p></div></CardHeader>
          <CardContent className="pt-5"><div className="overflow-x-auto"><table className="data-table min-w-[650px]"><thead><tr><th>Fast / slow</th><th>CAGR</th><th>Sharpe</th><th>Sortino</th><th>Max drawdown</th></tr></thead><tbody>{report.sensitivity.map((row) => <tr key={`${row.fast_span}-${row.slow_span}`} className={row.fast_span === report.assumptions.fast_span && row.slow_span === report.assumptions.slow_span ? "bg-accent/45" : ""}><td className="font-mono font-semibold">{row.fast_span} / {row.slow_span}</td><td className="font-mono">{percent(row.cagr)}</td><td className="font-mono">{number(row.sharpe_zero_cash)}</td><td className="font-mono">{number(row.sortino_zero_cash)}</td><td className="font-mono">{percent(row.max_drawdown)}</td></tr>)}</tbody></table></div><p className="mt-3 text-[10px] leading-4 text-muted-foreground">Highlighted: frozen month/quarter pair. Similar outcomes around 15–21 fast and 45–63 slow are more reassuring than one isolated optimum.</p></CardContent>
        </Card>
      </div>

      {report.cross_market ? <section className="space-y-5">
        <div><p className="page-eyebrow">Frozen transfer test</p><h2 className="mt-1 text-xl font-semibold tracking-[-0.025em]">Indian indices and large caps</h2><p className="mt-1 max-w-4xl text-xs leading-5 text-muted-foreground">Every asset uses the same 21/63 settings and its original model&apos;s evaluation start. Positive bars mean the alternative produced a higher Sharpe than the original.</p></div>
        <div className="grid gap-3 md:grid-cols-2">{report.cross_market.groups.map((group) => <Card key={group.name}><CardContent className="pt-5"><div className="flex items-start justify-between gap-3"><div><p className="terminal-label">{group.name}</p><p className="mt-2 text-lg font-semibold">Alternative vs original</p></div><Badge variant="outline">{group.summary.count} assets</Badge></div><div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4"><div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">CAGR wins</p><p className="mt-1 font-mono font-semibold">{group.summary.cagr_wins_vs_original}/{group.summary.count}</p></div><div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Sharpe wins</p><p className="mt-1 font-mono font-semibold">{group.summary.sharpe_wins_vs_original}/{group.summary.count}</p></div><div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Sortino wins</p><p className="mt-1 font-mono font-semibold">{group.summary.sortino_wins_vs_original}/{group.summary.count}</p></div><div className="rounded-md bg-emerald-500/8 p-3"><p className="terminal-label">DD wins</p><p className="mt-1 font-mono font-semibold text-emerald-700 dark:text-emerald-300">{group.summary.drawdown_wins_vs_original}/{group.summary.count}</p></div></div><p className="mt-3 text-[11px] text-muted-foreground">Median CAGR change {percent(group.summary.median_cagr_delta_original)} · Sharpe change {number(group.summary.median_sharpe_delta_original)}</p></CardContent></Card>)}</div>
        <Card><CardHeader className="border-b border-border/70"><CardTitle className="text-base">Sharpe change versus original model</CardTitle></CardHeader><CardContent className="pt-5"><div style={{ height: Math.max(440, crossRows.length * 28) }}><ResponsiveContainer width="100%" height="100%"><BarChart data={crossRows} layout="vertical" margin={{ top: 4, right: 18, left: 20, bottom: 0 }}><CartesianGrid horizontal={false} stroke="var(--border)" strokeDasharray="3 3" /><XAxis type="number" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis type="category" dataKey="name" width={142} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip content={<ChartTooltip format="number" />} /><ReferenceLine x={0} stroke="var(--foreground)" strokeOpacity={0.45} /><Bar dataKey="sharpe_delta_original" name="Sharpe change" fill={CANDIDATE} radius={[0, 2, 2, 0]} /></BarChart></ResponsiveContainer></div></CardContent></Card>
        {report.cross_market.groups.map((group) => <Card key={`${group.name}-table`}><CardHeader className="border-b border-border/70"><CardTitle className="text-base">{group.name}</CardTitle></CardHeader><CardContent className="pt-5"><div className="overflow-x-auto"><table className="data-table min-w-[1050px]"><thead><tr><th>Asset</th><th>CAGR</th><th>Sharpe</th><th>Sortino</th><th>Max drawdown</th><th>Beta</th><th>Invested</th><th>Latest</th></tr></thead><tbody>{group.rows.map((row) => <tr key={row.symbol}><td><p className="font-semibold">{row.name}</p><p className="mt-0.5 font-mono text-[9px] text-muted-foreground">{row.symbol}</p></td><td><p className="font-mono font-semibold">{percent(row.cagr)}</p><p className="text-[9px] text-muted-foreground">Old {percent(row.original_cagr)} · B&H {percent(row.benchmark_cagr)}</p></td><td><p className="font-mono font-semibold">{number(row.sharpe)}</p><p className="text-[9px] text-muted-foreground">Old {number(row.original_sharpe)} · B&H {number(row.benchmark_sharpe)}</p></td><td><p className="font-mono font-semibold">{number(row.sortino)}</p><p className="text-[9px] text-muted-foreground">Old {number(row.original_sortino)}</p></td><td><p className="font-mono font-semibold">{percent(row.max_drawdown)}</p><p className="text-[9px] text-muted-foreground">Old {percent(row.original_max_drawdown)}</p></td><td className="font-mono">{number(row.market_beta)}</td><td className="font-mono">{probability(row.time_in_market)}</td><td><Badge variant="outline">{row.latest_position.toUpperCase()}</Badge></td></tr>)}</tbody></table></div></CardContent></Card>)}
        <div className="rounded-lg border border-blue-500/20 bg-blue-500/6 px-5 py-4 text-xs leading-5 text-muted-foreground"><span className="font-semibold text-foreground">Reading the transfer test:</span> the alternative beat the original on most Indian indices and roughly half of large-cap risk metrics, but it beat buy-and-hold on neither CAGR nor Sharpe across this panel. {report.cross_market.large_cap_selection}.</div>
      </section> : null}

      <section className="rounded-lg border border-amber-500/25 bg-amber-500/7 px-5 py-4">
        <div className="flex gap-3"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-300" /><div className="text-xs leading-5 text-muted-foreground"><p className="font-semibold text-foreground">What can still go wrong</p><ul className="mt-2 space-y-1">{report.limitations.map((item) => <li key={item}>• {item}</li>)}</ul><p className="mt-3 font-mono text-[10px]">{report.source} · generated {new Date(report.generated_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}</p></div></div>
      </section>
    </div>
  );
}
