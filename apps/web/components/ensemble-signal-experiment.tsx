"use client";

import { useMemo, useState } from "react";
import {
  Area,
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
import { AlertTriangle, Beaker, CheckCircle2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type ForecastMetrics = {
  count: number;
  mae: number | null;
  rmse: number | null;
  oos_r2_vs_zero: number | null;
  direction_accuracy: number | null;
  correlation: number | null;
};

export type EnsembleSignalReport = {
  generated_at: string;
  source: string;
  evaluation_start: string;
  evaluation_end: string;
  status: string;
  assumptions: {
    forecast_horizon_sessions: number;
    minimum_training_rows: number;
    training_window_rows: number;
    refit_every_sessions: number;
    error_window_sessions: number;
    round_trip_cost: number;
    entry_edge_percentile: number;
    exit_edge_percentile: number;
    entry_probability: number;
    execution: string;
    weights: string;
    intervals: string;
  };
  latest: {
    date: string;
    ensemble_forecast: number | null;
    forecast_uncertainty: number | null;
    lower_80: number | null;
    upper_80: number | null;
    lower_90: number | null;
    upper_90: number | null;
    positive_probability: number | null;
    confidence_edge: number | null;
    edge_percentile: number | null;
    model_agreement: number;
    position: string;
    models: Record<string, {
      forecast: number | null;
      weight: number | null;
      rolling_error_sd: number | null;
    }>;
  };
  strategy_metrics: {
    cagr: number | null;
    annualized_volatility: number | null;
    sharpe_zero_cash: number | null;
    sortino_zero_cash: number | null;
    max_drawdown: number | null;
    total_return: number | null;
    benchmark_cagr: number | null;
    benchmark_annualized_volatility: number | null;
    benchmark_sharpe_zero_cash: number | null;
    benchmark_sortino_zero_cash: number | null;
    benchmark_max_drawdown: number | null;
    benchmark_total_return: number | null;
    time_in_market: number | null;
    entries: number;
    exits: number;
  };
  forecast_metrics: Record<string, ForecastMetrics>;
  interval_coverage: { coverage_80: number | null; coverage_90: number | null };
  uncertainty_bins: Array<{
    bin: number;
    count: number;
    mean_uncertainty: number | null;
    mae: number | null;
    coverage_80: number | null;
    coverage_90: number | null;
  }>;
  chart: Array<{
    date: string;
    close: number | null;
    target_5d: number | null;
    ridge_forecast: number | null;
    kalman_forecast: number | null;
    boosting_forecast: number | null;
    ensemble_forecast: number | null;
    lower_80: number | null;
    upper_80: number | null;
    confidence_edge: number | null;
    edge_percentile: number | null;
    positive_probability: number | null;
    model_agreement: number | null;
    position: number | null;
    strategy_equity: number | null;
    benchmark_equity: number | null;
  }>;
};

const COLORS = {
  ensemble: "#059669",
  ridge: "#2563eb",
  kalman: "#9333ea",
  boosting: "#d97706",
  actual: "#111827",
  benchmark: "#64748b",
  negative: "#e11d48",
};

function percent(value: number | null | undefined, digits = 2) {
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

function fullDate(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  }).format(new Date(`${value}T12:00:00+05:30`));
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    month: "short",
    year: "2-digit",
    timeZone: "Asia/Kolkata",
  }).format(new Date(`${value}T12:00:00+05:30`));
}

function ForecastTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number | [number, number]; color?: string }>;
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-56 rounded-md border border-border bg-card/95 p-3 text-xs shadow-xl backdrop-blur">
      <p className="mb-2 font-medium">{typeof label === "string" ? fullDate(label) : String(label ?? "")}</p>
      <div className="space-y-1.5">
        {payload.filter((item) => typeof item.value === "number").map((item) => (
          <div key={item.name} className="flex items-center justify-between gap-5">
            <span className="flex items-center gap-1.5 text-muted-foreground"><span className="size-2 rounded-full" style={{ background: item.color }} />{item.name}</span>
            <span className="font-mono font-semibold">{percent(item.value as number)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SimpleTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number; color?: string }>;
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-44 rounded-md border border-border bg-card/95 p-3 text-xs shadow-xl backdrop-blur">
      <p className="mb-2 font-medium">{typeof label === "string" && label.includes("-") ? fullDate(label) : String(label ?? "")}</p>
      {payload.filter((item) => item.value != null).map((item) => (
        <div key={item.name} className="mt-1 flex items-center justify-between gap-4">
          <span className="text-muted-foreground">{item.name}</span>
          <span className="font-mono font-semibold">{item.name?.includes("equity") ? number(item.value, 2) : percent(item.value, 2)}</span>
        </div>
      ))}
    </div>
  );
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="bg-card p-4">
      <p className="terminal-label">{label}</p>
      <p className="mt-2 font-mono text-xl font-semibold tracking-[-0.03em]">{value}</p>
      <p className="mt-1 text-[10px] leading-4 text-muted-foreground">{detail}</p>
    </div>
  );
}

export function EnsembleSignalExperiment({ report }: { report: EnsembleSignalReport }) {
  const [windowSessions, setWindowSessions] = useState(252);
  const visible = useMemo(
    () => report.chart.slice(-Math.min(windowSessions, report.chart.length)).map((point) => ({
      ...point,
      interval_80: point.lower_80 != null && point.upper_80 != null ? [point.lower_80, point.upper_80] : null,
    })),
    [report.chart, windowSessions],
  );
  const ensembleMetrics = report.forecast_metrics.ensemble;
  const componentRows = Object.entries(report.latest.models).map(([name, latest]) => ({
    name,
    ...latest,
    metrics: report.forecast_metrics[name],
  }));
  const uncertaintyUseful = (
    (report.uncertainty_bins.at(-1)?.mae ?? 0) > (report.uncertainty_bins[0]?.mae ?? 0)
  );
  const hasPredictiveEvidence = (
    (ensembleMetrics.oos_r2_vs_zero ?? -1) > 0
    && (ensembleMetrics.direction_accuracy ?? 0) > 0.5
  );

  return (
    <section className="space-y-5 pb-8">
      <div className="flex flex-col gap-3 rounded-xl border border-purple-500/20 bg-purple-500/[0.035] px-5 py-5 sm:px-7 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="page-eyebrow">Development lab · alternative forecast</p>
            <Badge variant="outline"><Beaker className="mr-1 size-3" /> Not used by production signal</Badge>
          </div>
          <h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">Five-session uncertainty-aware ensemble</h2>
          <p className="mt-2 max-w-4xl text-xs leading-5 text-muted-foreground">
            Ridge, an adaptive Kalman trend and shallow gradient boosting independently forecast the same five-session log return. Rolling completed errors determine their weights and prediction interval; no daily forecast is annualized.
          </p>
        </div>
        <label className="shrink-0 space-y-1 text-[10px]"><span className="block text-muted-foreground">Chart history</span><select value={windowSessions} onChange={(event) => setWindowSessions(Number(event.target.value))} className="h-8 rounded-md border border-border bg-background px-2 font-mono"><option value={63}>3 months</option><option value={126}>6 months</option><option value={252}>1 year</option><option value={504}>2 years</option></select></label>
      </div>

      <Card className="overflow-hidden">
        <CardContent className="p-0">
          <div className="grid lg:grid-cols-[minmax(0,1fr)_360px]">
            <div className="p-5 sm:p-6">
              <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="terminal-label">Latest forecast · {fullDate(report.latest.date)}</p><p className="mt-2 font-mono text-4xl font-semibold tracking-[-0.05em]">{percent(report.latest.ensemble_forecast)}</p><p className="mt-1 text-xs text-muted-foreground">Expected return over the next {report.assumptions.forecast_horizon_sessions} sessions</p></div><Badge variant="outline">Research position: {report.latest.position.toUpperCase()}</Badge></div>
              <div className="mt-5 grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-4">
                <Stat label="80% interval" value={`${percent(report.latest.lower_80)} to ${percent(report.latest.upper_80)}`} detail="Rolling out-of-sample residual band" />
                <Stat label="Net-positive probability" value={probability(report.latest.positive_probability)} detail={`Above ${probability(report.assumptions.round_trip_cost)} round-trip cost`} />
                <Stat label="Confidence edge" value={`${number(report.latest.confidence_edge)}σ`} detail={`${probability(report.latest.edge_percentile)} historical percentile`} />
                <Stat label="Model agreement" value={`${report.latest.model_agreement}/3`} detail="Forecasts exceeding estimated costs" />
              </div>
            </div>
            <div className="border-t border-border bg-muted/25 p-5 lg:border-l lg:border-t-0">
              <p className="terminal-label">Current component forecasts</p>
              <div className="mt-3 space-y-3">
                {componentRows.map((row) => (
                  <div key={row.name} className="rounded-md border border-border bg-card p-3">
                    <div className="flex items-center justify-between gap-3"><p className="text-xs font-semibold capitalize">{row.name}</p><p className="font-mono text-sm font-semibold">{percent(row.forecast)}</p></div>
                    <div className="mt-1.5 flex justify-between text-[10px] text-muted-foreground"><span>Weight {probability(row.weight)}</span><span>Rolling error {percent(row.rolling_error_sd)}</span></div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-border/70"><div><CardTitle className="text-base">Forecast versus what happened five sessions later</CardTitle><p className="mt-1 text-xs text-muted-foreground">The black realized-return line becomes available only after the five-session target completes. The green band is the 80% rolling residual interval known at forecast time.</p></div></CardHeader>
        <CardContent className="pt-5">
          <div className="h-[390px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={visible} margin={{ top: 8, right: 10, left: 4, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={(value) => `${(value * 100).toFixed(1)}%`} width={48} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<ForecastTooltip />} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                <ReferenceLine y={0} stroke="var(--border)" />
                <Area type="monotone" dataKey="interval_80" name="80% forecast interval" fill={COLORS.ensemble} fillOpacity={0.08} stroke="none" connectNulls={false} />
                <Line type="monotone" dataKey="target_5d" name="Realized 5-session return" stroke={COLORS.actual} strokeWidth={1.5} dot={false} />
                <Line type="monotone" dataKey="ensemble_forecast" name="Ensemble forecast" stroke={COLORS.ensemble} strokeWidth={2.2} dot={false} />
                <Line type="monotone" dataKey="ridge_forecast" name="Ridge" stroke={COLORS.ridge} strokeWidth={1} strokeOpacity={0.5} dot={false} />
                <Line type="monotone" dataKey="kalman_forecast" name="Kalman" stroke={COLORS.kalman} strokeWidth={1} strokeOpacity={0.5} dot={false} />
                <Line type="monotone" dataKey="boosting_forecast" name="Boosting" stroke={COLORS.boosting} strokeWidth={1} strokeOpacity={0.5} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(340px,0.75fr)]">
        <Card>
          <CardHeader className="border-b border-border/70"><div><CardTitle className="text-base">Genuine walk-forward forecast scorecard</CardTitle><p className="mt-1 text-xs text-muted-foreground">All targets were unseen when predicted. OOS R² compares mean-squared error with always forecasting zero return.</p></div></CardHeader>
          <CardContent className="pt-5">
            <div className="overflow-x-auto">
              <table className="data-table min-w-[700px]">
                <thead><tr><th>Model</th><th>Forecasts</th><th>MAE</th><th>RMSE</th><th>OOS R² vs zero</th><th>Direction</th><th>Correlation</th></tr></thead>
                <tbody>
                  {[...componentRows.map((row) => [row.name, row.metrics] as const), ["ensemble", ensembleMetrics] as const].map(([name, metrics]) => (
                    <tr key={name} className={name === "ensemble" ? "bg-emerald-500/[0.06]" : ""}><td className="font-semibold capitalize">{name}</td><td className="font-mono">{metrics.count.toLocaleString("en-IN")}</td><td className="font-mono">{percent(metrics.mae)}</td><td className="font-mono">{percent(metrics.rmse)}</td><td className="font-mono">{percent(metrics.oos_r2_vs_zero)}</td><td className="font-mono">{probability(metrics.direction_accuracy)}</td><td className="font-mono">{number(metrics.correlation, 3)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Does reported uncertainty mean anything?</CardTitle></CardHeader>
          <CardContent className="pt-5">
            <div className="h-[245px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={report.uncertainty_bins.map((row) => ({ ...row, label: `Q${row.bin}` }))}>
                  <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(value) => `${(value * 100).toFixed(1)}%`} width={44} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<SimpleTooltip />} />
                  <Bar dataKey="mae" name="Actual MAE" fill={COLORS.negative} radius={[2, 2, 0, 0]} />
                  <Bar dataKey="mean_uncertainty" name="Estimated uncertainty" fill={COLORS.ensemble} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-2 text-[10px] leading-4 text-muted-foreground">Q1 is the lowest predicted uncertainty; Q4 is the highest. Overall interval coverage: {probability(report.interval_coverage.coverage_80)} for the nominal 80% band and {probability(report.interval_coverage.coverage_90)} for the nominal 90% band.</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="border-b border-border/70"><div><CardTitle className="text-base">Fixed-rule strategy comparison</CardTitle><p className="mt-1 text-xs text-muted-foreground">Entry requires ≥{probability(report.assumptions.entry_probability)} net-positive probability, at least two agreeing models and edge above its trailing {probability(report.assumptions.entry_edge_percentile)} percentile. Exit uses the {probability(report.assumptions.exit_edge_percentile)} percentile or loss of agreement.</p></div></CardHeader>
        <CardContent className="pt-5">
          <div className="grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-4">
            <Stat label="CAGR" value={percent(report.strategy_metrics.cagr)} detail={`NIFTY ${percent(report.strategy_metrics.benchmark_cagr)}`} />
            <Stat label="Sharpe" value={number(report.strategy_metrics.sharpe_zero_cash)} detail={`NIFTY ${number(report.strategy_metrics.benchmark_sharpe_zero_cash)}`} />
            <Stat label="Maximum drawdown" value={percent(report.strategy_metrics.max_drawdown)} detail={`NIFTY ${percent(report.strategy_metrics.benchmark_max_drawdown)}`} />
            <Stat label="Time invested" value={probability(report.strategy_metrics.time_in_market)} detail={`${report.strategy_metrics.entries} entries · ${report.strategy_metrics.exits} exits`} />
          </div>
          <div className="mt-5 h-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={visible} margin={{ top: 8, right: 10, left: 4, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={42} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis domain={["auto", "auto"]} width={44} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<SimpleTooltip />} />
                <Line type="monotone" dataKey="strategy_equity" name="Ensemble equity" stroke={COLORS.ensemble} strokeWidth={2.1} dot={false} />
                <Line type="monotone" dataKey="benchmark_equity" name="NIFTY equity" stroke={COLORS.benchmark} strokeWidth={1.5} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <div className={`rounded-lg border px-5 py-4 text-xs leading-5 ${hasPredictiveEvidence ? "border-emerald-500/25 bg-emerald-500/[0.06]" : "border-amber-500/25 bg-amber-500/[0.07]"}`}>
        <div className="flex gap-3">
          {hasPredictiveEvidence ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-700" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700" />}
          <div>
            <p className="font-semibold">Current verdict: {hasPredictiveEvidence ? "promising, but still experimental" : "do not replace the existing signal"}</p>
            <p className="mt-1 text-muted-foreground">
              The ensemble {uncertaintyUseful ? "does rank uncertainty usefully" : "does not yet rank uncertainty reliably"}, and it has the lowest component-level RMSE. However, its OOS R² is {percent(ensembleMetrics.oos_r2_vs_zero)}, direction accuracy is {probability(ensembleMetrics.direction_accuracy)}, and the fixed-rule strategy CAGR is {percent(report.strategy_metrics.cagr)} versus {percent(report.strategy_metrics.benchmark_cagr)} for NIFTY. Model diversity reduced error slightly; it did not establish a tradable return forecast.
            </p>
            <p className="mt-2 text-[10px] text-muted-foreground">{report.assumptions.execution}. {report.assumptions.weights}. This remains a price-index experiment with zero cash yield and {probability(report.assumptions.round_trip_cost)} estimated round-trip cost.</p>
          </div>
        </div>
      </div>
    </section>
  );
}
