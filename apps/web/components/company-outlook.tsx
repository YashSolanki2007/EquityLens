"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type CompanyOutlook as CompanyOutlookData } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BrainCircuit,
  CalendarRange,
  ExternalLink,
  RefreshCw,
  Sparkles,
} from "lucide-react";

function directionClasses(direction: string) {
  if (direction === "positive") {
    return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  }
  if (direction === "negative") {
    return "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300";
  }
  if (direction === "unavailable") {
    return "border-border bg-muted text-muted-foreground";
  }
  return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300";
}

function HorizonRow({
  outlook,
}: {
  outlook: CompanyOutlookData["short_term"];
}) {
  return (
    <div className="grid gap-3 px-5 py-4 sm:grid-cols-[145px_1fr] sm:px-6">
      <div>
        <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
          <CalendarRange className="size-3.5" />
          {outlook.horizon}
        </p>
        <span
          className={`mt-2 inline-flex rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] ${directionClasses(
            outlook.direction
          )}`}
        >
          {outlook.direction}
        </span>
      </div>
      <p className="text-sm leading-6 text-foreground/90">{outlook.summary}</p>
    </div>
  );
}

export function CompanyOutlook({ ticker }: { ticker: string }) {
  const outlook = useQuery({
    queryKey: ["company-outlook", ticker],
    queryFn: () => api.getCompanyOutlook(ticker),
    staleTime: 60 * 60 * 1000,
    retry: false,
  });

  if (outlook.isLoading) {
    return (
      <section className="overflow-hidden rounded-lg border bg-card">
        <div className="flex items-center justify-between gap-4 border-b px-5 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <span className="grid size-9 place-items-center rounded-md bg-primary text-primary-foreground">
              <BrainCircuit className="size-4" />
            </span>
            <div>
              <p className="page-eyebrow">AI market outlook</p>
              <p className="mt-0.5 text-sm text-muted-foreground">
                Calculating indicators, scenarios, and recent-news context…
              </p>
            </div>
          </div>
          <Sparkles className="size-4 animate-pulse text-emerald-600" />
        </div>
        <div className="grid gap-4 p-5 sm:grid-cols-2 sm:p-6">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      </section>
    );
  }

  if (outlook.isError || !outlook.data) {
    return (
      <section className="flex items-start gap-3 rounded-lg border border-amber-500/25 bg-amber-500/5 p-4 text-sm">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
        <div className="flex-1">
          <p className="font-medium">Short market outlook is temporarily unavailable.</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            The rest of the company research page remains available.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => outlook.refetch()}
          disabled={outlook.isFetching}
        >
          <RefreshCw className={outlook.isFetching ? "animate-spin" : ""} />
          Retry
        </Button>
      </section>
    );
  }

  const data = outlook.data;
  return (
    <section className="overflow-hidden rounded-lg border bg-card">
      <div className="flex flex-col gap-3 border-b border-border/80 bg-muted/20 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="flex items-center gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-md bg-primary text-primary-foreground">
            <BrainCircuit className="size-4" />
          </span>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <p className="page-eyebrow">AI market outlook</p>
              <Badge variant="outline">3–30 trading days</Badge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Indicators + statistical scenarios + current-news research
            </p>
          </div>
        </div>
        <div className="text-left sm:text-right">
          <p className="text-xs font-semibold capitalize">
            {data.confidence_label} evidence confidence · {data.confidence_percent}%
          </p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            Updated {new Date(data.generated_at).toLocaleString()}
          </p>
        </div>
      </div>

      <div className="divide-y divide-border/80">
        <HorizonRow outlook={data.short_term} />
        <HorizonRow outlook={data.medium_term} />
      </div>

      <div className="flex flex-col gap-2 border-t border-border/80 bg-muted/20 px-5 py-3 text-[10px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <span>
          Llama interpretation · scenarios, not targets · research only, not investment advice
        </span>
        {(data.citations.length > 0 || data.limitations.length > 0) && (
          <details className="group">
            <summary className="cursor-pointer font-medium text-foreground/70">
              Sources & limitations
            </summary>
            <div className="mt-3 grid max-w-xl gap-3 rounded-md border bg-card p-3 text-xs shadow-sm sm:w-[520px]">
              {data.citations.length > 0 && (
                <div>
                  <p className="mb-1.5 font-semibold text-foreground">Sources</p>
                  <ul className="space-y-1.5">
                    {data.citations.map((citation, index) => (
                      <li key={`${citation.url}-${index}`}>
                        <a
                          href={citation.url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-start gap-1 text-emerald-700 hover:underline dark:text-emerald-400"
                        >
                          {citation.description ?? citation.source_type}
                          <ExternalLink className="mt-0.5 size-3 shrink-0" />
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {data.limitations.length > 0 && (
                <div>
                  <p className="mb-1.5 font-semibold text-foreground">Limitations</p>
                  <ul className="list-disc space-y-1 pl-4 leading-5">
                    {data.limitations.map((limitation) => (
                      <li key={limitation}>{limitation}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </details>
        )}
      </div>
    </section>
  );
}
