"use client";

import { api, type PriceForecast } from "@/lib/api";
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
  ChartNoAxesCombined,
  ExternalLink,
  Sigma,
  Waves,
} from "lucide-react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useMemo, useState } from "react";

const HORIZONS = [5, 10, 15] as const;
const SIMULATION_COUNTS = [1000, 2500, 5000] as const;

type ForecastChartRow = {
  date: string;
  median: number;
  p10: number;
  p25: number;
  p75: number;
  p90: number;
  range80: [number, number];
  range50: [number, number];
  volatility: number;
  regression?: number;
  [key: `path_${number}`]: number;
};

function compactCurrency(value: number | null | undefined, currency: string) {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
    style: "currency",
    currency,
    notation: value >= 10_000 ? "compact" : "standard",
    maximumFractionDigits: value >= 100 ? 0 : 2,
  }).format(value);
}

function percent(value: number | null | undefined, probability = false) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(probability ? value * 100 : value).toFixed(1)}%`;
}

function shortDate(value: string) {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function ForecastTooltip({
  active,
  payload,
  currency,
}: {
  active?: boolean;
  payload?: readonly { payload?: ForecastChartRow }[];
  currency: string;
}) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  return (
    <div className="rounded-md border border-border bg-popover px-3 py-2 text-xs shadow-lg">
      <p className="font-medium">{new Date(`${row.date}T00:00:00`).toLocaleDateString()}</p>
      <dl className="mt-2 grid grid-cols-[auto_auto] gap-x-4 gap-y-1 font-mono tabular-nums">
        <dt className="text-muted-foreground">Median</dt>
        <dd className="text-right">{compactCurrency(row.median, currency)}</dd>
        {row.regression != null && (
          <>
            <dt className="text-muted-foreground">Regression</dt>
            <dd className="text-right">
              {compactCurrency(row.regression, currency)}
            </dd>
          </>
        )}
        <dt className="text-muted-foreground">50% interval</dt>
        <dd className="text-right">
          {compactCurrency(row.p25, currency)}–{compactCurrency(row.p75, currency)}
        </dd>
        <dt className="text-muted-foreground">80% interval</dt>
        <dd className="text-right">
          {compactCurrency(row.p10, currency)}–{compactCurrency(row.p90, currency)}
        </dd>
        <dt className="text-muted-foreground">GARCH vol.</dt>
        <dd className="text-right">{percent(row.volatility)}</dd>
      </dl>
    </div>
  );
}

function ForecastVisual({
  forecast,
  showPaths,
}: {
  forecast: PriceForecast;
  showPaths: boolean;
}) {
  const data = useMemo<ForecastChartRow[]>(() => {
    if (!forecast.last_price || !forecast.fit_end) return [];
    const anchor = {
      date: forecast.fit_end,
      median: forecast.last_price,
      p10: forecast.last_price,
      p25: forecast.last_price,
      p75: forecast.last_price,
      p90: forecast.last_price,
      range80: [forecast.last_price, forecast.last_price] as [number, number],
      range50: [forecast.last_price, forecast.last_price] as [number, number],
      volatility: forecast.current_annualized_volatility_percent ?? 0,
      regression: forecast.regression_available
        ? forecast.last_price
        : undefined,
    } as ForecastChartRow;
    for (const path of forecast.sample_paths) anchor[`path_${path.id}`] = forecast.last_price;
    return [
      anchor,
      ...forecast.points.map((point, index) => {
        const row = {
          date: point.date,
          median: point.median,
          p10: point.p10,
          p25: point.p25,
          p75: point.p75,
          p90: point.p90,
          range80: [point.p10, point.p90] as [number, number],
          range50: [point.p25, point.p75] as [number, number],
          volatility: point.annualized_volatility_percent,
          regression:
            forecast.regression_points[index]?.predicted_price,
        } as ForecastChartRow;
        for (const path of forecast.sample_paths) {
          row[`path_${path.id}`] = path.points[index]?.price ?? point.median;
        }
        return row;
      }),
    ];
  }, [forecast]);

  return (
    <div className="space-y-5">
      <div className="h-[470px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 10, right: 16, left: 2, bottom: 4 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={shortDate}
              minTickGap={36}
              tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
              axisLine={{ stroke: "var(--border)" }}
              tickLine={false}
            />
            <YAxis
              domain={["auto", "auto"]}
              width={72}
              tickFormatter={(value) => compactCurrency(Number(value), forecast.currency)}
              tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<ForecastTooltip currency={forecast.currency} />} />
            <Area
              type="monotone"
              dataKey="range80"
              stroke="none"
              fill="var(--chart-2)"
              fillOpacity={0.13}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="range50"
              stroke="none"
              fill="var(--chart-1)"
              fillOpacity={0.2}
              isAnimationActive={false}
            />
            {showPaths &&
              forecast.sample_paths.map((path) => (
                <Line
                  key={path.id}
                  type="monotone"
                  dataKey={`path_${path.id}`}
                  stroke="var(--muted-foreground)"
                  strokeOpacity={0.18}
                  strokeWidth={0.8}
                  dot={false}
                  activeDot={false}
                  isAnimationActive={false}
                />
              ))}
            <ReferenceLine
              y={forecast.last_price ?? undefined}
              stroke="var(--muted-foreground)"
              strokeDasharray="4 4"
              label={{
                value: "Last close",
                fill: "var(--muted-foreground)",
                fontSize: 10,
                position: "insideTopRight",
              }}
            />
            <Line
              type="monotone"
              dataKey="median"
              stroke="var(--chart-1)"
              strokeWidth={2.2}
              dot={false}
              isAnimationActive={false}
            />
            {forecast.regression_available && (
              <Line
                type="monotone"
                dataKey="regression"
                stroke="var(--chart-3)"
                strokeWidth={2}
                strokeDasharray="6 4"
                dot={false}
                isAnimationActive={false}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div>
        <div className="mb-2 flex items-end justify-between gap-4">
          <div>
            <p className="terminal-label">Conditional volatility path</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Mean annualized volatility carried through the GARCH recursion.
            </p>
          </div>
          <span className="font-mono text-xs tabular-nums">
            {percent(forecast.points.at(-1)?.annualized_volatility_percent)}
          </span>
        </div>
        <div className="h-44 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, left: 2, bottom: 2 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={shortDate}
                minTickGap={48}
                tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                tickLine={false}
                axisLine={{ stroke: "var(--border)" }}
              />
              <YAxis
                width={54}
                tickFormatter={(value) => `${Number(value).toFixed(0)}%`}
                tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                tickLine={false}
                axisLine={false}
              />
              <Line
                type="monotone"
                dataKey="volatility"
                stroke="var(--chart-2)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="border-b border-r border-border/70 p-4 last:border-r-0">
      <p className="terminal-label">{label}</p>
      <p className="mt-2 font-mono text-xl font-semibold tracking-[-0.03em] tabular-nums">
        {value}
      </p>
      <p className="mt-1 text-[11px] text-muted-foreground">{detail}</p>
    </div>
  );
}

export function PriceForecastWorkspace({ ticker }: { ticker: string }) {
  const [horizon, setHorizon] = useState(15);
  const [simulations, setSimulations] = useState(2500);
  const [showPaths, setShowPaths] = useState(false);
  const forecast = useQuery({
    queryKey: ["company-price-forecast", ticker, horizon, simulations],
    queryFn: () => api.getCompanyPriceForecast(ticker, horizon, simulations),
    staleTime: 30 * 60 * 1000,
  });

  return (
    <div className="space-y-5">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <p className="page-eyebrow">Short-horizon price scenarios</p>
          <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em]">
            ARIMA–GARCH + multiple regression forecast
          </h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
            ARIMA estimates conditional return drift, GARCH updates volatility after each
            simulated shock, and Monte Carlo forms the probability bands. A separate
            direct-horizon regression uses lagged price momentum, relative volume, and
            price versus rolling VWAP. Forecasting is capped at 15 trading days.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <span className="terminal-label block pb-1.5">Horizon</span>
            <div className="flex rounded-md bg-muted p-1">
              {HORIZONS.map((days) => (
                <Button
                  key={days}
                  size="sm"
                  variant={horizon === days ? "default" : "ghost"}
                  className="h-7 px-2 font-mono text-[10px]"
                  onClick={() => setHorizon(days)}
                >
                  {days}D
                </Button>
              ))}
            </div>
          </div>
          <label className="space-y-1.5">
            <span className="terminal-label block">Paths</span>
            <select
              value={simulations}
              onChange={(event) => setSimulations(Number(event.target.value))}
              className="h-9 rounded-md border border-input bg-background px-3 font-mono text-xs outline-none focus:border-ring"
            >
              {SIMULATION_COUNTS.map((count) => (
                <option key={count} value={count}>{count.toLocaleString()}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {forecast.isLoading ? (
        <Skeleton className="h-[760px] w-full" />
      ) : forecast.isError || !forecast.data ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            The forecast model is temporarily unavailable.
          </CardContent>
        </Card>
      ) : !forecast.data.available ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Insufficient price history</CardTitle>
            <CardDescription>{forecast.data.limitations[0]}</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 overflow-hidden rounded-lg border border-border bg-card lg:grid-cols-5">
            <Stat
              label="Terminal median"
              value={compactCurrency(forecast.data.median_terminal_price, forecast.data.currency)}
              detail={`${horizon} modeled trading days`}
            />
            <Stat
              label="Terminal 80% range"
              value={`${compactCurrency(forecast.data.terminal_range_80_low, forecast.data.currency)}–${compactCurrency(forecast.data.terminal_range_80_high, forecast.data.currency)}`}
              detail="10th to 90th percentile"
            />
            <Stat
              label="Finish above last close"
              value={percent(forecast.data.probability_finish_above_last, true)}
              detail="Share of simulated terminal prices"
            />
            <Stat
              label="Current GARCH volatility"
              value={percent(forecast.data.current_annualized_volatility_percent)}
              detail="Annualized conditional estimate"
            />
            <Stat
              label="Regression terminal"
              value={
                forecast.data.regression_available
                  ? compactCurrency(
                      forecast.data.regression_terminal_price,
                      forecast.data.currency
                    )
                  : "Unavailable"
              }
              detail={
                forecast.data.regression_available
                  ? `${percent(
                      forecast.data.regression_terminal_return_percent
                    )} modeled return`
                  : "Insufficient regression inputs"
              }
            />
          </div>

          <Card className="gap-0 overflow-hidden py-0">
            <CardHeader className="flex flex-col gap-3 border-b border-border/70 py-5 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <ChartNoAxesCombined className="size-4 text-emerald-700 dark:text-emerald-400" />
                  {ticker} · simulated price distribution
                </CardTitle>
                <CardDescription className="mt-1">
                  Median path with central 50% and 80% Monte Carlo probability bands.
                </CardDescription>
              </div>
              <Button
                size="sm"
                variant={showPaths ? "secondary" : "outline"}
                onClick={() => setShowPaths((value) => !value)}
              >
                <Waves className="size-3.5" />
                {showPaths ? "Hide sample paths" : "Show sample paths"}
              </Button>
            </CardHeader>
            <CardContent className="p-4 sm:p-6">
              <div className="mb-3 flex flex-wrap items-center gap-4 text-[11px] text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-0.5 w-5 bg-chart-1" /> Median
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="size-3 bg-chart-1/20" /> Central 50%
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="size-3 bg-chart-2/15" /> Central 80%
                </span>
                {forecast.data.regression_available && (
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-0.5 w-5 border-t-2 border-dashed border-chart-3" />
                    Multiple regression
                  </span>
                )}
              </div>
              <ForecastVisual forecast={forecast.data} showPaths={showPaths} />
            </CardContent>
          </Card>

          <Card className="gap-0 overflow-hidden py-0">
            <CardHeader className="border-b border-border/70 py-4">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Activity className="size-4 text-muted-foreground" /> Model diagnostics
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-px bg-border p-0 sm:grid-cols-2 lg:grid-cols-4">
              {[
                ["ARIMA drift", percent(forecast.data.annualized_arima_drift_percent), "Annualized log-return mean"],
                ["AR / MA", `${forecast.data.arima_ar1?.toFixed(3)} / ${forecast.data.arima_ma1?.toFixed(3)}`, "ARIMA(1,1,1) coefficients"],
                ["GARCH α / β", `${forecast.data.garch_alpha1?.toFixed(3)} / ${forecast.data.garch_beta1?.toFixed(3)}`, "Shock and persistence terms"],
                ["Fit sample", `${forecast.data.observations.toLocaleString()} closes`, `${forecast.data.fit_start} to ${forecast.data.fit_end}`],
              ].map(([label, value, detail]) => (
                <div key={label} className="bg-card p-4">
                  <p className="terminal-label">{label}</p>
                  <p className="mt-2 font-mono text-base font-semibold tabular-nums">{value}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">{detail}</p>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="gap-0 overflow-hidden py-0">
            <CardHeader className="border-b border-border/70 py-4">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Sigma className="size-4 text-muted-foreground" />
                Multiple-regression diagnostics
              </CardTitle>
              <CardDescription>
                Each horizon predicts a future return directly from information
                available at the latest close—no future volume or VWAP is inserted.
              </CardDescription>
            </CardHeader>
            {forecast.data.regression_available ? (
              <>
                <CardContent className="grid gap-px bg-border p-0 sm:grid-cols-2 lg:grid-cols-4">
                  {[
                    [
                      "Validation MAE",
                      percent(
                        forecast.data.regression_validation_mae_percent
                      ),
                      "Time-ordered terminal-horizon return error",
                    ],
                    [
                      "Validation R²",
                      forecast.data.regression_validation_r_squared?.toFixed(3) ??
                        "—",
                      forecast.data.regression_validation_r_squared != null &&
                      forecast.data.regression_validation_r_squared < 0
                        ? "Weak: worse than the validation mean-return baseline"
                        : "Time-ordered out-of-sample explanatory fit",
                    ],
                    [
                      "Training sample",
                      `${forecast.data.regression_observations.toLocaleString()} rows`,
                      `${horizon}-session direct-horizon regression`,
                    ],
                    [
                      "Price vs. VWAP",
                      percent(
                        forecast.data.regression_latest_features
                          .price_vs_20d_vwap_percent
                      ),
                      "Latest close versus 20-session VWAP proxy",
                    ],
                  ].map(([label, value, detail]) => (
                    <div key={label} className="bg-card p-4">
                      <p className="terminal-label">{label}</p>
                      <p className="mt-2 font-mono text-base font-semibold tabular-nums">
                        {value}
                      </p>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {detail}
                      </p>
                    </div>
                  ))}
                </CardContent>
                <CardContent className="border-t p-4 sm:p-5">
                  <p className="terminal-label">Standardized terminal-horizon coefficients</p>
                  <div className="mt-3 grid gap-2 sm:grid-cols-3">
                    {[
                      [
                        "Price momentum",
                        forecast.data.regression_standardized_coefficients
                          .price_momentum,
                      ],
                      [
                        "Relative volume",
                        forecast.data.regression_standardized_coefficients
                          .relative_volume,
                      ],
                      [
                        "Price vs. VWAP",
                        forecast.data.regression_standardized_coefficients
                          .price_vs_vwap,
                      ],
                    ].map(([label, value]) => (
                      <div key={String(label)} className="rounded-md border bg-muted/20 p-3">
                        <p className="text-xs text-muted-foreground">{label}</p>
                        <p className="mt-1 font-mono text-sm font-semibold tabular-nums">
                          {typeof value === "number" ? value.toFixed(4) : "—"}
                        </p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </>
            ) : (
              <CardContent className="py-8 text-sm text-muted-foreground">
                {forecast.data.regression_limitations[0] ??
                  "The multiple regression could not be fitted for this listing."}
              </CardContent>
            )}
          </Card>

          <div className="flex flex-col gap-2 rounded-md border border-border/70 bg-muted/25 px-4 py-3 text-[11px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
            <span>
              Shorter horizons reduce extrapolation, but do not guarantee accuracy.
              Regression VWAP is a daily-bar proxy, not tick-level exchange VWAP.
              These are scenarios, not targets or recommendations.
            </span>
            <a
              href={forecast.data.source_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 hover:text-foreground"
            >
              {forecast.data.source} · delayed data <ExternalLink className="size-3" />
            </a>
          </div>
        </>
      )}
    </div>
  );
}
