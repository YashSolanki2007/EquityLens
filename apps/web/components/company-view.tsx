"use client";

import { api, formatMarketCap } from "@/lib/api";
import { useLiveQuotes } from "@/lib/use-live-quotes";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CompanyFinancialOverview } from "@/components/company-financial-overview";
import { CompanyFinancialStatements } from "@/components/company-financial-statements";
import { CompanyChat } from "@/components/company-chat";
import { CompanyOutlook } from "@/components/company-outlook";
import { CompanyPeerComparison } from "@/components/company-peer-comparison";
import { PriceForecastWorkspace } from "@/components/price-forecast-workspace";
import {
  IVPredictionWorkspace,
  OptionsChainWorkspace,
  StockMarketWorkspace,
} from "@/components/stock-market-workspace";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Building2, ExternalLink } from "lucide-react";
import Link from "next/link";

type CompanyDetail = {
  company: {
    ticker: string;
    name: string;
    cik?: string | null;
    isin?: string | null;
    country: string;
    reporting_currency: string;
    sector: string;
    industry: string;
    exchange: string;
  };
  market_snapshot: {
    price?: number | null;
    market_cap_usd?: number | null;
    market_cap_native?: number | null;
    currency?: string | null;
    summary?: string | null;
    retrieved_at: string;
    source: string;
    is_delayed_or_unverified: boolean;
  } | null;
  card_count: number;
  financial_facts: {
    concept: string;
    unit: string;
    value: number;
    end_date: string;
    fiscal_year?: number | null;
    fiscal_period?: string | null;
    form?: string | null;
    start_date?: string | null;
  }[];
};

type CompanyCard = {
  id: string;
  card_type: string;
  text: string;
  directness: string;
  materiality: string;
  source_url: string;
  source_section: string;
  source_excerpt: string;
  filing_date: string;
  confidence: number;
};

type Filing = {
  id: string;
  accession_number: string;
  form: string;
  filing_date: string;
  primary_doc_url?: string | null;
  description?: string | null;
};

export function CompanyView({ ticker }: { ticker: string }) {
  const detail = useQuery({
    queryKey: ["company", ticker],
    queryFn: () => api.getCompany(ticker) as Promise<CompanyDetail>,
  });
  const cards = useQuery({
    queryKey: ["company-cards", ticker],
    queryFn: () => api.getCompanyCards(ticker) as Promise<CompanyCard[]>,
  });
  const filings = useQuery({
    queryKey: ["company-filings", ticker],
    queryFn: () => api.getCompanyFilings(ticker) as Promise<Filing[]>,
  });
  const isIndia = detail.data?.company.country === "IN";
  const liveQuotes = useLiveQuotes([ticker], isIndia);
  const liveQuote = liveQuotes[ticker];

  if (detail.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-1/2" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (detail.isError || !detail.data) {
    return <p className="text-sm text-destructive">Company not found.</p>;
  }
  const d = detail.data;

  const byType = (cards.data ?? []).reduce<Record<string, CompanyCard[]>>((acc, c) => {
    (acc[c.card_type] ??= []).push(c);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <Link
        href="/discover"
        className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        Back to discovery
      </Link>

      <section className="overflow-hidden rounded-md border border-border bg-card shadow-[0_1px_2px_rgba(15,23,42,0.035)]">
        <div className="grid gap-6 p-5 lg:grid-cols-[1fr_auto]">
          <div className="flex min-w-0 items-start gap-4">
            <span className="grid size-11 shrink-0 place-items-center rounded-md bg-[#17315f] font-mono text-xs font-semibold text-white dark:bg-primary dark:text-primary-foreground">
              {d.company.ticker.slice(0, 3)}
            </span>
            <div className="min-w-0">
              <p className="page-eyebrow">Company profile</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-[-0.035em] sm:text-[1.75rem]">
                {d.company.name}
              </h1>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{d.company.ticker}</Badge>
                <Badge variant="outline">{d.company.exchange}</Badge>
                <span className="text-xs text-muted-foreground">{d.company.sector}</span>
                <span className="text-xs text-muted-foreground">·</span>
                <span className="text-xs text-muted-foreground">{d.company.industry}</span>
              </div>
              {d.market_snapshot?.summary && (
                <p className="mt-3 line-clamp-4 max-w-3xl text-[13px] leading-6 text-muted-foreground">
                  {d.market_snapshot.summary}
                </p>
              )}
            </div>
          </div>

          <div className="grid min-w-[280px] grid-cols-3 gap-px overflow-hidden rounded-md border border-border bg-border lg:self-start">
            {[
              [
                "Market cap",
                formatMarketCap(
                  d.market_snapshot?.market_cap_usd,
                  d.market_snapshot?.currency,
                  d.market_snapshot?.market_cap_native
                ),
              ],
              [
                liveQuote ? "Live price" : "Last price",
                liveQuote || d.market_snapshot?.price != null
                  ? `${(d.market_snapshot?.currency ?? d.company.reporting_currency) === "INR" ? "₹" : "$"}${(liveQuote?.price ?? d.market_snapshot?.price ?? 0).toFixed(2)}`
                  : "n/a",
              ],
              ["Evidence", `${d.card_count} cards`],
            ].map(([label, value]) => (
              <div key={label} className="bg-muted/25 px-3 py-3.5 text-left">
                <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  {label}
                </p>
                <p className="mt-1.5 font-mono text-sm font-semibold tabular-nums">{value}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border bg-muted/45 px-5 py-2.5 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <Building2 className="size-3.5" />
            {d.company.country === "IN"
              ? `ISIN ${d.company.isin ?? "not available"}`
              : `CIK ${d.company.cik}`}
          </span>
          {d.market_snapshot && (
            <>
              <span>
                {liveQuote ? "Yahoo WebSocket · live quote" : `${d.market_snapshot.source} · delayed/unverified`}
              </span>
              <span>
                {liveQuote
                  ? `Exchange time ${new Date(liveQuote.event_time).toLocaleString()}`
                  : `Retrieved ${new Date(d.market_snapshot.retrieved_at).toLocaleString()}`}
              </span>
            </>
          )}
        </div>
      </section>

      <CompanyOutlook ticker={ticker} />

      <Tabs defaultValue={d.company.country === "IN" ? "market" : "overview"}>
        <TabsList
          variant="line"
          className="max-w-full justify-start overflow-x-auto border-b border-border/80"
        >
          {d.company.country === "IN" && (
            <TabsTrigger value="market">Market & valuation</TabsTrigger>
          )}
          {d.company.country === "IN" && (
            <TabsTrigger value="options">Options chain</TabsTrigger>
          )}
          {d.company.country === "IN" && (
            <TabsTrigger value="iv-prediction">IV prediction</TabsTrigger>
          )}
          {d.company.country === "IN" && (
            <TabsTrigger value="peers">Peer comparison</TabsTrigger>
          )}
          <TabsTrigger value="forecast">Price scenarios</TabsTrigger>
          <TabsTrigger value="overview">Financial overview</TabsTrigger>
          {d.company.country === "IN" && (
            <TabsTrigger value="statements">Financial statements</TabsTrigger>
          )}
          <TabsTrigger value="cards">Semantic cards ({d.card_count})</TabsTrigger>
          <TabsTrigger value="filings">
            {d.company.country === "IN" ? "NSE filings" : "SEC filings"}
          </TabsTrigger>
          <TabsTrigger value="facts">Financial facts</TabsTrigger>
        </TabsList>

        {d.company.country === "IN" && (
          <TabsContent value="market" className="pt-4">
            <StockMarketWorkspace
              ticker={ticker}
              livePrice={liveQuote?.price}
              liveEventTime={liveQuote?.event_time}
            />
          </TabsContent>
        )}

        {d.company.country === "IN" && (
          <TabsContent value="options" className="pt-4">
            <OptionsChainWorkspace ticker={ticker} />
          </TabsContent>
        )}

        {d.company.country === "IN" && (
          <TabsContent value="iv-prediction" className="pt-4">
            <IVPredictionWorkspace ticker={ticker} />
          </TabsContent>
        )}

        {d.company.country === "IN" && (
          <TabsContent value="peers" className="pt-4">
            <CompanyPeerComparison ticker={ticker} />
          </TabsContent>
        )}

        <TabsContent value="forecast" className="pt-4">
          <PriceForecastWorkspace ticker={ticker} />
        </TabsContent>

        <TabsContent value="overview" className="pt-4">
          <CompanyFinancialOverview ticker={ticker} cards={cards.data ?? []} />
        </TabsContent>

        {d.company.country === "IN" && (
          <TabsContent value="statements" className="pt-4">
            <CompanyFinancialStatements ticker={ticker} />
          </TabsContent>
        )}

        <TabsContent value="cards" className="space-y-4 pt-4">
          {cards.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No cards generated yet. Run the card pipeline for this ticker.
            </p>
          )}
          {Object.entries(byType).map(([type, list]) => (
            <Card key={type} className="gap-3">
              <CardHeader>
                <CardTitle className="text-sm capitalize">
                  {type.replace(/_/g, " ")} ({list.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {list.map((c) => (
                  <div key={c.id} className="space-y-2 rounded-md border border-border/80 bg-muted/20 p-4 text-sm">
                    <p className="leading-6">{c.text}</p>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <Badge variant="outline" className="capitalize">{c.directness}</Badge>
                      <Badge variant="outline" className="capitalize">{c.materiality}</Badge>
                      <span>confidence {c.confidence.toFixed(2)}</span>
                      <span>{c.source_section}</span>
                      <a
                        href={c.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="ml-auto inline-flex items-center gap-1 text-emerald-700 hover:underline dark:text-emerald-400"
                      >
                        {d.company.country === "IN" ? "Annual report" : "10-K"}{" "}
                        {c.filing_date} <ExternalLink className="size-3" />
                      </a>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="filings" className="pt-4">
          <div className="overflow-hidden rounded-lg border bg-card">
            <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Form</th>
                  <th>Filed</th>
                  <th>Description</th>
                  <th>Link</th>
                </tr>
              </thead>
              <tbody>
                {(filings.data ?? []).map((f) => (
                  <tr key={f.id} className="border-b last:border-0">
                    <td className="font-medium">{f.form}</td>
                    <td>{f.filing_date}</td>
                    <td className="text-muted-foreground">
                      {f.description ?? "–"}
                    </td>
                    <td>
                      {f.primary_doc_url && (
                        <a
                          href={f.primary_doc_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-emerald-700 hover:underline dark:text-emerald-400"
                        >
                          view <ExternalLink className="size-3" />
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="facts" className="pt-4">
          <div className="overflow-hidden rounded-lg border bg-card">
            <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Concept</th>
                  <th>Period</th>
                  <th>Fiscal</th>
                  <th>Form</th>
                  <th className="text-right">
                    Value ({d.company.reporting_currency})
                  </th>
                </tr>
              </thead>
              <tbody>
                {(d.financial_facts ?? []).map((f, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td>{f.concept.replace("us-gaap:", "")}</td>
                    <td>
                      {f.start_date ? `${f.start_date} → ` : ""}
                      {f.end_date}
                    </td>
                    <td>
                      {f.fiscal_period ?? ""} {f.fiscal_year ?? ""}
                    </td>
                    <td>{f.form ?? ""}</td>
                    <td className="text-right font-mono">
                      {f.value.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            {d.company.country === "IN"
              ? "Cached from normalized exchange-market financial statements (delayed development data)."
              : "Cached from SEC Company Facts XBRL data (primary source)."}
          </p>
        </TabsContent>

      </Tabs>

      <CompanyChat ticker={ticker} companyName={d.company.name} />
    </div>
  );
}
