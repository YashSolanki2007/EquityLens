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
  Activity,
  CircleAlert,
  FlaskConical,
  Loader2,
  RefreshCw,
  Wifi,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

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
import { api, type PaperLabSpotTrade, type PaperLabSpotTradeMark } from "@/lib/api";
import { type LiveQuote, useLiveQuotes } from "@/lib/use-live-quotes";

const moneyFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const priceFormatter = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function signedMoney(value: number) {
  return `${value >= 0 ? "+" : "−"}${moneyFormatter.format(Math.abs(value))}`;
}

function signedPercent(value: number) {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(3)}%`;
}

function testProbability(value: number) {
  if (value < 0.001) return value.toExponential(2);
  return value.toFixed(4);
}

function timestamp(value: string) {
  return new Date(value).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "Asia/Kolkata",
  });
}

function clientLiveMark(
  trade: PaperLabSpotTrade,
  quotes: Record<string, LiveQuote>
): PaperLabSpotTradeMark | null {
  const longQuote = quotes[trade.long_ticker];
  const shortQuote = quotes[trade.short_ticker];
  if (!longQuote || !shortQuote || trade.status !== "open") return null;
  const longPnl = trade.long_units * (longQuote.price - trade.entry_long_price);
  const shortPnl = trade.short_units * (trade.entry_short_price - shortQuote.price);
  const totalPnl = longPnl + shortPnl;
  const currentLongNotional = trade.long_units * longQuote.price;
  const currentShortNotional = trade.short_units * shortQuote.price;
  return {
    id: null,
    long_price: longQuote.price,
    short_price: shortQuote.price,
    long_pnl: longPnl,
    short_pnl: shortPnl,
    total_pnl: totalPnl,
    return_percent:
      trade.entry_combined_notional > 0
        ? (totalPnl / trade.entry_combined_notional) * 100
        : 0,
    current_long_notional: currentLongNotional,
    current_short_notional: currentShortNotional,
    current_gross_notional: currentLongNotional + currentShortNotional,
    estimated_zscore: null,
    estimated_p_value:
      trade.live_mark?.estimated_p_value ??
      trade.latest_mark?.estimated_p_value ??
      trade.entry_p_value,
    quote_timestamp:
      longQuote.event_time > shortQuote.event_time
        ? longQuote.event_time
        : shortQuote.event_time,
    price_source: "Yahoo Finance WebSocket spot proxy",
    is_live: true,
    created_at:
      longQuote.received_at > shortQuote.received_at
        ? longQuote.received_at
        : shortQuote.received_at,
  };
}

function pnlColor(value: number) {
  return value >= 0
    ? "text-emerald-700 dark:text-emerald-400"
    : "text-rose-700 dark:text-rose-400";
}

function SpotPnlChart({
  trade,
  current,
}: {
  trade: PaperLabSpotTrade;
  current: PaperLabSpotTradeMark | null;
}) {
  const history = [
    {
      at: trade.entry_price_timestamp,
      totalPercent: 0,
      longContribution: 0,
      shortContribution: 0,
    },
    ...trade.marks.map((mark) => ({
      at: mark.quote_timestamp,
      totalPercent: mark.return_percent,
      longContribution: (mark.long_pnl / trade.entry_combined_notional) * 100,
      shortContribution: (mark.short_pnl / trade.entry_combined_notional) * 100,
    })),
  ];
  if (
    current &&
    history.at(-1)?.at !== current.quote_timestamp
  ) {
    history.push({
      at: current.quote_timestamp,
      totalPercent: current.return_percent,
      longContribution: (current.long_pnl / trade.entry_combined_notional) * 100,
      shortContribution: (current.short_pnl / trade.entry_combined_notional) * 100,
    });
  }
  const maxAbsolutePnl = Math.max(
    1,
    ...history.flatMap((point) => [
      Math.abs(point.totalPercent),
      Math.abs(point.longContribution),
      Math.abs(point.shortContribution),
    ])
  );
  return (
    <div className="h-[300px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={history} margin={{ top: 12, right: 12, left: 8, bottom: 4 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="at"
            minTickGap={48}
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            tickFormatter={(value) =>
              new Date(String(value)).toLocaleTimeString("en-IN", {
                hour: "2-digit",
                minute: "2-digit",
                timeZone: "Asia/Kolkata",
              })
            }
          />
          <YAxis
            width={72}
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            tickFormatter={(value) => `${Number(value).toFixed(1)}%`}
            domain={[-maxAbsolutePnl * 1.15, maxAbsolutePnl * 1.15]}
          />
          <Tooltip
            contentStyle={{
              borderRadius: 8,
              border: "1px solid var(--border)",
              background: "var(--card)",
              fontSize: 12,
            }}
            labelFormatter={(value) => timestamp(String(value))}
            formatter={(value, name) => [`${Number(value).toFixed(3)}%`, name]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <ReferenceLine y={0} stroke="var(--muted-foreground)" />
          <Line dataKey="totalPercent" name="Total return" stroke="var(--chart-1)" strokeWidth={2.5} dot={false} isAnimationActive={false} />
          <Line dataKey="longContribution" name="Long contribution" stroke="var(--chart-2)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          <Line dataKey="shortContribution" name="Short contribution" stroke="var(--chart-5)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function TradeCard({
  trade,
  quotes,
  closing,
  onClose,
}: {
  trade: PaperLabSpotTrade;
  quotes: Record<string, LiveQuote>;
  closing: boolean;
  onClose: () => void;
}) {
  const websocketMark = clientLiveMark(trade, quotes);
  const current = websocketMark ?? trade.live_mark ?? trade.latest_mark ?? null;
  const currentEstimatedZ =
    current?.estimated_zscore ?? trade.live_mark?.estimated_zscore ?? trade.latest_mark?.estimated_zscore;
  const currentEstimatedP =
    current?.estimated_p_value ?? trade.live_mark?.estimated_p_value ?? trade.latest_mark?.estimated_p_value;
  const pValueStatus =
    currentEstimatedP == null
      ? "Current p unavailable"
      : currentEstimatedP <= 0.0001
        ? "Entry-grade significance"
        : currentEstimatedP <= 0.001
          ? "Hold zone—above entry cutoff"
          : "Hard-exit threshold breached";
  const hasLive = Boolean(websocketMark ?? trade.live_mark);
  return (
    <Card>
      <CardHeader className="border-b border-border/70">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="flex flex-wrap items-center gap-2 text-lg">
              <Link href={`/company/${trade.long_ticker}`} className="font-mono text-emerald-700 hover:underline dark:text-emerald-400">
                Long {trade.long_ticker}
              </Link>
              <span className="text-muted-foreground">/</span>
              <Link href={`/company/${trade.short_ticker}`} className="font-mono text-rose-700 hover:underline dark:text-rose-400">
                Short {trade.short_ticker}
              </Link>
            </CardTitle>
            <CardDescription className="mt-1 font-mono">{trade.pair_id}</CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="default">
              {(trade.entry_expected_return_percent ?? 0).toFixed(2)}% modelled full-convergence return
            </Badge>
            <Badge variant="outline">Entry BH q {testProbability(trade.entry_q_value)}</Badge>
            {trade.formal_entry_signal ? <Badge variant="secondary">Formal ±2σ signal</Badge> : null}
            {hasLive ? (
              <Badge variant="outline" className="border-emerald-700/30 text-emerald-700 dark:text-emerald-400">
                <Wifi className="size-3" /> Live spot
              </Badge>
            ) : null}
            <Badge variant="outline">{trade.status}</Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-4 sm:p-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-emerald-700/20 bg-emerald-500/[0.05] p-3">
            <p className="terminal-label text-emerald-700 dark:text-emerald-400">Long entry → current</p>
            <p className="mt-1 font-mono font-semibold">
              ₹{priceFormatter.format(trade.entry_long_price)} → ₹{priceFormatter.format(current?.long_price ?? trade.entry_long_price)}
            </p>
            <p className="mt-1 text-[10px] text-muted-foreground">
              {trade.long_units.toFixed(4)} hedge units · entry {moneyFormatter.format(trade.entry_long_notional)}
            </p>
          </div>
          <div className="rounded-lg border border-rose-700/20 bg-rose-500/[0.05] p-3">
            <p className="terminal-label text-rose-700 dark:text-rose-400">Short entry → current</p>
            <p className="mt-1 font-mono font-semibold">
              ₹{priceFormatter.format(trade.entry_short_price)} → ₹{priceFormatter.format(current?.short_price ?? trade.entry_short_price)}
            </p>
            <p className="mt-1 text-[10px] text-muted-foreground">
              {trade.short_units.toFixed(4)} hedge units · entry {moneyFormatter.format(trade.entry_short_notional)}
            </p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="terminal-label">Leg P&amp;L</p>
            <p className={`mt-1 font-mono text-sm font-semibold ${pnlColor(current?.long_pnl ?? 0)}`}>
              Long {signedMoney(current?.long_pnl ?? 0)}
            </p>
            <p className={`mt-1 font-mono text-sm font-semibold ${pnlColor(current?.short_pnl ?? 0)}`}>
              Short {signedMoney(current?.short_pnl ?? 0)}
            </p>
          </div>
          <div className="rounded-lg border border-primary/25 bg-accent/35 p-3">
            <p className="terminal-label">Combined return</p>
            <p className={`mt-1 font-mono text-3xl font-semibold tracking-tight ${pnlColor(current?.return_percent ?? 0)}`}>
              {signedPercent(current?.return_percent ?? 0)}
            </p>
            <p className="mt-1 font-mono text-[10px] text-muted-foreground">
              {signedMoney(current?.total_pnl ?? 0)} simulated P&amp;L · {moneyFormatter.format(trade.entry_combined_notional)} gross entry notional
            </p>
          </div>
        </div>

        <section className="rounded-lg border border-border bg-muted/10 p-2">
          <div className="flex flex-wrap items-center justify-between gap-2 px-2 pt-2">
            <p className="text-xs font-semibold">Recorded spot-proxy P&amp;L</p>
            <p className="text-[10px] text-muted-foreground">
              {trade.marks.length} saved 15-minute mark(s)
            </p>
          </div>
          <SpotPnlChart trade={trade} current={current} />
        </section>

        <details className="rounded-lg border border-border bg-card p-3">
          <summary className="cursor-pointer text-xs font-semibold">
            15-minute observation table
          </summary>
          <div className="mt-3 max-h-80 overflow-auto">
            <table className="w-full min-w-[1120px] text-left text-[11px]">
              <thead className="sticky top-0 bg-card text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="px-2 py-2 font-medium">Interval ending</th>
                  <th className="px-2 py-2 font-medium">Long price</th>
                  <th className="px-2 py-2 font-medium">Short price</th>
                  <th className="px-2 py-2 font-medium">Long P&amp;L</th>
                  <th className="px-2 py-2 font-medium">Short P&amp;L</th>
                  <th className="px-2 py-2 font-medium">Estimated Z</th>
                  <th className="px-2 py-2 font-medium">Raw p</th>
                  <th className="px-2 py-2 font-medium">Return</th>
                  <th className="px-2 py-2 font-medium">Combined P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-border/60 font-mono">
                  <td className="px-2 py-2">
                    {timestamp(trade.entry_price_timestamp)} <span className="text-muted-foreground">(entry)</span>
                  </td>
                  <td className="px-2 py-2">₹{priceFormatter.format(trade.entry_long_price)}</td>
                  <td className="px-2 py-2">₹{priceFormatter.format(trade.entry_short_price)}</td>
                  <td className="px-2 py-2 text-muted-foreground">₹0.00</td>
                  <td className="px-2 py-2 text-muted-foreground">₹0.00</td>
                  <td className="px-2 py-2">{trade.entry_zscore.toFixed(3)}σ</td>
                  <td className="px-2 py-2">{testProbability(trade.entry_p_value)}</td>
                  <td className="px-2 py-2 font-semibold">+0.000%</td>
                  <td className="px-2 py-2 text-muted-foreground">+₹0.00</td>
                </tr>
                {trade.marks.map((mark) => (
                  <tr key={mark.id ?? mark.quote_timestamp} className="border-b border-border/60 font-mono">
                    <td className="px-2 py-2">{timestamp(mark.quote_timestamp)}</td>
                    <td className="px-2 py-2">₹{priceFormatter.format(mark.long_price)}</td>
                    <td className="px-2 py-2">₹{priceFormatter.format(mark.short_price)}</td>
                    <td className={`px-2 py-2 ${pnlColor(mark.long_pnl)}`}>{signedMoney(mark.long_pnl)}</td>
                    <td className={`px-2 py-2 ${pnlColor(mark.short_pnl)}`}>{signedMoney(mark.short_pnl)}</td>
                    <td className="px-2 py-2">
                      {mark.estimated_zscore == null ? "—" : `${mark.estimated_zscore.toFixed(3)}σ`}
                    </td>
                    <td className="px-2 py-2">
                      {mark.estimated_p_value == null ? "—" : testProbability(mark.estimated_p_value)}
                    </td>
                    <td className={`px-2 py-2 font-semibold ${pnlColor(mark.return_percent)}`}>
                      {signedPercent(mark.return_percent)}
                    </td>
                    <td className="px-2 py-2 text-muted-foreground">{signedMoney(mark.total_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>

        <div className="flex flex-col gap-3 rounded-lg border border-border p-3 text-xs sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1 text-muted-foreground">
            <p>
              Entry {timestamp(trade.entry_price_timestamp)} · {trade.entry_price_source}
            </p>
            <p className="font-mono">
              Entry raw p {testProbability(trade.entry_p_value)} · BH q {testProbability(trade.entry_q_value)} · KSS t {trade.entry_kss_statistic.toFixed(3)} · expected return {(trade.entry_expected_return_percent ?? 0).toFixed(3)}%
            </p>
            <p>
              New-entry rules are raw p ≤ 0.0001, KSS t ≤ −5.04 and expected return &gt; 1%. Existing historical observations are preserved; the BH q-value is displayed for comparison and does not admit, reject or size a trade.
            </p>
            <p className="font-mono">
              Actual entry Z {trade.entry_zscore.toFixed(3)}σ · latest estimated Z {currentEstimatedZ == null ? "unavailable" : `${currentEstimatedZ.toFixed(3)}σ`} · automatic exit at |Z| ≤ 0.1
            </p>
            <p>
              Actual entry Z is calculated at the saved opening prices using the frozen hedge ratio, spread mean and scale. A trade entered below zero closes at −0.1σ; one entered above zero closes at +0.1σ.
            </p>
            <p className="font-mono">
              Latest raw p {currentEstimatedP == null ? "unavailable" : testProbability(currentEstimatedP)}
              {" · "}{pValueStatus}{" · "}hard exit if p &gt; 0.001
            </p>
            {current ? (
              <p>
                {trade.status === "closed" ? "Final mark" : "Current mark"} {timestamp(current.quote_timestamp)} · {current.price_source}
              </p>
            ) : (
              <p>{trade.valuation_limitation}</p>
            )}
            {trade.closed_at ? (
              <p className="font-medium text-foreground">
                Closed {timestamp(trade.closed_at)} · {trade.exit_reason === "zscore_target_0_1" ? "spread reached the |Z| ≤ 0.1 exit band automatically" : trade.exit_reason === "zscore_zero" ? "spread reached/crossed Z = 0 automatically under the previous rule" : trade.exit_reason === "p_value_above_0_001" ? "raw p exceeded 0.001 hard limit automatically" : "closed manually"}
                {trade.exit_zscore != null ? ` · estimated exit Z ${trade.exit_zscore.toFixed(3)}σ` : ""}
                {trade.exit_p_value != null ? ` · exit p ${testProbability(trade.exit_p_value)}` : ""}
              </p>
            ) : null}
          </div>
          {trade.status === "open" ? (
            <Button size="sm" variant="outline" onClick={onClose} disabled={closing || !current}>
              {closing ? <Loader2 className="animate-spin" /> : null}
              Close observation
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

export function PairLabPaperTracker() {
  const [portfolioId, setPortfolioId] = useState<string>();
  const queryClient = useQueryClient();
  const lastSyncedKey = useRef<string | undefined>(undefined);

  useEffect(() => {
    const storageKey = "easy-invest-paper-portfolio-id";
    const existing = window.localStorage.getItem(storageKey);
    const resolved = existing ?? window.crypto.randomUUID();
    if (!existing) window.localStorage.setItem(storageKey, resolved);
    const frame = window.requestAnimationFrame(() => setPortfolioId(resolved));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  const trades = useQuery({
    queryKey: ["pair-method-lab-spot-trades", portfolioId],
    queryFn: () => api.listPairMethodLabSpotTrades(portfolioId!),
    enabled: Boolean(portfolioId),
    staleTime: 15_000,
    refetchOnWindowFocus: true,
  });
  const mark = useMutation({
    mutationFn: () => api.markPairMethodLabSpotTrades(portfolioId!),
    onSuccess: (data) =>
      queryClient.setQueryData(["pair-method-lab-spot-trades", portfolioId], data),
  });
  const sync = useMutation({
    mutationFn: () => api.syncPairMethodLabSpotTrades(portfolioId!),
    onSuccess: (data) => {
      queryClient.setQueryData(
        ["pair-method-lab-spot-trades", portfolioId],
        data.trades
      );
      window.setTimeout(() => mark.mutate(), 1_000);
    },
  });
  const close = useMutation({
    mutationFn: (tradeId: string) =>
      api.closePairMethodLabSpotTrade(portfolioId!, tradeId),
    onSuccess: () => trades.refetch(),
  });
  const syncTrades = sync.mutate;
  const saveMarks = mark.mutate;

  useEffect(() => {
    if (!portfolioId) return;
    const syncKey = portfolioId;
    if (lastSyncedKey.current === syncKey) return;
    lastSyncedKey.current = syncKey;
    syncTrades();
  }, [portfolioId, syncTrades]);

  useEffect(() => {
    if (!portfolioId) return;
    const interval = window.setInterval(() => saveMarks(), 15 * 60_000);
    return () => window.clearInterval(interval);
  }, [portfolioId, saveMarks]);

  const allTrades = useMemo(() => trades.data ?? [], [trades.data]);
  const openTrades = allTrades.filter((trade) => trade.status === "open");
  const tickers = useMemo(
    () => openTrades.flatMap((trade) => [trade.long_ticker, trade.short_ticker]),
    [openTrades]
  );
  const quotes = useLiveQuotes(tickers, openTrades.length > 0);
  const openPortfolioPnl = openTrades.reduce((sum, trade) => {
    const current = clientLiveMark(trade, quotes) ?? trade.live_mark ?? trade.latest_mark;
    return sum + (current?.total_pnl ?? 0);
  }, 0);
  const openGrossEntry = openTrades.reduce(
    (sum, trade) => sum + trade.entry_combined_notional,
    0
  );
  const openPortfolioReturn =
    openGrossEntry > 0 ? (openPortfolioPnl / openGrossEntry) * 100 : 0;
  const closedPortfolioPnl = allTrades
    .filter((trade) => trade.status === "closed")
    .reduce(
      (sum, trade) =>
        sum + (trade.realized_pnl ?? trade.latest_mark?.total_pnl ?? 0),
      0
    );
  const allTradesPnl = openPortfolioPnl + closedPortfolioPnl;
  const allTradesGrossEntry = allTrades.reduce(
    (sum, trade) => sum + trade.entry_combined_notional,
    0
  );
  const allTradesReturn =
    allTradesGrossEntry > 0 ? (allTradesPnl / allTradesGrossEntry) * 100 : 0;
  const loading = !portfolioId || trades.isLoading || sync.isPending;

  return (
    <section className="space-y-4">
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="flex flex-col gap-4 border-b border-border/70 p-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="page-eyebrow flex items-center gap-2">
              <Activity className="size-3.5" /> Existing observations only
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] sm:text-[2.5rem]">
              Paper-method spot-proxy portfolio
            </h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
              New paper-trade creation is paused. This page only continues tracking the original
              observations already in the database; refreshing or rerunning the scanner will not
              add another pair. Existing positions still close automatically when the fitted
              spread reaches the near-zero |Z| ≤ 0.1 exit band or when their refitted raw p-value exceeds 0.001,
              and their complete 15-minute history remains stored.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" asChild>
              <Link href="/pair-method-lab">
                <FlaskConical /> View candidate lab
              </Link>
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!portfolioId || mark.isPending || sync.isPending}
              onClick={() => mark.mutate()}
            >
              {mark.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              Refresh 15-minute history
            </Button>
          </div>
        </div>
        <div className="grid gap-px bg-border/70 sm:grid-cols-2 lg:grid-cols-5">
          {[
            { value: openTrades.length, label: "Open observations" },
            { value: allTrades.filter((trade) => trade.exit_reason === "zscore_target_0_1" || trade.exit_reason === "zscore_zero" || trade.exit_reason === "p_value_above_0_001").length, label: "Automatic rule exits" },
            { value: moneyFormatter.format(openGrossEntry), label: "Open gross entry notional" },
            {
              value: signedPercent(openPortfolioReturn),
              label: "Open-position marked return",
              note: `${signedMoney(openPortfolioPnl)} unrealized simulated P&L`,
              returnValue: openPortfolioReturn,
            },
            {
              value: signedPercent(allTradesReturn),
              label: "All-trades aggregate return",
              note: `${signedMoney(allTradesPnl)} realized + unrealized · ${moneyFormatter.format(allTradesGrossEntry)} cumulative gross entries`,
              returnValue: allTradesReturn,
            },
          ].map(({ value, label, note, returnValue }) => (
            <div key={label} className="bg-card px-5 py-4">
              <p className={`font-mono text-lg font-semibold ${returnValue == null ? "" : pnlColor(returnValue)}`}>
                {value}
              </p>
              <p className="terminal-label mt-1">{label}</p>
              {note ? <p className="mt-1 text-[10px] text-muted-foreground">{note}</p> : null}
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-amber-600/30 bg-amber-500/[0.07] p-4">
        <div className="flex items-start gap-3">
          <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" />
          <p className="text-xs leading-5 text-muted-foreground">
            This is a research proxy, not an executable cash-market strategy: the short stock
            leg cannot be held overnight in the normal Indian cash market. Fractional hedge
            units preserve the fitted raw-price ratio. P&amp;L excludes futures basis, lot sizing,
            brokerage, taxes, borrow availability, slippage and financing. The &gt;1% entry metric
            is a conditional gross return if the spread reaches its fitted mean; it is not a
            probability-weighted forecast or guarantee. Automatic exits are checked against
            completed 15-minute bars and approximately once per minute using available live quotes.
            A refitted p-value between 0.0001 and 0.001 remains open; a value above 0.001 is a hard exit.
          </p>
        </div>
      </div>

      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-72 w-full" />
        </div>
      ) : trades.isError || sync.isError ? (
        <Card className="border-rose-500/30">
          <CardContent className="py-8">
            <p className="font-semibold">The automatic spot-proxy tracker could not be loaded.</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Apply the latest development database migration and confirm the API is running.
            </p>
          </CardContent>
        </Card>
      ) : allTrades.length === 0 ? (
        <Card>
          <CardContent className="py-8">
            <p className="font-semibold">There are no existing observations to display.</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Automatic entry creation is paused. No new pair will be added until it is explicitly
              enabled again; any closed historical trades will remain stored and visible here.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {allTrades.map((trade) => (
            <TradeCard
              key={trade.id}
              trade={trade}
              quotes={quotes}
              closing={close.isPending && close.variables === trade.id}
              onClose={() => close.mutate(trade.id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
