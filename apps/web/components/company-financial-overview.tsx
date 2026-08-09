"use client";

import type { CompanyAnalysis, FinancialOverview } from "@/lib/api";
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
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  CircleAlert,
  ExternalLink,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type CompanyCardEvidence = {
  id: string;
  source_url: string;
  source_section: string;
  filing_date: string;
};

type Frequency = "annual" | "quarterly";

function formatMoney(
  value?: number | null,
  compact = false,
  currency = "USD"
): string {
  if (value == null) return "Not available";
  const sign = value < 0 ? "−" : "";
  const amount = Math.abs(value);
  if (currency === "INR") {
    const crore = amount / 10_000_000;
    if (compact) {
      if (crore >= 100_000) return `${sign}₹${(crore / 100_000).toFixed(1)}L Cr`;
      return `${sign}₹${crore.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr`;
    }
    return `${sign}₹${amount.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  }
  if (compact) {
    if (amount >= 1e12) return `${sign}$${(amount / 1e12).toFixed(1)}T`;
    if (amount >= 1e9) return `${sign}$${(amount / 1e9).toFixed(1)}B`;
    if (amount >= 1e6) return `${sign}$${(amount / 1e6).toFixed(0)}M`;
  }
  return `${sign}$${amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatPercent(value?: number | null): string {
  if (value == null) return "Not available";
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function EvidenceLinks({
  ids,
  cards,
}: {
  ids: string[];
  cards: CompanyCardEvidence[];
}) {
  const evidence = ids
    .map((id) => cards.find((card) => card.id === id))
    .filter((card): card is CompanyCardEvidence => Boolean(card));
  if (!evidence.length) return null;
  return (
    <div className="flex flex-wrap gap-2 pt-1">
      {evidence.slice(0, 3).map((card, index) => (
        <a
          key={card.id}
          href={card.source_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 hover:text-emerald-900 hover:underline dark:text-emerald-400 dark:hover:text-emerald-300"
        >
          Filing evidence {index + 1}
          <ExternalLink className="size-3" />
        </a>
      ))}
    </div>
  );
}

function AnalysisColumn({
  title,
  tone,
  points,
  cards,
}: {
  title: string;
  tone: "strength" | "weakness";
  points: CompanyAnalysis["strengths"];
  cards: CompanyCardEvidence[];
}) {
  const isStrength = tone === "strength";
  return (
    <Card
      className={
        isStrength
          ? "border-emerald-200/80 bg-emerald-50/20 dark:border-emerald-900 dark:bg-emerald-950/15"
          : "border-amber-200/80 bg-amber-50/20 dark:border-amber-900 dark:bg-amber-950/15"
      }
    >
      <CardHeader className="gap-1">
        <div className="flex items-center gap-2">
          {isStrength ? (
            <ShieldCheck className="size-4 text-emerald-600" />
          ) : (
            <CircleAlert className="size-4 text-amber-600" />
          )}
          <CardTitle className="text-base">{title}</CardTitle>
        </div>
        <CardDescription>
          Grounded in verified company cards, not market sentiment.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {points.length === 0 && (
          <p className="text-sm text-muted-foreground">
            The available evidence was not sufficient to support a specific {title.toLowerCase()}.
          </p>
        )}
        {points.map((point) => (
          <div key={`${title}-${point.title}`} className="space-y-1.5 border-b pb-3 last:border-0 last:pb-0">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-medium">{point.title}</p>
              <Badge variant="outline" className="capitalize">
                {point.confidence}
              </Badge>
            </div>
            <p className="text-sm leading-6 text-muted-foreground">{point.explanation}</p>
            <EvidenceLinks ids={point.evidence_card_ids} cards={cards} />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export function CompanyFinancialOverview({
  ticker,
  cards,
}: {
  ticker: string;
  cards: CompanyCardEvidence[];
}) {
  const [frequency, setFrequency] = useState<Frequency>("annual");
  const overview = useQuery({
    queryKey: ["company-financial-overview", ticker],
    queryFn: () => api.getCompanyFinancialOverview(ticker),
    staleTime: 5 * 60 * 1000,
  });
  const analysis = useQuery({
    queryKey: ["company-analysis", ticker],
    queryFn: () => api.getCompanyAnalysis(ticker),
    staleTime: Number.POSITIVE_INFINITY,
  });

  const chartData = useMemo(() => {
    const points = frequency === "annual" ? overview.data?.annual : overview.data?.quarterly;
    return (points ?? []).map((point) => ({
      ...point,
      label: point.period.replace(" ended ", "\n"),
    }));
  }, [frequency, overview.data]);

  if (overview.isLoading) {
    return (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  if (overview.isError || !overview.data) {
    return (
      <Card>
        <CardContent className="py-8 text-sm text-destructive">
          Financial history could not be loaded.
        </CardContent>
      </Card>
    );
  }

  const data: FinancialOverview = overview.data;
  const headline = data.headline;

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["Latest revenue", formatMoney(headline?.revenue, true, data.currency), headline?.period],
          ["Net income", formatMoney(headline?.net_income, true, data.currency), headline?.period],
          ["Net margin", headline?.net_margin_percent == null ? "Not available" : `${headline.net_margin_percent.toFixed(1)}%`, headline?.period],
          ["Revenue YoY", formatPercent(headline?.revenue_yoy_percent), headline?.period],
        ].map(([label, value, period]) => (
          <Card key={label} className="gap-1 py-5">
            <CardHeader className="py-0">
              <CardDescription className="text-[11px] font-semibold uppercase tracking-[0.09em]">
                {label}
              </CardDescription>
              <CardTitle className="mt-1 text-2xl tracking-[-0.04em] tabular-nums">
                {value}
              </CardTitle>
            </CardHeader>
            <CardContent className="py-0 text-xs text-muted-foreground">{period}</CardContent>
          </Card>
        ))}
      </div>

      <Card className="gap-4">
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <span className="grid size-8 place-items-center rounded-md bg-secondary text-secondary-foreground">
                <Activity className="size-4" />
              </span>
              Revenue and profit history
            </CardTitle>
            <CardDescription>
              Reported revenue and net income. Hover over a period for exact values.
            </CardDescription>
          </div>
          <div className="flex gap-1 rounded-xl bg-muted p-1">
            <Button
              size="sm"
              variant={frequency === "annual" ? "default" : "ghost"}
              onClick={() => setFrequency("annual")}
            >
              Annual
            </Button>
            <Button
              size="sm"
              variant={frequency === "quarterly" ? "default" : "ghost"}
              onClick={() => setFrequency("quarterly")}
            >
              Quarterly
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {chartData.length === 0 ? (
            <div className="grid h-80 place-items-center text-sm text-muted-foreground">
              No comparable {frequency} facts are available.
            </div>
          ) : (
            <div className="h-[360px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ left: 8, right: 12, top: 8, bottom: 8 }}>
                  <defs>
                    <linearGradient id={`revenue-${ticker}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--chart-2)" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="var(--chart-2)" stopOpacity={0.03} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.35} />
                  <XAxis
                    dataKey="period"
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={20}
                  />
                  <YAxis
                    tickFormatter={(value) => formatMoney(Number(value), true, data.currency)}
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    width={62}
                  />
                  <Tooltip
                    formatter={(value, name) => [
                      formatMoney(Number(value), true, data.currency),
                      name === "revenue" ? "Revenue" : "Net income",
                    ]}
                    labelFormatter={(label) => String(label)}
                  />
                  <Legend
                    formatter={(value) => (value === "revenue" ? "Revenue" : "Net income")}
                  />
                  <Area
                    type="monotone"
                    dataKey="revenue"
                    stroke="var(--chart-2)"
                    strokeWidth={2}
                    fill={`url(#revenue-${ticker})`}
                    connectNulls
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="net_income"
                    stroke="var(--chart-1)"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    connectNulls
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>Profit means reported net income; percentages are calculated deterministically.</span>
            <a
              href={data.source_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-emerald-700 hover:underline dark:text-emerald-400"
            >
              Financial data source <ExternalLink className="size-3" />
            </a>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-3">
        <div>
          <p className="page-eyebrow mb-2">Evidence-grounded analysis</p>
          <h2 className="flex items-center gap-2 text-xl font-semibold tracking-[-0.025em]">
            <Sparkles className="size-4 text-emerald-700 dark:text-emerald-400" />
            AI business assessment
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Llama evaluates only the verified evidence available in this project.
          </p>
        </div>

        {analysis.isLoading && (
          <div className="grid gap-4 md:grid-cols-2">
            <Skeleton className="h-64" />
            <Skeleton className="h-64" />
          </div>
        )}
        {analysis.isError && (
          <Card>
            <CardContent className="py-6 text-sm text-destructive">
              The AI assessment could not be generated. The financial chart remains available.
            </CardContent>
          </Card>
        )}
        {analysis.data && (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              <AnalysisColumn
                title="Potential strengths"
                tone="strength"
                points={analysis.data.strengths}
                cards={cards}
              />
              <AnalysisColumn
                title="Potential weaknesses"
                tone="weakness"
                points={analysis.data.weaknesses}
                cards={cards}
              />
            </div>

            <Card className="gap-4">
              <CardHeader className="gap-1">
                <CardTitle className="text-base">What may explain the revenue movements?</CardTitle>
                <CardDescription>
                  Confirmed catalysts are separated from contextual explanations and unsupported guesses.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {analysis.data.revenue_explanations.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    No comparable revenue movements were available for analysis.
                  </p>
                )}
                {analysis.data.revenue_explanations.map((item) => {
                  const increased = item.change_percent >= 0;
                  return (
                    <div
                      key={item.movement_id}
                      className="grid gap-3 border-b pb-4 last:border-0 last:pb-0 md:grid-cols-[150px_1fr]"
                    >
                      <div>
                        <p className="text-sm font-medium">{item.period}</p>
                        <p
                          className={`mt-1 flex items-center gap-1 text-lg font-semibold tabular-nums ${
                            increased ? "text-emerald-600" : "text-red-600"
                          }`}
                        >
                          {increased ? (
                            <ArrowUpRight className="size-4" />
                          ) : (
                            <ArrowDownRight className="size-4" />
                          )}
                          {formatPercent(item.change_percent)}
                        </p>
                      </div>
                      <div className="space-y-1.5">
                        <div className="flex flex-wrap gap-2">
                          <Badge variant="outline" className="capitalize">
                            {item.driver_type.replace(/_/g, " ")}
                          </Badge>
                          <Badge variant="outline" className="capitalize">
                            {item.confidence} confidence
                          </Badge>
                        </div>
                        <p className="text-sm leading-6 text-muted-foreground">
                          {item.explanation}
                        </p>
                        <EvidenceLinks ids={item.evidence_card_ids} cards={cards} />
                        <div className="flex flex-wrap gap-2 pt-1">
                          {item.evidence_ids.map((evidenceId) => {
                            const evidence = analysis.data.revenue_evidence.find(
                              (candidate) => candidate.id === evidenceId
                            );
                            if (!evidence) return null;
                            return (
                              <a
                                key={evidence.id}
                                href={evidence.url}
                                target="_blank"
                                rel="noreferrer"
                                title={evidence.excerpt}
                                className="inline-flex items-center gap-1 text-xs text-emerald-700 hover:underline dark:text-emerald-400"
                              >
                                {evidence.description}
                                <ExternalLink className="size-3" />
                              </a>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  );
                })}
                <p className="text-xs text-muted-foreground">
                  Generated by {analysis.data.model_name}
                  {analysis.data.cached ? " · cached for this filing version" : ""}
                  {" · "}
                  {new Date(analysis.data.generated_at).toLocaleString()}
                </p>
              </CardContent>
            </Card>
          </>
        )}
      </div>

      {data.limitations.length > 0 && (
        <p className="text-xs text-muted-foreground">{data.limitations.join(" ")}</p>
      )}
    </div>
  );
}
