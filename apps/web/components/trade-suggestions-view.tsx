"use client";

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
  ArrowDownRight,
  ArrowUpRight,
  CalendarClock,
  CircleAlert,
  GitCompareArrows,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Wallet,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type PairSuggestion, type PaperPairTrade } from "@/lib/api";
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

const integerFormatter = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 0,
});
const rupeeFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});
const P_VALUE_OPTIONS = [
  "0.0001",
  "0.0005",
  "0.001",
  "0.0025",
  "0.005",
  "0.01",
  "0.025",
  "0.05",
];

function formatPValueThreshold(value: number) {
  return value < 0.01 ? value.toFixed(4).replace(/0+$/, "") : value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function shortDate(value: string) {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
  });
}

function fullDate(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function dateTime(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  });
}

function usePaperPortfolioId() {
  const [portfolioId, setPortfolioId] = useState<string>();
  useEffect(() => {
    const storageKey = "easy-invest-paper-portfolio-id";
    const existing = window.localStorage.getItem(storageKey);
    let resolved = existing;
    if (!resolved) {
      resolved = window.crypto.randomUUID();
      window.localStorage.setItem(storageKey, resolved);
    }
    const frame = window.requestAnimationFrame(() => setPortfolioId(resolved));
    return () => window.cancelAnimationFrame(frame);
  }, []);
  return portfolioId;
}

function confidenceLabel(qValue: number) {
  if (qValue < 0.01) return "Very strong";
  if (qValue <= 0.05) return "Strong";
  if (qValue <= 0.15) return "Exploratory";
  return "High uncertainty";
}

function formatTestProbability(value: number) {
  if (value > 0 && value < 0.0001) return value.toExponential(2);
  return value.toFixed(4);
}

function signalLabel(pair: PairSuggestion) {
  return pair.signal === "watch" ? "Watch for a wider gap" : "Gap is active";
}

function EquityResearchLink({
  ticker,
  instrumentType,
  className = "",
}: {
  ticker: string;
  instrumentType: PairSuggestion["stock_a_type"];
  className?: string;
}) {
  if (instrumentType === "index") {
    return <span className={className}>{ticker}</span>;
  }

  return (
    <Link
      href={`/company/${encodeURIComponent(ticker)}`}
      className={`underline decoration-current/30 underline-offset-4 transition-colors hover:text-primary hover:decoration-current ${className}`}
      aria-label={`Open equity research for ${ticker}`}
    >
      {ticker}
    </Link>
  );
}

function PairMetric({
  label,
  value,
  helper,
}: {
  label: string;
  value: string;
  helper: string;
}) {
  return (
    <div className="rounded-md border border-border bg-muted/30 px-3 py-2.5">
      <p className="terminal-label">{label}</p>
      <p className="mt-1 font-mono text-base font-semibold tabular-nums">{value}</p>
      <p className="mt-0.5 text-[10px] leading-4 text-muted-foreground">{helper}</p>
    </div>
  );
}

function PriceRelationshipChart({ pair }: { pair: PairSuggestion }) {
  return (
    <div>
      <div className="mb-3">
        <p className="text-sm font-semibold">How the two stocks moved</p>
        <p className="text-xs text-muted-foreground">
          Both prices start at 100 so their paths are easy to compare.
        </p>
      </div>
      <div className="h-56 w-full" role="img" aria-label={`${pair.stock_a} and ${pair.stock_b} normalized price history`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={pair.chart} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
            <XAxis
              dataKey="date"
              tickFormatter={shortDate}
              tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
              tickLine={false}
              axisLine={false}
              minTickGap={34}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
              tickLine={false}
              axisLine={false}
              width={48}
              domain={["auto", "auto"]}
            />
            <Tooltip
              labelFormatter={(value) => shortDate(String(value))}
              formatter={(value, name) => [
                `${Number(value).toFixed(1)}`,
                name === "stock_a_indexed" ? pair.stock_a : pair.stock_b,
              ]}
              contentStyle={{
                borderRadius: 8,
                border: "1px solid var(--border)",
                background: "var(--card)",
                fontSize: 12,
              }}
            />
            <Legend
              formatter={(value) =>
                value === "stock_a_indexed" ? pair.stock_a : pair.stock_b
              }
              wrapperStyle={{ fontSize: 11 }}
            />
            <Line
              type="monotone"
              dataKey="stock_a_indexed"
              stroke="var(--chart-1)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 3 }}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="stock_b_indexed"
              stroke="var(--chart-2)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 3 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function SpreadChart({ pair }: { pair: PairSuggestion }) {
  return (
    <div>
      <div className="mb-3">
        <p className="text-sm font-semibold">How unusual the gap is</p>
        <p className="text-xs text-muted-foreground">
          Green bands mark a meaningful separation; the centre is normal.
        </p>
      </div>
      <div className="h-56 w-full" role="img" aria-label={`${pair.stock_a} and ${pair.stock_b} relationship distance`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={pair.chart} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
            <XAxis
              dataKey="date"
              tickFormatter={shortDate}
              tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
              tickLine={false}
              axisLine={false}
              minTickGap={34}
            />
            <YAxis
              domain={[-3.5, 3.5]}
              ticks={[-3, -2, 0, 2, 3]}
              tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
              tickLine={false}
              axisLine={false}
              width={48}
            />
            <Tooltip
              labelFormatter={(value) => shortDate(String(value))}
              formatter={(value) => [`${Number(value).toFixed(2)}σ`, "Distance"]}
              contentStyle={{
                borderRadius: 8,
                border: "1px solid var(--border)",
                background: "var(--card)",
                fontSize: 12,
              }}
            />
            <ReferenceLine y={2} stroke="var(--chart-1)" strokeDasharray="5 5" />
            <ReferenceLine y={0} stroke="var(--muted-foreground)" />
            <ReferenceLine y={-2} stroke="var(--chart-1)" strokeDasharray="5 5" />
            <Line
              type="monotone"
              dataKey="spread_zscore"
              name="Distance"
              stroke="var(--chart-3)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 3 }}
              connectNulls
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function PairCard({
  pair,
  rank,
  onTrack,
  isTracking,
  isTracked,
}: {
  pair: PairSuggestion;
  rank: number;
  onTrack: () => void;
  isTracking: boolean;
  isTracked: boolean;
}) {
  const active = pair.signal !== "watch";
  const instrumentTypeFor = (ticker: string) =>
    ticker === pair.stock_a ? pair.stock_a_type : pair.stock_b_type;

  return (
    <Card className="overflow-hidden py-0">
      <CardHeader className="border-b border-border bg-muted/25 px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <span className="grid size-8 shrink-0 place-items-center rounded-md bg-foreground font-mono text-xs font-semibold text-background">
              {String(rank).padStart(2, "0")}
            </span>
            <div className="min-w-0">
              <CardTitle className="flex flex-wrap items-center gap-2 text-lg">
                <EquityResearchLink
                  ticker={pair.stock_a}
                  instrumentType={pair.stock_a_type}
                />
                <GitCompareArrows className="size-4 text-muted-foreground" />
                <EquityResearchLink
                  ticker={pair.stock_b}
                  instrumentType={pair.stock_b_type}
                />
              </CardTitle>
              <CardDescription className="mt-1 truncate">
                {pair.stock_a_name} · {pair.stock_b_name}
              </CardDescription>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={active ? "default" : "secondary"}>{signalLabel(pair)}</Badge>
            <Badge
              variant="outline"
              className={
                pair.fdr_q_value <= 0.05
                  ? "border-emerald-700/30 text-emerald-700 dark:text-emerald-400"
                  : "border-amber-700/30 text-amber-700 dark:text-amber-400"
              }
            >
              {pair.fdr_q_value <= 0.05 ? "FDR passed" : "Higher-risk candidate"}
            </Badge>
            <Badge variant="outline">
              {pair.stock_a_type === "index" || pair.stock_b_type === "index"
                ? "Includes index"
                : pair.sector}
            </Badge>
            {pair.futures_plan_available && (
              <Button
                size="sm"
                onClick={onTrack}
                disabled={isTracking || isTracked}
              >
                <Plus className="size-3.5" />
                {isTracking
                  ? "Saving…"
                  : isTracked
                    ? "Paper pair tracked"
                    : active
                      ? "Track futures pair"
                      : "Paper-test watch setup"}
              </Button>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-4 sm:p-5">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.6fr)]">
          <div className="rounded-lg border border-emerald-700/20 bg-emerald-500/[0.06] p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-sm font-semibold">
                  {active ? "NSE futures order plan" : "Futures plan if the gap activates"}
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Expected reset by {fullDate(pair.estimated_reversion_date)}
                  {pair.futures_expiry
                    ? ` · selected expiry ${fullDate(pair.futures_expiry)}`
                    : ""}
                </p>
              </div>
              <Badge variant={active ? "default" : "secondary"}>
                {active ? "Enter together" : "Wait—no entry yet"}
              </Badge>
            </div>

            {pair.futures_plan_available ? (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-md border border-emerald-700/20 bg-card p-3">
                  <p className="terminal-label flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400">
                    <ArrowUpRight className="size-3.5" /> Buy futures
                  </p>
                  <p className="mt-1 text-lg font-semibold">
                    {integerFormatter.format(pair.long_futures_contracts ?? 0)}{" "}
                    {(pair.long_futures_contracts ?? 0) === 1
                      ? "contract"
                      : "contracts"}{" "}
                    of{" "}
                    <EquityResearchLink
                      ticker={pair.long_ticker}
                      instrumentType={instrumentTypeFor(pair.long_ticker)}
                    />
                  </p>
                  <p className="mt-1 font-mono text-xs font-medium">
                    {pair.long_futures_contract_name}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    NSE close {rupeeFormatter.format(pair.long_futures_price ?? 0)} ·{" "}
                    {integerFormatter.format(pair.long_futures_lot_size ?? 0)} units/lot
                    <br />
                    {integerFormatter.format(pair.long_futures_units ?? 0)} total units ·{" "}
                    {rupeeFormatter.format(pair.long_futures_notional_inr ?? 0)} notional
                  </p>
                </div>
                <div className="rounded-md border border-rose-700/20 bg-card p-3">
                  <p className="terminal-label flex items-center gap-1.5 text-rose-700 dark:text-rose-400">
                    <ArrowDownRight className="size-3.5" /> Short futures
                  </p>
                  <p className="mt-1 text-lg font-semibold">
                    {integerFormatter.format(pair.short_futures_contracts ?? 0)}{" "}
                    {(pair.short_futures_contracts ?? 0) === 1
                      ? "contract"
                      : "contracts"}{" "}
                    of{" "}
                    <EquityResearchLink
                      ticker={pair.short_ticker}
                      instrumentType={instrumentTypeFor(pair.short_ticker)}
                    />
                  </p>
                  <p className="mt-1 font-mono text-xs font-medium">
                    {pair.short_futures_contract_name}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    NSE close {rupeeFormatter.format(pair.short_futures_price ?? 0)} ·{" "}
                    {integerFormatter.format(pair.short_futures_lot_size ?? 0)} units/lot
                    <br />
                    {integerFormatter.format(pair.short_futures_units ?? 0)} total units ·{" "}
                    {rupeeFormatter.format(pair.short_futures_notional_inr ?? 0)} notional
                  </p>
                </div>
              </div>
            ) : (
              <div className="mt-4 rounded-md border border-amber-600/30 bg-amber-500/[0.08] p-3">
                <p className="text-sm font-semibold">No executable expiry is available</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {pair.futures_plan_note}
                </p>
              </div>
            )}

            <div className="mt-3 rounded-md border border-border bg-card/70 px-3 py-2.5 text-xs leading-5 text-muted-foreground">
              {!pair.futures_plan_available ? (
                <>
                  <strong className="text-foreground">What to do:</strong> skip this
                  setup until both legs have a common listed futures expiry.
                </>
              ) : active ? (
                <>
                  <strong className="text-foreground">How to place it:</strong> submit
                  the buy-futures and short-futures orders together, or as close
                  together as your broker allows. Close both before expiry when the
                  gap returns toward normal.
                </>
              ) : (
                <>
                  <strong className="text-foreground">What to do now:</strong> wait.
                  This pair is still inside its normal range. Use these quantities only
                  if the page later marks the gap as active.
                </>
              )}
              {pair.futures_plan_available && (
                <span className="mt-1 block">
                  Futures do not require paying the full notional upfront. Your
                  broker calculates and blocks SPAN/exposure margin, which changes
                  with market risk; use the broker&apos;s order preview for the
                  actual cash required.
                </span>
              )}
              {pair.futures_requires_rollover && (
                <span className="mt-1 block font-medium text-amber-700 dark:text-amber-400">
                  The nearest common expiry is before the estimated reset date. Close
                  before expiry or roll both legs together if the relationship has not
                  reverted.
                </span>
              )}
            </div>

            {pair.futures_plan_available && (
              <div className="mt-3 rounded-md border border-emerald-700/20 bg-emerald-500/[0.07] p-3">
              <p className="terminal-label">
                {active
                  ? "Potential gross return at 0σ"
                  : "Hypothetical gross return at 0σ"}
              </p>
              <p className="mt-1 font-mono text-2xl font-semibold tabular-nums text-emerald-700 dark:text-emerald-400">
                +{pair.example_gross_return_percent.toFixed(2)}%
              </p>
              <p className="text-[10px] text-muted-foreground">
                of combined position value
              </p>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                If the gap moves from {Math.abs(pair.current_zscore).toFixed(2)}σ
                to 0σ, the model estimates{" "}
                <EquityResearchLink
                  ticker={pair.long_ticker}
                  instrumentType={instrumentTypeFor(pair.long_ticker)}
                  className="font-medium text-foreground"
                />{" "}
                near{" "}
                {rupeeFormatter.format(pair.long_futures_target_price ?? 0)} and{" "}
                <EquityResearchLink
                  ticker={pair.short_ticker}
                  instrumentType={instrumentTypeFor(pair.short_ticker)}
                  className="font-medium text-foreground"
                />{" "}
                near{" "}
                {rupeeFormatter.format(pair.short_futures_target_price ?? 0)}. This
                assumes both prices share the convergence according to their
                historical relationship.
              </p>
              <p className="mt-1 text-[10px] leading-4 text-muted-foreground">
                Gross futures estimate only: excludes brokerage, taxes, slippage,
                daily mark-to-market funding, dividends, margin interest, and rollover.
              </p>
              </div>
            )}

            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              {pair.explanation}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <PairMetric
              label="Current gap"
              value={`${Math.abs(pair.current_zscore).toFixed(2)}σ`}
              helper={active ? "Outside the watch level" : "Still inside the watch level"}
            />
            <PairMetric
              label="Typical reset"
              value={`${pair.half_life_days.toFixed(0)} days`}
              helper="Historical estimate"
            />
            <PairMetric
              label="Moved together"
              value={`${Math.round(pair.return_correlation * 100)}%`}
              helper="Daily-return similarity"
            />
            <PairMetric
              label="Relationship"
              value={confidenceLabel(pair.fdr_q_value)}
              helper="Adjusted for all pairs tested"
            />
          </div>
        </div>

        <div className="mt-5 grid gap-6 border-t border-border pt-5 xl:grid-cols-2">
          <PriceRelationshipChart pair={pair} />
          <SpreadChart pair={pair} />
        </div>

        <details className="mt-4 rounded-md border border-border px-3 py-2 text-xs text-muted-foreground">
          <summary className="cursor-pointer font-medium text-foreground">
            Advanced statistical and liquidity details (optional)
          </summary>
          <div className="mt-3 grid gap-2 leading-5 sm:grid-cols-2 lg:grid-cols-4">
            <span>Model weighting: {pair.hedge_ratio.toFixed(3)}</span>
            <span>
              Futures expiry:{" "}
              {pair.futures_expiry ? fullDate(pair.futures_expiry) : "Unavailable"}
            </span>
            <span>
              Whole-lot hedge fit:{" "}
              {pair.futures_hedge_fit_percent == null
                ? "—"
                : `${pair.futures_hedge_fit_percent.toFixed(1)}%`}
            </span>
            <span>
              Futures prices dated: {fullDate(pair.futures_price_date)}
            </span>
            <span>
              Cointegration p: {formatTestProbability(pair.cointegration_p_value)}
            </span>
            <span>FDR q: {formatTestProbability(pair.fdr_q_value)}</span>
            <span>{integerFormatter.format(pair.observations)} daily observations</span>
            <span>
              <EquityResearchLink
                ticker={pair.stock_a}
                instrumentType={pair.stock_a_type}
              />
              :{" "}
              {pair.stock_a_type === "index"
                ? "Index · market cap N/A"
                : `₹${integerFormatter.format(pair.stock_a_market_cap_crore ?? 0)} Cr`}
            </span>
            <span>
              <EquityResearchLink
                ticker={pair.stock_b}
                instrumentType={pair.stock_b_type}
              />
              :{" "}
              {pair.stock_b_type === "index"
                ? "Index · market cap N/A"
                : `₹${integerFormatter.format(pair.stock_b_market_cap_crore ?? 0)} Cr`}
            </span>
            <span>
              <EquityResearchLink
                ticker={pair.stock_a}
                instrumentType={pair.stock_a_type}
              />{" "}
              median traded:{" "}
              {pair.stock_a_median_daily_value_crore == null
                ? "—"
                : `₹${pair.stock_a_median_daily_value_crore.toFixed(1)} Cr/day`}
            </span>
            <span>
              <EquityResearchLink
                ticker={pair.stock_b}
                instrumentType={pair.stock_b_type}
              />{" "}
              median traded:{" "}
              {pair.stock_b_median_daily_value_crore == null
                ? "—"
                : `₹${pair.stock_b_median_daily_value_crore.toFixed(1)} Cr/day`}
            </span>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

function PaperPairTracker({
  trades,
  isLoading,
  isError,
  isRefreshing,
  closingTradeId,
  onRefresh,
  onClose,
}: {
  trades?: PaperPairTrade[];
  isLoading: boolean;
  isError: boolean;
  isRefreshing: boolean;
  closingTradeId?: string;
  onRefresh: () => void;
  onClose: (tradeId: string) => void;
}) {
  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b border-border">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Wallet className="size-4 text-emerald-700 dark:text-emerald-400" />
              Paper futures pair tracker
            </CardTitle>
            <CardDescription className="mt-1 max-w-3xl">
              Track the exact long and short futures contracts without placing an
              order. Open positions use authenticated live futures LTPs when
              available, with a clearly labelled official NSE EOD fallback.
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={onRefresh}
            disabled={isRefreshing}
          >
            {isRefreshing ? (
              <Loader2 className="animate-spin" />
            ) : (
              <RefreshCw />
            )}
            Refresh values
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-5">
        {isLoading ? (
          <Skeleton className="h-48 w-full" />
        ) : isError ? (
          <div className="rounded-md border border-amber-600/30 bg-amber-500/[0.08] p-3 text-sm">
            Saved pair positions could not be loaded right now.
          </div>
        ) : !trades?.length ? (
          <div className="rounded-md border border-dashed border-border px-5 py-8 text-center">
            <p className="text-sm font-medium">No futures pairs tracked yet</p>
            <p className="mx-auto mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">
              Track an active pair or paper-test a watch setup. The nearest common
              expiry, whole-contract hedge ratio, entry closes and signal state will
              be saved.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {trades.map((trade) => {
              const mark =
                trade.status === "open"
                  ? (trade.live_mark ?? trade.latest_mark)
                  : trade.latest_mark;
              const pnl = mark?.total_pnl;
              const chart = trade.marks.map((item) => ({
                date: shortDate(item.price_date),
                totalPnl: item.total_pnl,
                longPnl: item.long_pnl,
                shortPnl: item.short_pnl,
              }));
              if (trade.status === "open" && trade.live_mark) {
                chart.push({
                  date: "Live",
                  totalPnl: trade.live_mark.total_pnl,
                  longPnl: trade.live_mark.long_pnl,
                  shortPnl: trade.live_mark.short_pnl,
                });
              }
              return (
                <section
                  key={trade.id}
                  className="overflow-hidden rounded-md border border-border"
                >
                  <div className="flex flex-col justify-between gap-3 border-b border-border bg-muted/25 px-4 py-3 sm:flex-row sm:items-start">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-semibold">
                          {trade.long_ticker} ↔ {trade.short_ticker}
                        </p>
                        <Badge variant="outline">
                          {trade.status === "open" ? "Open paper pair" : "Closed"}
                        </Badge>
                        {trade.status === "open" && mark?.is_live && (
                          <Badge
                            variant="outline"
                            className="border-emerald-700/30 text-emerald-700 dark:text-emerald-400"
                          >
                            Live futures LTP
                          </Badge>
                        )}
                        {trade.status === "open" && mark && !mark.is_live && (
                          <Badge
                            variant="outline"
                            className="border-amber-700/30 text-amber-700 dark:text-amber-400"
                          >
                            EOD futures fallback
                          </Badge>
                        )}
                        {trade.entry_signal === "watch" && (
                          <Badge
                            variant="outline"
                            className="border-amber-700/30 text-amber-700 dark:text-amber-400"
                          >
                            Entered before trigger
                          </Badge>
                        )}
                        {trade.requires_rollover && (
                          <Badge
                            variant="outline"
                            className="border-amber-700/30 text-amber-700 dark:text-amber-400"
                          >
                            May need rollover
                          </Badge>
                        )}
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        Entered {dateTime(trade.entry_price_timestamp ?? trade.created_at)} ·{" "}
                        {trade.entry_price_source} · expiry {fullDate(trade.expiry)}
                        {mark?.is_live
                          ? ` · latest quote ${dateTime(mark.quote_timestamp)}`
                          : ""}
                      </p>
                    </div>
                    {trade.status === "open" && (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={
                          !mark ||
                          Boolean(trade.valuation_limitation) ||
                          closingTradeId === trade.id
                        }
                        onClick={() => onClose(trade.id)}
                      >
                        {closingTradeId === trade.id
                          ? "Recording exit…"
                          : "Close paper pair"}
                      </Button>
                    )}
                  </div>

                  <div className="grid gap-0 xl:grid-cols-[0.95fr_1.15fr]">
                    <div className="border-b border-border p-4 xl:border-b-0 xl:border-r">
                      <div className="grid gap-2 sm:grid-cols-2">
                        <div className="rounded-md border border-emerald-700/20 bg-emerald-500/[0.06] p-3">
                          <p className="terminal-label text-emerald-700 dark:text-emerald-400">
                            Long futures
                          </p>
                          <p className="mt-1 text-sm font-semibold">
                            Buy {integerFormatter.format(trade.long_contracts)}{" "}
                            {trade.long_ticker} contracts
                          </p>
                          <p className="mt-1 font-mono text-[11px]">
                            {trade.long_contract_name}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {integerFormatter.format(trade.long_units)} underlying units
                          </p>
                          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-emerald-700/15 pt-3 text-xs">
                            <div>
                              <dt className="text-muted-foreground">Entry price</dt>
                              <dd className="mt-0.5 font-mono font-semibold">
                                {rupeeFormatter.format(trade.entry_long_price)}
                              </dd>
                            </div>
                            <div>
                              <dt className="text-muted-foreground">
                                {mark?.is_live
                                  ? "Live futures LTP"
                                  : trade.status === "open"
                                    ? "Latest EOD futures close"
                                    : "Exit price"}
                              </dt>
                              <dd className="mt-0.5 font-mono font-semibold">
                                {mark ? rupeeFormatter.format(mark.long_price) : "—"}
                              </dd>
                            </div>
                            <div>
                              <dt className="text-muted-foreground">Entry long notional</dt>
                              <dd className="mt-0.5 font-mono font-semibold">
                                {rupeeFormatter.format(trade.entry_long_notional)}
                              </dd>
                            </div>
                            <div>
                              <dt className="text-muted-foreground">Current long notional</dt>
                              <dd className="mt-0.5 font-mono font-semibold">
                                {mark
                                  ? rupeeFormatter.format(mark.current_long_notional)
                                  : "—"}
                              </dd>
                            </div>
                            <div className="col-span-2 border-t border-emerald-700/15 pt-2">
                              <dt className="text-muted-foreground">Long-leg P&amp;L</dt>
                              <dd
                                className={`mt-0.5 font-mono font-semibold ${
                                  mark == null
                                    ? ""
                                    : mark.long_pnl >= 0
                                      ? "text-emerald-700 dark:text-emerald-400"
                                      : "text-rose-700 dark:text-rose-400"
                                }`}
                              >
                                {mark
                                  ? `${mark.long_pnl >= 0 ? "+" : "−"}${rupeeFormatter.format(Math.abs(mark.long_pnl))}`
                                  : "—"}
                              </dd>
                            </div>
                          </dl>
                        </div>
                        <div className="rounded-md border border-rose-700/20 bg-rose-500/[0.05] p-3">
                          <p className="terminal-label text-rose-700 dark:text-rose-400">
                            Short futures
                          </p>
                          <p className="mt-1 text-sm font-semibold">
                            Sell {integerFormatter.format(trade.short_contracts)}{" "}
                            {trade.short_ticker} contracts
                          </p>
                          <p className="mt-1 font-mono text-[11px]">
                            {trade.short_contract_name}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {integerFormatter.format(trade.short_units)} underlying units
                          </p>
                          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-rose-700/15 pt-3 text-xs">
                            <div>
                              <dt className="text-muted-foreground">Entry price</dt>
                              <dd className="mt-0.5 font-mono font-semibold">
                                {rupeeFormatter.format(trade.entry_short_price)}
                              </dd>
                            </div>
                            <div>
                              <dt className="text-muted-foreground">
                                {mark?.is_live
                                  ? "Live futures LTP"
                                  : trade.status === "open"
                                    ? "Latest EOD futures close"
                                    : "Exit price"}
                              </dt>
                              <dd className="mt-0.5 font-mono font-semibold">
                                {mark ? rupeeFormatter.format(mark.short_price) : "—"}
                              </dd>
                            </div>
                            <div>
                              <dt className="text-muted-foreground">Entry short notional</dt>
                              <dd className="mt-0.5 font-mono font-semibold">
                                {rupeeFormatter.format(trade.entry_short_notional)}
                              </dd>
                            </div>
                            <div>
                              <dt className="text-muted-foreground">Current short notional</dt>
                              <dd className="mt-0.5 font-mono font-semibold">
                                {mark
                                  ? rupeeFormatter.format(mark.current_short_notional)
                                  : "—"}
                              </dd>
                            </div>
                            <div className="col-span-2 border-t border-rose-700/15 pt-2">
                              <dt className="text-muted-foreground">Short-leg P&amp;L</dt>
                              <dd
                                className={`mt-0.5 font-mono font-semibold ${
                                  mark == null
                                    ? ""
                                    : mark.short_pnl >= 0
                                      ? "text-emerald-700 dark:text-emerald-400"
                                      : "text-rose-700 dark:text-rose-400"
                                }`}
                              >
                                {mark
                                  ? `${mark.short_pnl >= 0 ? "+" : "−"}${rupeeFormatter.format(Math.abs(mark.short_pnl))}`
                                  : "—"}
                              </dd>
                            </div>
                          </dl>
                        </div>
                      </div>

                      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                        <div className="rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-muted-foreground">Combined entry notional</p>
                          <p className="mt-1 font-mono font-semibold">
                            {rupeeFormatter.format(trade.entry_combined_notional)}
                          </p>
                        </div>
                        <div className="rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-muted-foreground">
                            {trade.status === "closed" ? "Realized P&L" : "P&L if closed now"}
                          </p>
                          <p
                            className={`mt-1 font-mono font-semibold ${
                              pnl == null
                                ? ""
                                : pnl >= 0
                                  ? "text-emerald-700 dark:text-emerald-400"
                                  : "text-rose-700 dark:text-rose-400"
                            }`}
                          >
                            {pnl == null
                              ? "—"
                              : `${pnl >= 0 ? "+" : "−"}${rupeeFormatter.format(Math.abs(pnl))}`}
                          </p>
                        </div>
                        <div className="rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-muted-foreground">Gross-notional return</p>
                          <p
                            className={`mt-1 font-mono font-semibold ${
                              (mark?.return_percent ?? 0) >= 0
                                ? "text-emerald-700 dark:text-emerald-400"
                                : "text-rose-700 dark:text-rose-400"
                            }`}
                          >
                            {mark
                              ? `${mark.return_percent >= 0 ? "+" : ""}${mark.return_percent.toFixed(2)}%`
                              : "—"}
                          </p>
                        </div>
                        <div className="rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-muted-foreground">Whole-lot hedge fit</p>
                          <p className="mt-1 font-mono font-semibold">
                            {trade.hedge_fit_percent.toFixed(1)}%
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="p-4">
                      <p className="terminal-label">Recorded P&amp;L over time</p>
                      {chart.length ? (
                        <div className="mt-3 h-64">
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart
                              data={chart}
                              margin={{ top: 8, right: 18, left: 8, bottom: 8 }}
                            >
                              <CartesianGrid
                                strokeDasharray="3 3"
                                vertical={false}
                                stroke="var(--border)"
                              />
                              <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                              <YAxis
                                tick={{ fontSize: 10 }}
                                width={70}
                                tickFormatter={(value) =>
                                  `₹${integerFormatter.format(Number(value))}`
                                }
                              />
                              <Tooltip
                                formatter={(value, name) => [
                                  rupeeFormatter.format(Number(value)),
                                  String(name),
                                ]}
                              />
                              <Legend wrapperStyle={{ fontSize: 11 }} />
                              <ReferenceLine
                                y={0}
                                stroke="var(--muted-foreground)"
                              />
                              <Line
                                type="monotone"
                                dataKey="longPnl"
                                name="Long-leg P&L"
                                stroke="var(--chart-1)"
                                strokeWidth={1.5}
                                dot={{ r: 2 }}
                              />
                              <Line
                                type="monotone"
                                dataKey="shortPnl"
                                name="Short-leg P&L"
                                stroke="var(--chart-2)"
                                strokeWidth={1.5}
                                dot={{ r: 2 }}
                              />
                              <Line
                                type="monotone"
                                dataKey="totalPnl"
                                name="Combined P&L"
                                stroke="var(--chart-3)"
                                strokeWidth={2.5}
                                dot={{ r: 3 }}
                              />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      ) : (
                        <div className="mt-3 rounded-md bg-muted/25 px-4 py-8 text-center text-xs text-muted-foreground">
                          No official closing-price mark is available yet.
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="border-t border-border bg-muted/15 px-4 py-3 text-[11px] leading-5 text-muted-foreground">
                    {trade.valuation_limitation ? (
                      <span className="text-amber-700 dark:text-amber-400">
                        {trade.valuation_limitation}
                      </span>
                    ) : (
                      mark?.is_live
                        ? `P&L uses authenticated live LTPs for both exact saved futures contracts via ${mark.price_source}.`
                        : "P&L uses the saved live exit prices for both exact futures contracts."
                    )}{" "}
                    Gross notional is not cash paid: futures require broker margin and
                    settle through daily mark-to-market. Brokerage, taxes, slippage,
                    margin funding and rollover costs are excluded.
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function LoadingState() {
  return (
    <div className="space-y-4" aria-label="Scanning pair relationships">
      {[0, 1].map((item) => (
        <Card key={item}>
          <CardHeader>
            <Skeleton className="h-6 w-64" />
            <Skeleton className="h-4 w-80 max-w-full" />
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 lg:grid-cols-2">
              <Skeleton className="h-52 w-full" />
              <Skeleton className="h-52 w-full" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function TradeSuggestionsView() {
  const [pValueThreshold, setPValueThreshold] = useState(0.001);
  const portfolioId = usePaperPortfolioId();
  const queryClient = useQueryClient();
  const suggestions = useQuery({
    queryKey: ["trade-suggestions", pValueThreshold],
    queryFn: () => api.getTradeSuggestions(12, false, pValueThreshold),
    staleTime: 5 * 60 * 1000,
  });
  const refreshScan = useMutation({
    mutationFn: () => api.getTradeSuggestions(12, true, pValueThreshold),
    onSuccess: (data) => {
      queryClient.setQueryData(["trade-suggestions", pValueThreshold], data);
    },
  });
  const paperTrades = useQuery({
    queryKey: ["paper-pair-trades", portfolioId],
    queryFn: () => api.listPaperPairTrades(portfolioId!),
    enabled: Boolean(portfolioId),
    staleTime: 60 * 1000,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.some(
        (trade) => trade.status === "open" && trade.live_mark?.is_live
      )
        ? 5 * 1000
        : 5 * 60 * 1000;
    },
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
  const createPaperTrade = useMutation({
    mutationFn: (pairId: string) =>
      api.createPaperPairTrade(portfolioId!, pairId, pValueThreshold),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["paper-pair-trades", portfolioId],
      }),
  });
  const closePaperTrade = useMutation({
    mutationFn: (tradeId: string) =>
      api.closePaperPairTrade(portfolioId!, tradeId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["paper-pair-trades", portfolioId],
      }),
  });
  const scanPending = suggestions.isFetching || refreshScan.isPending;
  const paperTradeError =
    createPaperTrade.error instanceof Error
      ? createPaperTrade.error.message
      : closePaperTrade.error instanceof Error
        ? closePaperTrade.error.message
        : null;

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-5 border-b border-border pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <p className="page-eyebrow flex items-center gap-2">
            <Sparkles className="size-3.5" /> Market-neutral research
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] sm:text-[2.5rem]">
            Trade suggestions
          </h1>
          <div className="mt-3 max-w-2xl space-y-0.5 text-sm leading-6 text-muted-foreground">
            <p>Pairs trading looks for two related stocks that usually move together.</p>
            <p>When they drift apart, the idea is to buy the laggard and sell the leader.</p>
            <p>The trade aims to benefit if their usual relationship returns—not from guessing the market.</p>
          </div>
        </div>
        <div className="flex flex-col items-start gap-3 lg:items-end">
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">NSE F&amp;O only</Badge>
            <Badge variant="outline">Stocks ₹500 Cr minimum</Badge>
            <Badge variant="outline">Indices included</Badge>
            <Badge variant="outline">Latest 250 trading days</Badge>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <label className="space-y-1.5">
              <span className="terminal-label block">Cointegration p-value cutoff</span>
              <select
                value={String(pValueThreshold)}
                onChange={(event) => setPValueThreshold(Number(event.target.value))}
                className="h-9 min-w-48 rounded-md border border-input bg-card px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                aria-label="Cointegration p-value cutoff"
              >
                {P_VALUE_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                    {value === "0.001" ? " · default" : ""}
                    {value === "0.05" ? " · maximum" : ""}
                  </option>
                ))}
              </select>
              <span className="block max-w-56 text-[10px] leading-4 text-muted-foreground">
                Only pairs at or below this raw pair-level cutoff are shown.
              </span>
            </label>
            <Button
              variant="outline"
              onClick={() => refreshScan.mutate()}
              disabled={scanPending}
            >
              {scanPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              {scanPending ? "Scanning all pairs…" : "Refresh suggestions"}
            </Button>
          </div>
        </div>
      </section>

      {pValueThreshold > 0.001 && (
        <section className="rounded-lg border border-amber-600/30 bg-amber-500/[0.08] p-4">
          <div className="flex items-start gap-3">
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" />
            <div>
              <p className="text-sm font-semibold">
                Higher statistical tolerance: p ≤ {formatPValueThreshold(pValueThreshold)}
              </p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                This relaxes the raw cointegration test above the 0.001 default.
                Because it is not adjusted for the thousands of pairs tested, treat
                additional matches as exploratory and check the displayed FDR q-value.
              </p>
            </div>
          </div>
        </section>
      )}

      {suggestions.data && (
        <section className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
          {[
            [suggestions.data.official_underlyings, "Official underlyings"],
            [suggestions.data.universe_size, "Eligible instruments"],
            [suggestions.data.price_eligible_universe, "With enough history"],
            [suggestions.data.pairs_tested, "Pairs tested"],
          ].map(([value, label]) => (
            <div key={label} className="bg-card px-4 py-3">
              <p className="font-mono text-xl font-semibold tabular-nums">
                {integerFormatter.format(Number(value))}
              </p>
              <p className="terminal-label mt-1">{label}</p>
            </div>
          ))}
        </section>
      )}

      <PaperPairTracker
        trades={paperTrades.data}
        isLoading={!portfolioId || paperTrades.isLoading}
        isError={paperTrades.isError}
        isRefreshing={paperTrades.isFetching}
        closingTradeId={
          closePaperTrade.isPending ? closePaperTrade.variables : undefined
        }
        onRefresh={() => paperTrades.refetch()}
        onClose={(tradeId) => closePaperTrade.mutate(tradeId)}
      />

      {paperTradeError && (
        <section className="rounded-lg border border-amber-600/30 bg-amber-500/[0.08] p-4 text-xs leading-5">
          The paper pair could not be updated. {paperTradeError}
        </section>
      )}

      {suggestions.isPending ? (
        <LoadingState />
      ) : suggestions.isError ? (
        <Card className="border-rose-500/30">
          <CardContent className="flex flex-col items-start gap-3 py-6">
            <CircleAlert className="size-5 text-rose-600" />
            <div>
              <p className="font-semibold">The pair scan could not be completed.</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Check that market data and company snapshots are available, then try again.
              </p>
            </div>
            <Button variant="outline" onClick={() => suggestions.refetch()}>
              Try again
            </Button>
          </CardContent>
        </Card>
      ) : suggestions.data.results.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center">
            <ShieldCheck className="mx-auto size-7 text-emerald-700" />
            <p className="mt-3 font-semibold">No relationships passed every check today.</p>
            <p className="mx-auto mt-1 max-w-xl text-sm leading-6 text-muted-foreground">
              That is a valid result: the scanner will not manufacture an idea when the
              market-cap, history, cointegration, and trade-quality checks do not agree.
            </p>
          </CardContent>
        </Card>
      ) : (
        <section className="space-y-5" aria-label="Pair-trade suggestions">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="section-heading">Best current relationships</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Active gaps appear first, followed by stable pairs worth watching.
                Eligible pairs are ranked by gap size, expected reversion speed, and
                return similarity—not by q-value. {" "}
                The raw p-value cutoff is{" "}
                {formatPValueThreshold(suggestions.data.p_value_threshold)}. Showing the top{" "}
                {suggestions.data.returned} of{" "}
                {integerFormatter.format(suggestions.data.p_significant_pairs)}{" "}
                relationships that pass the selected cointegration cutoff and the
                remaining trade-quality checks. FDR q-values remain visible for context.
              </p>
            </div>
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <CalendarClock className="size-3.5" />
              Updated {new Date(suggestions.data.generated_at).toLocaleString("en-IN")}
              {suggestions.data.cached ? " · cached" : ""}
            </p>
          </div>
          {suggestions.data.results.map((pair, index) => (
            <PairCard
              key={pair.pair_id}
              pair={pair}
              rank={index + 1}
              onTrack={() => createPaperTrade.mutate(pair.pair_id)}
              isTracking={
                createPaperTrade.isPending &&
                createPaperTrade.variables === pair.pair_id
              }
              isTracked={Boolean(
                paperTrades.data?.some(
                  (trade) =>
                    trade.status === "open" && trade.pair_id === pair.pair_id
                )
              )}
            />
          ))}
        </section>
      )}

      {suggestions.data && (
        <section className="rounded-lg border border-amber-600/20 bg-amber-500/[0.06] p-4">
          <div className="flex items-start gap-3">
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" />
            <div>
              <p className="text-sm font-semibold">Treat these as research leads</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Statistical relationships can break. Futures are leveraged and settled
                through daily mark-to-market. Confirm live prices, available margin,
                liquidity, news, and execution risk with your broker, and close stock
                futures before expiry to avoid settlement obligations.
              </p>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
