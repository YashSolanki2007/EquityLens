"use client";

import {
  API_BASE,
  api,
  type FinancialStatementRow,
  type FinancialStatements,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Banknote,
  Download,
  ExternalLink,
  FileDown,
  FileSpreadsheet,
  Landmark,
  ReceiptText,
  Table2,
} from "lucide-react";
import { useMemo, useState } from "react";

type StatementType = "income" | "balance_sheet" | "cash_flow";
type Frequency = "annual" | "quarterly";

const STATEMENT_OPTIONS: {
  value: StatementType;
  label: string;
  icon: typeof ReceiptText;
}[] = [
  { value: "income", label: "Income statement", icon: ReceiptText },
  { value: "balance_sheet", label: "Balance sheet", icon: Landmark },
  { value: "cash_flow", label: "Cash flow", icon: Banknote },
];

function displayScale(currency: string) {
  return currency === "INR"
    ? { divisor: 10_000_000, label: "₹ crore" }
    : { divisor: 1_000_000, label: `${currency} millions` };
}

function unitLabel(row: FinancialStatementRow, currency: string) {
  if (row.value_type === "percent") return "%";
  if (row.value_type === "per_share") {
    return currency === "INR" ? "₹ / share" : `${currency} / share`;
  }
  if (row.value_type === "shares") return "shares";
  return displayScale(currency).label;
}

function formatNumber(value: number, maximumFractionDigits = 2) {
  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 0,
    maximumFractionDigits,
  }).format(value);
}

function formatStatementValue(
  value: number | null | undefined,
  row: FinancialStatementRow,
  currency: string
) {
  if (value == null || !Number.isFinite(value)) return "—";
  if (row.value_type === "percent") {
    return `${formatNumber(value * 100, 1)}%`;
  }
  if (row.value_type === "shares") {
    return new Intl.NumberFormat("en-IN", {
      notation: "compact",
      maximumFractionDigits: 2,
    }).format(value);
  }
  const scaled =
    row.value_type === "currency"
      ? value / displayScale(currency).divisor
      : value;
  const formatted = formatNumber(Math.abs(scaled), 2);
  const prefix =
    row.value_type === "per_share" ? (currency === "INR" ? "₹" : `${currency} `) : "";
  return scaled < 0 ? `(${prefix}${formatted})` : `${prefix}${formatted}`;
}

function exportUrl(
  ticker: string,
  format: "csv" | "xlsx",
  statementType: StatementType,
  frequency: Frequency
) {
  const params = new URLSearchParams({
    format,
    statement: statementType,
    frequency,
  });
  return `${API_BASE}/api/companies/${encodeURIComponent(
    ticker
  )}/financial-statements/export?${params.toString()}`;
}

export function CompanyFinancialStatements({ ticker }: { ticker: string }) {
  const [statementType, setStatementType] = useState<StatementType>("income");
  const [frequency, setFrequency] = useState<Frequency>("annual");
  const statements = useQuery({
    queryKey: ["company-financial-statements", ticker],
    queryFn: () => api.getCompanyFinancialStatements(ticker),
    staleTime: 30 * 60 * 1000,
  });

  const selectedStatement = useMemo(
    () =>
      statements.data?.statements.find(
        (statement) =>
          statement.statement_type === statementType &&
          statement.frequency === frequency
      ),
    [frequency, statementType, statements.data?.statements]
  );

  if (statements.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-[560px] w-full" />
      </div>
    );
  }

  if (statements.isError || !statements.data) {
    return (
      <Card>
        <CardContent className="py-10 text-center">
          <p className="text-sm font-medium">Financial statements are unavailable.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            The standardized statement source could not be loaded.
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-4"
            onClick={() => statements.refetch()}
          >
            Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  const data: FinancialStatements = statements.data;
  if (!data.available) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <FileSpreadsheet className="mx-auto size-7 text-muted-foreground" />
          <p className="mt-3 text-sm font-medium">
            No standardized statements are available for {ticker}.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Missing values are not estimated or filled by AI.
          </p>
        </CardContent>
      </Card>
    );
  }

  const rows = selectedStatement?.rows ?? [];
  const periods = selectedStatement?.periods ?? [];
  const currentPeriod = periods.at(-1);

  return (
    <div className="space-y-4">
      <section className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="flex flex-col gap-5 p-5 sm:p-6 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <p className="page-eyebrow">Analyst workspace</p>
            <h2 className="mt-1 flex items-center gap-2 text-xl font-semibold tracking-[-0.03em]">
              <Table2 className="size-5 text-emerald-700" />
              Full financial statements
            </h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Complete populated line items across historical annual and quarterly
              periods. Values stay numeric for analysis and export; blanks remain
              blanks.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <a
                href={exportUrl(ticker, "csv", statementType, frequency)}
                download
              >
                <FileDown className="size-3.5" />
                Export this CSV
              </a>
            </Button>
            <Button size="sm" asChild>
              <a
                href={exportUrl(ticker, "xlsx", statementType, frequency)}
                download
              >
                <Download className="size-3.5" />
                Export all to Excel
              </a>
            </Button>
          </div>
        </div>
        <div className="grid gap-px border-t border-border bg-border sm:grid-cols-3">
          <div className="bg-card px-5 py-3.5">
            <p className="terminal-label">Selected table</p>
            <p className="mt-1 text-sm font-semibold">
              {frequency === "annual" ? "Annual" : "Quarterly"}{" "}
              {selectedStatement?.title ?? "statement"}
            </p>
          </div>
          <div className="bg-card px-5 py-3.5">
            <p className="terminal-label">Coverage</p>
            <p className="mt-1 text-sm font-semibold tabular-nums">
              {rows.length} rows · {periods.length} periods
            </p>
          </div>
          <div className="bg-card px-5 py-3.5">
            <p className="terminal-label">Currency scale</p>
            <p className="mt-1 text-sm font-semibold">
              {displayScale(data.currency).label}
            </p>
          </div>
        </div>
      </section>

      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex max-w-full gap-1 overflow-x-auto rounded-md bg-muted/70 p-1">
          {STATEMENT_OPTIONS.map((option) => {
            const Icon = option.icon;
            return (
              <Button
                key={option.value}
                size="sm"
                variant={statementType === option.value ? "default" : "ghost"}
                onClick={() => setStatementType(option.value)}
              >
                <Icon className="size-3.5" />
                {option.label}
              </Button>
            );
          })}
        </div>
        <div className="flex gap-1 self-start rounded-md bg-muted/70 p-1 sm:self-auto">
          {(["annual", "quarterly"] as const).map((option) => (
            <Button
              key={option}
              size="sm"
              variant={frequency === option ? "default" : "ghost"}
              onClick={() => setFrequency(option)}
              className="capitalize"
            >
              {option}
            </Button>
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 bg-muted/25 px-4 py-3">
          <div>
            <p className="text-sm font-semibold">
              {frequency === "annual" ? "Annual" : "Quarterly"}{" "}
              {selectedStatement?.title}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Historical periods run left to right; the latest available period is
              highlighted.
            </p>
          </div>
          <Badge variant="outline">
            {currentPeriod
              ? `Latest ${new Date(`${currentPeriod}T00:00:00`).toLocaleDateString(
                  "en-IN",
                  { month: "short", year: "numeric" }
                )}`
              : "No periods"}
          </Badge>
        </div>

        {rows.length === 0 ? (
          <div className="py-14 text-center">
            <p className="text-sm font-medium">
              This statement frequency is unavailable.
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Try the other frequency or export the available statements.
            </p>
          </div>
        ) : (
          <div className="max-h-[720px] overflow-auto">
            <table className="data-table min-w-[820px]">
              <thead className="sticky top-0 z-20">
                <tr>
                  <th className="sticky left-0 z-30 min-w-[340px] bg-muted">
                    Line item
                  </th>
                  <th className="min-w-[110px]">Unit</th>
                  {periods.map((period) => (
                    <th
                      key={period}
                      className={cn(
                        "min-w-[145px] text-right",
                        period === currentPeriod && "bg-emerald-500/10 text-emerald-800"
                      )}
                    >
                      {new Date(`${period}T00:00:00`).toLocaleDateString("en-IN", {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                      })}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.key}
                    className={cn(
                      row.is_total &&
                        "border-t-2 border-border bg-muted/20 font-semibold"
                    )}
                  >
                    <td
                      className={cn(
                        "sticky left-0 z-10 bg-card",
                        row.is_total && "bg-[#f5f4ef] dark:bg-[#22211e]"
                      )}
                    >
                      {row.label}
                    </td>
                    <td className="font-mono text-[11px] text-muted-foreground">
                      {unitLabel(row, data.currency)}
                    </td>
                    {periods.map((period) => {
                      const value = row.values[period];
                      return (
                        <td
                          key={period}
                          className={cn(
                            "text-right font-mono text-xs tabular-nums",
                            value != null && value < 0 && "text-rose-700",
                            period === currentPeriod &&
                              "bg-emerald-500/6 dark:bg-emerald-500/5"
                          )}
                        >
                          {formatStatementValue(value, row, data.currency)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex flex-col gap-2 border-t border-border/70 bg-muted/25 px-4 py-3 text-[11px] leading-5 text-muted-foreground sm:flex-row sm:items-start sm:justify-between">
          <span>
            Standardized historical statements · delayed/unverified · no AI-filled
            values
          </span>
          <a
            href={data.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1 font-medium text-emerald-700 hover:underline dark:text-emerald-400"
          >
            {data.source}
            <ExternalLink className="size-3" />
          </a>
        </div>
      </div>

      <div className="rounded-lg border border-amber-200 bg-amber-50/55 px-4 py-3 text-xs leading-5 text-amber-950 dark:border-amber-900 dark:bg-amber-950/25 dark:text-amber-200">
        <div className="flex items-start gap-2">
          <ArrowUpRight className="mt-0.5 size-3.5 shrink-0" />
          <span>{data.limitations.join(" ")}</span>
        </div>
      </div>
    </div>
  );
}
