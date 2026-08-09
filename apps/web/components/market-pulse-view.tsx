"use client";

import type { MarketPulseArticle } from "@/lib/api";
import { api } from "@/lib/api";
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
import { useQuery } from "@tanstack/react-query";
import {
  CalendarDays,
  CircleAlert,
  ExternalLink,
  Globe2,
  Newspaper,
  RefreshCw,
  Sparkles,
} from "lucide-react";

const CATEGORY_LABELS: Record<MarketPulseArticle["category"], string> = {
  monetary_policy: "Monetary policy",
  economy: "Indian economy",
  geopolitics: "Geopolitics",
  energy_trade: "Energy & trade",
  technology_regulation: "Technology & regulation",
  other: "Market backdrop",
};

const DIRECTION_STYLES: Record<MarketPulseArticle["impact_direction"], string> = {
  positive: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  negative: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300",
  mixed: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  unclear: "border-border bg-muted text-muted-foreground",
};

function formatArticleDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(`${value}T12:00:00`));
}

function ArticleCard({ article }: { article: MarketPulseArticle }) {
  return (
    <Card className="gap-3 rounded-none border-0 border-b border-border py-5 shadow-none last:border-b-0 hover:bg-muted/20">
      <CardHeader className="gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{CATEGORY_LABELS[article.category]}</Badge>
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <CalendarDays className="size-3" />
            {formatArticleDate(article.published_date)}
          </span>
          <span className="text-xs text-muted-foreground">·</span>
          <span className="text-xs text-muted-foreground">{article.domain}</span>
        </div>
        <CardTitle className="text-lg leading-6">
          <a
            href={article.url}
            target="_blank"
            rel="noreferrer"
            className="group inline-flex items-start gap-2 transition-colors hover:text-emerald-700 dark:hover:text-emerald-400"
          >
            <span>{article.title}</span>
            <ExternalLink className="mt-1 size-4 shrink-0 opacity-50 transition-opacity group-hover:opacity-100" />
          </a>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <ol className="space-y-2">
          {article.summary_lines.slice(0, 3).map((line, index) => (
            <li key={`${article.id}-${index}`} className="flex gap-3 text-sm leading-6">
              <span className="mt-2 size-1.5 shrink-0 rounded-full bg-foreground/35" />
              <span>{line}</span>
            </li>
          ))}
        </ol>

        <div className="border-l-2 border-emerald-600 bg-muted/35 px-3.5 py-3">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Potential India market relevance
            </p>
            <Badge
              variant="outline"
              className={`capitalize ${DIRECTION_STYLES[article.impact_direction]}`}
            >
              {article.impact_direction}
            </Badge>
          </div>
          <p className="text-sm leading-6 text-muted-foreground">
            {article.market_relevance}
          </p>
          {article.affected_areas.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {article.affected_areas.map((area) => (
                <Badge key={area} variant="outline" className="font-normal">
                  {area}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function MarketPulseView() {
  const pulse = useQuery({
    queryKey: ["market-pulse", "IN"],
    queryFn: api.getMarketPulse,
    staleTime: 30 * 60 * 1000,
  });

  if (pulse.isLoading) {
    return (
      <div className="space-y-6">
        <div className="space-y-3 pt-4">
          <Skeleton className="h-9 w-72" />
          <Skeleton className="h-5 w-full max-w-2xl" />
        </div>
        <Skeleton className="h-36 w-full" />
        <div className="grid gap-4 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-96" />
          ))}
        </div>
      </div>
    );
  }

  if (pulse.isError || !pulse.data) {
    return (
      <Card className="mx-auto mt-12 max-w-2xl border-destructive/40">
        <CardContent className="flex items-start gap-3 py-2">
          <CircleAlert className="mt-0.5 size-5 shrink-0 text-destructive" />
          <div>
            <p className="font-medium">The current-news pulse could not be loaded.</p>
            <p className="mt-1 text-sm text-muted-foreground">{String(pulse.error)}</p>
            <Button className="mt-4" size="sm" variant="outline" onClick={() => pulse.refetch()}>
              Try again
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  const data = pulse.data;
  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-5 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="max-w-3xl space-y-2">
          <div className="page-eyebrow flex items-center gap-2">
            <Globe2 className="size-4" />
            Global events, Indian market lens
          </div>
          <h1 className="page-title">India market pulse</h1>
          <p className="page-description">
            A source-linked scan of macroeconomic, policy, trade, technology, energy, and
            geopolitical reporting published during the last {data.lookback_days} days.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => pulse.refetch()}
          disabled={pulse.isFetching}
        >
          <RefreshCw className={pulse.isFetching ? "animate-spin" : ""} />
          Reload
        </Button>
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_290px]">
        <Card className="gap-4 overflow-hidden border-foreground/20">
          <CardHeader className="gap-3">
            <div className="flex items-center justify-between">
              <p className="terminal-label">AI market brief · source grounded</p>
              <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-emerald-700 dark:text-emerald-400">
                <span className="size-1.5 rounded-full bg-emerald-600" />
                Current
              </span>
            </div>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Sparkles className="size-4 text-emerald-700 dark:text-emerald-400" />
              The current backdrop
            </CardTitle>
            <CardDescription className="max-w-4xl text-[15px] leading-7 text-foreground/75">
              {data.overview}
            </CardDescription>
          </CardHeader>
        </Card>

        <Card className="gap-3">
          <CardHeader>
            <CardTitle className="text-sm">Pulse parameters</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border bg-border">
              <div className="bg-card p-3">
                <p className="terminal-label">Sources</p>
                <p className="mt-1 font-mono text-xl font-semibold">
                  {data.articles.length}
                </p>
              </div>
              <div className="bg-card p-3">
                <p className="terminal-label">Window</p>
                <p className="mt-1 font-mono text-xl font-semibold">
                  {data.lookback_days}D
                </p>
              </div>
            </div>
            {data.key_themes.length > 0 && (
              <div>
                <p className="terminal-label mb-2">Key themes</p>
                <div className="flex flex-wrap gap-1.5">
                  {data.key_themes.map((theme) => (
                    <Badge key={theme} variant="outline">
                      {theme}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            <div className="space-y-1 border-t border-border pt-3 text-[11px] text-muted-foreground">
              <p>From {formatArticleDate(data.oldest_allowed_date)}</p>
              <p>Updated {new Date(data.as_of).toLocaleString()}</p>
            </div>
          </CardContent>
        </Card>
      </section>

      {data.limitations.length > 0 && (
        <div className="rounded-lg border border-amber-500/25 bg-amber-500/[0.06] p-4">
          <div className="flex items-start gap-2">
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-600" />
            <div className="space-y-1 text-sm text-muted-foreground">
              {data.limitations.map((limitation) => (
                <p key={limitation}>{limitation}</p>
              ))}
            </div>
          </div>
        </div>
      )}

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="grid size-9 place-items-center rounded-md bg-secondary text-secondary-foreground">
            <Newspaper className="size-4" />
          </span>
          <div>
            <h2 className="section-heading">Recent developments</h2>
            <p className="text-sm text-muted-foreground">
              Summaries are bounded to the linked article; open the original for full context.
            </p>
          </div>
        </div>

        {data.articles.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              No dated articles passed the strict seven-day freshness check.
            </CardContent>
          </Card>
        ) : (
          <Card className="gap-0 overflow-hidden py-0">
            {data.articles.map((article) => (
              <ArticleCard key={article.id} article={article} />
            ))}
          </Card>
        )}
      </section>

      <p className="border-t pt-4 text-xs leading-5 text-muted-foreground">
        News selection and summaries are informational only. “Potential relevance” describes
        possible transmission channels, not a forecast or recommendation. Source links and
        publication dates remain authoritative.
      </p>
    </div>
  );
}
