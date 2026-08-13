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
  ArrowDownUp,
  CircleAlert,
  ExternalLink,
  Loader2,
  RefreshCw,
  Sigma,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type CopulaPairSignal } from "@/lib/api";

type Filter = "all" | "entry" | "exit" | "watch";

function probability(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function testValue(value: number) {
  return value < 0.001 ? value.toExponential(2) : value.toFixed(4);
}

function signalLabel(signal: CopulaPairSignal["signal"]) {
  if (signal === "enter_long_a_short_b") return "Enter long A / short B";
  if (signal === "enter_short_a_long_b") return "Enter short A / long B";
  if (signal === "exit") return "Exit / equilibrium";
  return "Watch";
}

function signalTone(signal: CopulaPairSignal["signal"]) {
  if (signal.startsWith("enter_")) {
    return "border-emerald-700/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
  }
  if (signal === "exit") {
    return "border-blue-700/30 bg-blue-500/10 text-blue-700 dark:text-blue-400";
  }
  return "border-border bg-muted/50 text-muted-foreground";
}

function ConditionalProbabilityChart({ pair }: { pair: CopulaPairSignal }) {
  const tradingStart = pair.history.find((point) => point.phase === "trading")?.date;
  return (
    <div className="h-[280px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={pair.history} margin={{ top: 10, right: 10, left: 0, bottom: 4 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            minTickGap={36}
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            tickFormatter={(value) => String(value).slice(5)}
          />
          <YAxis
            width={42}
            domain={[0, 1]}
            ticks={[0, 0.1, 0.4, 0.5, 0.6, 0.9, 1]}
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`}
          />
          <Tooltip
            contentStyle={{
              borderRadius: 8,
              border: "1px solid var(--border)",
              background: "var(--card)",
              fontSize: 12,
            }}
            formatter={(value, name) => [probability(Number(value)), name]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <ReferenceLine y={0.1} stroke="var(--chart-5)" strokeDasharray="5 5" />
          <ReferenceLine y={0.4} stroke="var(--chart-2)" strokeDasharray="2 5" />
          <ReferenceLine y={0.5} stroke="var(--muted-foreground)" />
          <ReferenceLine y={0.6} stroke="var(--chart-2)" strokeDasharray="2 5" />
          <ReferenceLine y={0.9} stroke="var(--chart-5)" strokeDasharray="5 5" />
          {tradingStart ? (
            <ReferenceLine
              x={tradingStart}
              stroke="var(--foreground)"
              strokeDasharray="3 4"
              label={{ value: "Trading window", fontSize: 9, fill: "var(--muted-foreground)" }}
            />
          ) : null}
          <Line
            dataKey="h_a_given_b"
            name={`h(${pair.stock_a} | ${pair.stock_b})`}
            stroke="var(--chart-1)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            dataKey="h_b_given_a"
            name={`h(${pair.stock_b} | ${pair.stock_a})`}
            stroke="var(--chart-3)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function SignalCard({ pair, rank }: { pair: CopulaPairSignal; rank: number }) {
  const parameter =
    pair.copula_degrees_of_freedom == null
      ? `θ/ρ ${pair.copula_parameter.toFixed(3)}`
      : `ρ ${pair.copula_parameter.toFixed(3)} · ν ${pair.copula_degrees_of_freedom.toFixed(1)}`;
  return (
    <Card>
      <CardHeader className="gap-4 border-b border-border/70">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="font-mono">#{rank}</Badge>
              <Badge variant="outline" className={signalTone(pair.signal)}>
                {signalLabel(pair.signal)}
              </Badge>
              <Badge variant="outline">BH q {testValue(pair.fdr_q_value)}</Badge>
            </div>
            <CardTitle className="mt-3 flex flex-wrap items-center gap-2 text-xl">
              <Link href={`/company/${pair.stock_a}`} className="font-mono hover:text-primary hover:underline">
                {pair.stock_a}
              </Link>
              <ArrowDownUp className="size-4 text-muted-foreground" />
              <Link href={`/company/${pair.stock_b}`} className="font-mono hover:text-primary hover:underline">
                {pair.stock_b}
              </Link>
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              {pair.stock_a_name} · {pair.stock_b_name} · {pair.sector}
            </p>
          </div>
          <div className="rounded-lg border border-border bg-muted/35 px-4 py-3 sm:text-right">
            <p className="terminal-label">Selected dependence model</p>
            <p className="mt-1 font-mono text-sm font-semibold">{pair.copula_family}</p>
            <p className="mt-1 text-[10px] text-muted-foreground">{parameter} · AIC {pair.copula_aic.toFixed(2)}</p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5 pt-5">
        <div className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
          {[
            [probability(pair.h_a_given_b), `h(${pair.stock_a} | ${pair.stock_b})`, "Lower than 10% means A-spread is conditionally low"],
            [probability(pair.h_b_given_a), `h(${pair.stock_b} | ${pair.stock_a})`, "Higher than 90% means B-spread is conditionally high"],
            [pair.copula_family, "AIC-selected copula", `Kendall τ ${pair.kendall_tau.toFixed(3)}`],
            [`${pair.marginal_a} / ${pair.marginal_b}`, "A / B margins", "Lowest AIC among Gaussian, Student-t and Cauchy"],
          ].map(([value, label, note]) => (
            <div key={label} className="bg-card p-4">
              <p className="font-mono text-lg font-semibold">{value}</p>
              <p className="terminal-label mt-1">{label}</p>
              <p className="mt-1 text-[10px] leading-4 text-muted-foreground">{note}</p>
            </div>
          ))}
        </div>

        <div className={`rounded-lg border p-4 ${signalTone(pair.signal)}`}>
          <p className="text-sm font-semibold">{pair.signal_explanation}</p>
          {pair.long_ticker && pair.short_ticker ? (
            <p className="mt-2 font-mono text-xs">
              Long {pair.long_ticker} at reference weight {pair.long_weight?.toFixed(4)} · Short {pair.short_ticker} at reference weight {pair.short_weight?.toFixed(4)}
            </p>
          ) : null}
        </div>

        <ConditionalProbabilityChart pair={pair} />

        <div className="grid gap-3 text-xs text-muted-foreground sm:grid-cols-2 lg:grid-cols-4">
          <div><p className="terminal-label">Direct Engle–Granger</p><p className="mt-1 font-mono text-foreground">p {testValue(pair.engle_granger_p_value)}</p></div>
          <div><p className="terminal-label">Direct KSS</p><p className="mt-1 font-mono text-foreground">t {pair.kss_statistic.toFixed(3)}</p></div>
          <div><p className="terminal-label">NIFTY spread betas</p><p className="mt-1 font-mono text-foreground">{pair.reference_beta_a.toFixed(4)} / {pair.reference_beta_b.toFixed(4)}</p></div>
          <div><p className="terminal-label">Reference-spread KSS</p><p className="mt-1 font-mono text-foreground">{pair.reference_kss_a?.toFixed(3) ?? "—"} / {pair.reference_kss_b?.toFixed(3) ?? "—"}</p></div>
        </div>
      </CardContent>
    </Card>
  );
}

export function CopulaPairSignalsView() {
  const [filter, setFilter] = useState<Filter>("all");
  const queryClient = useQueryClient();
  const scan = useQuery({
    queryKey: ["copula-pair-signals"],
    queryFn: () => api.getCopulaPairSignals(80, false),
    staleTime: 15 * 60_000,
  });
  const refresh = useMutation({
    mutationFn: () => api.getCopulaPairSignals(80, true),
    onSuccess: (data) => queryClient.setQueryData(["copula-pair-signals"], data),
  });
  const data = refresh.data ?? scan.data;
  const results = useMemo(() => {
    const pairs = data?.results ?? [];
    if (filter === "entry") return pairs.filter((pair) => pair.signal.startsWith("enter_"));
    if (filter === "exit") return pairs.filter((pair) => pair.signal === "exit");
    if (filter === "watch") return pairs.filter((pair) => pair.signal === "watch");
    return pairs;
  }, [data?.results, filter]);
  const loading = scan.isLoading || refresh.isPending;

  return (
    <div className="space-y-5 pb-6">
      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="flex flex-col gap-5 border-b border-border/70 p-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="page-eyebrow flex items-center gap-2"><Sigma className="size-3.5" /> Conditional dependence signals</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] sm:text-[2.5rem]">Copula pair signals</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
              Entry and exit states come from AIC-selected copula conditional probabilities.
              Candidates first pass both existing cointegration tests and BH q &lt; 0.05; NIFTY
              replaces Bitcoin as the shared reference asset in the paper&apos;s spread construction.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link href="/pair-method-lab">Existing pair lab</Link>
            </Button>
            <Button variant="outline" size="sm" disabled={loading} onClick={() => refresh.mutate()}>
              {refresh.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              Refit models
            </Button>
          </div>
        </div>
        <div className="grid gap-px bg-border/70 sm:grid-cols-2 lg:grid-cols-5">
          {[
            [data?.dual_test_candidates ?? "—", "Dual-test candidates"],
            [data?.entry_signals ?? "—", "Copula entries"],
            [data?.exit_signals ?? "—", "Copula exits"],
            [data ? `${Math.round(data.entry_threshold * 100)}% / ${Math.round((1 - data.entry_threshold) * 100)}%` : "—", "Joint entry tails"],
            [data ? `${Math.round((0.5 - data.exit_threshold) * 100)}%–${Math.round((0.5 + data.exit_threshold) * 100)}%` : "—", "Two-sided exit band"],
          ].map(([value, label]) => (
            <div key={label} className="bg-card px-5 py-4"><p className="font-mono text-lg font-semibold">{value}</p><p className="terminal-label mt-1">{label}</p></div>
          ))}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader><CardTitle className="text-base">Signal rules</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-xs leading-5 text-muted-foreground">
            <p><strong className="text-foreground">Enter:</strong> one conditional probability must be below 10% while the reverse conditional probability is above 90%.</p>
            <p><strong className="text-foreground">Exit:</strong> both probabilities must return to the 40%–60% equilibrium band.</p>
            <p>The marginal distributions and copula family are re-selected by AIC on each 252-day formation sample, then evaluated over the latest five trading sessions.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">Source methodology</CardTitle></CardHeader>
          <CardContent className="text-xs leading-5 text-muted-foreground">
            <p>This is an explicit NSE adaptation of Tadi and Witzany&apos;s stationary-spread copula method, not a claim that their cryptocurrency results transfer unchanged.</p>
            <a href={data?.paper_url ?? "https://arxiv.org/abs/2305.06961"} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1.5 font-semibold text-primary hover:underline">Read the paper <ExternalLink className="size-3" /></a>
          </CardContent>
        </Card>
      </section>

      <div className="flex flex-wrap items-center gap-2" aria-label="Signal filters">
        {(["all", "entry", "exit", "watch"] as const).map((value) => (
          <Button key={value} size="sm" variant={filter === value ? "default" : "outline"} onClick={() => setFilter(value)}>
            {value === "all" ? "All signals" : value === "entry" ? "Entries" : value === "exit" ? "Exits" : "Watch"}
          </Button>
        ))}
        {data ? <span className="ml-auto text-[10px] text-muted-foreground">Generated {new Date(data.generated_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} · {data.cached ? "cached" : "fresh"}</span> : null}
      </div>

      {loading ? (
        <div className="space-y-4"><Skeleton className="h-80 w-full" /><Skeleton className="h-80 w-full" /></div>
      ) : scan.isError || refresh.isError ? (
        <Card className="border-rose-500/30"><CardContent className="py-8"><p className="font-semibold">The copula signal scan could not be completed.</p><p className="mt-1 text-sm text-muted-foreground">Confirm the API and historical-data connection, then refit the models.</p></CardContent></Card>
      ) : results.length === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">No pairs match this signal filter. The model does not force a trade when the joint probability rule is incomplete.</CardContent></Card>
      ) : (
        <section className="space-y-5" aria-label="Copula pair signals">
          {results.map((pair, index) => <SignalCard key={pair.pair_id} pair={pair} rank={index + 1} />)}
        </section>
      )}

      {data ? (
        <details className="rounded-lg border border-border bg-card p-4">
          <summary className="cursor-pointer text-sm font-semibold">Limitations and implementation notes</summary>
          <ul className="mt-3 space-y-2 pl-5 text-xs leading-5 text-muted-foreground">
            {data.limitations.map((limitation) => <li key={limitation} className="list-disc">{limitation}</li>)}
          </ul>
        </details>
      ) : null}

      <div className="rounded-lg border border-amber-600/30 bg-amber-500/[0.07] p-4">
        <div className="flex items-start gap-3"><CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" /><p className="text-xs leading-5 text-muted-foreground">This page generates research states only. An entry signal is not an order, and an exit state is meaningful only for a position opened under the same fitted copula cycle.</p></div>
      </div>
    </div>
  );
}
