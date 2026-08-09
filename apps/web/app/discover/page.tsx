"use client";

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
import { Textarea } from "@/components/ui/textarea";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  BarChart3,
  Clock3,
  Globe2,
  Loader2,
  Search,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

const INDIA_EXAMPLES = [
  "Find NSE companies involved in power transmission, grid equipment, or electrical infrastructure.",
  "Indian pharmaceutical companies with direct export exposure and positive latest-quarter revenue growth.",
  "NSE main-board companies supplying components or services to automobile manufacturers.",
  "Indian companies around ₹50,000 crore market cap involved in renewable power or energy infrastructure.",
  "NSE businesses exposed to data centers, cloud infrastructure, telecom networks, or digital payments.",
];

export default function DiscoverPage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"quick" | "standard">("standard");
  const market = "IN" as const;
  const examples = INDIA_EXAMPLES;

  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.listSessions });

  const run = useMutation({
    mutationFn: () => api.runSearch({ query, mode, market }),
    onSuccess: (data) => router.push(`/search/${data.search_id}`),
  });

  return (
    <div className="space-y-7">
      <section className="fade-in-up flex flex-col gap-5 border-b border-border pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl space-y-2">
          <p className="page-eyebrow">Company screening</p>
          <h1 className="page-title">Discover NSE companies</h1>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
            Search operating models, customer exposure, financial conditions, and
            catalysts across verified NSE annual reports.
          </p>
        </div>
        <div className="grid grid-cols-3 overflow-hidden rounded-md border border-border bg-border shadow-[0_1px_2px_rgba(15,23,42,0.035)]">
          {[
            ["2,386", "Equities"],
            ["1", "Market"],
            ["24/7", "Research"],
          ].map(([value, label]) => (
            <div key={label} className="min-w-24 bg-card px-4 py-3">
              <p className="font-mono text-base font-semibold tabular-nums">{value}</p>
              <p className="terminal-label mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="fade-in-up grid gap-5 [animation-delay:80ms] lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-2">
          <Card className="gap-0 overflow-hidden border-primary/25 py-0">
          <div className="flex items-center justify-between border-b border-border bg-accent/35 px-4 py-3 sm:px-5">
            <div className="flex items-center gap-2">
              <Search className="size-4 text-primary" />
              <span className="text-[12px] font-semibold">
                New company screen
              </span>
            </div>
            <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground">
              Natural language · evidence ranked
            </span>
          </div>
          <CardContent className="p-3 sm:p-5">
            <Textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask a detailed question about the companies you want to find…"
              aria-label="Describe the companies you want to research"
              className="min-h-36 resize-none border-0 bg-transparent px-1 py-2 text-base leading-7 shadow-none focus-visible:ring-0"
            />
            <div className="flex flex-col gap-3 border-t border-border pt-3 sm:flex-row sm:items-center">
              <div className="flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-2 text-xs font-medium text-foreground">
                <Globe2 className="size-3.5 text-primary" />
                <span>India · NSE main board</span>
              </div>
              <div className="flex w-fit rounded-md bg-muted p-1 text-xs">
                {(["quick", "standard"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    aria-pressed={mode === m}
                    onClick={() => setMode(m)}
                    className={`rounded px-3 py-1.5 font-medium transition-all ${
                      mode === m
                        ? "bg-card text-primary shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {m === "quick" ? "Quick · 5 results" : "Standard · 15 results"}
                  </button>
                ))}
              </div>
              <Button
                onClick={() => run.mutate()}
                disabled={!query.trim() || run.isPending}
                size="lg"
                className="sm:ml-auto"
              >
                {run.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Search className="size-4" />
                )}
                Start research
              </Button>
            </div>
          </CardContent>
          </Card>
          {run.isError && (
            <p className="px-2 text-sm text-destructive">{String(run.error)}</p>
          )}
        </div>

        <Card className="gap-0 py-0">
          <CardHeader className="border-b border-border py-4">
            <CardTitle className="flex items-center gap-2 text-sm">
              <BarChart3 className="size-4 text-primary" />
              Research templates
            </CardTitle>
            <CardDescription>
              Start with an institutional screening pattern.
            </CardDescription>
          </CardHeader>
          <div className="divide-y divide-border">
            {examples.map((example, index) => (
              <button
                key={example}
                type="button"
                onClick={() => setQuery(example)}
                className="group flex w-full items-start gap-3 px-4 py-3 text-left text-xs leading-5 text-muted-foreground transition-colors hover:bg-muted/55 hover:text-foreground"
              >
                <span className="mt-0.5 font-mono text-[10px] font-semibold text-muted-foreground">
                  0{index + 1}
                </span>
                <span className="line-clamp-2">{example}</span>
                <ArrowUpRight className="ml-auto mt-0.5 size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
              </button>
            ))}
          </div>
        </Card>
      </section>

      <section className="fade-in-up [animation-delay:140ms]">
        <Card className="gap-0 py-0">
          <CardHeader className="flex-row items-start justify-between space-y-0 border-b border-border py-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <Clock3 className="size-4 text-muted-foreground" />
                Recent research
              </CardTitle>
              <CardDescription className="mt-1">
                Reopen a previous search and continue the investigation.
              </CardDescription>
            </div>
            {sessions.data && sessions.data.length > 0 && (
              <Badge variant="outline">4 most recent</Badge>
            )}
          </CardHeader>
          <CardContent className="p-0">
            {sessions.isLoading && (
              <p className="p-5 text-sm text-muted-foreground">Loading recent research…</p>
            )}
            {sessions.data?.length === 0 && (
              <div className="p-8 text-center text-sm text-muted-foreground">
                Your completed research sessions will appear here.
              </div>
            )}
            <ul className="divide-y divide-border">
              {sessions.data?.slice(0, 4).map((session) => (
                <li key={session.id}>
                  <Link
                    href={`/search/${session.id}`}
                    className="group grid items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/45 sm:grid-cols-[minmax(0,1fr)_120px_170px_20px]"
                  >
                    <span className="truncate text-sm font-medium text-foreground">
                      {session.original_query}
                    </span>
                    <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
                      {session.market === "IN" ? "India · NSE" : "U.S. · NYSE"}
                    </span>
                    <span className="hidden text-xs text-muted-foreground sm:block">
                      {new Date(session.created_at).toLocaleString()}
                    </span>
                    <ArrowUpRight className="size-4 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
