"use client";

import type { ResultCandidate } from "@/lib/api";
import { formatMarketCap } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { CitationList } from "@/components/citation-list";
import { AlertTriangle, ArrowRight, FileText } from "lucide-react";
import Link from "next/link";

function statusColor(status: string): string {
  switch (status) {
    case "pass":
      return "border border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300";
    case "partial":
      return "border border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300";
    case "fail":
      return "border border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/30 dark:text-rose-300";
    default:
      return "border border-border bg-muted text-muted-foreground";
  }
}

export function ResultCard({ result }: { result: ResultCandidate }) {
  const allCitations = result.condition_results.flatMap((c) => c.citations);
  const semanticCards = Object.values(result.semantic_matches ?? {}).flatMap(
    (m) => ((m as { best_cards?: unknown[] }).best_cards ?? []) as {
      text?: string;
      directness?: string;
      similarity?: number;
      source_url?: string;
      source_excerpt?: string;
    }[]
  );

  return (
    <Card className="group gap-4 overflow-hidden transition-colors hover:border-input">
      <CardHeader className="flex flex-row items-start gap-4 space-y-0">
        {result.rank != null && (
          <span className="grid size-9 shrink-0 place-items-center rounded-md bg-primary font-mono text-sm font-semibold text-primary-foreground">
            {result.rank}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {result.rank != null && (
              <span className="sr-only">Rank {result.rank}</span>
            )}
            <Link
              href={`/company/${result.ticker}`}
              className="text-lg font-semibold tracking-[-0.025em] hover:text-emerald-700 dark:hover:text-emerald-400"
            >
              {result.ticker}
            </Link>
            <span className="truncate text-sm text-muted-foreground">{result.name}</span>
            {result.directness_badge && (
              <Badge variant="outline" className="capitalize">
                {result.directness_badge}
              </Badge>
            )}
            {result.timed_out && (
              <Badge variant="destructive" className="gap-1">
                <AlertTriangle className="size-3" /> incomplete
              </Badge>
            )}
            {result.eligible === false && (
              <Badge variant="outline" className="text-muted-foreground">
                not qualified
              </Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {formatMarketCap(
              result.market_cap_usd,
              result.currency,
              result.market_cap_native
            )} market cap
            {result.market_cap_retrieved_at &&
              ` (delayed, retrieved ${new Date(result.market_cap_retrieved_at).toLocaleString()})`}
          </p>
        </div>
        {result.match_percent != null && (
          <div className="min-w-20 text-right">
            <div className="text-2xl font-semibold tracking-[-0.04em]">{result.match_percent}%</div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
              Match
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-emerald-600"
                style={{ width: `${Math.max(0, Math.min(result.match_percent, 100))}%` }}
              />
            </div>
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {result.why_matched && (
          <p className="text-sm leading-6 text-foreground/90">{result.why_matched}</p>
        )}

        {semanticCards.length > 0 && (
          <div className="space-y-2 border-l-2 border-emerald-600 bg-emerald-50/40 p-3 text-xs text-muted-foreground dark:bg-emerald-950/20">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-emerald-800/75 dark:text-emerald-300">
              Strongest semantic evidence
            </p>
            {semanticCards.slice(0, 2).map((card, i) => (
              <p key={i} className="line-clamp-2 leading-5">
                <span className="capitalize font-medium text-foreground/80">
                  {card.directness}
                </span>{" "}
                · {card.text}
              </p>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {result.condition_results.map((c) => (
            <span
              key={c.condition_id + c.explanation.slice(0, 8)}
              title={c.explanation}
              className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${statusColor(c.status)}`}
            >
              {c.condition_id}: {c.status}
              {c.measured_value != null && ` (${c.measured_value}%)`}
            </span>
          ))}
        </div>

        {result.condition_results.some((c) => c.current_period) && (
          <p className="text-xs text-muted-foreground">
            {result.condition_results
              .filter((c) => c.current_period)
              .map(
                (c) =>
                  `${c.condition_id}: ${c.current_period} vs ${c.comparison_period}`
              )
              .join(" · ")}
          </p>
        )}

        {result.limitations.length > 0 && (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer font-medium">
              Limitations ({result.limitations.length})
            </summary>
            <ul className="mt-1 list-disc pl-4 space-y-0.5">
              {result.limitations.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          </details>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-border/70 pt-3">
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1">
                <FileText className="size-3.5" />
                Citations ({allCitations.length + semanticCards.length})
              </Button>
            </DialogTrigger>
            <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
              <DialogHeader>
                <DialogTitle>
                  Evidence for {result.ticker}
                </DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                {semanticCards.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium mb-1">
                      Verified filing semantic cards
                    </h4>
                    <CitationList
                      citations={semanticCards.map((card) => ({
                        source_type: "company_card",
                        url: card.source_url ?? "",
                        description: card.text,
                        excerpt: card.source_excerpt,
                      }))}
                    />
                  </div>
                )}
                <div>
                  <h4 className="text-sm font-medium mb-1">Research citations</h4>
                  <CitationList citations={allCitations} />
                  {allCitations.length === 0 && (
                    <p className="text-xs text-muted-foreground">
                      No research citations recorded.
                    </p>
                  )}
                </div>
              </div>
            </DialogContent>
          </Dialog>
          <span className="ml-auto text-xs text-muted-foreground">
            confidence {result.overall_confidence ?? "–"}
          </span>
          <Link
            href={`/company/${result.ticker}`}
            className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 hover:text-emerald-900 dark:text-emerald-400 dark:hover:text-emerald-300"
          >
            Company profile <ArrowRight className="size-3.5" />
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
