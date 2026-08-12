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
  Clock3,
  Loader2,
  RefreshCw,
  Sigma,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  api,
  type IntradayCopulaCandidate,
  type IntradayCopulaPendingEntry,
  type IntradayCopulaTrade,
} from "@/lib/api";

const money = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function probability(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function testValue(value: number) {
  return value < 0.001 ? value.toExponential(2) : value.toFixed(4);
}

function signedPercent(value: number) {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(3)}%`;
}

function signedMoney(value: number) {
  return `${value >= 0 ? "+" : "−"}${money.format(Math.abs(value))}`;
}

function atIst(value: string) {
  return new Date(value).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Kolkata",
  });
}

function pnlTone(value: number) {
  return value >= 0
    ? "text-emerald-700 dark:text-emerald-400"
    : "text-rose-700 dark:text-rose-400";
}

function signalLabel(signal: IntradayCopulaCandidate["signal"]) {
  if (signal === "enter_long_a_short_b") return "Long A / short B";
  if (signal === "enter_short_a_long_b") return "Short A / long B";
  if (signal === "exit") return "Copula equilibrium";
  return "Watch";
}

function exitLabel(reason: string | null | undefined) {
  if (reason === "profit_target_0_5") return "+0.5% take-profit";
  if (reason === "copula_equilibrium") return "Copula 40%–60% equilibrium";
  if (reason === "mandatory_intraday_square_off") return "15:10 mandatory square-off";
  if (reason === "manual") return "Manual close";
  return reason ?? "Open";
}

function CopulaChart({ candidate }: { candidate: IntradayCopulaCandidate }) {
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={candidate.history} margin={{ top: 10, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="timestamp"
            minTickGap={42}
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
            width={42}
            domain={[0, 1]}
            ticks={[0, 0.1, 0.4, 0.5, 0.6, 0.9, 1]}
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`}
          />
          <Tooltip
            contentStyle={{ borderRadius: 8, border: "1px solid var(--border)", background: "var(--card)", fontSize: 12 }}
            labelFormatter={(value) => atIst(String(value))}
            formatter={(value, name) => [probability(Number(value)), name]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {[0.1, 0.4, 0.6, 0.9].map((level) => (
            <ReferenceLine key={level} y={level} stroke="var(--muted-foreground)" strokeDasharray="4 5" />
          ))}
          <Line dataKey="h_a_given_b" name={`h(${candidate.stock_a} | ${candidate.stock_b})`} stroke="var(--chart-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line dataKey="h_b_given_a" name={`h(${candidate.stock_b} | ${candidate.stock_a})`} stroke="var(--chart-3)" strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function CandidateCard({ candidate }: { candidate: IntradayCopulaCandidate }) {
  return (
    <Card>
      <CardHeader className="gap-3 border-b border-border/70">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={candidate.can_enter ? "default" : "outline"}>{signalLabel(candidate.signal)}</Badge>
              <Badge variant="outline">BH q {testValue(candidate.fdr_q_value)}</Badge>
              {candidate.can_enter ? <Badge variant="secondary">Entry eligible now</Badge> : null}
            </div>
            <CardTitle className="mt-3 flex items-center gap-2 text-xl">
              <Link href={`/company/${candidate.stock_a}`} className="font-mono hover:underline">{candidate.stock_a}</Link>
              <span className="text-muted-foreground">/</span>
              <Link href={`/company/${candidate.stock_b}`} className="font-mono hover:underline">{candidate.stock_b}</Link>
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">{candidate.stock_a_name} · {candidate.stock_b_name} · {candidate.sector}</p>
          </div>
          <div className="rounded-lg border border-border bg-muted/35 px-4 py-3 sm:text-right">
            <p className="terminal-label">Five-minute model</p>
            <p className="mt-1 font-mono text-sm font-semibold">{candidate.copula_family}</p>
            <p className="mt-1 text-[10px] text-muted-foreground">{candidate.formation_bars.toLocaleString("en-IN")} prior-session bars · AIC {candidate.copula_aic.toFixed(2)}</p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 pt-5">
        <div className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
          {[
            [probability(candidate.h_a_given_b), `h(${candidate.stock_a} | ${candidate.stock_b})`],
            [probability(candidate.h_b_given_a), `h(${candidate.stock_b} | ${candidate.stock_a})`],
            [`${candidate.regression_days} days`, "Frozen NIFTY regression"],
            [`${candidate.intraday_sessions} sessions`, "Intraday formation coverage"],
          ].map(([value, label]) => (
            <div key={label} className="bg-card p-4"><p className="font-mono text-lg font-semibold">{value}</p><p className="terminal-label mt-1">{label}</p></div>
          ))}
        </div>
        <CopulaChart candidate={candidate} />
        <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
          <p>Latest completed bar {atIst(candidate.latest_bar_end)} · {candidate.stock_a} ₹{candidate.stock_a_price.toFixed(2)} · {candidate.stock_b} ₹{candidate.stock_b_price.toFixed(2)}</p>
          <p className="mt-1 font-mono">EG p {testValue(candidate.engle_granger_p_value)} · KSS t {candidate.kss_statistic.toFixed(3)} · margins {candidate.marginal_a}/{candidate.marginal_b}</p>
          <p className={`mt-2 ${candidate.can_enter ? "font-medium text-emerald-700 dark:text-emerald-400" : ""}`}>
            {candidate.can_enter ? `Automatic paper entry: long ${candidate.long_ticker}, short ${candidate.short_ticker}.` : candidate.entry_block_reason}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function PendingEntryCard({ entry }: { entry: IntradayCopulaPendingEntry }) {
  return (
    <Card>
      <CardHeader className="border-b border-border/70">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex flex-wrap gap-2">
              <Badge>Queued for next open</Badge>
              <Badge variant="outline">BH q {testValue(entry.entry_q_value)}</Badge>
            </div>
            <CardTitle className="mt-3 flex flex-wrap items-center gap-2 text-lg">
              <span className="font-mono text-emerald-700 dark:text-emerald-400">Long {entry.long_ticker}</span>
              <span className="text-muted-foreground">/</span>
              <span className="font-mono text-rose-700 dark:text-rose-400">Short {entry.short_ticker}</span>
            </CardTitle>
            <p className="mt-1 font-mono text-xs text-muted-foreground">{entry.pair_id} · {entry.copula_family}</p>
          </div>
          <div className="rounded-lg border border-border bg-muted/35 px-4 py-3 sm:text-right">
            <p className="terminal-label">Signal frozen</p>
            <p className="mt-1 font-mono text-sm font-semibold">{atIst(entry.signal_observed_at)}</p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 p-4 sm:grid-cols-3 sm:p-5">
        <div className="rounded-lg border border-border p-3"><p className="terminal-label">Observed h(A | B)</p><p className="mt-1 font-mono text-lg font-semibold">{probability(entry.observed_h_a_given_b)}</p></div>
        <div className="rounded-lg border border-border p-3"><p className="terminal-label">Observed h(B | A)</p><p className="mt-1 font-mono text-lg font-semibold">{probability(entry.observed_h_b_given_a)}</p></div>
        <div className="rounded-lg border border-primary/25 bg-accent/35 p-3"><p className="terminal-label">Planned execution</p><p className="mt-1 text-sm font-semibold">Next actual NSE session</p><p className="mt-1 text-[10px] text-muted-foreground">First five-minute cash bar Open (09:15 IST); weekends and holidays roll forward.</p></div>
      </CardContent>
    </Card>
  );
}

function TradeChart({ trade }: { trade: IntradayCopulaTrade }) {
  const data = [
    { timestamp: trade.entry_price_timestamp, returnPercent: 0 },
    ...trade.marks.map((mark) => ({ timestamp: mark.quote_timestamp, returnPercent: mark.return_percent })),
  ];
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 10, right: 8, left: 4, bottom: 4 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="timestamp"
            minTickGap={40}
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            tickFormatter={(value) => new Date(String(value)).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" })}
          />
          <YAxis width={62} tick={{ fontSize: 10, fill: "var(--muted-foreground)" }} tickFormatter={(value) => `${Number(value).toFixed(2)}%`} />
          <Tooltip
            contentStyle={{ borderRadius: 8, border: "1px solid var(--border)", background: "var(--card)", fontSize: 12 }}
            labelFormatter={(value) => atIst(String(value))}
            formatter={(value) => [`${Number(value).toFixed(3)}%`, "Pair return"]}
          />
          <ReferenceLine y={0} stroke="var(--muted-foreground)" />
          <ReferenceLine y={trade.profit_target_percent} stroke="var(--chart-2)" strokeDasharray="4 4" />
          <Line dataKey="returnPercent" name="Pair return" stroke="var(--chart-1)" strokeWidth={2.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function TradeCard({ trade, closing, onClose }: { trade: IntradayCopulaTrade; closing: boolean; onClose: () => void }) {
  const current = trade.latest_mark;
  const returnPercent = current?.return_percent ?? 0;
  const totalPnl = current?.total_pnl ?? trade.realized_pnl ?? 0;
  return (
    <Card>
      <CardHeader className="border-b border-border/70">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="flex flex-wrap items-center gap-2 text-lg">
              <span className="font-mono text-emerald-700 dark:text-emerald-400">Long {trade.long_ticker}</span>
              <span className="text-muted-foreground">/</span>
              <span className="font-mono text-rose-700 dark:text-rose-400">Short {trade.short_ticker}</span>
            </CardTitle>
            <p className="mt-1 font-mono text-xs text-muted-foreground">{trade.pair_id} · {trade.copula_family}</p>
          </div>
          <div className="flex flex-wrap gap-2"><Badge variant="outline">BH q {testValue(trade.entry_q_value)}</Badge><Badge variant={trade.status === "open" ? "default" : "secondary"}>{trade.status}</Badge></div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-4 sm:p-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-border p-3"><p className="terminal-label">Long entry → latest</p><p className="mt-1 font-mono font-semibold">₹{trade.entry_long_price.toFixed(2)} → ₹{(current?.long_price ?? trade.entry_long_price).toFixed(2)}</p><p className="mt-1 text-[10px] text-muted-foreground">{trade.long_units.toFixed(4)} fractional hedge units</p></div>
          <div className="rounded-lg border border-border p-3"><p className="terminal-label">Short entry → latest</p><p className="mt-1 font-mono font-semibold">₹{trade.entry_short_price.toFixed(2)} → ₹{(current?.short_price ?? trade.entry_short_price).toFixed(2)}</p><p className="mt-1 text-[10px] text-muted-foreground">{trade.short_units.toFixed(4)} fractional hedge units</p></div>
          <div className="rounded-lg border border-border p-3"><p className="terminal-label">Latest copula state</p><p className="mt-1 font-mono font-semibold">{probability(current?.h_a_given_b ?? trade.entry_h_a_given_b)} / {probability(current?.h_b_given_a ?? trade.entry_h_b_given_a)}</p><p className="mt-1 text-[10px] text-muted-foreground">Exit when both enter 40%–60%</p></div>
          <div className="rounded-lg border border-primary/25 bg-accent/35 p-3"><p className="terminal-label">Pair return</p><p className={`mt-1 font-mono text-2xl font-semibold ${pnlTone(returnPercent)}`}>{signedPercent(returnPercent)}</p><p className="mt-1 text-[10px] text-muted-foreground">{signedMoney(totalPnl)} on {money.format(trade.entry_combined_notional)} gross</p></div>
        </div>
        <TradeChart trade={trade} />
        <div className="flex flex-col gap-3 rounded-lg border border-border p-3 text-xs text-muted-foreground sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-1">
            <p>Entry {atIst(trade.entry_price_timestamp)} · {trade.entry_price_source}</p>
            <p className="font-mono">Entry h values {probability(trade.entry_h_a_given_b)} / {probability(trade.entry_h_b_given_a)} · KSS t {trade.entry_kss_statistic.toFixed(3)}</p>
            <p>Automatic exits: copula equilibrium, +{trade.profit_target_percent.toFixed(1)}%, or mandatory 15:10 IST square-off.</p>
            {trade.status === "closed" ? <p className="font-medium text-foreground">Closed {trade.closed_at ? atIst(trade.closed_at) : "—"} · {exitLabel(trade.exit_reason)}</p> : null}
          </div>
          {trade.status === "open" ? <Button size="sm" variant="outline" onClick={onClose} disabled={closing}>{closing ? <Loader2 className="animate-spin" /> : null}Close paper trade</Button> : null}
        </div>
      </CardContent>
    </Card>
  );
}

export function IntradayCopulaTrackerView() {
  const [portfolioId, setPortfolioId] = useState<string>();
  const queryClient = useQueryClient();

  useEffect(() => {
    const storageKey = "easy-invest-paper-portfolio-id";
    const existing = window.localStorage.getItem(storageKey);
    const resolved = existing ?? window.crypto.randomUUID();
    if (!existing) window.localStorage.setItem(storageKey, resolved);
    const frame = window.requestAnimationFrame(() => setPortfolioId(resolved));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  const tracker = useQuery({
    queryKey: ["intraday-copula-tracker", portfolioId],
    queryFn: () => api.syncIntradayCopulaTracker(portfolioId!),
    enabled: Boolean(portfolioId),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    refetchOnWindowFocus: true,
  });
  const close = useMutation({
    mutationFn: (tradeId: string) => api.closeIntradayCopulaTrade(portfolioId!, tradeId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["intraday-copula-tracker", portfolioId] }),
  });
  const data = tracker.data;
  const trades = useMemo(() => data?.trades ?? [], [data?.trades]);
  const openTrades = trades.filter((trade) => trade.status === "open");
  const closedTrades = trades.filter((trade) => trade.status === "closed");
  const queuedEntries = (data?.pending_entries ?? []).filter((entry) => entry.status === "queued");
  const closedPnl = closedTrades.reduce((sum, trade) => sum + (trade.realized_pnl ?? 0), 0);
  const markedOpenTrades = openTrades.filter((trade) => trade.latest_mark != null);
  const unrealizedPnl = markedOpenTrades.reduce((sum, trade) => sum + trade.latest_mark!.total_pnl, 0);
  const markedOpenNotional = markedOpenTrades.reduce((sum, trade) => sum + trade.entry_combined_notional, 0);
  const unrealizedPnlPercent = markedOpenNotional > 0 ? unrealizedPnl / markedOpenNotional * 100 : null;
  const netPnl = closedPnl + unrealizedPnl;
  const closedEntryNotional = closedTrades.reduce((sum, trade) => sum + trade.entry_combined_notional, 0);
  const netPnlNotional = closedEntryNotional + markedOpenNotional;
  const netPnlPercent = netPnlNotional > 0 ? netPnl / netPnlNotional * 100 : null;

  return (
    <div className="space-y-5 pb-6">
      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="flex flex-col gap-5 border-b border-border/70 p-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="page-eyebrow flex items-center gap-2"><Sigma className="size-3.5" /> Five-minute conditional dependence</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] sm:text-[2.5rem]">Intraday copula pair tracker</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">Strict daily pairs are re-hedged with 504 completed sessions, then evaluated on completed five-minute cash-equity bars. Copula tails create entries; signals seen after the cutoff or while NSE is closed queue for the next actual session’s opening price.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" asChild><Link href="/copula-pair-signals"><Activity /> Daily copula signals</Link></Button>
            <Button size="sm" variant="outline" disabled={!portfolioId || tracker.isFetching} onClick={() => tracker.refetch()}>{tracker.isFetching ? <Loader2 className="animate-spin" /> : <RefreshCw />}Check latest five-minute bar</Button>
          </div>
        </div>
        <div className="grid gap-px bg-border/70 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
          {[
            [data?.eligible_pairs ?? "—", "Dual-test intraday pairs", null],
            [data?.entry_signals ?? "—", "Current copula entries", null],
            [queuedEntries.length, "Queued for next open", null],
            [openTrades.length, "Open paper trades", null],
            [markedOpenTrades.length ? signedMoney(unrealizedPnl) : "—", "Open unrealized P&L", null],
            [unrealizedPnlPercent == null ? "—" : signedPercent(unrealizedPnlPercent), "Open P&L percent", null],
            [signedMoney(closedPnl), "Closed realized P&L", null],
            [signedMoney(netPnl), "Net total P&L", netPnlPercent == null ? "—" : signedPercent(netPnlPercent)],
          ].map(([value, label, detail]) => <div key={label} className="bg-card px-5 py-4"><p className="font-mono text-lg font-semibold">{value}</p><p className="terminal-label mt-1">{label}</p>{detail ? <p className="mt-1 font-mono text-xs text-muted-foreground">{detail} net return</p> : null}</div>)}
        </div>
      </section>

      <div className="rounded-lg border border-amber-600/30 bg-amber-500/[0.07] p-4">
        <div className="flex items-start gap-3"><CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" /><div className="text-xs leading-5 text-muted-foreground"><p>This is a paper tracker, not an order system. It uses theoretical ₹1,00,000 gross fractional-share hedges and excludes brokerage, taxes, bid/ask spread, slippage, margin and failed short-leg execution.</p><p className="mt-1">Yahoo five-minute history is delayed and unofficial. Late signals are frozen and paper-filled from the next session’s first five-minute bar Open; one entry per pair per session is permitted.</p></div></div>
      </div>

      {tracker.isLoading || !portfolioId ? (
        <div className="space-y-4"><Skeleton className="h-72 w-full" /><Skeleton className="h-72 w-full" /></div>
      ) : tracker.isError || !data ? (
        <Card className="border-rose-500/30"><CardContent className="py-8"><p className="font-semibold">The intraday copula tracker could not be loaded.</p><p className="mt-1 text-sm text-muted-foreground">Confirm the API can retrieve five-minute NSE bars and the database is at migration 0013.</p></CardContent></Card>
      ) : (
        <Tabs defaultValue="signals" className="space-y-4">
          <TabsList className="h-auto w-full justify-start gap-1 overflow-x-auto rounded-lg border border-border bg-card p-1 sm:w-auto">
            <TabsTrigger value="signals" className="gap-2 px-4 py-2">Current signals <Badge variant="secondary">{data.candidates.length}</Badge></TabsTrigger>
            <TabsTrigger value="queued" className="gap-2 px-4 py-2">Queued for next open <Badge variant="secondary">{queuedEntries.length}</Badge></TabsTrigger>
            <TabsTrigger value="open" className="gap-2 px-4 py-2">Open trades <Badge variant="secondary">{openTrades.length}</Badge></TabsTrigger>
            <TabsTrigger value="closed" className="gap-2 px-4 py-2">Closed trades <Badge variant="secondary">{closedTrades.length}</Badge></TabsTrigger>
          </TabsList>

          <TabsContent value="signals" className="space-y-4">
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground"><Clock3 className="size-4" /> Entry {data.entry_start_ist}–{data.last_entry_ist} IST · force close {data.forced_exit_ist} IST · refreshes every {data.bar_minutes} minutes</div>
            {data.candidates.length ? data.candidates.map((candidate) => <CandidateCard key={candidate.pair_id} candidate={candidate} />) : <Card><CardContent className="py-8"><p className="font-semibold">No pair has sufficient five-minute formation data.</p><p className="mt-1 text-sm text-muted-foreground">The strict daily gate may also currently have no dual-test, q ≤ 0.05 candidates.</p></CardContent></Card>}
          </TabsContent>

          <TabsContent value="queued" className="space-y-4">
            {queuedEntries.length ? queuedEntries.map((entry) => <PendingEntryCard key={entry.id} entry={entry} />) : <Card><CardContent className="py-8"><p className="font-semibold">No entry is queued for the next market open.</p><p className="mt-1 text-sm text-muted-foreground">A qualifying long/short copula signal observed after 14:30 IST or from the latest closed session will appear here automatically.</p></CardContent></Card>}
          </TabsContent>

          <TabsContent value="open" className="space-y-4">
            {openTrades.length ? openTrades.map((trade) => <TradeCard key={trade.id} trade={trade} closing={close.isPending && close.variables === trade.id} onClose={() => close.mutate(trade.id)} />) : <Card><CardContent className="py-8"><p className="font-semibold">No intraday copula trades are open.</p><p className="mt-1 text-sm text-muted-foreground">A trade is added only when both conditional probabilities jointly enter opposite 10% tails during the entry window.</p></CardContent></Card>}
          </TabsContent>

          <TabsContent value="closed" className="space-y-4">
            {closedTrades.length ? closedTrades.map((trade) => <TradeCard key={trade.id} trade={trade} closing={false} onClose={() => undefined} />) : <Card><CardContent className="py-8"><p className="font-semibold">No intraday copula trades have closed yet.</p><p className="mt-1 text-sm text-muted-foreground">Completed trades will remain here with their five-minute P&L history and exit reason.</p></CardContent></Card>}
          </TabsContent>
        </Tabs>
      )}

      {data ? <Card><CardHeader><CardTitle className="text-base">Method and limitations</CardTitle></CardHeader><CardContent className="space-y-2 text-xs leading-5 text-muted-foreground"><p>{data.data_source}</p>{data.limitations.map((limitation) => <p key={limitation}>• {limitation}</p>)}</CardContent></Card> : null}
    </div>
  );
}
