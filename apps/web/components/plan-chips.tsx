"use client";

import type { SearchPlan } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { formatMarketCap } from "@/lib/api";

function structuredLabel(c: SearchPlan["base_structured_conditions"][number]): string {
  const value = Array.isArray(c.value) ? c.value.join("–") : c.value;
  if (c.field === "market_cap_usd" || c.field === "market_cap_native") {
    const fmt = (v: unknown) => {
      if (typeof v !== "number") return String(v);
      if (c.field === "market_cap_usd") return formatMarketCap(v);
      const crore = v / 10_000_000;
      if (crore >= 100_000) {
        return `₹${(crore / 100_000).toLocaleString("en-IN", {
          maximumFractionDigits: 2,
        })} lakh crore`;
      }
      return `₹${crore.toLocaleString("en-IN", {
        maximumFractionDigits: 0,
      })} crore`;
    };
    if (c.operator === "around")
      return `market cap ≈ ${fmt(c.value)} ±${c.tolerance_percent ?? 40}%`;
    if (c.operator === "between" && Array.isArray(c.value))
      return `market cap ${fmt(c.value[0])}–${fmt(c.value[1])}`;
    return `market cap ${c.operator} ${fmt(c.value)}`;
  }
  return `${c.field} ${c.operator} ${value}`;
}

function researchLabel(c: SearchPlan["research_conditions"][number]): string {
  if (c.type === "revenue_yoy_growth")
    return `revenue YoY ${c.operator} ${c.threshold}%`;
  if (c.type === "net_income_yoy_growth")
    return `net income YoY ${c.operator} ${c.threshold}%`;
  if (c.type === "recent_sec_catalyst")
    return `catalyst: ${c.question?.slice(0, 70) ?? "recent event"}${(c.question?.length ?? 0) > 70 ? "…" : ""}`;
  return `filing question: ${c.question?.slice(0, 70) ?? c.id}`;
}

export function PlanChips({ plan }: { plan: SearchPlan }) {
  return (
    <div className="flex flex-wrap gap-2">
      {plan.base_semantic_conditions.map((c) => (
        <Badge
          key={c.id}
          variant="secondary"
          className="whitespace-normal border border-emerald-100 bg-emerald-50 font-normal text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300"
          title={c.concept}
        >
          Business fit · {c.concept.slice(0, 80)}
          {c.concept.length > 80 ? "…" : ""}
          {c.directness_required !== "any" ? ` (${c.directness_required})` : ""}
          {c.required ? "" : " (optional)"}
        </Badge>
      ))}
      {plan.base_structured_conditions.map((c, i) => (
        <Badge key={`s${i}`} variant="outline" className="bg-card font-normal">
          {structuredLabel(c)}
        </Badge>
      ))}
      {plan.research_conditions.map((c) => (
        <Badge key={c.id} variant="outline" className="whitespace-normal border-dashed bg-card font-normal">
          {researchLabel(c)}
        </Badge>
      ))}
      {plan.exclusions.map((e) => (
        <Badge key={e} variant="destructive" className="font-normal">
          exclude: {e}
        </Badge>
      ))}
    </div>
  );
}
