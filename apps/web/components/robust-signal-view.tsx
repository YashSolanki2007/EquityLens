"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CalendarClock,
  CheckCircle2,
  CircleX,
  Clock3,
  ExternalLink,
  FlaskConical,
  Gauge,
  ListChecks,
  Scale,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type NullableNumber = number | null;

type PerformanceMetrics = {
  observations: number;
  cagr: NullableNumber;
  annualized_volatility: NullableNumber;
  sharpe_zero_cash: NullableNumber;
  sortino_zero_cash: NullableNumber;
  annualized_downside_deviation: NullableNumber;
  max_drawdown: NullableNumber;
  total_return: NullableNumber;
  worst_day: NullableNumber;
  expected_shortfall_95: NullableNumber;
};

type PrimaryMetrics = PerformanceMetrics & {
  benchmark_observations: number;
  benchmark_cagr: NullableNumber;
  benchmark_annualized_volatility: NullableNumber;
  benchmark_sharpe_zero_cash: NullableNumber;
  benchmark_sortino_zero_cash: NullableNumber;
  benchmark_annualized_downside_deviation: NullableNumber;
  benchmark_max_drawdown: NullableNumber;
  benchmark_total_return: NullableNumber;
  benchmark_worst_day: NullableNumber;
  benchmark_expected_shortfall_95: NullableNumber;
  market_beta: NullableNumber;
  average_exposure: NullableNumber;
  median_exposure: NullableNumber;
  maximum_exposure: NullableNumber;
  positive_exposure_days: NullableNumber;
  regime_entries: number;
  regime_exits: number;
  fractional_turnover: NullableNumber;
  annualized_fractional_turnover: NullableNumber;
  cost_debit_sum: NullableNumber;
  weekly_decisions: number;
};

type ControlMetrics = PerformanceMetrics & {
  constant_exposure?: NullableNumber;
};

type Interval = {
  lower_95: NullableNumber;
  median: NullableNumber;
  upper_95: NullableNumber;
};

type BootstrapMetricSet = {
  cagr: Interval;
  sharpe: Interval;
  sortino: Interval;
  max_drawdown: Interval;
};

type BootstrapComparison = {
  repetitions: number;
  valid_repetitions: number;
  expected_block_sessions: number;
  seed: number;
  strategy: BootstrapMetricSet;
  comparator: BootstrapMetricSet;
  paired_difference_strategy_minus_comparator: BootstrapMetricSet;
  probability_sharpe_difference_positive: NullableNumber;
  block_length_sensitivity: Array<{
    expected_block_sessions: number;
    sharpe_difference_95: Interval;
    probability_sharpe_difference_positive: NullableNumber;
  }>;
};

type RobustSignalReport = {
  generated_at: string;
  source: string;
  status: string;
  name: string;
  formula: string;
  primary_evaluation_start: string;
  comparison_evaluation_start: string;
  evaluation_end: string;
  verdict: {
    passed_all_gates: boolean;
    classification: string;
    headline: string;
    reason: string;
  };
  assumptions: {
    fast_span: number;
    slow_span: number;
    ewma_volatility_span: number;
    rolling_volatility_window: number;
    risk_forecast_combination: string;
    target_volatility: number;
    rebalance: string;
    one_way_cost: number;
    cash_return: number;
    leverage_cap: number;
    shorting: boolean;
    execution: string;
    dividends: string;
    taxes_and_market_impact: string;
    partial_week_policy: string;
  };
  latest_signal: {
    market_date: string;
    market_data_status: string;
    last_completed_decision_date: string;
    next_scheduled_decision_date: string;
    regime: string;
    action_status: string;
    action: string;
    pending_target: NullableNumber;
    earliest_execution_date: string | null;
    current_completed_close_exposure: NullableNumber;
    close: NullableNumber;
    fast_ema: NullableNumber;
    slow_ema: NullableNumber;
    trend_score: NullableNumber;
    annualized_ewma_sd: NullableNumber;
    annualized_rolling_sd: NullableNumber;
    risk_forecast: NullableNumber;
    last_completed_target: NullableNumber;
    position_earning_latest_return: NullableNumber;
    position_after_latest_close: NullableNumber;
    unscheduled_daily_target_diagnostic: NullableNumber;
  };
  primary_metrics: PrimaryMetrics;
  comparison_window_metrics: PrimaryMetrics;
  controls: {
    volatility_only: ControlMetrics;
    trend_only: ControlMetrics;
    existing_21_63_ema: ControlMetrics;
    constant_exposure_matched_volatility: ControlMetrics;
    buy_and_hold: ControlMetrics;
  };
  chart: Array<{
    date: string;
    close: NullableNumber;
    strategy_equity: NullableNumber;
    benchmark_equity: NullableNumber;
    strategy_drawdown: NullableNumber;
    benchmark_drawdown: NullableNumber;
    fast_ema: NullableNumber;
    slow_ema: NullableNumber;
    trend_score: NullableNumber;
    risk_forecast: NullableNumber;
    target: NullableNumber;
    active_position: NullableNumber;
  }>;
  subperiods: Array<{
    period: string;
    start: string;
    end: string;
    average_exposure: NullableNumber;
    strategy_cagr: NullableNumber;
    strategy_sharpe: NullableNumber;
    strategy_sortino: NullableNumber;
    strategy_max_drawdown: NullableNumber;
    benchmark_cagr: NullableNumber;
    benchmark_sharpe: NullableNumber;
    benchmark_sortino: NullableNumber;
    benchmark_max_drawdown: NullableNumber;
  }>;
  statistics: {
    stationary_bootstrap: {
      volatility_only: BootstrapComparison;
      constant_exposure_matched_volatility: BootstrapComparison;
    };
    deflated_sharpe: {
      observations_months: number;
      declared_total_trials_lower_bound: number;
      candidate_annualized_monthly_sharpe: NullableNumber;
      trial_mean_annualized_sharpe: NullableNumber;
      trial_sd_annualized_sharpe: NullableNumber;
      selection_adjusted_threshold_annualized_sharpe: NullableNumber;
      monthly_skewness: NullableNumber;
      monthly_pearson_kurtosis: NullableNumber;
      probabilistic_sharpe_probability_vs_zero: NullableNumber;
      deflated_sharpe_probability: NullableNumber;
    };
    hac: {
      active_return_vs_constant_exposure: {
        observations: number;
        max_lag: number;
        annualized_mean: NullableNumber;
        annualized_standard_error: NullableNumber;
        t_statistic: NullableNumber;
        one_sided_p_value: NullableNumber;
        two_sided_p_value: NullableNumber;
      };
      market_model_alpha: {
        observations: number;
        max_lag: number;
        annualized_alpha: NullableNumber;
        annualized_alpha_standard_error: NullableNumber;
        market_beta: NullableNumber;
        t_statistic: NullableNumber;
        one_sided_p_value: NullableNumber;
        two_sided_p_value: NullableNumber;
      };
      lag_sensitivity: Array<{
        observations: number;
        max_lag: number;
        annualized_mean: NullableNumber;
        annualized_standard_error: NullableNumber;
        t_statistic: NullableNumber;
        one_sided_p_value: NullableNumber;
        two_sided_p_value: NullableNumber;
      }>;
    };
    trial_ledger: {
      local_streams: number;
      declared_total_trials_lower_bound: number;
      counts: {
        earlier_repository_configurations: number;
        new_local_streams: number;
        additional_selection_decision: number;
      };
      local_annualized_monthly_sharpe_min: NullableNumber;
      local_annualized_monthly_sharpe_median: NullableNumber;
      local_annualized_monthly_sharpe_max: NullableNumber;
    };
  };
  promotion_gates: Array<{
    gate: string;
    passed: boolean;
    value: number;
    required: number;
  }>;
  sensitivity: {
    ema_windows: Array<{
      fast_span: number;
      slow_span: number;
      cagr: NullableNumber;
      sharpe: NullableNumber;
      sortino: NullableNumber;
      max_drawdown: NullableNumber;
      average_exposure: NullableNumber;
    }>;
    volatility_targets: Array<{
      target_volatility: number;
      cagr: NullableNumber;
      annualized_volatility: NullableNumber;
      sharpe: NullableNumber;
      sortino: NullableNumber;
      max_drawdown: NullableNumber;
    }>;
    costs: Array<{
      one_way_cost: number;
      cagr: NullableNumber;
      sharpe: NullableNumber;
      sortino: NullableNumber;
      max_drawdown: NullableNumber;
    }>;
  };
  cross_market: {
    frozen_parameters: string;
    rows: Array<{
      symbol: string;
      name: string;
      evaluation_start: string;
      evaluation_end: string;
      cagr: NullableNumber;
      sharpe: NullableNumber;
      sortino: NullableNumber;
      max_drawdown: NullableNumber;
      benchmark_cagr: NullableNumber;
      benchmark_sharpe: NullableNumber;
      benchmark_sortino: NullableNumber;
      benchmark_max_drawdown: NullableNumber;
      average_exposure: NullableNumber;
    }>;
    summary: {
      available_markets: number;
      cagr_wins: number;
      sharpe_wins: number;
      sortino_wins: number;
      drawdown_wins: number;
      median_sharpe_delta: NullableNumber;
      median_drawdown_improvement: NullableNumber;
    };
  };
  recent_trade_events: Array<{
    decision_date: string;
    execution_date: string;
    action: string;
    target_exposure: NullableNumber;
    close: NullableNumber;
    trend_score: NullableNumber;
    risk_forecast: NullableNumber;
  }>;
  forward_test: {
    frozen_from: string;
    minimum_sessions: number;
    completed_sessions: number;
    configuration_hash: string;
    parameters_must_not_change: boolean;
  };
  references: Array<{
    title: string;
    url: string;
    role: string;
  }>;
  limitations: string[];
};

const STRATEGY = "#059669";
const BENCHMARK = "#2563eb";
const TARGET = "#f59e0b";
const ACTIVE = "#0f766e";
const RISK = "#9333ea";

function percent(value: NullableNumber | undefined, digits = 1) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
}

function probability(value: NullableNumber | undefined, digits = 1) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

function number(value: NullableNumber | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

function price(value: NullableNumber | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value);
}

function fullDate(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(`${value}T00:00:00`));
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    month: "short",
    year: "2-digit",
  }).format(new Date(`${value}T00:00:00`));
}

function Metric({
  label,
  value,
  benchmark,
  detail,
}: {
  label: string;
  value: string;
  benchmark?: string;
  detail: string;
}) {
  return (
    <div className="bg-card px-4 py-4 sm:px-5">
      <p className="terminal-label">{label}</p>
      <p className="mt-3 font-mono text-2xl font-semibold tracking-[-0.04em] tabular-nums">{value}</p>
      <p className="mt-2 font-mono text-[10px] text-muted-foreground">
        {benchmark ? `NIFTY 50 ${benchmark}` : "Longest available history"}
      </p>
      <p className="mt-1 text-[10px] leading-4 text-muted-foreground">{detail}</p>
    </div>
  );
}

type TooltipItem = { name?: string; value?: number; color?: string };

function ChartTooltip({
  active,
  payload,
  label,
  format = "percent",
}: {
  active?: boolean;
  payload?: TooltipItem[];
  label?: string | number;
  format?: "percent" | "equity" | "number";
}) {
  if (!active || !payload?.length) return null;
  const heading = typeof label === "string" && label.includes("-") ? fullDate(label) : String(label ?? "");
  const formatValue = (value: number | undefined) => {
    if (format === "equity") return `${number(value, 2)}×`;
    if (format === "number") return number(value, 3);
    return percent(value, 1);
  };
  return (
    <div className="min-w-44 rounded-md border border-border bg-card/95 p-3 text-xs shadow-xl backdrop-blur">
      <p className="mb-2 font-medium">{heading}</p>
      <div className="space-y-1.5">
        {payload.map((item) => (
          <div key={item.name} className="flex items-center justify-between gap-5">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="size-2 rounded-full" style={{ background: item.color }} />
              {item.name}
            </span>
            <span className="font-mono font-semibold">{formatValue(item.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function IntervalLine({ label, interval, kind = "number" }: { label: string; interval: Interval; kind?: "number" | "percent" }) {
  const format = kind === "percent" ? percent : number;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-border/70 py-3 first:border-t-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-mono text-[11px] font-semibold tabular-nums">
        {format(interval.lower_95)} <span className="text-muted-foreground">to</span> {format(interval.upper_95)}
        <span className="ml-2 text-muted-foreground">med {format(interval.median)}</span>
      </p>
    </div>
  );
}

function ControlRow({ name, metrics, note }: { name: string; metrics: ControlMetrics; note: string }) {
  return (
    <tr>
      <td>
        <p className="font-semibold">{name}</p>
        <p className="mt-0.5 text-[9px] leading-4 text-muted-foreground">{note}</p>
      </td>
      <td className="font-mono font-semibold">{percent(metrics.cagr)}</td>
      <td className="font-mono">{probability(metrics.annualized_volatility)}</td>
      <td className="font-mono font-semibold">{number(metrics.sharpe_zero_cash)}</td>
      <td className="font-mono">{number(metrics.sortino_zero_cash)}</td>
      <td className="font-mono">{percent(metrics.max_drawdown)}</td>
      <td className="font-mono">{percent(metrics.expected_shortfall_95, 2)}</td>
    </tr>
  );
}

export function RobustSignalView({ report }: { report: RobustSignalReport }) {
  const metrics = report.primary_metrics;
  const comparison = report.comparison_window_metrics;
  const latest = report.latest_signal;
  const isLong = latest.regime === "long";
  const hasPendingAction = latest.action_status === "pending_next_session_close";
  const displayedTarget = hasPendingAction ? latest.pending_target : latest.position_after_latest_close;
  const passedGates = report.promotion_gates.filter((gate) => gate.passed).length;
  const recentTrades = [...report.recent_trade_events].slice(-10).reverse();
  const bootstrapVolatility = report.statistics.stationary_bootstrap.volatility_only;
  const bootstrapMatched = report.statistics.stationary_bootstrap.constant_exposure_matched_volatility;
  const dsr = report.statistics.deflated_sharpe;
  const hac = report.statistics.hac;

  return (
    <div className="min-w-0 space-y-5 py-6 [&_[data-slot=card]]:min-w-0 [&_[data-slot=card-content]]:min-w-0">
      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="grid xl:grid-cols-[minmax(0,1fr)_440px]">
          <div className="px-5 py-6 sm:px-7 sm:py-7">
            <div className="flex flex-wrap items-center gap-2">
              <p className="page-eyebrow">Research system · selection-aware audit</p>
              <Badge variant="destructive"><ShieldAlert className="mr-1 size-3" /> Paper trade only</Badge>
              <Badge variant="outline"><FlaskConical className="mr-1 size-3" /> {report.statistics.trial_ledger.declared_total_trials_lower_bound}+ trials</Badge>
            </div>
            <h1 className="mt-3 max-w-3xl text-3xl font-semibold tracking-[-0.035em] sm:text-4xl">{report.verdict.headline}</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">{report.verdict.reason}</p>
            <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 font-mono text-[10px] text-muted-foreground">
              <span>{fullDate(report.primary_evaluation_start)}–{fullDate(report.evaluation_end)}</span>
              <span>{metrics.observations.toLocaleString("en-IN")} sessions</span>
              <span>{metrics.regime_entries} entries · {metrics.regime_exits} exits</span>
              <Link href="/alternative-signal" className="inline-flex items-center gap-1 font-semibold text-primary hover:underline">
                <ArrowLeft className="size-3" /> Prior candidate
              </Link>
            </div>
          </div>

          <div className="border-t border-border bg-[#202720] px-5 py-6 text-white xl:border-l xl:border-t-0 sm:px-7">
            <div className="flex items-center justify-between gap-3">
              <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-300">Latest actionable state</p>
              <Badge className={isLong ? "bg-emerald-400 text-emerald-950" : "bg-white/10 text-white"}>{isLong ? "LONG" : "CASH"}</Badge>
            </div>
            <div className="mt-5 flex items-end justify-between gap-4">
              <div>
                <p className="font-mono text-4xl font-semibold tracking-[-0.055em]">{probability(displayedTarget)}</p>
                <p className="mt-1 text-xs text-white/55">{hasPendingAction ? "Target at the next session close" : "Exposure after the latest completed close"}</p>
              </div>
              <p className="font-mono text-xs text-emerald-300">NIFTY {price(latest.close)}</p>
            </div>
            <div className="mt-5 grid gap-px overflow-hidden rounded-md bg-white/10 sm:grid-cols-3">
              <div className="bg-white/[0.04] p-3">
                <p className="text-[9px] uppercase tracking-[0.1em] text-white/45">Decision</p>
                <p className="mt-1 font-mono text-xs font-semibold">{fullDate(latest.last_completed_decision_date)}</p>
              </div>
              <div className="bg-white/[0.04] p-3">
                <p className="text-[9px] uppercase tracking-[0.1em] text-white/45">Current exposure</p>
                <p className="mt-1 font-mono text-xs font-semibold text-emerald-300">{probability(latest.current_completed_close_exposure)}</p>
              </div>
              <div className="bg-white/[0.04] p-3">
                <p className="text-[9px] uppercase tracking-[0.1em] text-white/45">{hasPendingAction ? "Earliest execution" : "Next decision"}</p>
                <p className="mt-1 font-mono text-xs font-semibold">{fullDate(hasPendingAction && latest.earliest_execution_date ? latest.earliest_execution_date : latest.next_scheduled_decision_date)}</p>
              </div>
            </div>
            <p className="mt-3 text-[11px] leading-5 text-white/55">
              {hasPendingAction
                ? `Pending ${latest.action}: move from ${probability(latest.current_completed_close_exposure)} to ${probability(latest.pending_target)} at the next available session close. The next scheduled decision remains ${fullDate(latest.next_scheduled_decision_date)}.`
                : `No pending trade: the daily diagnostic is ${probability(latest.unscheduled_daily_target_diagnostic)}, but only a completed weekly decision can change exposure.`}
            </p>
          </div>
        </div>

        <div className="grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-6">
          <Metric label="Annualized return" value={percent(metrics.cagr)} benchmark={percent(metrics.benchmark_cagr)} detail="Lower return accompanies the smaller risk budget." />
          <Metric label="Sharpe · 0% cash" value={number(metrics.sharpe_zero_cash)} benchmark={number(metrics.benchmark_sharpe_zero_cash)} detail="Not selection-adjusted; see the DSR evidence below." />
          <Metric label="Sortino · 0% MAR" value={number(metrics.sortino_zero_cash)} benchmark={number(metrics.benchmark_sortino_zero_cash)} detail={`Downside deviation ${probability(metrics.annualized_downside_deviation)}`} />
          <Metric label="Maximum drawdown" value={percent(metrics.max_drawdown)} benchmark={percent(metrics.benchmark_max_drawdown)} detail="A historical path statistic, not a future loss limit." />
          <Metric label="Expected shortfall · 95%" value={percent(metrics.expected_shortfall_95, 2)} benchmark={percent(metrics.benchmark_expected_shortfall_95, 2)} detail={`Worst day ${percent(metrics.worst_day, 2)}`} />
          <Metric label="Market beta" value={number(metrics.market_beta)} benchmark="1.00" detail={`${probability(metrics.average_exposure)} average exposure`} />
        </div>
      </section>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="rounded-lg border border-rose-500/25 bg-rose-500/6 px-5 py-4 text-xs leading-5 text-muted-foreground">
          <span className="font-semibold text-foreground">Honest verdict:</span> historical drawdown control is visible, but only {passedGates}/{report.promotion_gates.length} promotion gates pass. The volatility-only control is statistically indistinguishable in the paired bootstrap, and the deflated Sharpe probability is only {probability(dsr.deflated_sharpe_probability)}.
        </div>
        <div className="rounded-lg border border-blue-500/20 bg-blue-500/6 px-5 py-4 text-xs leading-5 text-muted-foreground">
          <span className="font-semibold text-foreground">Forward evidence:</span> {report.forward_test.completed_sessions}/{report.forward_test.minimum_sessions} unseen sessions completed. Parameters are frozen under <span className="font-mono">{report.forward_test.configuration_hash}</span>.
        </div>
      </div>

      <Card>
        <CardHeader className="border-b border-border/70">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base"><Scale className="size-4 text-blue-600" /> Same-window comparison from 2012</CardTitle>
              <p className="mt-1 text-[11px] text-muted-foreground">Shown for continuity with earlier experiments; the 2008 start above is the primary result.</p>
            </div>
            <Badge variant="outline">{fullDate(report.comparison_evaluation_start)} onward</Badge>
          </div>
        </CardHeader>
        <CardContent className="pt-5">
          <div className="grid gap-px overflow-hidden rounded-md bg-border sm:grid-cols-2 lg:grid-cols-5">
            {[
              ["CAGR", percent(comparison.cagr), `B&H ${percent(comparison.benchmark_cagr)}`],
              ["Sharpe", number(comparison.sharpe_zero_cash), `B&H ${number(comparison.benchmark_sharpe_zero_cash)}`],
              ["Sortino", number(comparison.sortino_zero_cash), `B&H ${number(comparison.benchmark_sortino_zero_cash)}`],
              ["Max drawdown", percent(comparison.max_drawdown), `B&H ${percent(comparison.benchmark_max_drawdown)}`],
              ["Average exposure", probability(comparison.average_exposure), `Beta ${number(comparison.market_beta)}`],
            ].map(([label, value, detail]) => (
              <div key={label} className="bg-card p-4">
                <p className="terminal-label">{label}</p>
                <p className="mt-2 font-mono text-xl font-semibold">{value}</p>
                <p className="mt-1 text-[10px] text-muted-foreground">{detail}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><Activity className="size-4 text-emerald-600" /> Growth of ₹1 · longest history</CardTitle></CardHeader>
        <CardContent className="pt-5">
          <div className="h-[370px]" role="img" aria-label="Equity growth chart for the risk-budgeted trend strategy and NIFTY 50 benchmark">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={report.chart}>
                <defs>
                  <linearGradient id="robustStrategyFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={STRATEGY} stopOpacity={0.22} /><stop offset="100%" stopColor={STRATEGY} stopOpacity={0} /></linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={54} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={(value) => `${value.toFixed(1)}×`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTooltip format="equity" />} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Area type="monotone" dataKey="strategy_equity" name="Risk-budgeted trend" stroke={STRATEGY} fill="url(#robustStrategyFill)" strokeWidth={2.3} dot={false} />
                <Line type="monotone" dataKey="benchmark_equity" name="NIFTY 50" stroke={BENCHMARK} strokeWidth={1.6} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="size-4 text-emerald-600" /> Drawdown paths</CardTitle></CardHeader>
          <CardContent className="pt-5">
            <div className="h-[300px]" role="img" aria-label="Drawdown comparison chart">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={report.chart}>
                  <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={48} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(value) => `${Math.round(value * 100)}%`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Area type="monotone" dataKey="benchmark_drawdown" name="NIFTY 50" stroke={BENCHMARK} fill={BENCHMARK} fillOpacity={0.05} dot={false} />
                  <Area type="monotone" dataKey="strategy_drawdown" name="Strategy" stroke={STRATEGY} fill={STRATEGY} fillOpacity={0.15} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><Gauge className="size-4 text-amber-600" /> Target and active exposure</CardTitle></CardHeader>
          <CardContent className="pt-5">
            <div className="h-[300px]" role="img" aria-label="Target exposure, active position, and risk forecast chart">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={report.chart}>
                  <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={48} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis yAxisId="exposure" domain={[0, 1]} tickFormatter={(value) => `${Math.round(value * 100)}%`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis yAxisId="risk" orientation="right" tickFormatter={(value) => `${Math.round(value * 100)}%`} width={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Area yAxisId="exposure" type="stepAfter" dataKey="target" name="Weekly target" stroke={TARGET} fill={TARGET} fillOpacity={0.08} dot={false} />
                  <Line yAxisId="exposure" type="stepAfter" dataKey="active_position" name="Active position" stroke={ACTIVE} strokeWidth={1.8} dot={false} />
                  <Line yAxisId="risk" type="monotone" dataKey="risk_forecast" name="Risk forecast" stroke={RISK} strokeWidth={1.2} strokeDasharray="4 3" dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="border-b border-border/70">
          <div>
            <CardTitle className="flex items-center gap-2 text-base"><Scale className="size-4 text-blue-600" /> Controls and ablations</CardTitle>
            <p className="mt-1 text-[11px] text-muted-foreground">Lower drawdown alone is not alpha. These controls separate trend timing, volatility sizing, and simple exposure reduction.</p>
          </div>
        </CardHeader>
        <CardContent className="pt-5">
          <div className="overflow-x-auto">
            <table className="data-table min-w-[900px]">
              <thead><tr><th>Return stream</th><th>CAGR</th><th>Volatility</th><th>Sharpe</th><th>Sortino</th><th>Max drawdown</th><th>ES 95%</th></tr></thead>
              <tbody>
                <ControlRow name="Risk-budgeted trend" metrics={metrics} note="Selected candidate; 15/45 trend plus max-volatility sizing." />
                <ControlRow name="Volatility only" metrics={report.controls.volatility_only} note="Same risk forecast and target, always risk-on." />
                <ControlRow name="Trend only" metrics={report.controls.trend_only} note="Same 15/45 regime, binary full exposure or cash." />
                <ControlRow name="Existing 21/63 EMA" metrics={report.controls.existing_21_63_ema} note="Earlier binary benchmark over the same long history." />
                <ControlRow name="Constant exposure" metrics={report.controls.constant_exposure_matched_volatility} note={`Fixed ${probability(report.controls.constant_exposure_matched_volatility.constant_exposure)} exposure matched to candidate volatility.`} />
                <ControlRow name="Buy and hold" metrics={report.controls.buy_and_hold} note="Unscaled NIFTY 50 price-index return." />
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Subperiod stability</CardTitle></CardHeader>
          <CardContent className="pt-5">
            <div className="overflow-x-auto">
              <table className="data-table min-w-[760px]">
                <thead><tr><th>Period</th><th>Exposure</th><th>CAGR</th><th>Sharpe</th><th>Sortino</th><th>Max drawdown</th></tr></thead>
                <tbody>
                  {report.subperiods.map((row) => (
                    <tr key={row.period}>
                      <td><p className="font-mono font-semibold">{row.period}</p><p className="text-[9px] text-muted-foreground">{fullDate(row.start)}–{fullDate(row.end)}</p></td>
                      <td className="font-mono">{probability(row.average_exposure)}</td>
                      <td><p className="font-mono font-semibold">{percent(row.strategy_cagr)}</p><p className="text-[9px] text-muted-foreground">B&H {percent(row.benchmark_cagr)}</p></td>
                      <td><p className="font-mono font-semibold">{number(row.strategy_sharpe)}</p><p className="text-[9px] text-muted-foreground">B&H {number(row.benchmark_sharpe)}</p></td>
                      <td><p className="font-mono font-semibold">{number(row.strategy_sortino)}</p><p className="text-[9px] text-muted-foreground">B&H {number(row.benchmark_sortino)}</p></td>
                      <td><p className="font-mono font-semibold">{percent(row.strategy_max_drawdown)}</p><p className="text-[9px] text-muted-foreground">B&H {percent(row.benchmark_max_drawdown)}</p></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><ListChecks className="size-4 text-amber-600" /> Promotion gates</CardTitle></CardHeader>
          <CardContent className="space-y-2 pt-5">
            {report.promotion_gates.map((gate) => (
              <div key={gate.gate} className={`flex gap-3 rounded-md border p-3 ${gate.passed ? "border-emerald-500/20 bg-emerald-500/6" : "border-rose-500/20 bg-rose-500/6"}`}>
                {gate.passed ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <CircleX className="mt-0.5 size-4 shrink-0 text-rose-600" />}
                <div className="min-w-0">
                  <p className="text-xs font-semibold leading-5">{gate.gate}</p>
                  <p className="mt-0.5 font-mono text-[9px] text-muted-foreground">Observed {number(gate.value, 3)} · required {number(gate.required, 3)}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <section className="space-y-5">
        <div>
          <p className="page-eyebrow">Uncertainty and selection</p>
          <h2 className="mt-1 text-xl font-semibold tracking-[-0.025em]">The statistical evidence does not validate alpha</h2>
          <p className="mt-1 max-w-4xl text-xs leading-5 text-muted-foreground">Intervals preserve return dependence with stationary blocks. DSR accounts for non-normality and at least {dsr.declared_total_trials_lower_bound} observed research trials. HAC tests use autocorrelation-robust standard errors.</p>
        </div>

        <div className="grid gap-5 xl:grid-cols-2">
          <Card>
            <CardHeader className="border-b border-border/70">
              <div><CardTitle className="text-base">Paired bootstrap · versus volatility only</CardTitle><p className="mt-1 text-[11px] text-muted-foreground">{bootstrapVolatility.valid_repetitions.toLocaleString("en-IN")} valid repetitions · expected block {bootstrapVolatility.expected_block_sessions} sessions</p></div>
            </CardHeader>
            <CardContent className="pt-2">
              <IntervalLine label="Sharpe difference" interval={bootstrapVolatility.paired_difference_strategy_minus_comparator.sharpe} />
              <IntervalLine label="Sortino difference" interval={bootstrapVolatility.paired_difference_strategy_minus_comparator.sortino} />
              <IntervalLine label="CAGR difference" interval={bootstrapVolatility.paired_difference_strategy_minus_comparator.cagr} kind="percent" />
              <IntervalLine label="Drawdown improvement" interval={bootstrapVolatility.paired_difference_strategy_minus_comparator.max_drawdown} kind="percent" />
              <p className="border-t border-border/70 pt-3 text-[11px] leading-5 text-muted-foreground">Probability Sharpe edge is positive: <span className="font-mono font-semibold text-foreground">{probability(bootstrapVolatility.probability_sharpe_difference_positive)}</span>. The 95% interval crosses zero.</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-border/70">
              <div><CardTitle className="text-base">Paired bootstrap · versus constant exposure</CardTitle><p className="mt-1 text-[11px] text-muted-foreground">Same realized volatility as the candidate, without timing.</p></div>
            </CardHeader>
            <CardContent className="pt-2">
              <IntervalLine label="Sharpe difference" interval={bootstrapMatched.paired_difference_strategy_minus_comparator.sharpe} />
              <IntervalLine label="Sortino difference" interval={bootstrapMatched.paired_difference_strategy_minus_comparator.sortino} />
              <IntervalLine label="CAGR difference" interval={bootstrapMatched.paired_difference_strategy_minus_comparator.cagr} kind="percent" />
              <IntervalLine label="Drawdown improvement" interval={bootstrapMatched.paired_difference_strategy_minus_comparator.max_drawdown} kind="percent" />
              <p className="border-t border-border/70 pt-3 text-[11px] leading-5 text-muted-foreground">Probability Sharpe edge is positive: <span className="font-mono font-semibold text-foreground">{probability(bootstrapMatched.probability_sharpe_difference_positive)}</span>. This interval also crosses zero.</p>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-5 xl:grid-cols-3">
          <Card>
            <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Deflated Sharpe ratio</CardTitle></CardHeader>
            <CardContent className="space-y-3 pt-5">
              <div className="rounded-md bg-rose-500/7 p-4"><p className="terminal-label">Selection-adjusted probability</p><p className="mt-2 font-mono text-3xl font-semibold text-rose-700 dark:text-rose-300">{probability(dsr.deflated_sharpe_probability)}</p></div>
              <div className="grid grid-cols-2 gap-2 text-[10px]"><div className="rounded-md bg-muted/30 p-3"><p className="text-muted-foreground">Candidate Sharpe</p><p className="mt-1 font-mono font-semibold">{number(dsr.candidate_annualized_monthly_sharpe, 3)}</p></div><div className="rounded-md bg-muted/30 p-3"><p className="text-muted-foreground">Selection threshold</p><p className="mt-1 font-mono font-semibold">{number(dsr.selection_adjusted_threshold_annualized_sharpe, 3)}</p></div></div>
              <p className="text-[11px] leading-5 text-muted-foreground">The unadjusted probability versus zero is {probability(dsr.probabilistic_sharpe_probability_vs_zero)}, but it collapses after accounting for selection.</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-border/70"><CardTitle className="text-base">HAC active return</CardTitle></CardHeader>
            <CardContent className="space-y-3 pt-5">
              <div className="grid grid-cols-2 gap-2"><div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Annualized mean</p><p className="mt-1 font-mono font-semibold">{percent(hac.active_return_vs_constant_exposure.annualized_mean)}</p></div><div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">HAC standard error</p><p className="mt-1 font-mono font-semibold">{percent(hac.active_return_vs_constant_exposure.annualized_standard_error)}</p></div></div>
              <p className="font-mono text-sm font-semibold">t {number(hac.active_return_vs_constant_exposure.t_statistic, 3)} · one-sided p {number(hac.active_return_vs_constant_exposure.one_sided_p_value, 3)}</p>
              <p className="text-[11px] leading-5 text-muted-foreground">Against constant exposure, the active return is not statistically distinguishable from zero.</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-border/70"><CardTitle className="text-base">HAC market-model alpha</CardTitle></CardHeader>
            <CardContent className="space-y-3 pt-5">
              <div className="grid grid-cols-2 gap-2"><div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Annualized alpha</p><p className="mt-1 font-mono font-semibold">{percent(hac.market_model_alpha.annualized_alpha)}</p></div><div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Market beta</p><p className="mt-1 font-mono font-semibold">{number(hac.market_model_alpha.market_beta, 3)}</p></div></div>
              <p className="font-mono text-sm font-semibold">t {number(hac.market_model_alpha.t_statistic, 3)} · two-sided p {number(hac.market_model_alpha.two_sided_p_value, 3)}</p>
              <p className="text-[11px] leading-5 text-muted-foreground">Borderline before selection correction; insufficient beside the failed DSR and transfer gates.</p>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Robustness to block and HAC lag choices</CardTitle></CardHeader>
          <CardContent className="pt-5">
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="overflow-x-auto"><table className="data-table min-w-[520px]"><thead><tr><th>Bootstrap block</th><th>Sharpe difference · 95%</th><th>P(edge &gt; 0)</th></tr></thead><tbody>{bootstrapVolatility.block_length_sensitivity.map((row) => <tr key={row.expected_block_sessions}><td className="font-mono font-semibold">{row.expected_block_sessions} sessions</td><td className="font-mono">{number(row.sharpe_difference_95.lower_95)} to {number(row.sharpe_difference_95.upper_95)}</td><td className="font-mono">{probability(row.probability_sharpe_difference_positive)}</td></tr>)}</tbody></table></div>
              <div className="overflow-x-auto"><table className="data-table min-w-[520px]"><thead><tr><th>HAC max lag</th><th>t statistic</th><th>One-sided p</th><th>Two-sided p</th></tr></thead><tbody>{hac.lag_sensitivity.map((row) => <tr key={row.max_lag}><td className="font-mono font-semibold">{row.max_lag}</td><td className="font-mono">{number(row.t_statistic, 3)}</td><td className="font-mono">{number(row.one_sided_p_value, 3)}</td><td className="font-mono">{number(row.two_sided_p_value, 3)}</td></tr>)}</tbody></table></div>
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="space-y-5">
        <div><p className="page-eyebrow">Parameter and implementation stress</p><h2 className="mt-1 text-xl font-semibold tracking-[-0.025em]">Results are sensitive to the risk budget and costs</h2></div>
        <div className="grid gap-5 xl:grid-cols-3">
          <Card>
            <CardHeader className="border-b border-border/70"><CardTitle className="text-base">EMA windows</CardTitle></CardHeader>
            <CardContent className="pt-5"><div className="overflow-x-auto"><table className="data-table min-w-[520px]"><thead><tr><th>Fast / slow</th><th>CAGR</th><th>Sharpe</th><th>MDD</th></tr></thead><tbody>{report.sensitivity.ema_windows.map((row) => <tr key={`${row.fast_span}-${row.slow_span}`} className={row.fast_span === report.assumptions.fast_span && row.slow_span === report.assumptions.slow_span ? "bg-accent/45" : ""}><td className="font-mono font-semibold">{row.fast_span} / {row.slow_span}</td><td className="font-mono">{percent(row.cagr)}</td><td className="font-mono">{number(row.sharpe)}</td><td className="font-mono">{percent(row.max_drawdown)}</td></tr>)}</tbody></table></div></CardContent>
          </Card>
          <Card>
            <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Volatility target</CardTitle></CardHeader>
            <CardContent className="pt-5"><div className="overflow-x-auto"><table className="data-table min-w-[480px]"><thead><tr><th>Target</th><th>Realized vol</th><th>CAGR</th><th>Sharpe</th><th>MDD</th></tr></thead><tbody>{report.sensitivity.volatility_targets.map((row) => <tr key={row.target_volatility} className={row.target_volatility === report.assumptions.target_volatility ? "bg-accent/45" : ""}><td className="font-mono font-semibold">{probability(row.target_volatility, 0)}</td><td className="font-mono">{probability(row.annualized_volatility)}</td><td className="font-mono">{percent(row.cagr)}</td><td className="font-mono">{number(row.sharpe)}</td><td className="font-mono">{percent(row.max_drawdown)}</td></tr>)}</tbody></table></div></CardContent>
          </Card>
          <Card>
            <CardHeader className="border-b border-border/70"><CardTitle className="text-base">One-way trading cost</CardTitle></CardHeader>
            <CardContent className="pt-5"><div className="overflow-x-auto"><table className="data-table min-w-[450px]"><thead><tr><th>Cost</th><th>CAGR</th><th>Sharpe</th><th>Sortino</th><th>MDD</th></tr></thead><tbody>{report.sensitivity.costs.map((row) => <tr key={row.one_way_cost} className={row.one_way_cost === report.assumptions.one_way_cost ? "bg-accent/45" : ""}><td className="font-mono font-semibold">{(row.one_way_cost * 10_000).toFixed(0)} bps</td><td className="font-mono">{percent(row.cagr)}</td><td className="font-mono">{number(row.sharpe)}</td><td className="font-mono">{number(row.sortino)}</td><td className="font-mono">{percent(row.max_drawdown)}</td></tr>)}</tbody></table></div></CardContent>
          </Card>
        </div>
      </section>

      <section className="space-y-5">
        <div><p className="page-eyebrow">Frozen transfer test</p><h2 className="mt-1 text-xl font-semibold tracking-[-0.025em]">Drawdown control transfers; alpha does not</h2><p className="mt-1 max-w-4xl text-xs leading-5 text-muted-foreground">{report.cross_market.frozen_parameters}. No market receives asset-specific tuning.</p></div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ["CAGR wins", report.cross_market.summary.cagr_wins],
            ["Sharpe wins", report.cross_market.summary.sharpe_wins],
            ["Sortino wins", report.cross_market.summary.sortino_wins],
            ["Drawdown wins", report.cross_market.summary.drawdown_wins],
          ].map(([label, value]) => <div key={label} className="rounded-md border border-border bg-card p-4"><p className="terminal-label">{label}</p><p className="mt-2 font-mono text-2xl font-semibold">{value}/{report.cross_market.summary.available_markets}</p></div>)}
        </div>
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Indian index transfer results</CardTitle></CardHeader>
          <CardContent className="pt-5"><div className="overflow-x-auto"><table className="data-table min-w-[1050px]"><thead><tr><th>Index</th><th>Window</th><th>CAGR</th><th>Sharpe</th><th>Sortino</th><th>Max drawdown</th><th>Exposure</th></tr></thead><tbody>{report.cross_market.rows.map((row) => <tr key={row.symbol}><td><p className="font-semibold">{row.name}</p><p className="font-mono text-[9px] text-muted-foreground">{row.symbol}</p></td><td className="font-mono text-[10px]">{fullDate(row.evaluation_start)}<br />{fullDate(row.evaluation_end)}</td><td><p className="font-mono font-semibold">{percent(row.cagr)}</p><p className="text-[9px] text-muted-foreground">B&H {percent(row.benchmark_cagr)}</p></td><td><p className="font-mono font-semibold">{number(row.sharpe)}</p><p className="text-[9px] text-muted-foreground">B&H {number(row.benchmark_sharpe)}</p></td><td><p className="font-mono font-semibold">{number(row.sortino)}</p><p className="text-[9px] text-muted-foreground">B&H {number(row.benchmark_sortino)}</p></td><td><p className="font-mono font-semibold">{percent(row.max_drawdown)}</p><p className="text-[9px] text-muted-foreground">B&H {percent(row.benchmark_max_drawdown)}</p></td><td className="font-mono">{probability(row.average_exposure)}</td></tr>)}</tbody></table></div></CardContent>
        </Card>
        <div className="rounded-lg border border-blue-500/20 bg-blue-500/6 px-5 py-4 text-xs leading-5 text-muted-foreground"><span className="font-semibold text-foreground">Transfer verdict:</span> median Sharpe change is {number(report.cross_market.summary.median_sharpe_delta)}, while median drawdown improves by {percent(report.cross_market.summary.median_drawdown_improvement)}. This is consistent with defensive exposure reduction, not a broad return edge.</div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(340px,0.8fr)]">
        <Card>
          <CardHeader className="border-b border-border/70"><div><CardTitle className="flex items-center gap-2 text-base"><Clock3 className="size-4 text-emerald-600" /> Recent regime trades</CardTitle><p className="mt-1 text-[11px] text-muted-foreground">Decision close, next-session execution, and target exposure. Weekly resizing within a regime is omitted.</p></div></CardHeader>
          <CardContent className="pt-5"><div className="overflow-x-auto"><table className="data-table min-w-[760px]"><thead><tr><th>Decision</th><th>Execution</th><th>Action</th><th>Target</th><th>NIFTY close</th><th>Trend / risk</th></tr></thead><tbody>{recentTrades.map((trade) => <tr key={`${trade.decision_date}-${trade.action}`}><td className="font-mono">{fullDate(trade.decision_date)}</td><td className="font-mono">{fullDate(trade.execution_date)}</td><td><Badge variant={trade.action === "enter" ? "default" : "secondary"}>{trade.action}</Badge></td><td className="font-mono font-semibold">{probability(trade.target_exposure)}</td><td className="font-mono">{price(trade.close)}</td><td className="font-mono text-[10px]">{number(trade.trend_score, 3)} / {probability(trade.risk_forecast)}</td></tr>)}</tbody></table></div></CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><CalendarClock className="size-4 text-blue-600" /> Frozen forward test</CardTitle></CardHeader>
          <CardContent className="space-y-4 pt-5">
            <div className="rounded-md bg-muted/30 p-4"><p className="terminal-label">Progress</p><p className="mt-2 font-mono text-3xl font-semibold">{report.forward_test.completed_sessions}<span className="text-base text-muted-foreground"> / {report.forward_test.minimum_sessions}</span></p><div className="mt-3 h-1.5 overflow-hidden rounded-full bg-border"><div className="h-full bg-blue-600" style={{ width: `${Math.min(100, (report.forward_test.completed_sessions / report.forward_test.minimum_sessions) * 100)}%` }} /></div></div>
            <div className="space-y-2 text-xs leading-5 text-muted-foreground"><p><span className="font-semibold text-foreground">Frozen from:</span> {fullDate(report.forward_test.frozen_from)}</p><p><span className="font-semibold text-foreground">Configuration:</span> <span className="font-mono">{report.forward_test.configuration_hash}</span></p><p>Parameters must remain unchanged for these sessions to count as genuinely unseen evidence.</p></div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><BookOpen className="size-4 text-blue-600" /> Methods and counterevidence</CardTitle></CardHeader>
          <CardContent className="space-y-2 pt-5">
            {report.references.map((reference) => (
              <a key={reference.url} href={reference.url} target="_blank" rel="noreferrer" className="group flex items-start justify-between gap-4 rounded-md border border-border p-3 transition-colors hover:bg-accent/45">
                <div><p className="text-xs font-semibold leading-5 group-hover:text-primary">{reference.title}</p><p className="mt-0.5 text-[10px] leading-4 text-muted-foreground">{reference.role}</p></div>
                <ExternalLink className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
              </a>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2 text-base"><AlertTriangle className="size-4 text-amber-600" /> Limitations</CardTitle></CardHeader>
          <CardContent className="space-y-3 pt-5">
            {report.limitations.map((item) => <div key={item} className="flex gap-2.5 text-xs leading-5 text-muted-foreground"><AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-600" /><p>{item}</p></div>)}
            <div className="border-t border-border pt-4"><p className="terminal-label">Exact frozen rule</p><p className="mt-2 font-mono text-[10px] leading-5 text-muted-foreground">{report.formula}</p></div>
          </CardContent>
        </Card>
      </div>

      <section className="rounded-lg border border-amber-500/25 bg-amber-500/7 px-5 py-4">
        <div className="flex gap-3">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-300" />
          <div className="text-xs leading-5 text-muted-foreground">
            <p className="font-semibold text-foreground">Research use only</p>
            <p className="mt-1">This page describes a historical, selection-contaminated experiment. It is not a recommendation, a promised drawdown limit, or evidence that the latest exposure will be profitable.</p>
            <p className="mt-3 font-mono text-[10px]">{report.source} · generated {new Date(report.generated_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}</p>
          </div>
        </div>
      </section>

      <div className="flex justify-end">
        <Link href="/alternative-signal" className="inline-flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline">Compare the prior EMA candidate <ArrowRight className="size-3.5" /></Link>
      </div>
    </div>
  );
}
