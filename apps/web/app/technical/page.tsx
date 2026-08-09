"use client";

import { api, type TechnicalScanResponse } from "@/lib/api";
import { useLiveQuotes } from "@/lib/use-live-quotes";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  ChartNoAxesCombined,
  Clock3,
  DatabaseZap,
  Loader2,
  Search,
  Waves,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

const EXAMPLES = [
  "NSE stocks with RSI below 35, bullish MACD and price above VWAP.",
  "Renewable power companies with positive 15-candle momentum and relative volume above 1.5x.",
  "F&O stocks with call OI change above 10%, PCR above 1.2 and RSI below 45.",
  "Banking companies with a nearest-expiry put delta between 0.25 and 0.35 and positive 15-candle momentum.",
];

const CANDLE_INTERVALS = [
  { value: "1m", label: "1 minute" },
  { value: "5m", label: "5 minutes" },
  { value: "15m", label: "15 minutes" },
  { value: "30m", label: "30 minutes" },
  { value: "1h", label: "1 hour" },
  { value: "1d", label: "1 day" },
] as const;

type CandleInterval = (typeof CANDLE_INTERVALS)[number]["value"];
const INDICATOR_LABELS: Record<string, string> = {
  rsi_14: "RSI(14)",
  macd_histogram: "MACD histogram",
  price_vs_vwap_percent: "Price vs VWAP",
  ema_9_vs_ema_21_percent: "EMA 9 vs 21",
  return_5c_percent: "5-candle return",
  return_15c_percent: "15-candle return",
  return_60c_percent: "60-candle return",
  relative_volume: "Relative volume",
  atr_percent: "ATR / price",
  bollinger_position_percent: "Bollinger position",
  call_oi_change_percent: "Call OI change",
  put_oi_change_percent: "Put OI change",
  put_call_oi_ratio: "Put/call OI ratio",
  call_delta: "Call |delta|",
  put_delta: "Put |delta|",
};
const OPTION_INDICATORS = new Set([
  "call_oi_change_percent",
  "put_oi_change_percent",
  "put_call_oi_ratio",
  "call_delta",
  "put_delta",
]);

function percent(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function planLabel(condition: TechnicalScanResponse["plan"]["conditions"][number]) {
  const operator = { gt: ">", gte: "≥", lt: "<", lte: "≤", between: "between" }[
    condition.operator
  ] ?? condition.operator;
  const value = Array.isArray(condition.value)
    ? condition.value.join("–")
    : condition.value;
  return `${INDICATOR_LABELS[condition.indicator] ?? condition.indicator} ${operator} ${value}`;
}

export default function TechnicalScannerPage() {
  const [query, setQuery] = useState(EXAMPLES[0]);
  const [candleInterval, setCandleInterval] = useState<CandleInterval>("1m");
  const [candleCount, setCandleCount] = useState(70);
  const status = useQuery({
    queryKey: ["technical-status"],
    queryFn: api.getTechnicalStatus,
    refetchInterval: 3_000,
  });
  const scan = useMutation({
    mutationFn: () => api.runTechnicalScan(query, 20, candleInterval, candleCount),
  });
  const liveQuotes = useLiveQuotes(
    scan.data?.results.map((result) => result.ticker) ?? [],
  );
  const intervalLabel =
    CANDLE_INTERVALS.find((item) => item.value === candleInterval)?.label ?? candleInterval;
  const hasOptionFilter =
    scan.data?.plan.conditions.some((condition) =>
      OPTION_INDICATORS.has(condition.indicator),
    ) ?? false;
  const showCandleMetrics = !scan.data?.candle_scan_skipped;

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-5 border-b border-border pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <p className="page-eyebrow flex items-center gap-2">
            <Waves className="size-3.5" /> Multi-timeframe semantic scanner
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] sm:text-[2.5rem]">
            Search business context and market structure together.
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            Natural language is separated into verified-card semantics and deterministic
            technical and nearest-expiry option-chain conditions, then evaluated across
            the NSE main board using the exact candle interval and bounded window you select.
          </p>
        </div>
        <div className="grid grid-cols-3 overflow-hidden rounded-lg border border-border bg-border">
          {[
            ["2,386", "Main-board universe"],
            [candleInterval, "Interval"],
            [String(candleCount), "Candles"],
          ].map(([value, label]) => (
            <div key={label} className="min-w-24 bg-card px-4 py-3 text-center">
              <p className="font-mono text-lg font-semibold tabular-nums">{value}</p>
              <p className="terminal-label mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="gap-0 overflow-hidden py-0">
          <div className="flex items-center justify-between bg-[#24241f] px-4 py-3 text-white sm:px-5">
            <span className="flex items-center gap-2 font-mono text-[11px] font-semibold uppercase tracking-[0.1em]">
              <ChartNoAxesCombined className="size-4 text-emerald-300" /> New algorithmic scan
            </span>
            <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-white/50">
              India · NSE main board
            </span>
          </div>
          <CardContent className="p-4 sm:p-5">
            <Textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label="Describe the technical and business conditions to scan"
              className="min-h-32 resize-none border-0 bg-transparent px-1 text-base leading-7 shadow-none focus-visible:ring-0"
            />
            <div className="grid gap-4 border-t border-border py-4 md:grid-cols-[220px_minmax(0,1fr)]">
              <label className="space-y-2">
                <span className="terminal-label block">Candle duration</span>
                <select
                  value={candleInterval}
                  onChange={(event) => setCandleInterval(event.target.value as CandleInterval)}
                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  aria-label="Candle duration"
                >
                  {CANDLE_INTERVALS.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-2">
                <span className="flex items-center justify-between gap-3">
                  <span className="terminal-label">Number of candles</span>
                  <span className="font-mono text-[10px] text-muted-foreground">35–70</span>
                </span>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={35}
                    max={70}
                    step={1}
                    value={candleCount}
                    onChange={(event) => setCandleCount(Number(event.target.value))}
                    className="h-2 min-w-0 flex-1 cursor-pointer accent-emerald-600"
                    aria-label="Number of candles"
                  />
                  <Input
                    type="number"
                    min={35}
                    max={70}
                    value={candleCount}
                    onChange={(event) => {
                      const value = Number(event.target.value);
                      if (Number.isFinite(value)) setCandleCount(Math.min(70, Math.max(35, value)));
                    }}
                    className="w-20 font-mono tabular-nums"
                    aria-label="Candle count"
                  />
                </div>
                <span className="block text-[10px] text-muted-foreground">
                  Fetch {candleCount} × {intervalLabel} candles per stock.
                </span>
              </label>
            </div>
            <div className="flex flex-col gap-3 border-t border-border pt-3 sm:flex-row sm:items-center">
              <span className="text-xs text-muted-foreground">
                RSI · MACD · VWAP · momentum · OI change · PCR · call/put delta
              </span>
              <Button
                onClick={() => scan.mutate()}
                disabled={!query.trim() || scan.isPending}
                className="sm:ml-auto"
              >
                {scan.isPending ? <Loader2 className="animate-spin" /> : <Search />}
                {scan.isPending ? "Scanning market…" : "Run scan"}
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="gap-0 py-0">
          <CardHeader className="border-b border-border py-4">
            <CardTitle className="flex items-center gap-2 text-sm">
              <DatabaseZap className="size-4" /> Data pipeline
            </CardTitle>
            <CardDescription>Current scanner configuration.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 py-4 text-xs">
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Active source</span>
              <Badge
                variant={
                  status.data?.upstox_configured || status.data?.yahoo_stream.connected
                    ? "default"
                    : "outline"
                }
              >
                {status.data?.active_source ?? "Checking…"}
              </Badge>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Live quote coverage</span>
              <span className="flex items-center gap-1.5 font-mono">
                <span
                  className={`size-1.5 rounded-full ${
                    status.data?.yahoo_stream.connected ? "bg-emerald-500" : "bg-muted-foreground/40"
                  }`}
                />
                {status.data?.yahoo_stream.connected
                  ? `${status.data.yahoo_stream.base_symbols} F&O${
                      status.data.yahoo_stream.dynamic_symbols
                        ? ` + ${status.data.yahoo_stream.dynamic_symbols} dynamic`
                        : ""
                    } · ${status.data.yahoo_stream.connected_shards}/${status.data.yahoo_stream.total_shards} feeds`
                  : "Waiting"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Parallel requests</span>
              <span className="font-mono">{status.data?.concurrency ?? "—"}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Input window</span>
              <span className="font-mono">{candleCount} × {candleInterval}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Options source</span>
              <span className="text-right font-mono">NSE · nearest expiry</span>
            </div>
            {!status.isLoading && !status.data?.upstox_configured && (
              <p className="border-t border-border pt-3 leading-5 text-muted-foreground">
                Yahoo&apos;s WebSocket pins the current NSE F&O universe and dynamically
                adds displayed scan results, up to {status.data?.yahoo_stream.max_symbols ?? 500}
                {" "}symbols. yfinance history still backfills the selected candle window.
              </p>
            )}
          </CardContent>
        </Card>
      </section>

      <div className="flex flex-wrap gap-2">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => setQuery(example)}
            className="rounded-full border border-border bg-card px-3 py-1.5 text-left text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            {example}
          </button>
        ))}
      </div>

      {scan.isError && (
        <Card>
          <CardContent className="py-6 text-sm text-destructive">
            The scan could not be completed: {String(scan.error)}
          </CardContent>
        </Card>
      )}

      {scan.data && (
        <section className="space-y-4">
          <div className="flex flex-col gap-3 border-b border-border pb-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="page-eyebrow">Parsed scan</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {scan.data.plan.semantic_concept && (
                  <Badge variant="secondary">Business: {scan.data.plan.semantic_concept}</Badge>
                )}
                {scan.data.plan.conditions.map((condition, index) => (
                  <Badge key={`${condition.indicator}-${index}`} variant="outline">
                    {planLabel(condition)}
                  </Badge>
                ))}
                {scan.data.plan.sort_by && (
                  <Badge variant="secondary">
                    Sort: {INDICATOR_LABELS[scan.data.plan.sort_by] ?? scan.data.plan.sort_by}
                    {scan.data.plan.sort_direction === "desc" ? " ↓" : " ↑"}
                  </Badge>
                )}
              </div>
            </div>
            <div className="flex items-center gap-4 font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              {scan.data.candle_scan_skipped ? (
                <span>Candles skipped</span>
              ) : (
                <span>{scan.data.scanned}/{scan.data.semantic_candidates} scanned</span>
              )}
              {hasOptionFilter && (
                <span>
                  {scan.data.options_scanned}/{scan.data.option_candidates} chains
                </span>
              )}
              <span>{scan.data.returned} matches</span>
              {!scan.data.candle_scan_skipped && (
                <span>{scan.data.candle_limit} × {scan.data.candle_interval}</span>
              )}
              <span>{scan.data.data_source}</span>
            </div>
          </div>

          <Card className="gap-0 overflow-hidden py-0">
            <div className="overflow-x-auto">
              <table
                className={`w-full text-left text-xs ${
                  hasOptionFilter
                    ? showCandleMetrics
                      ? "min-w-[1540px]"
                      : "min-w-[1040px]"
                    : "min-w-[1080px]"
                }`}
              >
                <thead className="border-b border-border bg-muted/35 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Company</th>
                    <th className="px-3 py-3 text-right">Match</th>
                    <th className="px-3 py-3 text-right">Price</th>
                    {showCandleMetrics && (
                      <>
                        <th className="px-3 py-3 text-right">RSI</th>
                        <th className="px-3 py-3 text-right">MACD hist.</th>
                        <th className="px-3 py-3 text-right">vs VWAP</th>
                        <th className="px-3 py-3 text-right">EMA 9/21</th>
                        <th className="px-3 py-3 text-right">15 candles</th>
                        <th className="px-3 py-3 text-right">Rel. vol.</th>
                      </>
                    )}
                    {hasOptionFilter && (
                      <>
                        <th className="px-3 py-3 text-right">Expiry</th>
                        <th className="px-3 py-3 text-right">Call Δ / strike</th>
                        <th className="px-3 py-3 text-right">Put Δ / strike</th>
                        <th className="px-3 py-3 text-right">Call ΔOI</th>
                        <th className="px-3 py-3 text-right">Put ΔOI</th>
                        <th className="px-3 py-3 text-right">PCR</th>
                      </>
                    )}
                    <th className="px-4 py-3 text-right">As of</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {scan.data.results.map((result) => {
                    const liveQuote = liveQuotes[result.ticker];
                    const displayPrice = liveQuote?.price ?? result.price;
                    const displayTime = liveQuote?.event_time ?? result.candle_time;
                    return (
                      <tr key={result.ticker} className="transition-colors hover:bg-muted/30">
                        <td className="max-w-[310px] px-4 py-3">
                          <Link
                            href={`/company/${result.ticker}`}
                            className="group inline-flex items-center gap-2 font-medium hover:underline"
                          >
                            {result.ticker}
                            <ArrowUpRight className="size-3 opacity-50 group-hover:opacity-100" />
                          </Link>
                          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                            {result.name}
                          </p>
                          {result.semantic_evidence && (
                            <p className="mt-1 line-clamp-1 text-[10px] text-muted-foreground">
                              {result.semantic_evidence}
                            </p>
                          )}
                        </td>
                        <td className="px-3 py-3 text-right font-mono font-semibold tabular-nums">
                          {(result.combined_score * 100).toFixed(1)}%
                        </td>
                        <td className="px-3 py-3 text-right font-mono tabular-nums">
                          <span className="inline-flex items-center justify-end gap-1.5">
                            {liveQuote && (
                              <span
                                className="size-1.5 rounded-full bg-emerald-500"
                                title="Live Yahoo quote"
                              />
                            )}
                            {displayPrice == null
                              ? "—"
                              : `₹${displayPrice.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`}
                          </span>
                        </td>
                        {showCandleMetrics && (
                          <>
                            <td className="px-3 py-3 text-right font-mono tabular-nums">
                              {result.rsi_14?.toFixed(1) ?? "—"}
                            </td>
                            <td className="px-3 py-3 text-right font-mono tabular-nums">
                              {result.macd_histogram?.toFixed(3) ?? "—"}
                            </td>
                            <td className="px-3 py-3 text-right font-mono tabular-nums">
                              {percent(result.price_vs_vwap_percent)}
                            </td>
                            <td className="px-3 py-3 text-right font-mono tabular-nums">
                              {percent(result.ema_9_vs_ema_21_percent)}
                            </td>
                            <td className="px-3 py-3 text-right font-mono tabular-nums">
                              {percent(result.return_15c_percent)}
                            </td>
                            <td className="px-3 py-3 text-right font-mono tabular-nums">
                              {result.relative_volume == null
                                ? "—"
                                : `${result.relative_volume.toFixed(2)}x`}
                            </td>
                          </>
                        )}
                        {hasOptionFilter && (
                          <>
                            <td className="px-3 py-3 text-right font-mono tabular-nums">
                              {result.option_expiry ?? "—"}
                            </td>
                            <td className="px-3 py-3 text-right font-mono tabular-nums">
                              {result.call_delta == null
                                ? "—"
                                : `${result.call_delta.toFixed(2)} / ₹${result.call_delta_strike?.toLocaleString("en-IN") ?? "—"}`}
                            </td>
                            <td className="px-3 py-3 text-right font-mono tabular-nums">
                              {result.put_delta == null
                                ? "—"
                                : `${result.put_delta.toFixed(2)} / ₹${result.put_delta_strike?.toLocaleString("en-IN") ?? "—"}`}
                            </td>
                            <td className="px-3 py-3 text-right font-mono tabular-nums">
                              {percent(result.call_oi_change_percent)}
                            </td>
                            <td className="px-3 py-3 text-right font-mono tabular-nums">
                              {percent(result.put_oi_change_percent)}
                            </td>
                            <td className="px-3 py-3 text-right font-mono tabular-nums">
                              {result.put_call_oi_ratio?.toFixed(2) ?? "—"}
                            </td>
                          </>
                        )}
                        <td className="px-4 py-3 text-right text-[10px] text-muted-foreground">
                          {new Date(displayTime).toLocaleString()}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {scan.data.results.length === 0 && (
              <div className="py-12 text-center text-sm text-muted-foreground">
                No scanned company satisfied every required condition.
              </div>
            )}
          </Card>

          <div className="space-y-1 text-[11px] leading-5 text-muted-foreground">
            {scan.data.limitations.map((limitation) => (
              <p key={limitation}>• {limitation}</p>
            ))}
          </div>
        </section>
      )}

      {!scan.data && !scan.isPending && (
        <div className="grid gap-4 sm:grid-cols-3">
          {[
            [Activity, "Vectorized indicators", "RSI, MACD, EMA, VWAP, ATR and Bollinger metrics are calculated in one pandas pass."],
            [Clock3, "Latest available session", "During closed markets, the scanner uses the most recent candles at your selected interval rather than returning empty results."],
            [DatabaseZap, "Semantic + market structure", "Annual-report similarity and candle rules narrow the universe before bounded NSE option-chain filters are applied."],
          ].map(([Icon, title, description]) => {
            const FeatureIcon = Icon as typeof Activity;
            return (
              <Card key={String(title)}>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-sm">
                    <FeatureIcon className="size-4" /> {String(title)}
                  </CardTitle>
                  <CardDescription className="leading-5">{String(description)}</CardDescription>
                </CardHeader>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
