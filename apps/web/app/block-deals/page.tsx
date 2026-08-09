"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, type BlockDeal } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ArrowUpRight,
  CalendarDays,
  ExternalLink,
  Handshake,
  IndianRupee,
  Loader2,
  Search,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

type SortKey = "trade_date" | "trade_value_inr";
type SortDirection = "asc" | "desc";

function formatAmount(value: number) {
  if (value >= 10_000_000) {
    return `₹${(value / 10_000_000).toLocaleString("en-IN", {
      maximumFractionDigits: 2,
      minimumFractionDigits: 2,
    })} Cr`;
  }
  if (value >= 100_000) {
    return `₹${(value / 100_000).toLocaleString("en-IN", {
      maximumFractionDigits: 2,
      minimumFractionDigits: 2,
    })} L`;
  }
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function formatPrice(value: number) {
  return `₹${value.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(`${value}T00:00:00`));
}

function SortButton({
  label,
  column,
  sortKey,
  direction,
  onSort,
}: {
  label: string;
  column: SortKey;
  sortKey: SortKey;
  direction: SortDirection;
  onSort: (column: SortKey) => void;
}) {
  const active = sortKey === column;
  const Icon = !active ? ArrowUpDown : direction === "asc" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      onClick={() => onSort(column)}
      className="inline-flex items-center gap-1.5 transition-colors hover:text-foreground"
      aria-label={`Sort by ${label}`}
    >
      {label}
      <Icon className="size-3" />
    </button>
  );
}

export default function BlockDealsPage() {
  const [days, setDays] = useState(30);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("trade_value_inr");
  const [direction, setDirection] = useState<SortDirection>("desc");
  const deals = useQuery({
    queryKey: ["block-deals", days],
    queryFn: () => api.getBlockDeals(days),
    staleTime: 10 * 60 * 1000,
  });

  const visibleDeals = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = (deals.data?.deals ?? []).filter((deal) => {
      if (!needle) return true;
      return [deal.symbol, deal.company_name, deal.client_name, deal.side].some((value) =>
        value.toLowerCase().includes(needle),
      );
    });
    return [...filtered].sort((left, right) => {
      const leftValue = left[sortKey];
      const rightValue = right[sortKey];
      const comparison =
        typeof leftValue === "number"
          ? leftValue - (rightValue as number)
          : leftValue.localeCompare(rightValue as string);
      return direction === "asc" ? comparison : -comparison;
    });
  }, [deals.data?.deals, direction, search, sortKey]);

  const stats = useMemo(() => {
    const rows = deals.data?.deals ?? [];
    return {
      totalValue: rows.reduce((sum, deal) => sum + deal.trade_value_inr, 0),
      stocks: new Set(rows.map((deal) => deal.symbol)).size,
      latestDate: rows.reduce(
        (latest, deal) => (deal.trade_date > latest ? deal.trade_date : latest),
        "",
      ),
    };
  }, [deals.data?.deals]);

  function changeSort(column: SortKey) {
    if (sortKey === column) {
      setDirection((current) => (current === "desc" ? "asc" : "desc"));
      return;
    }
    setSortKey(column);
    setDirection("desc");
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-5 border-b border-border pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <p className="page-eyebrow flex items-center gap-2">
            <Handshake className="size-3.5" /> NSE disclosed activity
          </p>
          <h1 className="page-title mt-2">Block deals</h1>
          <p className="page-description mt-3">
            Explore exchange-disclosed NSE block transactions, including the named client,
            buy or sell side, quantity, weighted-average price, and estimated deal value.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {[7, 30, 90].map((window) => (
            <Button
              key={window}
              type="button"
              size="sm"
              variant={days === window ? "default" : "outline"}
              onClick={() => setDays(window)}
            >
              {window} days
            </Button>
          ))}
        </div>
      </section>

      {deals.isLoading && (
        <Card>
          <CardContent className="flex min-h-52 items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Loading NSE disclosures…
          </CardContent>
        </Card>
      )}

      {deals.isError && (
        <Card className="border-destructive/40">
          <CardContent className="space-y-3 py-6">
            <p className="text-sm font-medium text-destructive">
              The NSE block-deal feed could not be loaded.
            </p>
            <p className="text-xs text-muted-foreground">
              {deals.error instanceof Error ? deals.error.message : "Unknown data-source error"}
            </p>
            <Button size="sm" variant="outline" onClick={() => deals.refetch()}>
              Try again
            </Button>
          </CardContent>
        </Card>
      )}

      {deals.data && (
        <>
          <section className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 xl:grid-cols-4">
            {[
              [formatAmount(stats.totalValue), "Disclosed value", IndianRupee],
              [String(deals.data.deals.length), "Block-deal records", Handshake],
              [String(stats.stocks), "Stocks represented", Search],
              [stats.latestDate ? formatDate(stats.latestDate) : "—", "Latest disclosure", CalendarDays],
            ].map(([value, label, Icon]) => (
              <div key={String(label)} className="bg-card p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-mono text-xl font-semibold tabular-nums">{String(value)}</p>
                  <Icon className="size-4 text-muted-foreground" />
                </div>
                <p className="terminal-label mt-1">{String(label)}</p>
              </div>
            ))}
          </section>

          <section className="overflow-hidden rounded-lg border border-border bg-card">
            <div className="flex flex-col gap-3 border-b border-border p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="section-heading">Recent disclosures</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  {formatDate(deals.data.from_date)}–{formatDate(deals.data.to_date)} · sorted by{" "}
                  {sortKey === "trade_value_inr" ? "amount" : "date"} {direction === "desc" ? "high to low" : "low to high"}
                </p>
              </div>
              <label className="relative block w-full sm:w-80">
                <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search stock or client…"
                  className="pl-9"
                  aria-label="Search block deals"
                />
              </label>
            </div>

            <div className="overflow-x-auto">
              <table className="data-table min-w-[1000px]">
                <thead>
                  <tr>
                    <th>
                      <SortButton
                        label="Date"
                        column="trade_date"
                        sortKey={sortKey}
                        direction={direction}
                        onSort={changeSort}
                      />
                    </th>
                    <th>Stock</th>
                    <th>Client</th>
                    <th>Side</th>
                    <th className="text-right">Quantity</th>
                    <th className="text-right">Avg. price</th>
                    <th className="text-right">
                      <SortButton
                        label="Amount"
                        column="trade_value_inr"
                        sortKey={sortKey}
                        direction={direction}
                        onSort={changeSort}
                      />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visibleDeals.map((deal: BlockDeal, index) => (
                    <tr
                      key={`${deal.trade_date}-${deal.symbol}-${deal.client_name}-${deal.side}-${deal.quantity}-${index}`}
                    >
                      <td className="whitespace-nowrap font-mono text-xs tabular-nums">
                        {formatDate(deal.trade_date)}
                      </td>
                      <td>
                        <Link
                          href={`/company/${deal.symbol}`}
                          aria-label={`Analyze ${deal.company_name}`}
                          className="group inline-flex max-w-60 items-start gap-2 rounded-sm outline-none transition-colors hover:text-emerald-700 focus-visible:ring-2 focus-visible:ring-ring dark:hover:text-emerald-400"
                        >
                          <span className="min-w-0">
                            <span className="block font-mono text-xs font-semibold group-hover:underline group-hover:underline-offset-2">
                              {deal.symbol}
                            </span>
                            <span className="mt-0.5 block max-w-52 truncate text-xs text-muted-foreground transition-colors group-hover:text-foreground">
                              {deal.company_name}
                            </span>
                          </span>
                          <ArrowUpRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-emerald-700 dark:group-hover:text-emerald-400" />
                        </Link>
                      </td>
                      <td className="max-w-80 text-xs font-medium">{deal.client_name}</td>
                      <td>
                        <Badge
                          variant="outline"
                          className={
                            deal.side === "BUY"
                              ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300"
                              : "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300"
                          }
                        >
                          {deal.side}
                        </Badge>
                      </td>
                      <td className="text-right font-mono text-xs tabular-nums">
                        {deal.quantity.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                      </td>
                      <td className="text-right font-mono text-xs tabular-nums">
                        {formatPrice(deal.weighted_average_price)}
                      </td>
                      <td className="text-right font-mono text-xs font-semibold tabular-nums">
                        {formatAmount(deal.trade_value_inr)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {visibleDeals.length === 0 && (
              <div className="border-t border-border px-4 py-12 text-center text-sm text-muted-foreground">
                {search
                  ? "No block deals match this search."
                  : "NSE reported no block deals in the selected period."}
              </div>
            )}
          </section>

          <section className="flex flex-col gap-3 rounded-lg border border-border bg-muted/25 p-4 text-xs leading-5 text-muted-foreground sm:flex-row sm:items-start sm:justify-between">
            <div className="max-w-4xl">
              <p>{deals.data.limitation}</p>
              <p className="mt-1">
                Amount is estimated as quantity × weighted-average price. A disclosed client
                is not necessarily an institutional investor.
              </p>
            </div>
            <a
              href={deals.data.source_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex shrink-0 items-center gap-1.5 font-medium text-emerald-700 hover:underline dark:text-emerald-400"
            >
              View NSE source <ExternalLink className="size-3" />
            </a>
          </section>
        </>
      )}
    </div>
  );
}
