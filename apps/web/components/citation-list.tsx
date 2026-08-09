"use client";

import type { Citation } from "@/lib/api";
import { ExternalLink } from "lucide-react";

export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <ul className="space-y-2">
      {citations.map((c, i) => (
        <li key={i} className="space-y-1.5 rounded-md border border-border/80 bg-muted/25 p-3 text-xs">
          <div className="flex items-center gap-2">
            <span className="font-medium uppercase text-[10px] tracking-wide text-muted-foreground">
              {c.source_type.replace("_", " ")}
            </span>
            {c.filing_date && (
              <span className="text-muted-foreground">{c.filing_date}</span>
            )}
            {c.url && (
              <a
                href={c.url}
                target="_blank"
                rel="noreferrer"
                className="ml-auto inline-flex items-center gap-1 font-medium text-emerald-700 hover:text-emerald-900 hover:underline dark:text-emerald-400 dark:hover:text-emerald-300"
              >
                source <ExternalLink className="size-3" />
              </a>
            )}
          </div>
          {c.description && <p>{c.description}</p>}
          {c.excerpt && (
            <blockquote className="line-clamp-4 border-l-2 border-emerald-200 pl-2 leading-5 text-muted-foreground dark:border-emerald-800">
              {c.excerpt}
            </blockquote>
          )}
        </li>
      ))}
    </ul>
  );
}
