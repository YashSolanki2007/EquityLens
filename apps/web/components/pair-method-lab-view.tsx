"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Beaker,
  CircleAlert,
  ExternalLink,
  GitCompareArrows,
  Loader2,
  RefreshCw,
  ShieldCheck,
  WalletCards,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type PairMethodLabCandidate } from "@/lib/api";

const integerFormatter = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const rupeeFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

function pValue(value: number | null | undefined) {
  if (value == null) return "—";
  if (value < 0.0001) return value.toExponential(2);
  return value.toFixed(4);
}

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${value.toFixed(1)}%`;
}

function fullDate(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(`${value}T00:00:00+05:30`).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  });
}

function tickerLink(
  ticker: string,
  instrumentType: "stock" | "index",
) {
  if (instrumentType === "index") {
    return <span className="font-mono font-semibold">{ticker}</span>;
  }
  return (
    <Link
      href={`/company/${encodeURIComponent(ticker)}`}
      className="font-mono font-semibold text-primary hover:underline"
    >
      {ticker}
    </Link>
  );
}

function signalText(pair: PairMethodLabCandidate) {
  if (pair.paper_signal === "long_a_short_b") {
    return `Paper rule: long ${pair.stock_a}, short ${pair.stock_b}`;
  }
  if (pair.paper_signal === "short_a_long_b") {
    return `Paper rule: short ${pair.stock_a}, long ${pair.stock_b}`;
  }
  return "Inside the paper's ±2σ entry band";
}

function comparisonText(pair: PairMethodLabCandidate) {
  if (pair.comparison === "both_methods") return "Found by both";
  if (pair.comparison === "paper_only") return "Paper method only";
  if (pair.comparison === "current_only") return "Current method only";
  return "Neither current screen";
}

function stabilityText(pair: PairMethodLabCandidate) {
  if (pair.stability_band === "strong") return "Strong stability";
  if (pair.stability_band === "moderate") return "Moderate stability";
  if (pair.stability_band === "unstable") return "Unstable relationship";
  return "Insufficient stability history";
}

function MethodBadge({ passed, children }: { passed: boolean; children: React.ReactNode }) {
  return (
    <Badge
      variant="outline"
      className={
        passed
          ? "border-emerald-700/30 text-emerald-700 dark:text-emerald-400"
          : "text-muted-foreground"
      }
    >
      {passed ? <ShieldCheck className="size-3" /> : null}
      {children}
    </Badge>
  );
}

function PairPriceChart({ pair }: { pair: PairMethodLabCandidate }) {
  return (
    <div className="h-[270px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={pair.chart} margin={{ top: 12, right: 12, left: 0, bottom: 4 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            minTickGap={38}
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            tickFormatter={(value) => String(value).slice(5)}
          />
          <YAxis
            width={42}
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            domain={["auto", "auto"]}
          />
          <Tooltip
            contentStyle={{
              borderRadius: 8,
              border: "1px solid var(--border)",
              background: "var(--card)",
              fontSize: 12,
            }}
            formatter={(value, name) => [Number(value).toFixed(2), name]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line
            dataKey="stock_a_indexed"
            name={pair.stock_a}
            stroke="var(--chart-1)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            dataKey="stock_b_indexed"
            name={pair.stock_b}
            stroke="var(--chart-2)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function PaperZScoreChart({ pair }: { pair: PairMethodLabCandidate }) {
  return (
    <div className="h-[270px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={pair.chart} margin={{ top: 12, right: 12, left: 0, bottom: 4 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            minTickGap={38}
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            tickFormatter={(value) => String(value).slice(5)}
          />
          <YAxis
            width={42}
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            tickFormatter={(value) => `${Number(value).toFixed(0)}σ`}
          />
          <Tooltip
            contentStyle={{
              borderRadius: 8,
              border: "1px solid var(--border)",
              background: "var(--card)",
              fontSize: 12,
            }}
            formatter={(value) => [`${Number(value).toFixed(2)}σ`, "Paper Z-score"]}
          />
          <ReferenceLine y={2} stroke="var(--chart-3)" strokeDasharray="5 5" />
          <ReferenceLine y={1} stroke="var(--muted-foreground)" strokeDasharray="2 5" />
          <ReferenceLine y={0} stroke="var(--foreground)" strokeOpacity={0.55} />
          <ReferenceLine y={-1} stroke="var(--muted-foreground)" strokeDasharray="2 5" />
          <ReferenceLine y={-2} stroke="var(--chart-3)" strokeDasharray="5 5" />
          <Line
            dataKey="paper_zscore"
            name="Paper Z-score"
            stroke="var(--chart-3)"
            strokeWidth={1.6}
            strokeDasharray="6 3"
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-md border border-border bg-card p-3">
      <p className="terminal-label">{label}</p>
      <p className="mt-1 font-mono text-lg font-semibold tabular-nums">{value}</p>
      {note ? <p className="mt-1 text-[10px] leading-4 text-muted-foreground">{note}</p> : null}
    </div>
  );
}

function CandidateCard({
  pair,
  rank,
  engleGrangerCutoff,
  currentComparisonDays,
}: {
  pair: PairMethodLabCandidate;
  rank: number;
  engleGrangerCutoff: number;
  currentComparisonDays: number;
}) {
  return (
    <Card className="overflow-hidden py-0">
      <CardHeader className="border-b border-border bg-muted/25 px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="grid size-8 shrink-0 place-items-center rounded-md bg-foreground font-mono text-xs font-semibold text-background">
              {String(rank).padStart(2, "0")}
            </span>
            <div>
              <CardTitle className="flex flex-wrap items-center gap-2 text-lg">
                {tickerLink(pair.stock_a, pair.stock_a_type)}
                <GitCompareArrows className="size-4 text-muted-foreground" />
                {tickerLink(pair.stock_b, pair.stock_b_type)}
              </CardTitle>
              <CardDescription className="mt-1">
                {pair.stock_a_name} · {pair.stock_b_name}
              </CardDescription>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {pair.tracker_entry_type ? (
              <Badge
                variant="outline"
                className="border-emerald-700/30 text-emerald-700 dark:text-emerald-400"
              >
                {pair.tracker_entry_type === "direct"
                  ? "Tracker: direct entry"
                  : "Tracker: confirmed convergence"}
              </Badge>
            ) : null}
            <Badge variant={pair.paper_signal === "inside_entry_band" ? "secondary" : "default"}>
              {signalText(pair)}
            </Badge>
            <Badge variant={pair.stability_band === "strong" ? "default" : "outline"}>
              {stabilityText(pair)} · {percent(pair.stability_score_percent)}
            </Badge>
            <Badge variant="outline">{comparisonText(pair)}</Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-4 sm:p-5">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(330px,0.65fr)]">
          <div className="space-y-4">
            <section className="rounded-lg border border-border bg-muted/10 p-2">
              <p className="px-2 pt-2 text-xs font-semibold">Indexed price comparison</p>
              <PairPriceChart pair={pair} />
              <p className="px-2 pb-2 text-[10px] leading-4 text-muted-foreground">
                Both adjusted closing-price series are rebased to 100 for visual comparison.
              </p>
            </section>
            <section className="rounded-lg border border-border bg-muted/10 p-2">
              <p className="px-2 pt-2 text-xs font-semibold">Paper-method spread Z-score</p>
              <PaperZScoreChart pair={pair} />
              <p className="px-2 pb-2 text-[10px] leading-4 text-muted-foreground">
                The tracker arms at |Z| ≥ 1.7 and exits near |Z| ≤ 0.2. Zero is the adaptive rolling mean.
              </p>
            </section>
          </div>

          <div className="space-y-4">
            <section className="rounded-lg border border-emerald-700/25 bg-emerald-500/[0.07] p-4">
              <p className="terminal-label text-emerald-700 dark:text-emerald-400">
                Potential gross return to Z = 0
              </p>
              <p className="mt-1 font-mono text-2xl font-semibold tabular-nums text-emerald-700 dark:text-emerald-400">
                {pair.potential_convergence_return_percent.toFixed(2)}%
              </p>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                Conditional return on both legs’ gross notional if the current {pair.current_zscore.toFixed(2)}σ
                raw-price spread fully returns to its adaptive mean. It is not probability-weighted
                and excludes costs, futures basis, lot rounding and margin.
              </p>
              {pair.tracker_recent_peak_abs_zscore != null ? (
                <p className="mt-2 font-mono text-[10px] text-muted-foreground">
                  Recent peak |Z| {pair.tracker_recent_peak_abs_zscore.toFixed(2)} · remaining return to |Z| = 0.2 {pair.tracker_remaining_return_percent?.toFixed(2) ?? "—"}%
                </p>
              ) : null}
            </section>

            <section className="rounded-lg border border-border p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="terminal-label">Nearest-expiry futures capital exposure</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Expiry {fullDate(pair.futures_expiry)} · prices dated {fullDate(pair.futures_price_date)}
                  </p>
                </div>
                <Badge variant={pair.capital_plan_is_active ? "default" : "secondary"}>
                  {pair.capital_plan_is_active ? "Current entry direction" : "Illustrative—no entry"}
                </Badge>
              </div>

              {pair.futures_capital_available ? (
                <>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <div className="rounded-md border border-emerald-700/20 bg-emerald-500/[0.05] p-3">
                      <p className="terminal-label text-emerald-700 dark:text-emerald-400">Long futures</p>
                      <p className="mt-1 font-mono text-sm font-semibold">{pair.capital_long_ticker}</p>
                      <p className="mt-2 font-mono text-xl font-semibold tabular-nums">
                        {rupeeFormatter.format(pair.long_futures_notional_inr ?? 0)}
                      </p>
                      <p className="mt-1 text-[10px] leading-4 text-muted-foreground">
                        {integerFormatter.format(pair.long_futures_contracts ?? 0)} contract(s) · {integerFormatter.format(pair.long_futures_units ?? 0)} units · {rupeeFormatter.format(pair.long_futures_price ?? 0)} futures price
                      </p>
                    </div>
                    <div className="rounded-md border border-rose-700/20 bg-rose-500/[0.05] p-3">
                      <p className="terminal-label text-rose-700 dark:text-rose-400">Short futures</p>
                      <p className="mt-1 font-mono text-sm font-semibold">{pair.capital_short_ticker}</p>
                      <p className="mt-2 font-mono text-xl font-semibold tabular-nums">
                        {rupeeFormatter.format(pair.short_futures_notional_inr ?? 0)}
                      </p>
                      <p className="mt-1 text-[10px] leading-4 text-muted-foreground">
                        {integerFormatter.format(pair.short_futures_contracts ?? 0)} contract(s) · {integerFormatter.format(pair.short_futures_units ?? 0)} units · {rupeeFormatter.format(pair.short_futures_price ?? 0)} futures price
                      </p>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap items-end justify-between gap-2 rounded-md bg-muted/45 p-3">
                    <div>
                      <p className="terminal-label">Combined gross notional</p>
                      <p className="mt-1 font-mono text-xl font-semibold tabular-nums">
                        {rupeeFormatter.format(pair.combined_futures_notional_inr ?? 0)}
                      </p>
                    </div>
                    <p className="text-[10px] text-muted-foreground">
                      Whole-lot hedge fit {percent(pair.futures_hedge_fit_percent)}
                    </p>
                  </div>
                </>
              ) : (
                <p className="mt-3 text-xs leading-5 text-muted-foreground">
                  {pair.futures_capital_note ?? "A common futures capital plan is unavailable."}
                </p>
              )}
              {pair.futures_capital_available ? (
                <p className="mt-3 text-[10px] leading-4 text-muted-foreground">
                  {pair.futures_capital_note} This is exposure, not cash paid; check the broker order preview for actual margin.
                </p>
              ) : null}
            </section>

            <section className="rounded-lg border border-border p-4">
              <p className="terminal-label">Latest 252-day formation window</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <MethodBadge passed={pair.engle_granger_pass}>
                  Engle–Granger {pair.engle_granger_pass ? "passed" : "failed"}
                </MethodBadge>
                <MethodBadge passed={pair.kss_pass}>
                  KSS {pair.kss_pass ? "passed" : "failed"}
                </MethodBadge>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <Metric
                  label="EG raw p"
                  value={pValue(pair.engle_granger_p_value)}
                  note={`Stricter lab cutoff: ${engleGrangerCutoff}`}
                />
                <Metric
                  label="BH-adjusted q"
                  value={pValue(pair.fdr_q_value)}
                  note="Primary result ordering; tracker requires q ≤ 0.05"
                />
                <Metric
                  label="KSS statistic"
                  value={pair.kss_statistic.toFixed(3)}
                  note={`Passes at ≤ ${pair.kss_critical_value}`}
                />
                <Metric label="OU half-life" value={`${pair.half_life_days.toFixed(1)} days`} />
                <Metric
                  label="Adaptive window"
                  value={`${pair.adaptive_lookback_days} days`}
                  note="Calculated from half-life"
                />
              </div>
            </section>

            <section className="rounded-lg border border-border p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="terminal-label">Six-window stability score</p>
                  <p className="mt-1 font-mono text-2xl font-semibold tabular-nums">
                    {percent(pair.stability_score_percent)}
                  </p>
                </div>
                <Badge variant={pair.stability_band === "strong" ? "default" : "outline"}>
                  {stabilityText(pair)}
                </Badge>
              </div>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                Both tests passed together in {pair.stability_passed_windows} of {pair.rolling_windows}{" "}
                weekly 252-day windows. Strong = 5–6 passes, moderate = 4, unstable = 0–3.
              </p>
              <p className="terminal-label mt-4">Rolling out-of-sample diagnostic</p>
              <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                <div>
                  <p className="text-muted-foreground">EG stayed significant</p>
                  <p className="mt-0.5 font-mono font-semibold">{percent(pair.engle_granger_stability_percent)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">KSS stayed significant</p>
                  <p className="mt-0.5 font-mono font-semibold">{percent(pair.kss_stability_percent)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Entry crossings</p>
                  <p className="mt-0.5 font-mono font-semibold">{pair.entry_events}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Reached exit band</p>
                  <p className="mt-0.5 font-mono font-semibold">{percent(pair.reversion_success_rate_percent)}</p>
                </div>
              </div>
              <p className="mt-3 text-[10px] leading-4 text-muted-foreground">
                “Reached exit band” only
                measures weeks with an actual ±2σ crossing; no crossing means no paper trade.
              </p>
            </section>

            <section className="rounded-lg border border-primary/20 bg-accent/35 p-4">
              <p className="terminal-label text-primary">Against the current scanner</p>
              <div className="mt-2 grid grid-cols-3 gap-3 text-sm">
                <div>
                  <p className="text-[10px] text-muted-foreground">Current p</p>
                  <p className="font-mono font-semibold">{pValue(pair.current_method_p_value)}</p>
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground">Current half-life</p>
                  <p className="font-mono font-semibold">
                    {pair.current_method_half_life_days == null
                      ? "—"
                      : `${pair.current_method_half_life_days.toFixed(1)}d`}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground">Current Z</p>
                  <p className="font-mono font-semibold">
                    {pair.current_method_zscore == null ? "—" : `${pair.current_method_zscore.toFixed(2)}σ`}
                  </p>
                </div>
              </div>
              <p className="mt-3 text-xs leading-5 text-muted-foreground">
                Lab’s current-method comparison: {currentComparisonDays} observations, log prices,
                fixed 60-day Z-score window and p ≤ 0.001.
                Paper lab: 252-day rolling formation, adaptive window and p ≤ {engleGrangerCutoff} or KSS pass.
                The lab list is ordered by BH-adjusted q. The tracker requires both lab tests,
                q ≤ 0.05 and |Z| ≥ 1.7 before opening a spot-proxy observation.
              </p>
            </section>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function PairMethodLabView() {
  const [screeningMode, setScreeningMode] = useState("q_value");
  const [testFilter, setTestFilter] = useState("both");
  const [comparisonFilter, setComparisonFilter] = useState("all");
  const [absoluteZFilter, setAbsoluteZFilter] = useState("tracker");
  const [qValueCutoff, setQValueCutoff] = useState("0.05");
  const queryClient = useQueryClient();
  const scan = useQuery({
    queryKey: ["pair-method-lab"],
    queryFn: () => api.getPairMethodLab(160, false),
    staleTime: 5 * 60 * 1000,
  });
  const refresh = useMutation({
    mutationFn: () => api.getPairMethodLab(160, true),
    onSuccess: (data) => queryClient.setQueryData(["pair-method-lab"], data),
  });
  const results = useMemo(() => {
    return (scan.data?.results ?? []).filter((pair) => {
      const testMatch =
        testFilter === "either" ||
        (testFilter === "both" && pair.engle_granger_pass && pair.kss_pass) ||
        (testFilter === "exactly_one" && pair.engle_granger_pass !== pair.kss_pass) ||
        (testFilter === "engle_granger_only" && pair.engle_granger_pass && !pair.kss_pass) ||
        (testFilter === "kss_only" && pair.kss_pass && !pair.engle_granger_pass);
      const comparisonMatch =
        comparisonFilter === "all" || pair.comparison === comparisonFilter;
      const screeningMatch =
        screeningMode === "q_value"
          ? pair.fdr_q_value <= Number(qValueCutoff) && testMatch
          : testMatch && comparisonMatch;
      const absoluteZMatch =
        absoluteZFilter === "all" ||
        (absoluteZFilter === "tracker" && pair.tracker_entry_type != null) ||
        Math.abs(pair.current_zscore) >= Number(absoluteZFilter);
      return screeningMatch && absoluteZMatch;
    });
  }, [
    absoluteZFilter,
    comparisonFilter,
    qValueCutoff,
    scan.data?.results,
    screeningMode,
    testFilter,
  ]);
  const pending = scan.isFetching || refresh.isPending;

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-5 border-b border-border pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <p className="page-eyebrow flex items-center gap-2">
            <Beaker className="size-3.5" /> Development experiment
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] sm:text-[2.5rem]">
            Dynamic pairs-method lab
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            Compare the current pair scanner with the rolling Engle–Granger, nonlinear
            KSS and OU half-life method from the linked cryptocurrency paper—adapted to
            daily NSE F&amp;O data and kept completely outside production trade suggestions.
            Both comparison models use the same 252-day sample on this page.
          </p>
          {scan.data ? (
            <a
              href={scan.data.paper_url}
              target="_blank"
              rel="noreferrer"
              className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
            >
              {scan.data.paper_title} <ExternalLink className="size-3" />
            </a>
          ) : null}
        </div>
        <div className="flex flex-col items-start gap-3 lg:items-end">
          <div className="flex flex-wrap gap-2">
            <Badge>Development only</Badge>
            <Badge variant="outline">All eligible NSE F&amp;O pairs</Badge>
            <Badge variant="outline">₹500 Cr minimum</Badge>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" asChild>
              <Link href="/pair-method-tracker">
                <WalletCards /> Open P&amp;L tracker
              </Link>
            </Button>
            <Button variant="outline" onClick={() => refresh.mutate()} disabled={pending}>
              {pending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              {pending ? "Running paper scan…" : "Re-run experiment"}
            </Button>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-amber-600/30 bg-amber-500/[0.07] p-4">
        <div className="flex items-start gap-3">
          <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" />
          <div>
            <p className="text-sm font-semibold">A comparison experiment, not a recommendation engine</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              The source paper used minute crypto prices and executable BitMEX quotes. This page
              substitutes daily equity/index history, so it evaluates whether the selection logic
              behaves differently—it does not reproduce the paper’s reported profitability. The
              lab now applies approximately 0.01% thresholds to both tests: p ≤ 0.0001 for
              Engle–Granger and a separately calibrated residual statistic for KSS. A pair can
              still appear after passing either test unless you select “Both tests.”
            </p>
          </div>
        </div>
      </section>

      {scan.data ? (
        <>
          <section className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border lg:grid-cols-6">
            {[
              [scan.data.official_underlyings, "Official underlyings"],
              [scan.data.universe_size, "Eligible universe"],
              [scan.data.price_eligible_universe, "Enough history"],
              [scan.data.pairs_tested, "Pairs tested"],
              [scan.data.engle_granger_candidates, "EG candidates"],
              [scan.data.kss_candidates, "KSS candidates"],
            ].map(([value, label]) => (
              <div key={label} className="bg-card px-4 py-3">
                <p className="font-mono text-xl font-semibold tabular-nums">
                  {integerFormatter.format(Number(value))}
                </p>
                <p className="terminal-label mt-1">{label}</p>
              </div>
            ))}
          </section>

          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <Metric label="Formation" value={`${scan.data.formation_days} days`} note="Re-estimated weekly" />
            <Metric label="Current comparison" value={`${scan.data.current_comparison_days} days`} note="Same window, log prices" />
            <Metric label="Validation" value={`${scan.data.trading_days} days`} note="Out-of-sample week" />
            <Metric label="Stability" value={`${scan.data.rolling_validation_windows} windows`} note="Both tests must pass together" />
            <Metric label="EG cutoff" value={`p ≤ ${scan.data.engle_granger_cutoff}`} note="Stricter lab confidence: 0.01%" />
            <Metric label="KSS cutoff" value={`t ≤ ${scan.data.kss_critical_value}`} note="Calibrated 0.01% residual cutoff" />
          </section>

          <section className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="section-heading">Method comparison results</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Showing {results.length} of {scan.data.returned} deeply validated candidates,
                ranked from lowest to highest BH q-value. {screeningMode === "q_value"
                  ? `FDR mode requires q ≤ ${qValueCutoff} and the selected test outcome; the versus-current comparison is ignored. This controls the expected false-discovery share, not a per-pair confidence probability.`
                  : "Method mode applies the test and versus-current selections."}
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <label className="space-y-1">
                <span className="terminal-label block">Screening basis</span>
                <select
                  value={screeningMode}
                  onChange={(event) => setScreeningMode(event.target.value)}
                  className="h-9 rounded-md border border-input bg-card px-3 text-sm"
                >
                  <option value="method">Method diagnostics</option>
                  <option value="q_value">FDR q-value + test result</option>
                </select>
              </label>
              <label className="space-y-1">
                <span className="terminal-label block">Passed test</span>
                <select
                  value={testFilter}
                  onChange={(event) => setTestFilter(event.target.value)}
                  className="h-9 rounded-md border border-input bg-card px-3 text-sm"
                >
                  <option value="either">At least one test</option>
                  <option value="both">Both tests</option>
                  <option value="exactly_one">Exactly one test</option>
                  <option value="engle_granger_only">Engle–Granger only</option>
                  <option value="kss_only">KSS nonlinear only</option>
                </select>
              </label>
              {screeningMode === "method" ? (
                <label className="space-y-1">
                  <span className="terminal-label block">Versus current</span>
                  <select
                    value={comparisonFilter}
                    onChange={(event) => setComparisonFilter(event.target.value)}
                    className="h-9 rounded-md border border-input bg-card px-3 text-sm"
                  >
                    <option value="all">All comparisons</option>
                    <option value="both_methods">Found by both</option>
                    <option value="paper_only">Paper method only</option>
                    <option value="current_only">Current method only</option>
                  </select>
                </label>
              ) : (
                <label className="space-y-1">
                  <span className="terminal-label block">Maximum FDR q-value</span>
                  <select
                    value={qValueCutoff}
                    onChange={(event) => setQValueCutoff(event.target.value)}
                    className="h-9 rounded-md border border-input bg-card px-3 text-sm"
                  >
                    <option value="0.05">q ≤ 0.05 · 5% FDR</option>
                    <option value="0.075">q ≤ 0.075 · 7.5% FDR</option>
                    <option value="0.10">q ≤ 0.10 · 10% FDR</option>
                    <option value="0.125">q ≤ 0.125 · 12.5% FDR</option>
                    <option value="0.15">q ≤ 0.15 · 15% FDR</option>
                  </select>
                </label>
              )}
              <label className="space-y-1">
                <span className="terminal-label block">Absolute Z-score</span>
                <select
                  value={absoluteZFilter}
                  onChange={(event) => setAbsoluteZFilter(event.target.value)}
                  className="h-9 rounded-md border border-input bg-card px-3 text-sm"
                >
                  <option value="all">All Z-scores</option>
                  <option value="tracker">Tracker-qualified entries</option>
                  <option value="0.5">|Z| ≥ 0.5σ</option>
                  <option value="1">|Z| ≥ 1σ</option>
                  <option value="1.5">|Z| ≥ 1.5σ</option>
                  <option value="1.7">|Z| ≥ 1.7σ — tracker entry</option>
                  <option value="2">|Z| ≥ 2σ — paper entry</option>
                  <option value="2.5">|Z| ≥ 2.5σ</option>
                  <option value="3">|Z| ≥ 3σ</option>
                </select>
              </label>
            </div>
          </section>
        </>
      ) : null}

      {scan.isPending ? (
        <div className="space-y-4">
          {[0, 1].map((item) => (
            <Card key={item}>
              <CardHeader><Skeleton className="h-6 w-72" /></CardHeader>
              <CardContent className="grid gap-4 lg:grid-cols-2">
                <Skeleton className="h-96 w-full" />
                <Skeleton className="h-96 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : scan.isError ? (
        <Card className="border-rose-500/30">
          <CardContent className="py-8">
            <p className="font-semibold">The development scan could not be completed.</p>
            <p className="mt-1 text-sm text-muted-foreground">
              The production scanner is unaffected. Check the API and historical-data connection,
              then re-run this experiment.
            </p>
            <Button className="mt-4" variant="outline" onClick={() => scan.refetch()}>
              Try again
            </Button>
          </CardContent>
        </Card>
      ) : results.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No candidates match the selected filters.
          </CardContent>
        </Card>
      ) : (
        <section className="space-y-5" aria-label="Paper method candidates">
          {results.map((pair, index) => (
            <CandidateCard
              key={pair.pair_id}
              pair={pair}
              rank={index + 1}
              engleGrangerCutoff={scan.data!.engle_granger_cutoff}
              currentComparisonDays={scan.data!.current_comparison_days}
            />
          ))}
        </section>
      )}

      {scan.data ? (
        <details className="rounded-lg border border-border bg-card p-4">
          <summary className="cursor-pointer text-sm font-semibold">Method limits and implementation notes</summary>
          <ul className="mt-3 space-y-2 pl-5 text-xs leading-5 text-muted-foreground">
            {scan.data.limitations.map((limitation) => (
              <li key={limitation} className="list-disc">{limitation}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
