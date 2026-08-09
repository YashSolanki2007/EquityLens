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
  ArrowDownRight,
  ArrowRight,
  CheckCircle2,
  FlaskConical,
  Gauge,
  ShieldCheck,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type MetricSet = {
  lookback: number;
  threshold: number;
  cagr: number | null;
  annualized_volatility: number | null;
  sharpe_zero_cash: number | null;
  max_drawdown: number | null;
  total_return: number | null;
  benchmark_cagr: number | null;
  benchmark_annualized_volatility: number | null;
  benchmark_sharpe_zero_cash: number | null;
  benchmark_max_drawdown: number | null;
  benchmark_total_return: number | null;
  time_in_market: number | null;
  entries: number;
  exits: number;
  turnover_cost_sum: number | null;
  market_beta: number | null;
};

type BacktestReport = {
  generated_at: string;
  source: string;
  formula: string;
  evaluation_start: string;
  evaluation_end: string;
  observations: number;
  assumptions: {
    instrument: string;
    primary_lookback_sessions: number;
    entry_threshold: number;
    execution: string;
    one_way_cost: number;
    cash_return: number;
    dividends: string;
    positioning: string;
  };
  primary_metrics: MetricSet;
  latest_signal: {
    beta_daily: number | null;
    annualized_slope: number | null;
    r_squared: number | null;
    score: number | null;
  };
  chart: Array<{
    date: string;
    strategy: number | null;
    benchmark: number | null;
    strategy_drawdown: number | null;
    benchmark_drawdown: number | null;
    score: number | null;
    annualized_slope: number | null;
    r_squared: number | null;
    position: number | null;
  }>;
  yearly_returns: Array<{ year: number; strategy: number | null; benchmark: number | null }>;
  sensitivity: MetricSet[];
};

const STRATEGY = "#059669";
const BENCHMARK = "#2563eb";
function percent(value: number | null | undefined, digits = 1) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
}

function multiple(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(2)}×`;
}

function plain(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat("en-IN", { month: "short", year: "2-digit" }).format(
    new Date(`${value}T00:00:00`),
  );
}

function fullDate(value: string) {
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" }).format(
    new Date(`${value}T00:00:00`),
  );
}

function MetricComparison({
  label,
  strategy,
  benchmark,
  formatter,
  detail,
}: {
  label: string;
  strategy: number | null;
  benchmark: number | null;
  formatter: (value: number | null) => string;
  detail: string;
}) {
  return (
    <div className="bg-card px-4 py-4 sm:px-5">
      <p className="terminal-label">{label}</p>
      <div className="mt-3 flex items-end justify-between gap-3">
        <p className="font-mono text-2xl font-semibold tracking-[-0.04em] tabular-nums">
          {formatter(strategy)}
        </p>
        <p className="pb-0.5 font-mono text-[11px] text-muted-foreground">
          vs {formatter(benchmark)}
        </p>
      </div>
      <p className="mt-2 text-[11px] leading-4 text-muted-foreground">{detail}</p>
    </div>
  );
}

function ChartTooltip({
  active,
  payload,
  label,
  kind = "percent",
}: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number; color?: string }>;
  label?: string | number;
  kind?: "percent" | "equity" | "signal";
}) {
  if (!active || !payload?.length) return null;
  const labelText = typeof label === "string"
    ? label.includes("-")
      ? fullDate(label)
      : label
    : String(label ?? "");
  return (
    <div className="min-w-40 rounded-md border border-border bg-card/95 p-3 text-xs shadow-xl backdrop-blur">
      <p className="mb-2 font-medium">{labelText}</p>
      <div className="space-y-1.5">
        {payload.map((item) => (
          <div key={item.name} className="flex items-center justify-between gap-5">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="size-2 rounded-full" style={{ background: item.color }} />
              {item.name}
            </span>
            <span className="font-mono font-semibold tabular-nums">
              {kind === "equity"
                ? multiple(item.value)
                : kind === "signal"
                  ? item.name === "R²"
                    ? plain(item.value, 2)
                    : percent(item.value, 1)
                  : percent(item.value, 1)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function sensitivityTone(sharpe: number | null, benchmarkSharpe: number | null) {
  if (sharpe == null || benchmarkSharpe == null) return "bg-muted/30";
  const difference = sharpe - benchmarkSharpe;
  if (difference >= 0.1) return "bg-emerald-500/15 text-emerald-800 dark:text-emerald-200";
  if (difference >= -0.1) return "bg-amber-500/15 text-amber-800 dark:text-amber-200";
  return "bg-rose-500/10 text-rose-800 dark:text-rose-200";
}

export function BetaR2BacktestView({ report }: { report: BacktestReport }) {
  const metrics = report.primary_metrics;
  const benchmarkSharpe = metrics.benchmark_sharpe_zero_cash;
  const thresholdPercent = Math.round(report.assumptions.entry_threshold * 100);
  const sensitivityByLookback = [21, 63, 126, 252].map((lookback) => ({
    lookback,
    rows: report.sensitivity.filter((row) => row.lookback === lookback),
  }));

  return (
    <div className="space-y-5 py-6">
      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="grid gap-0 xl:grid-cols-[minmax(0,1fr)_420px]">
          <div className="px-5 py-6 sm:px-7 sm:py-7">
            <div className="flex flex-wrap items-center gap-2">
              <p className="page-eyebrow">System · strategy research</p>
              <Badge variant="outline"><FlaskConical className="mr-1 size-3" /> Historical test</Badge>
            </div>
            <h1 className="mt-3 max-w-3xl text-3xl font-semibold tracking-[-0.045em] sm:text-[2.5rem]">
              Beta × R² reduced the fall, but missed the market.
            </h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
              A {report.assumptions.primary_lookback_sessions}-session log-price trend on the NIFTY 50,
              held only when its annualized beta × R² score exceeded {thresholdPercent}%. The result is
              lower volatility and a much shallower drawdown, but weaker return and risk-adjusted performance
              than staying invested.
            </p>
            <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-[11px] text-muted-foreground">
              <span>{fullDate(report.evaluation_start)} – {fullDate(report.evaluation_end)}</span>
              <span>{report.observations.toLocaleString("en-IN")} sessions</span>
              <span>{metrics.entries} entries · {metrics.exits} exits</span>
              <span>{percent(metrics.time_in_market, 1)} time invested</span>
            </div>
          </div>
          <div className="border-t border-border bg-[#23251f] px-5 py-6 text-white xl:border-l xl:border-t-0 sm:px-7">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-300">
              Bottom line
            </p>
            <div className="mt-4 flex gap-3">
              <AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-300" />
              <div>
                <p className="text-lg font-semibold tracking-[-0.02em]">Not a standalone alpha signal</p>
                <p className="mt-2 text-sm leading-6 text-white/68">
                  CAGR trailed by {percent((metrics.cagr ?? 0) - (metrics.benchmark_cagr ?? 0), 1)} and
                  Sharpe trailed by {plain((metrics.sharpe_zero_cash ?? 0) - (metrics.benchmark_sharpe_zero_cash ?? 0), 2)}.
                  The useful feature was risk control: maximum drawdown improved by {percent(
                    Math.abs(metrics.benchmark_max_drawdown ?? 0) - Math.abs(metrics.max_drawdown ?? 0),
                    1,
                  )}.
                </p>
              </div>
            </div>
          </div>
        </div>
        <div className="grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-5">
          <MetricComparison
            label="Annualized return"
            strategy={metrics.cagr}
            benchmark={metrics.benchmark_cagr}
            formatter={(value) => percent(value, 1)}
            detail="Strategy versus NIFTY 50 price index"
          />
          <MetricComparison
            label="Sharpe · 0% cash"
            strategy={metrics.sharpe_zero_cash}
            benchmark={metrics.benchmark_sharpe_zero_cash}
            formatter={(value) => plain(value, 2)}
            detail="No risk-free return credited while in cash"
          />
          <MetricComparison
            label="Maximum drawdown"
            strategy={metrics.max_drawdown}
            benchmark={metrics.benchmark_max_drawdown}
            formatter={(value) => percent(value, 1)}
            detail="Peak-to-trough loss over the test"
          />
          <MetricComparison
            label="Total return"
            strategy={metrics.total_return}
            benchmark={metrics.benchmark_total_return}
            formatter={(value) => percent(value, 0)}
            detail="Growth of one unit after modeled costs"
          />
          <MetricComparison
            label="Market beta"
            strategy={metrics.market_beta}
            benchmark={1}
            formatter={(value) => plain(value, 2)}
            detail="OLS beta to daily NIFTY 50 returns"
          />
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.7fr)_minmax(320px,0.7fr)]">
        <Card className="overflow-hidden">
          <CardHeader className="border-b border-border/70">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Activity className="size-4 text-emerald-600" /> Growth of ₹1
              </CardTitle>
              <div className="flex items-center gap-4 font-mono text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-emerald-600" /> Beta × R²</span>
                <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-blue-600" /> NIFTY 50</span>
              </div>
            </div>
          </CardHeader>
          <CardContent className="pt-5">
            <div className="h-[360px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={report.chart} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="strategyFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={STRATEGY} stopOpacity={0.18} />
                      <stop offset="100%" stopColor={STRATEGY} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={52} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(value) => `${value.toFixed(1)}×`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip kind="equity" />} />
                  <Area type="monotone" dataKey="strategy" name="Beta × R²" stroke={STRATEGY} fill="url(#strategyFill)" strokeWidth={2.2} dot={false} />
                  <Line type="monotone" dataKey="benchmark" name="NIFTY 50" stroke={BENCHMARK} strokeWidth={1.8} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border/70">
            <CardTitle className="flex items-center gap-2 text-base"><Gauge className="size-4 text-blue-600" /> Exact test rule</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5 pt-5">
            <div className="rounded-lg border border-border bg-muted/30 p-4">
              <p className="terminal-label">Signal</p>
              <p className="mt-3 overflow-x-auto whitespace-nowrap font-mono text-sm font-semibold">
                Sₜ = (e<sup>252βₜ</sup> − 1) × R²ₜ
              </p>
              <div className="mt-4 flex items-center gap-2 text-xs">
                <span className="rounded-md bg-emerald-500/12 px-2 py-1 font-mono text-emerald-800 dark:text-emerald-200">Sₜ &gt; 5%</span>
                <ArrowRight className="size-3.5 text-muted-foreground" />
                <span>100% long</span>
              </div>
              <div className="mt-2 flex items-center gap-2 text-xs">
                <span className="rounded-md bg-muted px-2 py-1 font-mono">Sₜ ≤ 5%</span>
                <ArrowRight className="size-3.5 text-muted-foreground" />
                <span>100% cash</span>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 border-t border-border pt-4">
                <div>
                  <p className="terminal-label">Latest fitted β</p>
                  <p className="mt-1 font-mono text-sm font-semibold">
                    {report.latest_signal.beta_daily == null
                      ? "—"
                      : `${(report.latest_signal.beta_daily * 10_000).toFixed(2)} bps / session`}
                  </p>
                </div>
                <div>
                  <p className="terminal-label">Annualized β trend</p>
                  <p className="mt-1 font-mono text-sm font-semibold">{percent(report.latest_signal.annualized_slope, 1)}</p>
                </div>
              </div>
            </div>
            <div className="space-y-3 text-xs leading-5 text-muted-foreground">
              <div className="flex gap-2"><CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /><p>OLS fitted to 63 daily log closes, with no future observations in the window.</p></div>
              <div className="flex gap-2"><CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /><p>Signal delayed to the next session’s close before the position changes.</p></div>
              <div className="flex gap-2"><CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /><p>10 bps charged on every entry and exit; no leverage or short selling.</p></div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="size-4 text-emerald-600" /> Drawdown from prior peak</CardTitle></CardHeader>
          <CardContent className="pt-5">
            <div className="h-[290px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={report.chart} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={48} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(value) => `${Math.round(value * 100)}%`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Area type="monotone" dataKey="benchmark_drawdown" name="NIFTY 50" stroke={BENCHMARK} fill={BENCHMARK} fillOpacity={0.08} dot={false} />
                  <Area type="monotone" dataKey="strategy_drawdown" name="Beta × R²" stroke={STRATEGY} fill={STRATEGY} fillOpacity={0.14} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><ArrowDownRight className="size-4 text-rose-600" /> Calendar-year return</CardTitle></CardHeader>
          <CardContent className="pt-5">
            <div className="h-[290px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={report.yearly_returns} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                  <XAxis dataKey="year" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(value) => `${Math.round(value * 100)}%`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="strategy" name="Beta × R²" fill={STRATEGY} radius={[2, 2, 0, 0]} />
                  <Bar dataKey="benchmark" name="NIFTY 50" fill={BENCHMARK} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="border-b border-border/70">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="text-base">Signal history and market exposure</CardTitle>
            <p className="text-[11px] text-muted-foreground">Green shading marks periods held long</p>
          </div>
        </CardHeader>
        <CardContent className="pt-5">
          <div className="h-[310px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={report.chart} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={48} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="signal" tickFormatter={(value) => `${Math.round(value * 100)}%`} width={44} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="fit" orientation="right" domain={[0, 1]} tickFormatter={(value) => value.toFixed(1)} width={34} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTooltip kind="signal" />} />
                <ReferenceLine yAxisId="signal" y={report.assumptions.entry_threshold} stroke="#d97706" strokeDasharray="5 4" label={{ value: "5% entry", fontSize: 10, fill: "#d97706" }} />
                <Area yAxisId="signal" type="stepAfter" dataKey="position" name="Long exposure" fill={STRATEGY} fillOpacity={0.07} stroke="none" />
                <Line yAxisId="signal" type="monotone" dataKey="score" name="Beta × R²" stroke={STRATEGY} strokeWidth={1.7} dot={false} />
                <Line yAxisId="signal" type="monotone" dataKey="annualized_slope" name="Annualized β" stroke={BENCHMARK} strokeWidth={1.2} strokeDasharray="4 3" dot={false} />
                <Line yAxisId="fit" type="monotone" dataKey="r_squared" name="R²" stroke="#a855f7" strokeWidth={1.2} strokeOpacity={0.7} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-border/70">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">Parameter sensitivity · Sharpe ratio</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">Same evaluation dates and costs; no parameter was selected on a holdout set.</p>
            </div>
            <Badge variant="outline">Benchmark Sharpe {plain(benchmarkSharpe, 2)}</Badge>
          </div>
        </CardHeader>
        <CardContent className="pt-5">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-separate border-spacing-1 text-center text-xs">
              <thead>
                <tr>
                  <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">Lookback</th>
                  {[0, 5, 10, 15].map((threshold) => <th key={threshold} className="px-3 py-2 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">Entry &gt; {threshold}%</th>)}
                </tr>
              </thead>
              <tbody>
                {sensitivityByLookback.map(({ lookback, rows }) => (
                  <tr key={lookback}>
                    <th className="px-3 py-3 text-left font-mono font-semibold">{lookback} sessions</th>
                    {rows.map((row) => (
                      <td key={row.threshold} className={`rounded-md px-3 py-3 font-mono font-semibold ${sensitivityTone(row.sharpe_zero_cash, benchmarkSharpe)}`}>
                        {plain(row.sharpe_zero_cash, 2)}
                        <span className="mt-1 block text-[9px] font-normal opacity-70">CAGR {percent(row.cagr, 1)}</span>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-[11px] leading-5 text-muted-foreground">
            No tested combination exceeded the benchmark’s Sharpe ratio. That makes the conclusion less dependent on the chosen 63-session / 5% presentation case.
          </p>
        </CardContent>
      </Card>

      <section className="grid gap-5 lg:grid-cols-3">
        <div className="surface-subtle p-5">
          <p className="terminal-label">What worked</p>
          <p className="mt-3 text-sm font-semibold">Drawdown control</p>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">The cash filter reduced annualized volatility from {percent(metrics.benchmark_annualized_volatility, 1)} to {percent(metrics.annualized_volatility, 1)} and materially softened the worst decline.</p>
        </div>
        <div className="surface-subtle p-5">
          <p className="terminal-label">What failed</p>
          <p className="mt-3 text-sm font-semibold">Return capture</p>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">The indicator stayed out of the market {percent(1 - (metrics.time_in_market ?? 0), 1)} of the time, missing enough positive days that the lower risk did not produce a better Sharpe ratio.</p>
        </div>
        <div className="surface-subtle p-5">
          <p className="terminal-label">Interpretation</p>
          <p className="mt-3 text-sm font-semibold">A risk overlay, not proven alpha</p>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">This version may be more useful for changing exposure than forecasting excess return. It needs multi-market, out-of-sample testing before any live use.</p>
        </div>
      </section>

      <section className="rounded-lg border border-amber-500/25 bg-amber-500/7 px-5 py-4">
        <div className="flex gap-3">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-300" />
          <div className="text-xs leading-5 text-muted-foreground">
            <p className="font-semibold text-foreground">Limits of this rough test</p>
            <p className="mt-1">
              The NIFTY 50 price index is not directly tradable and excludes dividends. Cash earns 0%, taxes and market impact are excluded, Yahoo data are delayed, and thresholds were not frozen on a separate development period. Results are research evidence, not a live-trading recommendation.
            </p>
            <p className="mt-2 font-mono text-[10px]">Source: {report.source} · generated {new Date(report.generated_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}</p>
          </div>
        </div>
      </section>
    </div>
  );
}
