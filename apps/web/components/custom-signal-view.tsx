"use client";

import { useMemo, useState } from "react";
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
  ArrowRight,
  BrainCircuit,
  Clock3,
  Gauge,
  ShieldCheck,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type StrategyMetrics = {
  threshold: number;
  threshold_method: string;
  threshold_quantile: number | null;
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
  benchmark_annualized_downside_deviation: number | null;
  benchmark_max_drawdown: number | null;
  benchmark_total_return: number | null;
  time_in_market: number | null;
  entries: number;
  exits: number;
};

type CalibrationPoint = {
  bin: number;
  predicted: number | null;
  observed: number | null;
  count: number;
};

type CustomSignalReport = {
  generated_at: string;
  source: string;
  evaluation_start: string;
  evaluation_end: string;
  formula: string;
  assumptions: {
    lookback_sessions: number;
    minimum_training_rows: number;
    refit_every_sessions: number;
    pdf_window_sessions: number;
    ewma_span: number;
    beta_binomial_prior_strength: number;
    maximum_expected_window: number;
    signal_threshold: number;
    signal_threshold_method: string;
    signal_threshold_quantile: number;
    signal_threshold_minimum_rows: number;
    one_way_cost: number;
    execution: string;
    positioning: string;
    cash_return: number;
    dividends: string;
  };
  primary_metrics: StrategyMetrics;
  probability_metrics: {
    raw_brier: number | null;
    adjusted_brier: number | null;
    base_brier: number | null;
    raw_log_loss: number | null;
    adjusted_log_loss: number | null;
    hit_rate: number | null;
    mean_raw_probability: number | null;
    mean_adjusted_probability: number | null;
    mean_expected_window: number | null;
    window_with_event_rate: number | null;
    forecast_count: number;
  };
  latest_signal: {
    date: string;
    daily_beta: number | null;
    annualized_beta: number | null;
    daily_beta_forecast: number | null;
    standardized_daily_forecast: number | null;
    r_squared: number | null;
    conditional_daily_sd: number | null;
    raw_probability: number | null;
    adjusted_probability: number | null;
    raw_custom_score: number | null;
    custom_score: number | null;
    signal_threshold: number | null;
    position: string;
    expected_window: number;
    window_observations: number;
    events_in_window: number;
    days_since_hit: number;
    yeo_johnson_lambda: number | null;
    transformed_mean: number | null;
    transformed_sd: number | null;
  };
  latest_pdf_parameters: Record<string, number | null>;
  raw_calibration: CalibrationPoint[];
  adjusted_calibration: CalibrationPoint[];
  chart: Array<{
    date: string;
    strategy_equity: number | null;
    benchmark_equity: number | null;
    strategy_drawdown: number | null;
    benchmark_drawdown: number | null;
    annualized_slope: number | null;
    predicted_return: number | null;
    raw_probability: number | null;
    adjusted_probability: number | null;
    raw_custom_score: number | null;
    custom_score: number | null;
    signal_threshold: number | null;
    position: number | null;
  }>;
  momentum_diagnostic: {
    percentile_lookback_sessions: number;
    minimum_history_sessions: number;
    points: Array<{
      date: string;
      close: number | null;
      custom_score: number | null;
      score_percentile: number | null;
      signal_threshold: number | null;
      position: number | null;
    }>;
  };
  yearly_returns: Array<{
    year: number;
    strategy: number | null;
    benchmark: number | null;
    gross_strategy: number | null;
    time_in_market: number | null;
    switches: number;
    cost_debit_sum: number | null;
    long_day_market_sum: number | null;
    cash_day_market_sum: number | null;
    best_missed_day: { date: string; return: number | null } | null;
    worst_held_day: { date: string; return: number | null } | null;
    quarters: Array<{ quarter: number; strategy: number | null; benchmark: number | null; time_in_market: number | null }>;
  }>;
  sensitivity: StrategyMetrics[];
  cross_market: {
    frozen_parameters: string;
    large_cap_selection: string;
    groups: Array<{
      name: string;
      summary: {
        count: number;
        cagr_win_rate: number | null;
        sharpe_win_rate: number | null;
        sortino_win_rate: number | null;
        drawdown_win_rate: number | null;
        median_cagr_delta: number | null;
        median_sharpe_delta: number | null;
        median_sortino_delta: number | null;
        median_drawdown_improvement: number | null;
      };
      rows: Array<{
        symbol: string;
        name: string;
        group: string;
        evaluation_start: string;
        evaluation_end: string;
        forecast_count: number;
        signal_threshold: number | null;
        threshold_method: string;
        threshold_quantile: number;
        latest_position: string;
        cagr: number | null;
        benchmark_cagr: number | null;
        cagr_delta: number | null;
        sharpe: number | null;
        benchmark_sharpe: number | null;
        sharpe_delta: number | null;
        sortino: number | null;
        benchmark_sortino: number | null;
        sortino_delta: number | null;
        max_drawdown: number | null;
        benchmark_max_drawdown: number | null;
        drawdown_improvement: number | null;
        market_beta: number | null;
        time_in_market: number | null;
        entries: number;
      }>;
    }>;
  } | null;
  standard_deviation: {
    summary: {
      current_daily_sd: number | null;
      mean_daily_sd: number | null;
      median_daily_sd: number | null;
      p10_daily_sd: number | null;
      p25_daily_sd: number | null;
      p75_daily_sd: number | null;
      p90_daily_sd: number | null;
      share_daily_sd_above_1pct: number | null;
      absolute_return_above_1pct: number | null;
      up_return_above_1pct: number | null;
      down_return_below_1pct: number | null;
      current_annualized_sd: number | null;
      median_annualized_sd: number | null;
      p90_annualized_sd: number | null;
      within_1sd: number | null;
      within_2sd: number | null;
      within_3sd: number | null;
    };
    history: Array<{ date: string; annualized_sd: number | null; daily_sd: number | null }>;
    recent: Array<{ date: string; return: number | null; upper_1sd: number | null; lower_1sd: number | null }>;
  };
};

const STRATEGY = "#059669";
const BENCHMARK = "#2563eb";
const DOWN = "#e11d48";
const PURPLE = "#9333ea";
const AMBER = "#d97706";
const priceFormatter = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 2,
});

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

function Metric({ label, value, comparison, detail }: { label: string; value: string; comparison?: string; detail: string }) {
  return (
    <div className="bg-card px-4 py-4 sm:px-5">
      <p className="terminal-label">{label}</p>
      <div className="mt-3 flex items-end justify-between gap-3">
        <p className="font-mono text-2xl font-semibold tracking-[-0.04em] tabular-nums">{value}</p>
        {comparison ? <p className="pb-0.5 font-mono text-[11px] text-muted-foreground">vs {comparison}</p> : null}
      </div>
      <p className="mt-2 text-[11px] leading-4 text-muted-foreground">{detail}</p>
    </div>
  );
}

function ChartTooltip({ active, payload, label, equity = false }: { active?: boolean; payload?: Array<{ name?: string; value?: number; color?: string }>; label?: string | number; equity?: boolean }) {
  if (!active || !payload?.length) return null;
  const labelText = typeof label === "string" && label.includes("-") ? fullDate(label) : String(label ?? "");
  return (
    <div className="min-w-44 rounded-md border border-border bg-card/95 p-3 text-xs shadow-xl backdrop-blur">
      <p className="mb-2 font-medium">{labelText}</p>
      <div className="space-y-1.5">
        {payload.map((item) => (
          <div key={item.name} className="flex items-center justify-between gap-5">
            <span className="flex items-center gap-1.5 text-muted-foreground"><span className="size-2 rounded-full" style={{ background: item.color }} />{item.name}</span>
            <span className="font-mono font-semibold">{equity ? `${number(item.value, 2)}×` : percent(item.value, 1)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

type MomentumPoint = CustomSignalReport["momentum_diagnostic"]["points"][number];
type MomentumRulePoint = MomentumPoint & {
  candidate_position: number;
  entry_price: number | null;
  exit_price: number | null;
};

function MomentumTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name?: string; value?: number; color?: string }>; label?: string | number }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-48 rounded-md border border-border bg-card/95 p-3 text-xs shadow-xl backdrop-blur">
      <p className="mb-2 font-medium">{typeof label === "string" ? fullDate(label) : String(label ?? "")}</p>
      <div className="space-y-1.5">
        {payload.filter((item) => item.value != null).map((item) => {
          const isPrice = item.name === "NIFTY 50 close" || item.name === "Candidate entry" || item.name === "Candidate exit";
          const shown = isPrice
            ? priceFormatter.format(item.value ?? 0)
            : item.name === "Score percentile" || item.name === "Candidate position"
              ? probability(item.value)
              : percent(item.value, 2);
          return (
            <div key={item.name} className="flex items-center justify-between gap-5">
              <span className="flex items-center gap-1.5 text-muted-foreground"><span className="size-2 rounded-full" style={{ background: item.color }} />{item.name}</span>
              <span className="font-mono font-semibold">{shown}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MomentumDiagnostic({ diagnostic }: { diagnostic: CustomSignalReport["momentum_diagnostic"] }) {
  const [windowSessions, setWindowSessions] = useState(126);
  const [entryPercentile, setEntryPercentile] = useState(70);
  const [exitPercentile, setExitPercentile] = useState(40);

  const rulePoints = useMemo<MomentumRulePoint[]>(() => {
    return diagnostic.points.reduce<MomentumRulePoint[]>((points, point) => {
      const previousPosition = points.at(-1)?.candidate_position ?? 0;
      const rank = point.score_percentile;
      const shouldEnter = rank != null && point.close != null && previousPosition === 0 && rank >= entryPercentile / 100;
      const shouldExit = rank != null && point.close != null && previousPosition === 1 && rank <= exitPercentile / 100;
      const candidatePosition = shouldEnter ? 1 : shouldExit ? 0 : previousPosition;
      return [...points, {
        ...point,
        candidate_position: candidatePosition,
        entry_price: shouldEnter ? point.close : null,
        exit_price: shouldExit ? point.close : null,
      }];
    }, []);
  }, [diagnostic.points, entryPercentile, exitPercentile]);

  const visible = useMemo(
    () => rulePoints.slice(-Math.min(windowSessions, rulePoints.length)),
    [rulePoints, windowSessions]
  );
  const visibleDates = useMemo(() => new Set(visible.map((point) => point.date)), [visible]);
  const followThrough = useMemo(() => {
    const returns: number[] = [];
    rulePoints.forEach((point, index) => {
      const future = rulePoints[index + 5];
      if (point.entry_price != null && future?.close != null && visibleDates.has(point.date)) {
        returns.push(future.close / point.entry_price - 1);
      }
    });
    return {
      entries: visible.filter((point) => point.entry_price != null).length,
      exits: visible.filter((point) => point.exit_price != null).length,
      averageFiveSessionReturn: returns.length
        ? returns.reduce((sum, value) => sum + value, 0) / returns.length
        : null,
      positiveFiveSessionRate: returns.length
        ? returns.filter((value) => value > 0).length / returns.length
        : null,
    };
  }, [rulePoints, visible, visibleDates]);

  return (
    <Card>
      <CardHeader className="border-b border-border/70">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <CardTitle className="text-base">Price versus indicator momentum diagnostic</CardTitle>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">
              The lower panel ranks each score against the preceding {diagnostic.percentile_lookback_sessions} sessions. Entry and exit use separate percentiles, so this experiment does not depend on one fixed score or the current median-volatility cutoff.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-[10px]">
            <label className="space-y-1"><span className="block text-muted-foreground">History</span><select value={windowSessions} onChange={(event) => setWindowSessions(Number(event.target.value))} className="h-8 rounded-md border border-border bg-background px-2 font-mono"><option value={21}>1 month</option><option value={63}>3 months</option><option value={126}>6 months</option><option value={252}>1 year</option><option value={504}>2 years</option></select></label>
            <label className="space-y-1"><span className="block text-muted-foreground">Enter above</span><select value={entryPercentile} onChange={(event) => setEntryPercentile(Number(event.target.value))} className="h-8 rounded-md border border-border bg-background px-2 font-mono">{[60, 70, 80, 90].map((value) => <option key={value} value={value}>{value}th percentile</option>)}</select></label>
            <label className="space-y-1"><span className="block text-muted-foreground">Exit below</span><select value={exitPercentile} onChange={(event) => setExitPercentile(Number(event.target.value))} className="h-8 rounded-md border border-border bg-background px-2 font-mono">{[20, 30, 40, 50].filter((value) => value < entryPercentile).map((value) => <option key={value} value={value}>{value}th percentile</option>)}</select></label>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 pt-5">
        <div className="grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-4">
          <div className="bg-card p-3"><p className="terminal-label">Candidate entries</p><p className="mt-1 font-mono text-lg font-semibold">{followThrough.entries}</p></div>
          <div className="bg-card p-3"><p className="terminal-label">Candidate exits</p><p className="mt-1 font-mono text-lg font-semibold">{followThrough.exits}</p></div>
          <div className="bg-card p-3"><p className="terminal-label">Average next 5 sessions</p><p className="mt-1 font-mono text-lg font-semibold">{percent(followThrough.averageFiveSessionReturn, 2)}</p></div>
          <div className="bg-card p-3"><p className="terminal-label">Positive after 5 sessions</p><p className="mt-1 font-mono text-lg font-semibold">{probability(followThrough.positiveFiveSessionRate)}</p></div>
        </div>

        <div>
          <p className="mb-2 terminal-label">NIFTY 50 price · candidate entry/exit markers</p>
          <div className="h-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={visible} syncId="momentum-diagnostic" margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis domain={["auto", "auto"]} tickFormatter={(value) => priceFormatter.format(value)} width={58} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<MomentumTooltip />} />
                <Line type="monotone" dataKey="close" name="NIFTY 50 close" stroke={BENCHMARK} strokeWidth={2} dot={false} />
                <Line type="linear" dataKey="entry_price" name="Candidate entry" stroke="transparent" dot={{ r: 4, fill: STRATEGY, stroke: "white", strokeWidth: 1.5 }} activeDot={false} connectNulls={false} />
                <Line type="linear" dataKey="exit_price" name="Candidate exit" stroke="transparent" dot={{ r: 4, fill: DOWN, stroke: "white", strokeWidth: 1.5 }} activeDot={false} connectNulls={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div>
          <p className="mb-2 terminal-label">Custom score and its trailing percentile rank</p>
          <div className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={visible} syncId="momentum-diagnostic" margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="score" tickFormatter={(value) => `${(value * 100).toFixed(1)}%`} width={52} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="rank" orientation="right" domain={[0, 1]} tickFormatter={(value) => `${Math.round(value * 100)}th`} width={44} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<MomentumTooltip />} />
                <ReferenceLine yAxisId="score" y={0} stroke="var(--border)" />
                <ReferenceLine yAxisId="rank" y={entryPercentile / 100} stroke={STRATEGY} strokeDasharray="5 4" />
                <ReferenceLine yAxisId="rank" y={exitPercentile / 100} stroke={DOWN} strokeDasharray="5 4" />
                <Area yAxisId="rank" type="stepAfter" dataKey="candidate_position" name="Candidate position" fill={STRATEGY} fillOpacity={0.07} stroke="none" />
                <Line yAxisId="score" type="monotone" dataKey="custom_score" name="Custom score" stroke={PURPLE} strokeWidth={1.8} dot={false} />
                <Line yAxisId="rank" type="monotone" dataKey="score_percentile" name="Score percentile" stroke={AMBER} strokeWidth={1.6} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
        <p className="text-[10px] leading-4 text-muted-foreground">
          This is a descriptive research view, not a selected production rule. The percentile uses only information available before each observation. The five-session figures are gross follow-through diagnostics and exclude trading costs; choose entry and exit bands using walk-forward validation, not the best-looking setting on this chart.
        </p>
      </CardContent>
    </Card>
  );
}

function brierImprovement(model: number | null, baseline: number | null) {
  if (model == null || baseline == null || baseline === 0) return null;
  return (baseline - model) / baseline;
}

export function CustomSignalView({ report }: { report: CustomSignalReport }) {
  const metrics = report.primary_metrics;
  const latest = report.latest_signal;
  const probabilityMetrics = report.probability_metrics;
  const calibration = report.raw_calibration.map((point, index) => ({
    bin: `Q${point.bin}`,
    rawPredicted: point.predicted,
    rawObserved: point.observed,
    adjustedPredicted: report.adjusted_calibration[index]?.predicted ?? null,
    adjustedObserved: report.adjusted_calibration[index]?.observed ?? null,
  }));
  const isLong = latest.position === "long";
  const crossRows = report.cross_market?.groups.flatMap((group) => group.rows) ?? [];
  const focusYears = [2013, 2015, 2018, 2022]
    .map((year) => report.yearly_returns.find((row) => row.year === year))
    .filter((row): row is CustomSignalReport["yearly_returns"][number] => Boolean(row));

  return (
    <div className="space-y-5 py-6">
      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="grid xl:grid-cols-[minmax(0,1fr)_430px]">
          <div className="px-5 py-6 sm:px-7 sm:py-7">
            <div className="flex flex-wrap items-center gap-2">
              <p className="page-eyebrow">System · probabilistic research</p>
              <Badge variant="outline"><BrainCircuit className="mr-1 size-3" /> Expanding walk-forward</Badge>
            </div>
            <h1 className="mt-3 text-3xl font-semibold tracking-[-0.045em] sm:text-[2.5rem]">Custom signal</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
              A {report.assumptions.lookback_sessions}-session log-price beta becomes tomorrow’s return forecast. A walk-forward Yeo–Johnson PDF estimates the probability of meeting that forecast, then a beta-binomial event window adjusts it for recent non-IID behaviour.
            </p>
            <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-[11px] text-muted-foreground">
              <span>{fullDate(report.evaluation_start)} – {fullDate(report.evaluation_end)}</span>
              <span>{probabilityMetrics.forecast_count.toLocaleString("en-IN")} genuine forecasts</span>
              <span>Refit every {report.assumptions.refit_every_sessions} sessions</span>
              <span>{metrics.entries} entries · {metrics.exits} exits</span>
            </div>
          </div>
          <div className="border-t border-border bg-[#22251f] px-5 py-6 text-white xl:border-l xl:border-t-0 sm:px-7">
            <div className="flex items-center justify-between gap-3">
              <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-300">Latest signal · {fullDate(latest.date)}</p>
              <Badge className={isLong ? "bg-emerald-400 text-emerald-950" : "bg-white/10 text-white"}>{isLong ? "LONG" : "CASH"}</Badge>
            </div>
            <p className="mt-4 font-mono text-4xl font-semibold tracking-[-0.05em]">{percent(latest.custom_score, 2)}</p>
            <p className="mt-1 text-xs text-white/55">Annualized-beta probability score · median daily-SD cutoff {percent(report.assumptions.signal_threshold, 2)}</p>
            <div className="mt-5 grid grid-cols-3 gap-px overflow-hidden rounded-md bg-white/10">
              <div className="bg-white/[0.04] p-3"><p className="text-[9px] uppercase tracking-[0.1em] text-white/45">Tomorrow mₜ</p><p className="mt-1 font-mono text-sm font-semibold">{percent(latest.daily_beta_forecast, 2)}</p></div>
              <div className="bg-white/[0.04] p-3"><p className="text-[9px] uppercase tracking-[0.1em] text-white/45">PDF probability</p><p className="mt-1 font-mono text-sm font-semibold text-purple-300">{probability(latest.raw_probability)}</p></div>
              <div className="bg-white/[0.04] p-3"><p className="text-[9px] uppercase tracking-[0.1em] text-white/45">Adjusted qₜ</p><p className="mt-1 font-mono text-sm font-semibold text-emerald-300">{probability(latest.adjusted_probability)}</p></div>
            </div>
            <p className="mt-3 text-[11px] text-white/55">Daily log-price β {percent(latest.daily_beta, 3)} · Annualized β {percent(latest.annualized_beta, 2)} · Yeo–Johnson λ {number(latest.yeo_johnson_lambda, 2)}</p>
          </div>
        </div>
        <div className="grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-6">
          <Metric label="Annualized return" value={percent(metrics.cagr)} comparison={percent(metrics.benchmark_cagr)} detail="Custom signal versus NIFTY 50" />
          <Metric label="Sharpe · 0% cash" value={number(metrics.sharpe_zero_cash)} comparison={number(metrics.benchmark_sharpe_zero_cash)} detail="Risk-adjusted return, zero cash yield" />
          <Metric label="Sortino · 0% MAR" value={number(metrics.sortino_zero_cash)} comparison={number(metrics.benchmark_sortino_zero_cash)} detail={`Downside deviation ${probability(metrics.annualized_downside_deviation)}`} />
          <Metric label="Maximum drawdown" value={percent(metrics.max_drawdown)} comparison={percent(metrics.benchmark_max_drawdown)} detail="Peak-to-trough decline" />
          <Metric label="Market beta" value={number(metrics.market_beta)} comparison="1.00" detail="OLS beta to daily NIFTY returns" />
          <Metric label="Time invested" value={probability(metrics.time_in_market)} detail="Long exposure; otherwise cash" />
        </div>
      </section>

      <MomentumDiagnostic diagnostic={report.momentum_diagnostic} />

      <section className="space-y-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="page-eyebrow">Conditional dispersion</p>
            <h2 className="mt-1 text-xl font-semibold tracking-[-0.025em]">What one standard deviation looks like</h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">SD is the model’s expected size of an ordinary daily move, not its direction. The 21-session EWMA estimate expands after turbulent returns and contracts during quiet periods.</p>
          </div>
          <Badge variant="outline">Current daily SD {probability(report.standard_deviation.summary.current_daily_sd, 2)}</Badge>
        </div>

        <div className="rounded-lg border border-blue-500/20 bg-blue-500/6 px-5 py-4 text-xs leading-5 text-muted-foreground">
          <span className="font-semibold text-foreground">Restored annualized entry rule:</span> the 63-session daily log-price slope is compounded over 252 sessions and multiplied by the adjusted probability. The score is compared with that instrument&apos;s expanding historical median daily SD. The current NIFTY 50 cutoff is {probability(report.assumptions.signal_threshold, 2)}.
        </div>

        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(330px,0.8fr)]">
          <Card>
            <CardHeader className="border-b border-border/70">
              <div className="flex flex-wrap items-center justify-between gap-3"><CardTitle className="text-base">Recent daily returns versus dynamic ±1 SD</CardTitle><span className="text-[10px] text-muted-foreground">Latest 252 sessions</span></div>
            </CardHeader>
            <CardContent className="pt-5">
              <div className="h-[330px]">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={report.standard_deviation.recent} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                    <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                    <YAxis tickFormatter={(value) => `${(value * 100).toFixed(1)}%`} width={45} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                    <Tooltip content={<ChartTooltip />} />
                    <ReferenceLine y={0} stroke="var(--border)" />
                    <Bar dataKey="return" name="Daily return" fill={BENCHMARK} fillOpacity={0.38} />
                    <Line type="monotone" dataKey="upper_1sd" name="+1 SD" stroke={STRATEGY} strokeWidth={1.5} dot={false} />
                    <Line type="monotone" dataKey="lower_1sd" name="−1 SD" stroke={DOWN} strokeWidth={1.5} dot={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-border/70"><CardTitle className="text-base">How often returns stayed inside each band</CardTitle></CardHeader>
            <CardContent className="space-y-5 pt-5">
              {[
                ["Within ±1 SD", report.standard_deviation.summary.within_1sd, 0.6827],
                ["Within ±2 SD", report.standard_deviation.summary.within_2sd, 0.9545],
                ["Within ±3 SD", report.standard_deviation.summary.within_3sd, 0.9973],
              ].map(([label, empirical, normal]) => (
                <div key={String(label)}>
                  <div className="flex items-center justify-between gap-4 text-xs"><span className="font-medium">{String(label)}</span><span className="font-mono font-semibold">{probability(empirical as number | null)}</span></div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-emerald-600" style={{ width: `${Math.min(100, (Number(empirical) || 0) * 100)}%` }} /></div>
                  <p className="mt-1 text-[10px] text-muted-foreground">Normal benchmark {probability(normal as number)}</p>
                </div>
              ))}
              <div className="border-t border-border pt-4">
                <p className="text-xs leading-5 text-muted-foreground">If the empirical coverage is below the normal benchmark, moves outside that SD band happen more often than a Gaussian model expects.</p>
              </div>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className="border-b border-border/70">
            <div className="flex flex-wrap items-center justify-between gap-3"><CardTitle className="text-base">Daily conditional SD through time</CardTitle><div className="flex gap-3 font-mono text-[10px] text-muted-foreground"><span>Mean {probability(report.standard_deviation.summary.mean_daily_sd, 2)}</span><span>90th pct {probability(report.standard_deviation.summary.p90_daily_sd, 2)}</span></div></div>
          </CardHeader>
          <CardContent className="pt-5">
            <div className="h-[320px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={report.standard_deviation.history} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                  <defs><linearGradient id="sdFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={PURPLE} stopOpacity={0.25} /><stop offset="100%" stopColor={PURPLE} stopOpacity={0} /></linearGradient></defs>
                  <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={52} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(value) => `${(value * 100).toFixed(1)}%`} width={45} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <ReferenceLine y={0.01} stroke={DOWN} strokeWidth={1.5} strokeDasharray="5 4" />
                  <ReferenceLine y={report.standard_deviation.summary.median_daily_sd ?? undefined} stroke="#d97706" strokeDasharray="3 4" />
                  <Area type="monotone" dataKey="daily_sd" name="Daily conditional SD" stroke={PURPLE} fill="url(#sdFill)" strokeWidth={1.8} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-2 border-t border-border pt-4 sm:grid-cols-3 xl:grid-cols-6">
              <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Mean daily SD</p><p className="mt-1 font-mono font-semibold">{probability(report.standard_deviation.summary.mean_daily_sd, 2)}</p></div>
              <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Median</p><p className="mt-1 font-mono font-semibold">{probability(report.standard_deviation.summary.median_daily_sd, 2)}</p></div>
              <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">75th percentile</p><p className="mt-1 font-mono font-semibold">{probability(report.standard_deviation.summary.p75_daily_sd, 2)}</p></div>
              <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">90th percentile</p><p className="mt-1 font-mono font-semibold">{probability(report.standard_deviation.summary.p90_daily_sd, 2)}</p></div>
              <div className="rounded-md bg-rose-500/7 p-3"><p className="terminal-label">SD above 1%</p><p className="mt-1 font-mono font-semibold">{probability(report.standard_deviation.summary.share_daily_sd_above_1pct)}</p></div>
              <div className="rounded-md bg-blue-500/7 p-3"><p className="terminal-label">|Return| at least 1%</p><p className="mt-1 font-mono font-semibold">{probability(report.standard_deviation.summary.absolute_return_above_1pct)}</p><p className="mt-1 text-[9px] text-muted-foreground">Up {probability(report.standard_deviation.summary.up_return_above_1pct)} · down {probability(report.standard_deviation.summary.down_return_below_1pct)}</p></div>
            </div>
            <p className="mt-3 text-[10px] text-muted-foreground">Red dashed line: 1% daily SD. Amber dashed line: historical median daily SD.</p>
          </CardContent>
        </Card>
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(330px,0.75fr)]">
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><Activity className="size-4 text-emerald-600" /> Growth of ₹1</CardTitle></CardHeader>
          <CardContent className="pt-5">
            <div className="h-[350px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={report.chart} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                  <defs><linearGradient id="customFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={STRATEGY} stopOpacity={0.2} /><stop offset="100%" stopColor={STRATEGY} stopOpacity={0} /></linearGradient></defs>
                  <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={52} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(value) => `${value.toFixed(1)}×`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip equity />} />
                  <Area type="monotone" dataKey="strategy_equity" name="Custom signal" stroke={STRATEGY} fill="url(#customFill)" strokeWidth={2.2} dot={false} />
                  <Line type="monotone" dataKey="benchmark_equity" name="NIFTY 50" stroke={BENCHMARK} strokeWidth={1.7} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><Gauge className="size-4 text-blue-600" /> Signal construction</CardTitle></CardHeader>
          <CardContent className="space-y-4 pt-5">
            <div className="rounded-md bg-muted/35 p-4">
              <p className="terminal-label">Return forecast</p>
              <p className="mt-2 font-mono text-xs">mₜ = exp(βdaily,ₜ) − 1</p>
            </div>
            <div className="rounded-md bg-muted/35 p-4">
              <p className="terminal-label">PDF probability</p>
              <p className="mt-2 font-mono text-xs">qraw = P(Rₜ₊₁ ≥ mₜ) for mₜ ≥ 0; lower tail otherwise</p>
            </div>
            <div className="rounded-md bg-muted/35 p-4">
              <p className="terminal-label">Adjusted score</p>
              <p className="mt-2 font-mono text-xs">Sₜ = [exp(252βdaily,ₜ) − 1] × qadjusted,ₜ</p>
            </div>
            <div className="flex items-center gap-2 text-xs"><span className="rounded-md bg-emerald-500/12 px-2 py-1 font-mono text-emerald-800 dark:text-emerald-200">Sₜ &gt; {probability(report.assumptions.signal_threshold, 2)}</span><ArrowRight className="size-3.5 text-muted-foreground" /><span>long</span></div>
            <div className="flex items-center gap-2 text-xs"><span className="rounded-md bg-muted px-2 py-1 font-mono">otherwise</span><ArrowRight className="size-3.5 text-muted-foreground" /><span>cash</span></div>
            <p className="border-t border-border pt-4 text-[11px] leading-5 text-muted-foreground">The PDF is fitted to EWMA-volatility-standardized returns with Yeo–Johnson, using only the preceding {report.assumptions.pdf_window_sessions} sessions. The event-window layer then calibrates its probability from completed forecasts only.</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-border/70">
            <CardTitle className="flex items-center gap-2 text-base"><BrainCircuit className="size-4 text-purple-600" /> Probability calibration</CardTitle>
          </CardHeader>
          <CardContent className="pt-5">
            <div className="h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={calibration} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                  <XAxis dataKey="bin" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(value) => `${Math.round(value * 100)}%`} width={40} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Bar dataKey="rawPredicted" name="Raw PDF" fill="#c4b5fd" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="rawObserved" name="Raw observed" fill={PURPLE} radius={[2, 2, 0, 0]} />
                  <Bar dataKey="adjustedPredicted" name="Adjusted" fill="#86efac" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="adjustedObserved" name="Adjusted observed" fill={STRATEGY} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Window adjustment vs raw</p><p className="mt-2 font-mono text-lg font-semibold">{percent(brierImprovement(probabilityMetrics.adjusted_brier, probabilityMetrics.raw_brier), 2)}</p><p className="mt-1 text-[10px] text-muted-foreground">Brier improvement</p></div>
              <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Adjusted vs base rate</p><p className="mt-2 font-mono text-lg font-semibold">{percent(brierImprovement(probabilityMetrics.adjusted_brier, probabilityMetrics.base_brier), 2)}</p><p className="mt-1 text-[10px] text-muted-foreground">Brier improvement</p></div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><Clock3 className="size-4 text-amber-600" /> Non-IID expected window</CardTitle></CardHeader>
          <CardContent className="space-y-5 pt-5">
            <p className="text-sm leading-6 text-muted-foreground">The raw probability implies an expected waiting window of ceil(1/q). Completed forecast hits inside that window update q through a beta-binomial posterior rather than assuming a fixed IID event rate.</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-md border border-border p-4"><p className="terminal-label">Expected window</p><p className="mt-2 font-mono text-2xl font-semibold">{latest.expected_window} days</p><p className="mt-1 text-[10px] text-muted-foreground">from raw q {probability(latest.raw_probability)}</p></div>
              <div className="rounded-md border border-border p-4"><p className="terminal-label">Observed hits</p><p className="mt-2 font-mono text-2xl font-semibold">{latest.events_in_window}/{latest.window_observations}</p><p className="mt-1 text-[10px] text-muted-foreground">forecast met or exceeded</p></div>
            </div>
            <div className="flex gap-2 rounded-md bg-amber-500/8 p-3 text-xs leading-5 text-muted-foreground"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-300" /><p>The adjustment does not declare an event “due.” A window with misses lowers probability; clustered hits raise it. A prior strength of {report.assumptions.beta_binomial_prior_strength} prevents a two- or three-day window from dominating the PDF.</p></div>
            <div className="grid grid-cols-2 gap-3 border-t border-border pt-4 text-xs">
              <div><p className="terminal-label">Probability update</p><p className="mt-1 font-mono font-semibold">{probability(latest.raw_probability)} → {probability(latest.adjusted_probability)}</p></div>
              <div><p className="terminal-label">Days since last hit</p><p className="mt-1 font-mono font-semibold">{latest.days_since_hit} sessions</p></div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Signal, beta and Yeo–Johnson probability</CardTitle></CardHeader>
        <CardContent className="pt-5">
          <div className="h-[330px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={report.chart} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={48} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="signal" tickFormatter={(value) => `${Math.round(value * 100)}%`} width={44} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="probability" orientation="right" domain={[0, 0.7]} tickFormatter={(value) => `${Math.round(value * 100)}%`} width={40} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTooltip />} />
                <Line yAxisId="signal" type="stepAfter" dataKey="signal_threshold" name="Expanding median daily-SD cutoff" stroke="#d97706" strokeWidth={1.4} strokeDasharray="5 4" dot={false} />
                <Area yAxisId="signal" type="stepAfter" dataKey="position" name="Long exposure" fill={STRATEGY} fillOpacity={0.06} stroke="none" />
                <Line yAxisId="signal" type="monotone" dataKey="custom_score" name="Custom score" stroke={STRATEGY} strokeWidth={1.8} dot={false} />
                <Line yAxisId="signal" type="monotone" dataKey="raw_custom_score" name="Raw PDF score" stroke="#94a3b8" strokeWidth={1} strokeDasharray="4 3" dot={false} />
                <Line yAxisId="probability" type="monotone" dataKey="raw_probability" name="Raw PDF probability" stroke={PURPLE} strokeWidth={1.2} dot={false} />
                <Line yAxisId="probability" type="monotone" dataKey="adjusted_probability" name="Adjusted probability" stroke={DOWN} strokeWidth={1.2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="size-4 text-emerald-600" /> Drawdown</CardTitle></CardHeader>
          <CardContent className="pt-5"><div className="h-[280px]"><ResponsiveContainer width="100%" height="100%"><AreaChart data={report.chart}><CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" /><XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={48} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tickFormatter={(value) => `${Math.round(value * 100)}%`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip content={<ChartTooltip />} /><Area type="monotone" dataKey="benchmark_drawdown" name="NIFTY 50" stroke={BENCHMARK} fill={BENCHMARK} fillOpacity={0.07} dot={false} /><Area type="monotone" dataKey="strategy_drawdown" name="Custom signal" stroke={STRATEGY} fill={STRATEGY} fillOpacity={0.13} dot={false} /></AreaChart></ResponsiveContainer></div></CardContent>
        </Card>
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Calendar-year returns</CardTitle></CardHeader>
          <CardContent className="pt-5">
            <div className="mb-5 grid grid-cols-2 gap-3">
              <div className="rounded-md bg-emerald-500/8 p-3"><p className="terminal-label">Method · total period</p><p className="mt-2 font-mono text-xl font-semibold">{percent(metrics.total_return, 0)}</p><p className="mt-1 text-[10px] text-muted-foreground">₹1 became ₹{number(1 + (metrics.total_return ?? 0), 2)}</p></div>
              <div className="rounded-md bg-blue-500/8 p-3"><p className="terminal-label">Index · total period</p><p className="mt-2 font-mono text-xl font-semibold">{percent(metrics.benchmark_total_return, 0)}</p><p className="mt-1 text-[10px] text-muted-foreground">₹1 became ₹{number(1 + (metrics.benchmark_total_return ?? 0), 2)}</p></div>
            </div>
            <div className="h-[280px]"><ResponsiveContainer width="100%" height="100%"><BarChart data={report.yearly_returns}><CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" /><XAxis dataKey="year" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tickFormatter={(value) => `${Math.round(value * 100)}%`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip content={<ChartTooltip />} /><Bar dataKey="strategy" name="Custom signal" fill={STRATEGY} radius={[2, 2, 0, 0]} /><Bar dataKey="benchmark" name="NIFTY 50" fill={BENCHMARK} radius={[2, 2, 0, 0]} /></BarChart></ResponsiveContainer></div>
            <p className="mt-3 text-[10px] leading-4 text-muted-foreground">Total period includes partial 2012 and 2026 endpoint years and compounds daily returns; it is not the sum of annual percentages.</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="border-b border-border/70">
          <div><CardTitle className="text-base">Why the signal diverged in the focus years</CardTitle><p className="mt-1 text-xs text-muted-foreground">Return attribution separates market moves that occurred while long from moves missed while in cash.</p></div>
        </CardHeader>
        <CardContent className="pt-5">
          <div className="grid gap-4 xl:grid-cols-2">
            {focusYears.map((row) => {
              const descriptions: Record<number, string> = {
                2013: "The fitted trend stayed defensive through the taper-tantrum reversal. It absorbed losses while long, then remained in cash for several of September’s sharp rebound days.",
                2015: "The index was negative too. The model was still long for the 24 August global sell-off, then reduced exposure after the damage; repeated switches added friction.",
                2018: "This was the clearest whipsaw year: the method held through parts of the February and September–October declines, then missed rebound days after beta turned negative.",
                2022: "The model correctly stayed out during most of the second-quarter decline, but lost during the February shock and after re-entering in Q3, while cash periods contained much of the year’s positive rebound.",
              };
              return (
                <div key={row.year} className="rounded-lg border border-border p-4">
                  <div className="flex items-start justify-between gap-4"><div><p className="font-mono text-lg font-semibold">{row.year}</p><p className="mt-1 text-xs text-muted-foreground">Method {percent(row.strategy)} · Index {percent(row.benchmark)}</p></div><Badge variant="outline">{probability(row.time_in_market)} invested</Badge></div>
                  <p className="mt-3 text-xs leading-5 text-muted-foreground">{descriptions[row.year]}</p>
                  <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <div className="rounded-md bg-muted/30 p-2.5"><p className="terminal-label">Long-day sum</p><p className="mt-1 font-mono text-xs font-semibold">{percent(row.long_day_market_sum)}</p></div>
                    <div className="rounded-md bg-muted/30 p-2.5"><p className="terminal-label">Cash-day sum</p><p className="mt-1 font-mono text-xs font-semibold">{percent(row.cash_day_market_sum)}</p></div>
                    <div className="rounded-md bg-muted/30 p-2.5"><p className="terminal-label">Switches</p><p className="mt-1 font-mono text-xs font-semibold">{row.switches}</p></div>
                    <div className="rounded-md bg-muted/30 p-2.5"><p className="terminal-label">Cost debit</p><p className="mt-1 font-mono text-xs font-semibold">{percent(-(row.cost_debit_sum ?? 0))}</p></div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-border pt-3 text-[10px] text-muted-foreground">
                    {row.worst_held_day ? <span>Worst held: {fullDate(row.worst_held_day.date)} · {percent(row.worst_held_day.return)}</span> : null}
                    {row.best_missed_day ? <span>Best missed: {fullDate(row.best_missed_day.date)} · {percent(row.best_missed_day.return)}</span> : null}
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Entry-percentile sensitivity</CardTitle></CardHeader>
        <CardContent className="pt-5">
          <div className="overflow-x-auto">
            <table className="data-table min-w-[840px]">
              <thead><tr><th>Historical daily-SD percentile</th><th>Current cutoff</th><th>CAGR</th><th>Sharpe</th><th>Sortino</th><th>Max drawdown</th><th>Time invested</th><th>Entries</th></tr></thead>
              <tbody>{report.sensitivity.map((row) => <tr key={`${row.threshold_method}-${row.threshold_quantile}`} className={row.threshold_quantile === report.assumptions.signal_threshold_quantile ? "bg-accent/45" : ""}><td className="font-mono font-semibold">{probability(row.threshold_quantile, 0)} percentile</td><td className="font-mono">{percent(row.threshold, 2)}</td><td className="font-mono">{percent(row.cagr)}</td><td className="font-mono">{number(row.sharpe_zero_cash)}</td><td className="font-mono">{number(row.sortino_zero_cash)}</td><td className="font-mono">{percent(row.max_drawdown)}</td><td className="font-mono">{probability(row.time_in_market)}</td><td className="font-mono">{row.entries}</td></tr>)}</tbody>
            </table>
          </div>
          <p className="mt-3 text-[11px] leading-5 text-muted-foreground">The highlighted median row is live. Every daily-SD cutoff is calculated from completed historical observations only, with at least {report.assumptions.signal_threshold_minimum_rows} observations.</p>
        </CardContent>
      </Card>

      {report.cross_market ? (
        <section className="space-y-5">
          <div>
            <p className="page-eyebrow">Frozen-parameter validation</p>
            <h2 className="mt-1 text-xl font-semibold tracking-[-0.025em]">Does the signal generalize?</h2>
            <p className="mt-1 max-w-4xl text-xs leading-5 text-muted-foreground">Each row uses the same settings as NIFTY 50 without asset-specific tuning. “Buy & hold” is the same instrument’s return over the identical evaluation window.</p>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {report.cross_market.groups.map((group) => (
              <Card key={group.name}>
                <CardContent className="pt-5">
                  <div className="flex items-start justify-between gap-4"><div><p className="terminal-label">{group.name}</p><p className="mt-2 text-lg font-semibold">Cross-market scorecard</p></div><Badge variant="outline">{group.summary.count} assets</Badge></div>
                  <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">CAGR wins</p><p className="mt-1 font-mono font-semibold">{Math.round((group.summary.cagr_win_rate ?? 0) * group.summary.count)}/{group.summary.count}</p></div>
                    <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Sharpe wins</p><p className="mt-1 font-mono font-semibold">{Math.round((group.summary.sharpe_win_rate ?? 0) * group.summary.count)}/{group.summary.count}</p></div>
                    <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Sortino wins</p><p className="mt-1 font-mono font-semibold">{Math.round((group.summary.sortino_win_rate ?? 0) * group.summary.count)}/{group.summary.count}</p></div>
                    <div className="rounded-md bg-emerald-500/8 p-3"><p className="terminal-label">Drawdown wins</p><p className="mt-1 font-mono font-semibold text-emerald-700 dark:text-emerald-300">{Math.round((group.summary.drawdown_win_rate ?? 0) * group.summary.count)}/{group.summary.count}</p></div>
                  </div>
                  <p className="mt-3 text-[11px] text-muted-foreground">Median CAGR gap {percent(group.summary.median_cagr_delta)} · median drawdown improvement {percent(group.summary.median_drawdown_improvement)}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Annualized return gap versus buy-and-hold</CardTitle></CardHeader>
            <CardContent className="pt-5">
              <div style={{ height: Math.max(440, crossRows.length * 28) }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={crossRows} layout="vertical" margin={{ top: 4, right: 18, left: 20, bottom: 0 }}>
                    <CartesianGrid horizontal={false} stroke="var(--border)" strokeDasharray="3 3" />
                    <XAxis type="number" tickFormatter={(value) => `${Math.round(value * 100)}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="name" width={142} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                    <Tooltip content={<ChartTooltip />} />
                    <ReferenceLine x={0} stroke="var(--foreground)" strokeOpacity={0.45} />
                    <Bar dataKey="cagr_delta" name="Method minus buy & hold CAGR" fill={PURPLE} radius={[0, 2, 2, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          {report.cross_market.groups.map((group) => (
            <Card key={`${group.name}-table`}>
              <CardHeader className="border-b border-border/70"><div><CardTitle className="text-base">{group.name}</CardTitle><p className="mt-1 text-[11px] text-muted-foreground">Method shown first; buy-and-hold comparison underneath.</p></div></CardHeader>
              <CardContent className="pt-5">
                <div className="overflow-x-auto">
                  <table className="data-table min-w-[940px]">
                    <thead><tr><th>Asset</th><th>Current score cutoff</th><th>CAGR</th><th>Sharpe</th><th>Sortino</th><th>Maximum drawdown</th><th>Market beta</th><th>Invested</th><th>Latest</th></tr></thead>
                    <tbody>{group.rows.map((row) => (
                      <tr key={row.symbol}>
                        <td><p className="font-semibold">{row.name}</p><p className="mt-0.5 font-mono text-[9px] text-muted-foreground">{row.symbol}</p></td>
                        <td className="font-mono font-semibold">{percent(row.signal_threshold, 2)}</td>
                        <td><p className="font-mono font-semibold">{percent(row.cagr)}</p><p className="text-[9px] text-muted-foreground">B&H {percent(row.benchmark_cagr)}</p></td>
                        <td><p className="font-mono font-semibold">{number(row.sharpe)}</p><p className="text-[9px] text-muted-foreground">B&H {number(row.benchmark_sharpe)}</p></td>
                        <td><p className="font-mono font-semibold">{number(row.sortino)}</p><p className="text-[9px] text-muted-foreground">B&H {number(row.benchmark_sortino)}</p></td>
                        <td><p className="font-mono font-semibold">{percent(row.max_drawdown)}</p><p className="text-[9px] text-muted-foreground">B&H {percent(row.benchmark_max_drawdown)}</p></td>
                        <td className="font-mono">{number(row.market_beta)}</td>
                        <td className="font-mono">{probability(row.time_in_market)}</td>
                        <td><Badge variant="outline">{row.latest_position.toUpperCase()}</Badge></td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          ))}

          <div className="rounded-lg border border-rose-500/20 bg-rose-500/6 px-5 py-4 text-xs leading-5 text-muted-foreground">
          <span className="font-semibold text-foreground">Conclusion:</span> the current {report.assumptions.lookback_sessions}-session version must be judged across assets rather than from NIFTY 50 alone. {report.cross_market.frozen_parameters}. {report.cross_market.large_cap_selection}. Stock histories are Yahoo auto-adjusted series; this is not a historical-constituent portfolio test.
          </div>
        </section>
      ) : null}

      <section className="space-y-3">
        <div>
          <p className="page-eyebrow">Model stack</p>
          <h2 className="mt-1 text-xl font-semibold tracking-[-0.025em]">From beta forecast to adjusted probability</h2>
        </div>
        <div className="grid gap-3 lg:grid-cols-3">
          <Card><CardContent className="pt-5"><p className="terminal-label">1 · Forecast</p><p className="mt-2 text-sm font-semibold">{report.assumptions.lookback_sessions}-session log-price OLS</p><p className="mt-2 text-xs leading-5 text-muted-foreground">The daily slope defines tomorrow&apos;s hurdle mₜ = exp(βdaily) − 1. For scoring, it is compounded to βannual = exp(252βdaily) − 1.</p></CardContent></Card>
          <Card><CardContent className="pt-5"><p className="terminal-label">2 · Continuous PDF</p><p className="mt-2 text-sm font-semibold">EWMA + Yeo–Johnson</p><p className="mt-2 text-xs leading-5 text-muted-foreground">Returns are standardized by the volatility known before they occurred. Yeo–Johnson transforms those shocks, a normal CDF is fitted, and mₜ is inserted as the tail threshold.</p></CardContent></Card>
          <Card><CardContent className="pt-5"><p className="terminal-label">3 · Non-IID calibration</p><p className="mt-2 text-sm font-semibold">Expected-window beta-binomial</p><p className="mt-2 text-xs leading-5 text-muted-foreground">ceil(1/qraw) defines the expected event window. Completed hits update q, after which βannual × qadjusted produces the restored score.</p></CardContent></Card>
        </div>
        <div className="rounded-lg border border-purple-500/20 bg-purple-500/6 px-5 py-4 text-xs leading-5 text-muted-foreground">
          <span className="font-semibold text-foreground">Important interpretation:</span> the event is “tomorrow’s return meets or exceeds the contemporaneous beta forecast,” not a fixed ±1% move. The probability layer is refitted every {report.assumptions.refit_every_sessions} sessions and never sees the return it is forecasting.
        </div>
      </section>

      <section className="rounded-lg border border-amber-500/25 bg-amber-500/7 px-5 py-4">
        <div className="flex gap-3"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-300" /><div className="text-xs leading-5 text-muted-foreground"><p className="font-semibold text-foreground">Interpretation and limits</p><p className="mt-1">The probability forecasts modestly improve Brier score, but the frozen cross-market test does not support a general alpha claim. The method mainly lowers exposure and often drawdown. Cash earns zero, the primary NIFTY test uses a non-tradable price index, and the current large-cap screen has survivorship bias. Treat this as a research signal, not a trading recommendation.</p><p className="mt-2 font-mono text-[10px]">{report.source} · generated {new Date(report.generated_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}</p></div></div>
      </section>
    </div>
  );
}
