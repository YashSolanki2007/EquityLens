"use client";

import type { ResultCandidate } from "@/lib/api";
import { formatMarketCap } from "@/lib/api";
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export function ComparisonTable({ results }: { results: ResultCandidate[] }) {
  const ranked = results.filter((r) => r.rank != null);
  if (ranked.length < 2) {
    return (
      <p className="text-sm text-muted-foreground">
        At least two qualified companies are needed for comparison.
      </p>
    );
  }
  const conditionIds = Array.from(
    new Set(ranked.flatMap((r) => r.condition_results.map((c) => c.condition_id)))
  );
  const growthData = ranked
    .map((r) => {
      const rev = r.condition_results.find((c) =>
        c.condition_type?.includes("revenue")
      );
      return { ticker: r.ticker, growth: rev?.measured_value ?? null };
    })
    .filter((d) => d.growth != null);

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Match</th>
              <th>Market cap</th>
              <th>Semantic</th>
              {conditionIds.map((id) => (
                <th key={id}>
                  {id}
                </th>
              ))}
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((r) => (
              <tr key={r.ticker} className="border-b last:border-0">
                <td className="font-medium">
                  #{r.rank} {r.ticker}
                </td>
                <td>{r.match_percent}%</td>
                <td>
                  {formatMarketCap(
                    r.market_cap_usd,
                    r.currency,
                    r.market_cap_native
                  )}
                </td>
                <td>
                  {r.semantic_score != null ? r.semantic_score.toFixed(2) : "–"}
                </td>
                {conditionIds.map((id) => {
                  const c = r.condition_results.find((x) => x.condition_id === id);
                  return (
                    <td key={id}>
                      {c
                        ? `${c.status}${c.measured_value != null ? ` (${c.measured_value}%)` : ""}`
                        : "–"}
                    </td>
                  );
                })}
                <td>{r.overall_confidence ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {growthData.length > 0 && (
        <div className="h-52 border-t border-border/70 pt-4">
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            Verified latest-quarter revenue YoY growth (%)
          </p>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={growthData} margin={{ left: 0, right: 16 }}>
              <XAxis dataKey="ticker" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} width={36} />
              <Tooltip formatter={(v) => [`${v}%`, "revenue YoY"]} />
              <Bar dataKey="growth" fill="var(--chart-1)" radius={3} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
