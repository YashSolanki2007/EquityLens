"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CircleAlert,
  GitBranch,
  Loader2,
  RefreshCw,
  ShieldCheck,
  WalletCards,
} from "lucide-react";
import { FormEvent, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, type PaperPairPortfolio } from "@/lib/api";
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

const rupees = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function shortDate(value: string) {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
  });
}

function PortfolioSummary({ portfolio }: { portfolio: PaperPairPortfolio }) {
  const latest = portfolio.marks.at(-1);
  const summary = portfolio.selection_summary;
  return (
    <div className="space-y-5">
      <div className="grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
        {[
          [rupees.format(latest?.portfolio_value_inr ?? portfolio.initial_capital_inr), "Paper value"],
          [rupees.format(latest?.total_pnl_inr ?? 0), "Stock-leg P&L"],
          [`${summary.selected_pairs}`, "Pairs selected"],
          [`${summary.unique_companies}`, "Unique companies"],
        ].map(([value, label]) => (
          <div key={label} className="bg-card px-4 py-3">
            <p className="font-mono text-lg font-semibold tabular-nums">{value}</p>
            <p className="terminal-label mt-1">{label}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.05fr_1.4fr]">
        <div className="space-y-3 rounded-md border border-border p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              variant="outline"
              className={
                summary.fully_ticker_disjoint
                  ? "border-emerald-700/30 text-emerald-700 dark:text-emerald-400"
                  : "border-amber-700/30 text-amber-700 dark:text-amber-400"
              }
            >
              {summary.fully_ticker_disjoint
                ? "No company repeated"
                : "Same-side overlap used"}
            </Badge>
            <Badge variant="outline">
              Mean |correlation| {percent(summary.mean_absolute_pair_correlation)}
            </Badge>
            <Badge variant="outline">
              Max |correlation| {percent(summary.maximum_absolute_pair_correlation)}
            </Badge>
          </div>
          <div className="space-y-2">
            {portfolio.positions.map((position) => (
              <div
                key={position.pair_id}
                className="rounded-md border border-border bg-muted/20 px-3 py-2.5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold">
                    <span className="text-emerald-700 dark:text-emerald-400">
                      Long {position.long_ticker}
                    </span>{" "}
                    <span className="text-muted-foreground">/</span>{" "}
                    <span className="text-rose-700 dark:text-rose-400">
                      Short {position.short_ticker}
                    </span>
                  </p>
                  <span className="font-mono text-xs tabular-nums">
                    {rupees.format(position.allocated_gross_inr)}
                  </span>
                </div>
                <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
                  {position.long_units.toFixed(4)} long units at {rupees.format(position.entry_long_price)} ·{" "}
                  {position.short_units.toFixed(4)} short units at {rupees.format(position.entry_short_price)} ·{" "}
                  mean |corr| {percent(position.mean_abs_correlation_to_portfolio)}
                </p>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-md border border-border p-4">
          <div className="mb-3">
            <p className="text-sm font-semibold">Paper portfolio value</p>
            <p className="text-xs text-muted-foreground">
              Initial amount plus long- and short-leg P&amp;L from stock closes.
            </p>
          </div>
          <div className="h-72 w-full" role="img" aria-label="Paper pair portfolio value history">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={portfolio.marks} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="date"
                  tickFormatter={shortDate}
                  tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                  tickLine={false}
                  axisLine={false}
                  minTickGap={32}
                />
                <YAxis
                  tickFormatter={(value) => `₹${Math.round(Number(value) / 1000)}k`}
                  tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                  tickLine={false}
                  axisLine={false}
                  width={54}
                  domain={["auto", "auto"]}
                />
                <Tooltip
                  labelFormatter={(value) => shortDate(String(value))}
                  formatter={(value) => [rupees.format(Number(value)), "Portfolio value"]}
                  contentStyle={{
                    borderRadius: 8,
                    border: "1px solid var(--border)",
                    background: "var(--card)",
                    fontSize: 12,
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="portfolio_value_inr"
                  stroke="var(--chart-1)"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 3 }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <details className="rounded-md border border-border px-4 py-3 text-xs">
        <summary className="cursor-pointer font-semibold">Sizing and valuation assumptions</summary>
        <ul className="mt-2 list-disc space-y-1.5 pl-4 leading-5 text-muted-foreground">
          {portfolio.limitations.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </details>
    </div>
  );
}

export function PairPortfolioBuilder({
  ownerPortfolioId,
  pValueThreshold,
}: {
  ownerPortfolioId?: string;
  pValueThreshold: number;
}) {
  const [amount, setAmount] = useState("500000");
  const queryClient = useQueryClient();
  const queryKey = ["paper-pair-portfolio", ownerPortfolioId];
  const portfolio = useQuery({
    queryKey,
    queryFn: () => api.getCurrentPairPortfolio(ownerPortfolioId!, true),
    enabled: Boolean(ownerPortfolioId),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
  const create = useMutation({
    mutationFn: (investmentAmount: number) =>
      api.createPairPortfolio(ownerPortfolioId!, investmentAmount, pValueThreshold),
    onSuccess: (data) => queryClient.setQueryData(queryKey, data),
  });
  const refresh = useMutation({
    mutationFn: () => api.refreshPairPortfolio(ownerPortfolioId!),
    onSuccess: (data) => queryClient.setQueryData(queryKey, data),
  });
  const parsedAmount = Number(amount.replace(/,/g, ""));
  const amountIsValid = Number.isFinite(parsedAmount) && parsedAmount >= 10_000;
  const error = create.error instanceof Error
    ? create.error.message
    : refresh.error instanceof Error
      ? refresh.error.message
      : portfolio.error instanceof Error
        ? portfolio.error.message
        : null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (amountIsValid) create.mutate(parsedAmount);
  }

  return (
    <Card className="overflow-hidden border-emerald-700/20">
      <CardHeader className="border-b border-border bg-emerald-500/[0.035]">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
          <div className="max-w-3xl">
            <CardTitle className="flex items-center gap-2 text-base">
              <WalletCards className="size-4 text-emerald-700 dark:text-emerald-400" />
              Build a diversified pair portfolio
            </CardTitle>
            <CardDescription className="mt-1 leading-5">
              Choose an amount and the builder selects up to six active pairs. It minimizes
              absolute pair-return correlation and prioritizes using every company only once.
            </CardDescription>
          </div>
          <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <label className="space-y-1.5">
              <span className="terminal-label block">Paper investment amount</span>
              <div className="flex h-9 min-w-52 items-center rounded-md border border-input bg-card px-3 shadow-xs focus-within:ring-[3px] focus-within:ring-ring/50">
                <span className="mr-1 text-sm text-muted-foreground">₹</span>
                <input
                  inputMode="decimal"
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  aria-label="Paper investment amount in rupees"
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none"
                />
              </div>
            </label>
            <Button disabled={!ownerPortfolioId || !amountIsValid || create.isPending}>
              {create.isPending ? <Loader2 className="animate-spin" /> : <GitBranch />}
              {portfolio.data ? "Rebuild portfolio" : "Build portfolio"}
            </Button>
            {portfolio.data && (
              <Button
                type="button"
                variant="outline"
                disabled={refresh.isPending}
                onClick={() => refresh.mutate()}
              >
                {refresh.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                Refresh prices
              </Button>
            )}
          </form>
        </div>
        <div className="flex flex-wrap gap-2 pt-1">
          <Badge variant="outline"><ShieldCheck /> Opposite-side ticker reuse blocked</Badge>
          <Badge variant="outline">Spot prices only</Badge>
          <Badge variant="outline">Fractional paper units</Badge>
        </div>
      </CardHeader>
      <CardContent className="pt-5">
        {!ownerPortfolioId || portfolio.isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : error ? (
          <div className="flex items-start gap-3 rounded-md border border-amber-600/30 bg-amber-500/[0.08] p-4 text-sm">
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" />
            <p>The pair portfolio could not be updated. {error}</p>
          </div>
        ) : portfolio.data ? (
          <PortfolioSummary portfolio={portfolio.data} />
        ) : (
          <div className="rounded-md border border-dashed border-border px-5 py-8 text-center">
            <p className="text-sm font-medium">No pair portfolio built yet</p>
            <p className="mx-auto mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">
              Enter at least ₹10,000. The result is a paper P&amp;L proxy—not an executable
              short-selling or margin plan.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
