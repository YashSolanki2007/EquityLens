"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, WalletCards } from "lucide-react";

import { PaperIVTradeTracker } from "@/components/stock-market-workspace";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

type TrackerFilter = "open" | "all" | "closed";

function money(value: number) {
  return `₹${Math.abs(value).toLocaleString("en-IN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  })}`;
}

export function TradeTrackerView() {
  const [portfolioId, setPortfolioId] = useState<string>();
  const [filter, setFilter] = useState<TrackerFilter>("open");
  const queryClient = useQueryClient();

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

  const trades = useQuery({
    queryKey: ["all-option-paper-trades", portfolioId],
    queryFn: () => api.listOptionPaperTrades(portfolioId!),
    enabled: Boolean(portfolioId),
    staleTime: 60 * 1000,
    refetchOnWindowFocus: true,
  });
  const closeTrade = useMutation({
    mutationFn: ({ ticker, tradeId }: { ticker: string; tradeId: string }) =>
      api.closeCompanyPaperIVTrade(ticker, portfolioId!, tradeId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["all-option-paper-trades", portfolioId],
      }),
  });

  const allTrades = useMemo(() => trades.data ?? [], [trades.data]);
  const visibleTrades = useMemo(
    () =>
      allTrades.filter((trade) => {
        if (filter === "all") return true;
        return trade.status === filter;
      }),
    [allTrades, filter]
  );
  const openTrades = allTrades.filter((trade) => trade.status === "open");
  const totalRisk = openTrades.reduce((sum, trade) => sum + trade.capital_at_risk, 0);
  const livePnl = openTrades.reduce(
    (sum, trade) => sum + (trade.latest_mark?.pnl ?? 0),
    0
  );
  const markedTrades = openTrades.filter((trade) => trade.latest_mark != null).length;

  function closeOptionTrade(tradeId: string) {
    const trade = allTrades.find((item) => item.id === tradeId);
    if (trade) closeTrade.mutate({ ticker: trade.ticker, tradeId });
  }

  const updateError =
    closeTrade.error instanceof Error ? closeTrade.error.message : null;

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <section className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="grid gap-5 border-b border-border/70 px-5 py-5 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <p className="page-eyebrow">Development workspace</p>
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-50 px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.08em] text-amber-800 dark:bg-amber-950/25 dark:text-amber-300">
                <FlaskConical className="size-3" /> Dev only
              </span>
            </div>
            <h1 className="mt-2 flex items-center gap-2 text-2xl font-semibold tracking-[-0.035em]">
              <WalletCards className="size-5 text-emerald-700 dark:text-emerald-400" />
              Trade tracker
            </h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
              Every options paper trade saved from an IV Prediction tab, collected in
              one place for development testing. Values refresh from the latest
              available option-chain exit prices.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {(["open", "all", "closed"] as const).map((value) => (
              <Button
                key={value}
                variant={filter === value ? "default" : "outline"}
                size="sm"
                onClick={() => setFilter(value)}
              >
                {value === "open" ? "Open" : value === "closed" ? "Closed" : "All"}
              </Button>
            ))}
          </div>
        </div>

        <div className="grid gap-px bg-border/70 sm:grid-cols-2 lg:grid-cols-4">
          <div className="bg-card px-5 py-4">
            <p className="terminal-label">Open positions</p>
            <p className="mt-2 font-mono text-xl font-semibold">{openTrades.length}</p>
          </div>
          <div className="bg-card px-5 py-4">
            <p className="terminal-label">Marked positions</p>
            <p className="mt-2 font-mono text-xl font-semibold">
              {markedTrades}/{openTrades.length}
            </p>
          </div>
          <div className="bg-card px-5 py-4">
            <p className="terminal-label">Capital at risk</p>
            <p className="mt-2 font-mono text-xl font-semibold">{money(totalRisk)}</p>
          </div>
          <div className="bg-card px-5 py-4">
            <p className="terminal-label">Combined open P&amp;L</p>
            <p
              className={`mt-2 font-mono text-xl font-semibold ${
                livePnl >= 0
                  ? "text-emerald-700 dark:text-emerald-400"
                  : "text-rose-700 dark:text-rose-400"
              }`}
            >
              {livePnl >= 0 ? "+" : "−"}
              {money(livePnl)}
            </p>
          </div>
        </div>
      </section>

      {updateError && (
        <div className="rounded-md border border-amber-500/30 bg-amber-50/60 px-4 py-3 text-xs leading-5 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
          The paper position could not be closed. {updateError}
        </div>
      )}

      <PaperIVTradeTracker
        trades={visibleTrades}
        isLoading={!portfolioId || trades.isLoading}
        isError={trades.isError}
        isRefreshing={trades.isFetching}
        closingTradeId={
          closeTrade.isPending ? closeTrade.variables?.tradeId : undefined
        }
        onRefresh={() => trades.refetch()}
        onClose={closeOptionTrade}
        title={`${filter === "all" ? "All" : filter === "open" ? "Open" : "Closed"} option paper trades`}
        description="Positions from every stock are marked using the same bid-to-sell and ask-to-buy-back rules used on the company page."
        showCompany
        emptyTitle={`No ${filter === "all" ? "" : `${filter} `}option paper trades`}
        emptyDescription="Track a strategy from any company’s IV Prediction tab and it will appear here automatically."
      />
    </div>
  );
}
