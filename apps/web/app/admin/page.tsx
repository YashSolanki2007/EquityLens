"use client";

import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Clock3,
  Database,
  FileSearch,
  Loader2,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import Link from "next/link";

type AdminStatus = {
  universe_size: number;
  missing_identifiers: string[];
  companies: {
    ticker: string;
    name: string;
    country: string;
    identifier?: string | null;
    filings: number;
    downloaded_primary_filing: number;
    cards: number;
    cards_embedded: number;
  }[];
  recent_jobs: {
    id: string;
    job_type: string;
    ticker?: string | null;
    status: string;
    error?: string | null;
    created_at: string;
  }[];
};

function formatDuration(seconds?: number | null) {
  if (seconds == null) return "Calculating…";
  if (seconds < 60) return "< 1 minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minutes`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} hours`;
  return `${Math.round(hours / 24)} days`;
}

function ProgressBar({
  value,
  tone = "emerald",
}: {
  value: number;
  tone?: "emerald" | "amber";
}) {
  const bounded = Math.min(100, Math.max(0, value));
  return (
    <div
      className="h-2 overflow-hidden rounded-full bg-muted"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={bounded}
    >
      <div
        className={`h-full rounded-full transition-[width] duration-700 ${
          tone === "emerald" ? "bg-emerald-600" : "bg-amber-500"
        }`}
        style={{ width: `${bounded}%` }}
      />
    </div>
  );
}

export default function AdminPage() {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["admin-status"],
    queryFn: () => api.adminStatus() as Promise<AdminStatus>,
    refetchInterval: 15000,
  });
  const materialization = useQuery({
    queryKey: ["materialization-status"],
    queryFn: api.materializationStatus,
    refetchInterval: 5000,
  });

  const bootstrap = useMutation({
    mutationFn: api.adminBootstrap,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-status"] }),
  });
  const ingest = useMutation({
    mutationFn: (ticker: string) => api.adminIngest(ticker),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-status"] }),
  });

  if (status.isLoading) return <Skeleton className="h-96 w-full" />;
  if (status.isError || !status.data)
    return (
      <p className="text-sm text-destructive">
        Failed to load admin status: {String(status.error)}
      </p>
    );

  const d = status.data;
  const fullyIngested = d.companies.filter(
    (c) => c.downloaded_primary_filing > 0
  ).length;
  const withCards = d.companies.filter((c) => c.cards >= 10).length;
  const failedJobs = d.recent_jobs.filter((j) => j.status === "failed");
  const m = materialization.data;

  return (
    <div className="space-y-7">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="page-eyebrow flex items-center gap-2">
            <Database className="size-3.5" />
            System workspace
          </p>
          <h1 className="page-title mt-2">Data operations</h1>
          <p className="page-description mt-2">
            Monitor filing coverage, verified-card generation, embeddings, and ingestion jobs.
          </p>
        </div>
        <div className="flex gap-2 sm:ml-auto">
          <Button
            size="sm"
            variant="outline"
            className="gap-1"
            onClick={() => status.refetch()}
          >
            <RefreshCw className="size-3.5" /> Refresh
          </Button>
          <Button
            size="sm"
            onClick={() => bootstrap.mutate()}
            disabled={bootstrap.isPending}
          >
            {bootstrap.isPending && <Loader2 className="size-4 animate-spin" />}
            Bootstrap universe
          </Button>
        </div>
      </div>

      {m && (
        <Card className="gap-5 overflow-hidden border-emerald-700/25">
          <CardHeader className="border-b border-border bg-emerald-950/[0.035]">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Activity className="size-4 text-emerald-700 dark:text-emerald-400" />
                  NSE semantic materialization
                </CardTitle>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  Annual reports are processed transiently, verified, and embedded into
                  the searchable company-card index.
                </p>
              </div>
              <Badge
                className="w-fit gap-1.5 sm:ml-auto"
                variant={m.state === "running" ? "secondary" : "outline"}
              >
                {m.state === "running" && (
                  <span className="size-1.5 animate-pulse rounded-full bg-emerald-500" />
                )}
                {m.state === "running"
                  ? "Running"
                  : m.state === "completed"
                    ? "Completed"
                    : m.state === "idle"
                      ? "Paused"
                      : "Awaiting status"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[
                [
                  Clock3,
                  "Current stage",
                  m.stage === "metadata" ? "Report discovery" : "Verified cards",
                ],
                [
                  Activity,
                  "Stage progress",
                  `${m.run_completed.toLocaleString("en-IN")} / ${m.run_total.toLocaleString("en-IN")}`,
                ],
                [
                  Sparkles,
                  "Overall ETA",
                  m.stage === "metadata" ? "30–48 hours" : formatDuration(m.eta_seconds),
                ],
                [
                  FileSearch,
                  "Last completed",
                  m.last_ticker ?? "Waiting…",
                ],
              ].map(([Icon, label, value]) => {
                const MetricIcon = Icon as typeof Activity;
                return (
                  <div key={String(label)} className="rounded-lg border border-border bg-card p-3">
                    <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                      <MetricIcon className="size-3" />
                      {String(label)}
                    </p>
                    <p className="mt-1.5 truncate font-mono text-sm font-semibold">
                      {String(value)}
                    </p>
                  </div>
                );
              })}
            </div>

            <div className="space-y-2">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-sm font-medium">
                    {m.stage === "metadata" ? "Current metadata sweep" : "Current card build"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {m.rate_per_hour
                      ? `${m.rate_per_hour.toLocaleString("en-IN", { maximumFractionDigits: 1 })} companies/hour`
                      : "Measuring throughput…"}
                    {m.stage === "metadata" && m.eta_seconds != null
                      ? ` · stage ETA ${formatDuration(m.eta_seconds)}`
                      : ""}
                  </p>
                </div>
                <p className="font-mono text-xl font-semibold tabular-nums">
                  {m.run_percent.toFixed(1)}%
                </p>
              </div>
              <ProgressBar value={m.run_percent} />
            </div>

            <div className="grid gap-5 border-t border-border pt-5 md:grid-cols-2">
              <div className="space-y-2">
                <div className="flex justify-between gap-3 text-xs">
                  <span className="font-medium">Annual-report sources found</span>
                  <span className="font-mono tabular-nums text-muted-foreground">
                    {m.companies_with_reports.toLocaleString("en-IN")} /{" "}
                    {m.universe_size.toLocaleString("en-IN")} ·{" "}
                    {m.report_coverage_percent.toFixed(1)}%
                  </span>
                </div>
                <ProgressBar value={m.report_coverage_percent} tone="amber" />
              </div>
              <div className="space-y-2">
                <div className="flex justify-between gap-3 text-xs">
                  <span className="font-medium">Search-ready verified cards</span>
                  <span className="font-mono tabular-nums text-muted-foreground">
                    {m.companies_with_cards.toLocaleString("en-IN")} /{" "}
                    {m.universe_size.toLocaleString("en-IN")} ·{" "}
                    {m.card_coverage_percent.toFixed(1)}%
                  </span>
                </div>
                <ProgressBar value={m.card_coverage_percent} />
              </div>
            </div>

            <p className="text-[11px] leading-5 text-muted-foreground">
              ETA is recalculated from the current stage&apos;s observed throughput and
              may move when a report needs retries or cannot be parsed. The page refreshes
              automatically every five seconds.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {[
          ["Universe", `${d.universe_size} companies`],
          ["Primary filing ingested", `${fullyIngested}/${d.universe_size}`],
          ["≥10 verified cards", `${withCards}/${d.universe_size}`],
          [
            "Missing identifiers",
            d.missing_identifiers.length
              ? d.missing_identifiers.join(", ")
              : "none",
          ],
        ].map(([label, value]) => (
          <Card key={label as string} className="gap-1 py-5">
            <CardHeader className="py-0">
              <CardTitle className="text-[11px] font-semibold uppercase tracking-[0.09em] text-muted-foreground">
                {label}
              </CardTitle>
            </CardHeader>
            <CardContent className="py-0 text-xl font-semibold tracking-[-0.035em]">
              {value}
            </CardContent>
          </Card>
        ))}
      </div>

      {failedJobs.length > 0 && (
        <Card className="border-destructive gap-2">
          <CardHeader>
            <CardTitle className="text-sm">Failed jobs</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-xs">
            {failedJobs.map((j) => (
              <p key={j.id}>
                {j.job_type} {j.ticker ?? ""}: {j.error}
              </p>
            ))}
          </CardContent>
        </Card>
      )}

      <Card className="gap-3 overflow-hidden">
        <CardHeader>
          <CardTitle className="text-base">Coverage by company</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          <div className="max-h-[520px] overflow-x-auto overflow-y-auto">
            <table className="data-table">
              <thead className="sticky top-0 z-10 bg-muted">
                <tr>
                  <th>Ticker</th>
                  <th>Market</th>
                  <th>CIK / ISIN</th>
                  <th>Filings</th>
                  <th>Primary filing</th>
                  <th>Cards</th>
                  <th>Embedded</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {d.companies.map((c) => (
                  <tr key={c.ticker} className="border-b last:border-0">
                    <td>
                      <Link href={`/company/${c.ticker}`} className="font-medium hover:underline">
                        {c.ticker}
                      </Link>
                    </td>
                    <td>{c.country === "IN" ? "India" : "U.S."}</td>
                    <td className="font-mono text-xs">
                      {c.identifier ?? "—"}
                    </td>
                    <td>{c.filings}</td>
                    <td>
                      {c.downloaded_primary_filing > 0 ? (
                        <Badge variant="secondary">yes</Badge>
                      ) : (
                        <Badge variant="destructive">no</Badge>
                      )}
                    </td>
                    <td>
                      <span className={c.cards >= 10 ? "" : "text-destructive"}>
                        {c.cards}
                      </span>
                    </td>
                    <td>{c.cards_embedded}</td>
                    <td>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => ingest.mutate(c.ticker)}
                        disabled={ingest.isPending}
                      >
                        Re-ingest
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Card className="gap-3">
        <CardHeader>
          <CardTitle className="text-base">Recent ingestion jobs</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-xs">
          {d.recent_jobs.length === 0 && (
            <p className="text-muted-foreground">No jobs yet.</p>
          )}
          {d.recent_jobs.map((j) => (
            <p key={j.id} className="flex items-center gap-2 rounded-xl border border-border/70 bg-muted/25 p-2.5">
              <Badge
                variant={
                  j.status === "done"
                    ? "secondary"
                    : j.status === "failed"
                      ? "destructive"
                      : "outline"
                }
              >
                {j.status}
              </Badge>
              <span>
                {j.job_type} {j.ticker ?? ""} · {new Date(j.created_at).toLocaleString()}
              </span>
            </p>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
