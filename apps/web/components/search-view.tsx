"use client";

import { api, streamSearch, type ProgressEvent } from "@/lib/api";
import { ChatPanel } from "@/components/chat-panel";
import { ComparisonTable } from "@/components/comparison-table";
import { FunnelPanel } from "@/components/funnel-panel";
import { PlanChips } from "@/components/plan-chips";
import { ProgressTimeline } from "@/components/progress-timeline";
import { ResultCard } from "@/components/result-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, MessageSquareText, Pencil, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export function SearchView({ id }: { id: string }) {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [live, setLive] = useState(true);
  const [editOpen, setEditOpen] = useState(false);
  const [instruction, setInstruction] = useState("");
  const streamStarted = useRef(false);

  const session = useQuery({
    queryKey: ["search", id],
    queryFn: () => api.getSearch(id),
    refetchInterval: (q) =>
      q.state.data && ["completed", "failed"].includes(q.state.data.status)
        ? false
        : 4000,
  });

  useEffect(() => {
    if (streamStarted.current) return;
    streamStarted.current = true;
    const close = streamSearch(
      id,
      (event) => {
        setEvents((prev) => [...prev, event]);
        if (["completed", "failed", "plan_ready"].includes(event.stage)) {
          queryClient.invalidateQueries({ queryKey: ["search", id] });
        }
      },
      () => setLive(false)
    );
    return close;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const modify = useMutation({
    mutationFn: (text: string) => api.patchPlan(id, { instruction: text, rerun: true }),
    onSuccess: () => {
      setEditOpen(false);
      setInstruction("");
      setEvents([]);
      streamStarted.current = false;
      queryClient.invalidateQueries({ queryKey: ["search", id] });
      streamSearch(
        id,
        (event) => setEvents((prev) => [...prev, event]),
        () => queryClient.invalidateQueries({ queryKey: ["search", id] })
      );
    },
  });

  if (session.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (session.isError || !session.data) {
    return <p className="text-destructive text-sm">Failed to load session: {String(session.error)}</p>;
  }

  const s = session.data;
  const running = !["completed", "failed"].includes(s.status);
  const ranked = s.results.filter((r) => r.rank != null);
  const others = s.results.filter((r) => r.rank == null && r.stage !== "semantic");

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 space-y-6">
        <div className="space-y-3 border-b border-border pb-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="page-eyebrow">Research session</span>
            <Badge variant={s.status === "completed" ? "secondary" : "outline"} className="capitalize">
              {s.status}
            </Badge>
            <Badge variant="outline">
              {s.market === "IN" ? "India · NSE main board" : "United States · NYSE 100"}
            </Badge>
          </div>
          <h1 className="max-w-4xl text-2xl font-semibold leading-tight tracking-[-0.035em] sm:text-3xl">
            {s.original_query}
          </h1>
          <p className="text-xs text-muted-foreground">
            {s.mode === "quick" ? "Quick" : "Standard"} search · {s.market === "IN" ? "NSE" : "NYSE"} universe · started{" "}
            {new Date(s.created_at).toLocaleString()}
          </p>
        </div>

        {s.search_plan && (
          <Card className="gap-3">
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <div>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <SlidersHorizontal className="size-4 text-muted-foreground" />
                  Interpreted conditions
                </CardTitle>
                <CardDescription className="mt-1">
                  Semantic concepts and exact financial constraints extracted from your query.
                </CardDescription>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="gap-1"
                onClick={() => setEditOpen((v) => !v)}
              >
                <Pencil className="size-3.5" /> Modify
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              <PlanChips plan={s.search_plan} />
              {editOpen && (
                <form
                  className="flex gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (instruction.trim()) modify.mutate(instruction.trim());
                  }}
                >
                  <Input
                    value={instruction}
                    onChange={(e) => setInstruction(e.target.value)}
                    placeholder='e.g. "Increase the market-cap tolerance to 70%"'
                  />
                  <Button type="submit" disabled={modify.isPending}>
                    {modify.isPending && <Loader2 className="size-4 animate-spin" />}
                    Apply & rerun
                  </Button>
                </form>
              )}
              {modify.isError && (
                <p className="text-xs text-destructive">{String(modify.error)}</p>
              )}
            </CardContent>
          </Card>
        )}

        {(running || live || events.length > 0) && (
          <Card className="gap-3">
            <CardHeader>
              <CardTitle className="text-sm">Research progress</CardTitle>
            </CardHeader>
            <CardContent>
              <ProgressTimeline events={events} status={s.status} />
            </CardContent>
          </Card>
        )}

        {s.error && (
          <Card className="border-destructive">
            <CardContent className="text-sm text-destructive py-3">
              Search failed: {s.error}
            </CardContent>
          </Card>
        )}

        {s.funnel && (
          <Card className="gap-2">
            <CardHeader>
              <CardTitle className="text-sm">Candidate funnel</CardTitle>
            </CardHeader>
            <CardContent>
              <FunnelPanel funnel={s.funnel} />
            </CardContent>
          </Card>
        )}

        <Tabs defaultValue="results" className="gap-4">
          <TabsList variant="line" className="w-full justify-start border-b border-border/75 pb-0">
            <TabsTrigger value="results">
              Results {ranked.length > 0 && `(${ranked.length})`}
            </TabsTrigger>
            <TabsTrigger value="comparison">Comparison</TabsTrigger>
            <TabsTrigger value="others">
              Not qualified {others.length > 0 && `(${others.length})`}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="results" className="space-y-4 pt-1">
            {ranked.length === 0 && !running && (
              <p className="text-sm text-muted-foreground">
                No companies fully qualified for every required condition. Check the
                &ldquo;Not qualified&rdquo; tab for near misses and their limitations, or relax a
                condition via Modify.
              </p>
            )}
            {ranked.length === 0 && running && (
              <p className="text-sm text-muted-foreground flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" /> Research in progress…
              </p>
            )}
            {ranked.map((r) => (
              <ResultCard key={r.company_id} result={r} />
            ))}
          </TabsContent>
          <TabsContent value="comparison" className="pt-1">
            <Card>
              <CardContent>
                <ComparisonTable results={s.results} />
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="others" className="space-y-4 pt-1">
            {others.length === 0 && (
              <p className="text-sm text-muted-foreground">Every researched candidate qualified.</p>
            )}
            {others.map((r) => (
              <ResultCard key={r.company_id} result={r} />
            ))}
          </TabsContent>
        </Tabs>
      </div>

      <aside className="flex min-h-[520px] flex-col lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)]">
        <Card className="min-h-0 flex-1 gap-0 overflow-hidden border-foreground/15">
          <CardHeader className="border-b border-border/70 py-4">
            <CardTitle className="flex items-center gap-2 text-sm">
              <MessageSquareText className="size-4 text-primary" />
              Research assistant
            </CardTitle>
            <CardDescription>
              Ask about rankings, change filters, or investigate current events.
            </CardDescription>
          </CardHeader>
          <CardContent className="min-h-0 flex-1 py-4">
            <ChatPanel searchId={id} />
          </CardContent>
        </Card>
      </aside>
    </div>
  );
}
