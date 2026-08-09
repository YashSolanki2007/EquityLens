"use client";

import { api, type PeerMetricDefinition } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  CheckCircle2,
  Info,
  Plus,
  RotateCcw,
  Search,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

type CompanyOption = {
  ticker: string;
  name: string;
  country: string;
  exchange: string;
  sector: string;
  industry: string;
};

type SortState = {
  key: string;
  direction: "asc" | "desc";
};

function isCompanyOption(value: unknown): value is CompanyOption {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.ticker === "string" &&
    typeof candidate.name === "string" &&
    typeof candidate.country === "string" &&
    typeof candidate.exchange === "string" &&
    typeof candidate.sector === "string" &&
    typeof candidate.industry === "string"
  );
}

function formatMetric(
  value: number | null | undefined,
  definition: PeerMetricDefinition,
  currency: string
) {
  if (value == null || !Number.isFinite(value)) return "—";
  if (definition.format === "currency_compact") {
    try {
      return new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency,
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value);
    } catch {
      return `${currency} ${new Intl.NumberFormat("en-IN", {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value)}`;
    }
  }
  if (definition.format === "percent") {
    return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
  }
  if (definition.format === "multiple") {
    return `${value.toFixed(2)}×`;
  }
  return value.toFixed(2);
}

function relativeCellClass(
  percentile: number | null | undefined,
  isComparable: boolean
) {
  if (!isComparable || percentile == null) return "";
  if (percentile >= 67) {
    return "bg-emerald-500/8 text-emerald-800 dark:text-emerald-300";
  }
  if (percentile <= 33) {
    return "bg-rose-500/7 text-rose-800 dark:text-rose-300";
  }
  return "bg-amber-500/7";
}

function SummaryList({
  values,
  empty,
  tone,
}: {
  values: string[];
  empty: string;
  tone: "positive" | "watch";
}) {
  if (!values.length) {
    return <p className="mt-2 text-sm text-muted-foreground">{empty}</p>;
  }
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {values.map((value) => (
        <Badge
          key={value}
          variant="outline"
          className={cn(
            tone === "positive"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300"
              : "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300"
          )}
        >
          {value}
        </Badge>
      ))}
    </div>
  );
}

export function CompanyPeerComparison({ ticker }: { ticker: string }) {
  const [selection, setSelection] = useState<string[] | null>(null);
  const [sort, setSort] = useState<SortState>({
    key: "market_cap",
    direction: "desc",
  });
  const [addOpen, setAddOpen] = useState(false);
  const [search, setSearch] = useState("");

  const comparison = useQuery({
    queryKey: ["peer-comparison", ticker, selection?.join(",") ?? "automatic"],
    queryFn: () => api.getCompanyPeerComparison(ticker, selection ?? undefined),
    placeholderData: (previous) => previous,
  });
  const companyUniverse = useQuery({
    queryKey: ["company-universe-for-peers"],
    queryFn: () => api.listCompanies(),
    enabled: addOpen,
    staleTime: 30 * 60 * 1000,
  });

  const definitions = comparison.data?.metric_definitions ?? [];
  const selectedTickers = useMemo(
    () =>
      comparison.data?.companies
        .filter((company) => !company.is_subject)
        .map((company) => company.ticker) ?? [],
    [comparison.data?.companies]
  );
  const sortedCompanies = useMemo(() => {
    const companies = [...(comparison.data?.companies ?? [])];
    companies.sort((left, right) => {
      if (left.is_subject) return -1;
      if (right.is_subject) return 1;
      const leftValue = left.metrics[sort.key];
      const rightValue = right.metrics[sort.key];
      if (leftValue == null) return 1;
      if (rightValue == null) return -1;
      return sort.direction === "asc"
        ? leftValue - rightValue
        : rightValue - leftValue;
    });
    return companies;
  }, [comparison.data?.companies, sort]);

  const availableCompanies = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    const selected = new Set([ticker, ...selectedTickers]);
    return (companyUniverse.data ?? [])
      .filter(isCompanyOption)
      .filter(
        (company) =>
          company.country === "IN" &&
          !selected.has(company.ticker) &&
          (!normalizedSearch ||
            company.ticker.toLowerCase().includes(normalizedSearch) ||
            company.name.toLowerCase().includes(normalizedSearch) ||
            company.industry.toLowerCase().includes(normalizedSearch))
      )
      .slice(0, 20);
  }, [companyUniverse.data, search, selectedTickers, ticker]);

  const changeSort = (key: string) => {
    setSort((current) => ({
      key,
      direction:
        current.key === key && current.direction === "desc" ? "asc" : "desc",
    }));
  };
  const removePeer = (symbol: string) => {
    setSelection(selectedTickers.filter((tickerValue) => tickerValue !== symbol));
  };
  const addPeer = (symbol: string) => {
    if (selectedTickers.length >= 7) return;
    setSelection([...selectedTickers, symbol]);
    setSearch("");
    setAddOpen(false);
  };

  if (comparison.isLoading && !comparison.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-80 w-full" />
      </div>
    );
  }

  if (comparison.isError || !comparison.data) {
    return (
      <Card>
        <CardContent className="py-8 text-center">
          <p className="text-sm font-medium">Peer comparison is unavailable.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            The company or its comparison data could not be loaded.
          </p>
          <Button
            className="mt-4"
            variant="outline"
            size="sm"
            onClick={() => comparison.refetch()}
          >
            Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  const data = comparison.data;
  return (
    <div className="space-y-4">
      <Card className="overflow-hidden">
        <CardHeader className="gap-4 border-b border-border/70 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="page-eyebrow">Relative view</p>
            <CardTitle className="mt-1 flex items-center gap-2 text-lg">
              <Users className="size-4 text-emerald-700" />
              {data.peer_group_label}
            </CardTitle>
            <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground">
              {data.selection_method}. Relative colours rank only the companies
              currently shown and exclude unavailable values.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {selection !== null && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setSelection(null)}
              >
                <RotateCcw className="size-3.5" />
                Reset automatic peers
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAddOpen(true)}
              disabled={data.companies.length >= 8}
            >
              <Plus className="size-3.5" />
              Add company
            </Button>
          </div>
        </CardHeader>
        <CardContent className="grid gap-px bg-border p-0 sm:grid-cols-3">
          <div className="bg-card p-4">
            <p className="terminal-label">Comparison set</p>
            <p className="mt-2 text-2xl font-semibold tabular-nums">
              {data.companies.length}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              1 selected company · {Math.max(0, data.companies.length - 1)} peers
            </p>
          </div>
          <div className="bg-card p-4">
            <p className="terminal-label">Relative strengths</p>
            <SummaryList
              values={data.subject_strengths}
              empty="Not enough comparable values yet."
              tone="positive"
            />
          </div>
          <div className="bg-card p-4">
            <p className="terminal-label">Worth checking</p>
            <SummaryList
              values={data.subject_watch_items}
              empty="No clear relative weakness in available metrics."
              tone="watch"
            />
          </div>
        </CardContent>
      </Card>

      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 bg-muted/25 px-4 py-3">
          <div>
            <p className="text-sm font-semibold">Company comparison</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Click a metric heading to sort peers. The selected company remains
              pinned at the top.
            </p>
          </div>
          {comparison.isFetching && (
            <span className="text-xs text-muted-foreground">Refreshing…</span>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="data-table min-w-[1500px]">
            <thead>
              <tr>
                <th className="sticky left-0 z-20 min-w-[280px] bg-muted">
                  Company
                </th>
                <th className="min-w-[190px]">Why this peer</th>
                {definitions.map((definition) => (
                  <th key={definition.key} className="min-w-[132px]">
                    <button
                      type="button"
                      title={definition.description}
                      onClick={() => changeSort(definition.key)}
                      className="inline-flex items-center gap-1.5 text-left hover:text-foreground"
                    >
                      {definition.label}
                      {sort.key === definition.key ? (
                        sort.direction === "desc" ? (
                          <ArrowDown className="size-3" />
                        ) : (
                          <ArrowUp className="size-3" />
                        )
                      ) : (
                        <ArrowUpDown className="size-3 opacity-45" />
                      )}
                    </button>
                  </th>
                ))}
                <th className="min-w-[120px]">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {sortedCompanies.map((company) => (
                <tr
                  key={company.ticker}
                  className={cn(
                    company.is_subject && "bg-emerald-500/5 hover:bg-emerald-500/8"
                  )}
                >
                  <td
                    className={cn(
                      "sticky left-0 z-10",
                      company.is_subject ? "bg-[#f2f8f2] dark:bg-[#18251f]" : "bg-card"
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <Link
                            href={`/company/${company.ticker}`}
                            className="font-semibold hover:text-emerald-700 hover:underline"
                          >
                            {company.ticker}
                          </Link>
                          {company.is_subject && (
                            <Badge className="bg-emerald-700 text-white">
                              Selected
                            </Badge>
                          )}
                        </div>
                        <Link
                          href={`/company/${company.ticker}`}
                          className="mt-0.5 block max-w-[220px] truncate text-xs text-muted-foreground hover:text-foreground"
                          title={company.name}
                        >
                          {company.name}
                        </Link>
                      </div>
                      {!company.is_subject && (
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          aria-label={`Remove ${company.ticker} from comparison`}
                          onClick={() => removePeer(company.ticker)}
                        >
                          <X className="size-3" />
                        </Button>
                      )}
                    </div>
                  </td>
                  <td>
                    <p className="text-xs leading-5">{company.selection_reason}</p>
                    {company.similarity_percent != null && (
                      <p className="mt-0.5 text-[11px] text-muted-foreground">
                        {company.similarity_percent.toFixed(0)}% business match
                      </p>
                    )}
                  </td>
                  {definitions.map((definition) => {
                    const value = company.metrics[definition.key];
                    const percentile = company.percentiles[definition.key];
                    return (
                      <td
                        key={definition.key}
                        className={cn(
                          "font-mono text-xs tabular-nums",
                          relativeCellClass(
                            percentile,
                            definition.higher_is_better != null
                          )
                        )}
                        title={
                          percentile == null
                            ? definition.description
                            : `${definition.description} Relative percentile: ${percentile.toFixed(0)}`
                        }
                      >
                        {formatMetric(value, definition, company.currency)}
                      </td>
                    );
                  })}
                  <td>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs tabular-nums">
                        {company.data_completeness_percent.toFixed(0)}%
                      </span>
                      {company.data_completeness_percent >= 70 && (
                        <CheckCircle2 className="size-3.5 text-emerald-700" />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-col gap-2 border-t border-border/70 bg-muted/25 px-4 py-3 text-[11px] leading-5 text-muted-foreground sm:flex-row sm:items-start sm:justify-between">
          <div className="flex max-w-3xl items-start gap-1.5">
            <Info className="mt-0.5 size-3.5 shrink-0" />
            <span>
              Green and amber-red shading is directional only where a generally
              favourable direction is meaningful. Peer comparison is descriptive,
              not a buy or sell recommendation.
            </span>
          </div>
          <span className="shrink-0">
            Data as of {new Date(data.data_as_of).toLocaleString()}
          </span>
        </div>
      </div>

      {data.limitations.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-4 py-3 text-xs leading-5 text-amber-900 dark:border-amber-900 dark:bg-amber-950/25 dark:text-amber-200">
          {data.limitations.join(" ")}
        </div>
      )}

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Add a company</DialogTitle>
            <DialogDescription>
              Search the NSE mainboard universe and add up to seven peer companies.
            </DialogDescription>
          </DialogHeader>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search ticker, company or industry"
              className="pl-9"
              autoFocus
            />
          </div>
          <div className="max-h-[360px] space-y-1 overflow-y-auto pr-1">
            {companyUniverse.isLoading &&
              Array.from({ length: 5 }).map((_, index) => (
                <Skeleton key={index} className="h-14 w-full" />
              ))}
            {!companyUniverse.isLoading &&
              availableCompanies.map((company) => (
                <button
                  type="button"
                  key={company.ticker}
                  onClick={() => addPeer(company.ticker)}
                  className="flex w-full items-center justify-between gap-4 rounded-md border border-transparent px-3 py-2.5 text-left transition-colors hover:border-border hover:bg-muted/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">{company.ticker}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {company.name}
                    </p>
                  </div>
                  <Badge variant="outline" className="max-w-[180px] truncate">
                    {company.industry}
                  </Badge>
                </button>
              ))}
            {!companyUniverse.isLoading && availableCompanies.length === 0 && (
              <p className="py-10 text-center text-sm text-muted-foreground">
                No matching NSE company found.
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
