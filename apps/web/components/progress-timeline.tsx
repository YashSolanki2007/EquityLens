"use client";

import type { ProgressEvent } from "@/lib/api";
import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";

const STAGES: [string, string][] = [
  ["planning_query", "Planning query"],
  ["retrieving_semantic_candidates", "Semantic retrieval"],
  ["applying_base_filters", "Base filters"],
  ["validating_financials", "Research & financial verification"],
  ["ranking_results", "Ranking"],
  ["completed", "Completed"],
];

export function ProgressTimeline({
  events,
  status,
}: {
  events: ProgressEvent[];
  status: string;
}) {
  const seen = new Set(events.map((e) => e.stage));
  const failed = seen.has("failed") || status === "failed";
  const done = seen.has("completed") || status === "completed";
  const researching = events.filter(
    (e) => e.stage === "researching_candidate" && !e.done
  );
  const currentIdx = STAGES.findIndex(([key]) => !seen.has(key));

  return (
    <div className="space-y-1.5">
      <ol className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
        {STAGES.map(([key, label], i) => {
          const isDone = seen.has(key) && (key !== "completed" || done);
          const isActive = !done && !failed && i === currentIdx;
          return (
            <li key={key} className="flex items-center gap-1.5">
              {failed && isActive ? (
                <XCircle className="size-4 text-destructive" />
              ) : isDone ? (
                <CheckCircle2 className="size-4 text-green-600" />
              ) : isActive ? (
                <Loader2 className="size-4 animate-spin text-muted-foreground" />
              ) : (
                <Circle className="size-4 text-muted-foreground/40" />
              )}
              <span className={isDone ? "font-medium" : "text-muted-foreground"}>{label}</span>
            </li>
          );
        })}
      </ol>
      {researching.length > 0 && !done && (
        <p className="text-xs text-muted-foreground">
          Researching: {researching.map((e) => String(e.ticker)).join(", ")}
        </p>
      )}
    </div>
  );
}
