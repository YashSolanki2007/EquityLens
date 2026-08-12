"use client";

import { Boxes, CircleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { PairPortfolioBuilder } from "@/components/pair-portfolio-builder";
import { Badge } from "@/components/ui/badge";

const P_VALUE_OPTIONS = [
  "0.0001",
  "0.0005",
  "0.001",
  "0.0025",
  "0.005",
  "0.01",
  "0.025",
  "0.05",
];

function usePaperPortfolioId() {
  const [portfolioId, setPortfolioId] = useState<string>();
  useEffect(() => {
    const storageKey = "easy-invest-paper-portfolio-id";
    const existing = window.localStorage.getItem(storageKey);
    const resolved = existing ?? window.crypto.randomUUID();
    if (!existing) window.localStorage.setItem(storageKey, resolved);
    const frame = window.requestAnimationFrame(() => setPortfolioId(resolved));
    return () => window.cancelAnimationFrame(frame);
  }, []);
  return portfolioId;
}

export function PairPortfolioView() {
  const portfolioId = usePaperPortfolioId();
  const [pValueThreshold, setPValueThreshold] = useState(0.001);

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-5 border-b border-border pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <p className="page-eyebrow flex items-center gap-2">
            <Boxes className="size-3.5" /> Portfolio construction
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] sm:text-[2.5rem]">
            Pair portfolio
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            Turn active pair signals into one paper portfolio while limiting company
            overlap and dependence between the selected long/short return streams.
          </p>
        </div>
        <div className="flex flex-col items-start gap-3 lg:items-end">
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">Paper portfolio</Badge>
            <Badge variant="outline">Stock-price tracking</Badge>
            <Badge variant="outline">Up to six pairs</Badge>
          </div>
          <label className="space-y-1.5">
            <span className="terminal-label block">Cointegration p-value cutoff</span>
            <select
              value={String(pValueThreshold)}
              onChange={(event) => setPValueThreshold(Number(event.target.value))}
              className="h-9 min-w-48 rounded-md border border-input bg-card px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              aria-label="Portfolio cointegration p-value cutoff"
            >
              {P_VALUE_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value}
                  {value === "0.001" ? " · default" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      {pValueThreshold > 0.001 && (
        <section className="flex items-start gap-3 rounded-lg border border-amber-600/30 bg-amber-500/[0.08] p-4">
          <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" />
          <div>
            <p className="text-sm font-semibold">Exploratory statistical cutoff</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              A looser cutoff may supply more diversification candidates, but it also
              admits weaker pair relationships. Review the saved q-values before relying
              on the result.
            </p>
          </div>
        </section>
      )}

      <PairPortfolioBuilder
        ownerPortfolioId={portfolioId}
        pValueThreshold={pValueThreshold}
      />
    </div>
  );
}
