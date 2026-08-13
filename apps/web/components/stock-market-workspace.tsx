"use client";

import {
  api,
  type IVStrategy,
  type IVSurfaceForecast,
  type OptionsChain,
  type PaperIVTrade,
  type PriceHistory,
  type PriceRange,
  type TradingRatios,
} from "@/lib/api";
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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BrainCircuit,
  CandlestickChart,
  ExternalLink,
  Gauge,
  Plus,
  RefreshCw,
  Wallet,
} from "lucide-react";
import {
  Bar,
  BarChart as RechartsBarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  HistogramSeries,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

function formatNumber(value?: number | null, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-IN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function formatCompact(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return Intl.NumberFormat("en-IN", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(2)}%`;
}

function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  }).format(new Date(value));
}

function indiaDateKey(value: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Kolkata",
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function ratioTone(value?: number | null): string {
  if (value == null) return "";
  return value >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400";
}

function normalizeTradingViewTicker(ticker: string) {
  return ticker.toUpperCase().replace(/[^A-Z0-9]/g, "_");
}

function tradingViewWidgetSymbol(ticker: string) {
  // TradingView's public widgets do not currently include NSE in their
  // licensed market list. Passing an NSE symbol makes the widget silently
  // fall back to AAPL. BSE is supported (EOD) and dual-listed Indian
  // companies generally use the same TradingView ticker.
  return `BSE:${normalizeTradingViewTicker(ticker)}`;
}

function tradingViewNseUrl(ticker: string) {
  return `https://in.tradingview.com/symbols/NSE-${normalizeTradingViewTicker(ticker)}/`;
}

const TRADING_VIEW_CHART_HEIGHT = 640;
const PRICE_RANGES: PriceRange[] = ["1M", "3M", "6M", "1Y", "5Y", "MAX"];

async function hasTradingViewBseSymbol(ticker: string): Promise<boolean> {
  const symbol = tradingViewWidgetSymbol(ticker);
  try {
    const response = await fetch("https://scanner.tradingview.com/india/scan", {
      method: "POST",
      // text/plain keeps this a CORS-simple request. TradingView accepts the
      // JSON payload while avoiding a preflight it does not permit.
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      body: JSON.stringify({
        symbols: { tickers: [symbol], query: { types: [] } },
        columns: ["name"],
      }),
    });
    if (!response.ok) return false;
    const result = (await response.json()) as {
      data?: Array<{ s?: string }>;
    };
    return result.data?.some((item) => item.s === symbol) ?? false;
  } catch {
    // If availability cannot be confirmed, prefer the NSE-history chart over
    // leaving the user with a blank or invalid TradingView embed.
    return false;
  }
}

function TradingViewAdvancedChart({
  ticker,
  onUnavailable,
}: {
  ticker: string;
  onUnavailable: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const syncTheme = () => {
      setTheme(
        document.documentElement.classList.contains("dark") ? "dark" : "light"
      );
    };
    syncTheme();
    const observer = new MutationObserver(syncTheme);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    container.replaceChildren();
    container.style.height = `${TRADING_VIEW_CHART_HEIGHT}px`;

    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    widget.style.height = "calc(100% - 28px)";
    widget.style.width = "100%";
    container.appendChild(widget);

    const attribution = document.createElement("div");
    attribution.className =
      "tradingview-widget-copyright flex h-7 items-center justify-end px-2 text-[10px] text-muted-foreground";
    const link = document.createElement("a");
    link.href = `https://in.tradingview.com/symbols/${tradingViewWidgetSymbol(ticker).replace(":", "-")}/`;
    link.target = "_blank";
    link.rel = "noopener nofollow";
    link.textContent = `${ticker} BSE chart by TradingView`;
    link.className = "hover:underline";
    attribution.appendChild(link);
    container.appendChild(attribution);

    const script = document.createElement("script");
    script.src =
      "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.onerror = onUnavailable;
    script.innerHTML = JSON.stringify({
      autosize: false,
      width: "100%",
      height: TRADING_VIEW_CHART_HEIGHT,
      symbol: tradingViewWidgetSymbol(ticker),
      interval: "D",
      timezone: "exchange",
      theme,
      backgroundColor: theme === "dark" ? "#171715" : "#ffffff",
      gridColor:
        theme === "dark"
          ? "rgba(120, 113, 108, 0.16)"
          : "rgba(120, 113, 108, 0.12)",
      style: "1",
      locale: "en",
      withdateranges: true,
      hide_side_toolbar: false,
      hide_top_toolbar: false,
      hide_legend: false,
      hide_volume: false,
      allow_symbol_change: true,
      save_image: true,
      studies: [],
      calendar: false,
      support_host: "https://www.tradingview.com",
    });
    container.appendChild(script);
    return () => {
      script.onerror = null;
      container.replaceChildren();
    };
  }, [onUnavailable, theme, ticker]);

  return (
    <div className="relative overflow-hidden rounded-md border border-border/80 bg-background">
      <div
        ref={containerRef}
        className="tradingview-widget-container h-[640px] min-h-[640px] w-full"
        aria-label={`${ticker} TradingView Advanced Chart`}
      />
    </div>
  );
}

type CursorCandle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

function indiaDate(value: string): string {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function TradingChart({
  history,
  livePrice,
  liveEventTime,
}: {
  history: PriceHistory;
  livePrice?: number;
  liveEventTime?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const latestDisplayRef = useRef<CursorCandle | null>(
    history.candles.at(-1) ?? null
  );
  const [cursor, setCursor] = useState<CursorCandle | null>(
    history.candles.at(-1) ?? null
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container || history.candles.length === 0) return;

    const dark = document.documentElement.classList.contains("dark");
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 500,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: dark ? "#a8a29e" : "#78716c",
        fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: dark ? "#292524" : "#eeeae3" },
        horzLines: { color: dark ? "#292524" : "#eeeae3" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: dark ? "#78716c" : "#a8a29e",
          labelBackgroundColor: "#166534",
        },
        horzLine: {
          color: dark ? "#78716c" : "#a8a29e",
          labelBackgroundColor: "#166534",
        },
      },
      rightPriceScale: {
        borderColor: dark ? "#44403c" : "#d6d3d1",
        scaleMargins: { top: 0.08, bottom: 0.24 },
      },
      timeScale: {
        borderColor: dark ? "#44403c" : "#d6d3d1",
        timeVisible: false,
        rightOffset: 4,
        barSpacing: history.range === "1M" ? 15 : 7,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#16a34a",
      downColor: "#e11d48",
      borderUpColor: "#16a34a",
      borderDownColor: "#e11d48",
      wickUpColor: "#16a34a",
      wickDownColor: "#e11d48",
      priceLineVisible: true,
      lastValueVisible: true,
    });
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    candleSeries.setData(
      history.candles.map((candle) => ({
        time: candle.time,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      }))
    );
    volumeSeries.setData(
      history.candles.map((candle) => ({
        time: candle.time,
        value: candle.volume,
        color:
          candle.close >= candle.open
            ? "rgba(22, 163, 74, 0.38)"
            : "rgba(225, 29, 72, 0.38)",
      }))
    );
    chart.timeScale().fitContent();

    const byTime = new Map(
      history.candles.map((candle) => [candle.time, candle])
    );
    const handleCrosshair = (params: MouseEventParams<Time>) => {
      if (!params.time) {
        setCursor(latestDisplayRef.current);
        return;
      }
      const key =
        typeof params.time === "string"
          ? params.time
          : typeof params.time === "number"
            ? new Date(params.time * 1000).toISOString().slice(0, 10)
            : `${params.time.year}-${String(params.time.month).padStart(2, "0")}-${String(params.time.day).padStart(2, "0")}`;
      setCursor(
        key === history.candles.at(-1)?.time
          ? latestDisplayRef.current
          : byTime.get(key) ?? latestDisplayRef.current
      );
    };
    chart.subscribeCrosshairMove(handleCrosshair);

    const resize = new ResizeObserver(([entry]) => {
      chart.applyOptions({ width: entry.contentRect.width });
    });
    resize.observe(container);

    const themeObserver = new MutationObserver(() => {
      const isDark = document.documentElement.classList.contains("dark");
      chart.applyOptions({
        layout: { textColor: isDark ? "#a8a29e" : "#78716c" },
        grid: {
          vertLines: { color: isDark ? "#292524" : "#eeeae3" },
          horzLines: { color: isDark ? "#292524" : "#eeeae3" },
        },
        rightPriceScale: {
          borderColor: isDark ? "#44403c" : "#d6d3d1",
        },
        timeScale: { borderColor: isDark ? "#44403c" : "#d6d3d1" },
      });
    });
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    return () => {
      resize.disconnect();
      themeObserver.disconnect();
      chart.unsubscribeCrosshairMove(handleCrosshair);
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      chart.remove();
    };
  }, [history]);

  const liveCandle = useMemo<CursorCandle | null>(() => {
    const latest = history.candles.at(-1);
    if (
      !latest ||
      livePrice == null ||
      !liveEventTime ||
      indiaDate(liveEventTime) !== latest.time
    ) {
      return null;
    }
    return {
      ...latest,
      high: Math.max(latest.high, livePrice),
      low: Math.min(latest.low, livePrice),
      close: livePrice,
    };
  }, [history, liveEventTime, livePrice]);

  useEffect(() => {
    const latest = history.candles.at(-1) ?? null;
    if (!liveCandle) {
      latestDisplayRef.current = latest;
      return;
    }
    latestDisplayRef.current = liveCandle;
    candleSeriesRef.current?.update({
      time: liveCandle.time,
      open: liveCandle.open,
      high: liveCandle.high,
      low: liveCandle.low,
      close: liveCandle.close,
    });
    volumeSeriesRef.current?.update({
      time: liveCandle.time,
      value: liveCandle.volume,
      color:
        liveCandle.close >= liveCandle.open
          ? "rgba(22, 163, 74, 0.38)"
          : "rgba(225, 29, 72, 0.38)",
    });
  }, [history, liveCandle]);

  const displayedCursor =
    cursor?.time === liveCandle?.time ? liveCandle : cursor;
  const direction = displayedCursor
    ? displayedCursor.close - displayedCursor.open
    : 0;

  return (
    <div className="overflow-hidden rounded-md border border-border/80 bg-background/35">
      <div className="flex min-h-14 flex-wrap items-center gap-x-5 gap-y-2 border-b border-border/70 px-4 py-2 font-mono text-[11px]">
        <span className="text-muted-foreground">
          {displayedCursor?.time ?? "—"}
        </span>
        {[
          ["O", displayedCursor?.open],
          ["H", displayedCursor?.high],
          ["L", displayedCursor?.low],
          ["C", displayedCursor?.close],
        ].map(([label, value]) => (
          <span key={String(label)}>
            <span className="text-muted-foreground">{label} </span>
            <span className={ratioTone(direction)}>
              {formatNumber(value as number | undefined)}
            </span>
          </span>
        ))}
        <span>
          <span className="text-muted-foreground">VOL </span>
          {formatCompact(displayedCursor?.volume)}
        </span>
      </div>
      <div
        ref={containerRef}
        className="h-[500px] w-full"
        aria-label={`${history.ticker} interactive NSE candlestick chart`}
      />
    </div>
  );
}

function RatioCell({
  label,
  value,
  sublabel,
  tone,
}: {
  label: string;
  value: string;
  sublabel?: string;
  tone?: string;
}) {
  return (
    <div className="min-h-24 border-b border-r border-border/70 p-4 last:border-r-0">
      <p className="terminal-label">{label}</p>
      <p className={`mt-2 font-mono text-xl font-semibold tracking-[-0.03em] tabular-nums ${tone ?? ""}`}>
        {value}
      </p>
      {sublabel && <p className="mt-1 text-[11px] text-muted-foreground">{sublabel}</p>}
    </div>
  );
}

function RatioDashboard({ data, livePrice }: { data: TradingRatios; livePrice?: number }) {
  const currentPrice = livePrice ?? data.current_price;
  const priceChange =
    currentPrice != null && data.previous_close != null && data.previous_close !== 0
      ? ((currentPrice - data.previous_close) / data.previous_close) * 100
      : null;
  const rows = [
    [
      [livePrice == null ? "Price" : "Live price", `₹${formatNumber(currentPrice)}`, priceChange == null ? undefined : `${priceChange >= 0 ? "+" : ""}${priceChange.toFixed(2)}% today`, ratioTone(priceChange)],
      ["Market cap", `₹${formatCompact(data.market_cap)}`, "Native INR value"],
      ["P/E · trailing", formatNumber(data.trailing_pe), "Price / trailing earnings"],
      ["P/E · forward", formatNumber(data.forward_pe), "Price / forecast earnings"],
      ["EPS · trailing", `₹${formatNumber(data.trailing_eps)}`, "Earnings per share"],
      ["EPS · forward", `₹${formatNumber(data.forward_eps)}`, "Forecast EPS"],
    ],
    [
      ["Price / book", formatNumber(data.price_to_book), "Market price / book value"],
      ["PEG", formatNumber(data.peg_ratio), "P/E adjusted for growth"],
      ["Book value", `₹${formatNumber(data.book_value)}`, "Per share"],
      ["Profit margin", formatPercent(data.profit_margin_percent), "Net income / revenue"],
      ["Operating margin", formatPercent(data.operating_margin_percent), "Operating profit / revenue"],
      ["Gross margin", formatPercent(data.gross_margin_percent), "Gross profit / revenue"],
    ],
    [
      ["Revenue growth", formatPercent(data.revenue_growth_percent), "Latest reported period", ratioTone(data.revenue_growth_percent)],
      ["Earnings growth", formatPercent(data.earnings_growth_percent), "Latest reported period", ratioTone(data.earnings_growth_percent)],
      ["Return on equity", formatPercent(data.return_on_equity_percent), "Net income / equity"],
      ["Debt / equity", formatPercent(data.debt_to_equity_percent), "Total debt / equity"],
      ["Dividend yield", formatPercent(data.dividend_yield_percent), "Indicated annual yield"],
      ["Payout ratio", formatPercent(data.payout_ratio_percent), "Dividend / earnings"],
    ],
    [
      ["52W high", `₹${formatNumber(data.fifty_two_week_high)}`, "Trailing 52 weeks"],
      ["52W low", `₹${formatNumber(data.fifty_two_week_low)}`, "Trailing 52 weeks"],
      ["Volume", formatCompact(data.volume), "Latest session"],
      ["Avg volume", formatCompact(data.average_volume), "Reported average"],
      ["Current ratio", formatNumber(data.current_ratio), "Current assets / liabilities"],
      ["Beta", formatNumber(data.beta), "Market sensitivity"],
    ],
  ] as const;

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <CardHeader className="border-b border-border/70 py-5">
        <CardTitle className="flex items-center gap-2 text-base">
          <Gauge className="size-4 text-emerald-700 dark:text-emerald-400" />
          Valuation and trading ratios
        </CardTitle>
        <CardDescription>
          Market multiples, per-share fundamentals, profitability, growth, and trading statistics.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {rows.map((row, rowIndex) => (
          <div
            key={rowIndex}
            className="grid grid-cols-2 border-b border-border/70 last:border-b-0 md:grid-cols-3 xl:grid-cols-6"
          >
            {row.map(([label, value, sublabel, tone]) => (
              <RatioCell
                key={label}
                label={label}
                value={value}
                sublabel={sublabel}
                tone={tone}
              />
            ))}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function OptionValue({ value, percent = false }: { value?: number | null; percent?: boolean }) {
  return (
    <span className="font-mono tabular-nums">
      {percent ? formatPercent(value) : formatCompact(value)}
    </span>
  );
}

function GreekValue({
  value,
  digits = 3,
}: {
  value?: number | null;
  digits?: number;
}) {
  return (
    <span className="font-mono tabular-nums">
      {value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits)}
    </span>
  );
}

function buildInterpolatedExceedanceCurve(
  curve: OptionsChain["distribution"]["curve"]
) {
  if (curve.length < 2) {
    return curve.map((point) => ({
      price: point.strike_price,
      probability_at_or_above_percent: point.probability_above * 100,
    }));
  }

  const x = curve.map((point) => point.strike_price);
  const y = curve.map((point) => point.probability_above);
  const segmentWidths = x.slice(0, -1).map((value, index) => x[index + 1] - value);
  const secantSlopes = segmentWidths.map(
    (width, index) => (y[index + 1] - y[index]) / width
  );
  const tangents = new Array<number>(curve.length).fill(0);

  if (curve.length === 2) {
    tangents[0] = secantSlopes[0];
    tangents[1] = secantSlopes[0];
  } else {
    const endpointTangent = (
      firstWidth: number,
      secondWidth: number,
      firstSlope: number,
      secondSlope: number
    ) => {
      let tangent =
        ((2 * firstWidth + secondWidth) * firstSlope - firstWidth * secondSlope) /
        (firstWidth + secondWidth);
      if (Math.sign(tangent) !== Math.sign(firstSlope)) tangent = 0;
      else if (
        Math.sign(firstSlope) !== Math.sign(secondSlope) &&
        Math.abs(tangent) > Math.abs(3 * firstSlope)
      ) {
        tangent = 3 * firstSlope;
      }
      return tangent;
    };

    tangents[0] = endpointTangent(
      segmentWidths[0],
      segmentWidths[1],
      secantSlopes[0],
      secantSlopes[1]
    );
    const last = curve.length - 1;
    tangents[last] = endpointTangent(
      segmentWidths[last - 1],
      segmentWidths[last - 2],
      secantSlopes[last - 1],
      secantSlopes[last - 2]
    );
    for (let index = 1; index < last; index += 1) {
      const previousSlope = secantSlopes[index - 1];
      const nextSlope = secantSlopes[index];
      if (previousSlope === 0 || nextSlope === 0 || previousSlope * nextSlope < 0) {
        tangents[index] = 0;
        continue;
      }
      const previousWidth = segmentWidths[index - 1];
      const nextWidth = segmentWidths[index];
      const firstWeight = 2 * nextWidth + previousWidth;
      const secondWeight = nextWidth + 2 * previousWidth;
      tangents[index] =
        (firstWeight + secondWeight) /
        (firstWeight / previousSlope + secondWeight / nextSlope);
    }
  }

  const priceRange = x.at(-1)! - x[0];
  // Roughly one sample per horizontal pixel; for ordinary stocks this is also
  // at least one value per rupee, while remaining responsive for very high prices.
  const sampleCount = Math.min(1600, Math.max(200, Math.ceil(priceRange)));
  const samples = [];
  let segment = 0;
  for (let sample = 0; sample <= sampleCount; sample += 1) {
    const price = x[0] + (priceRange * sample) / sampleCount;
    while (segment < x.length - 2 && price > x[segment + 1]) segment += 1;
    const width = segmentWidths[segment];
    const normalized = width ? (price - x[segment]) / width : 0;
    const squared = normalized * normalized;
    const cubed = squared * normalized;
    const h00 = 2 * cubed - 3 * squared + 1;
    const h10 = cubed - 2 * squared + normalized;
    const h01 = -2 * cubed + 3 * squared;
    const h11 = cubed - squared;
    const interpolated =
      h00 * y[segment] +
      h10 * width * tangents[segment] +
      h01 * y[segment + 1] +
      h11 * width * tangents[segment + 1];
    const lower = Math.min(y[segment], y[segment + 1]);
    const upper = Math.max(y[segment], y[segment + 1]);
    samples.push({
      price: Number(price.toFixed(4)),
      probability_at_or_above_percent:
        Math.min(upper, Math.max(lower, interpolated)) * 100,
    });
  }
  return samples;
}

function ProbabilityDistributionView({ chain }: { chain: OptionsChain }) {
  const distribution = chain.distribution;
  if (!distribution.available) {
    return (
      <div className="border-b border-border/70 p-6">
        <div className="rounded-md border border-dashed border-border bg-muted/20 p-6 text-center">
          <p className="text-sm font-medium">Expiry distribution unavailable</p>
          <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            {distribution.limitation}
          </p>
        </div>
      </div>
    );
  }

  const chartData = distribution.buckets.map((bucket) => ({
    ...bucket,
    probability_percent: bucket.probability * 100,
  }));
  const exceedanceData = buildInterpolatedExceedanceCurve(distribution.curve);
  const qualityTone =
    distribution.quality_label === "high"
      ? "text-emerald-700 dark:text-emerald-400"
      : distribution.quality_label === "medium"
        ? "text-amber-700 dark:text-amber-400"
        : "text-rose-700 dark:text-rose-400";

  return (
    <section className="space-y-5 border-b border-border/70 p-4 sm:p-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div>
          <p className="terminal-label">Options-implied expiry distribution</p>
          <h3 className="mt-1 text-lg font-semibold tracking-[-0.025em]">
            Where the chain places probability mass
          </h3>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">
            Risk-neutral probabilities for {chain.selected_expiry}, inferred independently
            from this expiry&apos;s liquid strikes. This describes the terminal price—not
            the path taken before expiry.
          </p>
        </div>
        <div className="rounded-md border border-border bg-muted/25 px-3 py-2 text-right">
          <p className="terminal-label">Data quality</p>
          <p className={`mt-1 font-mono text-lg font-semibold capitalize ${qualityTone}`}>
            {distribution.quality_label} · {distribution.quality_score.toFixed(0)}/100
          </p>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(310px,0.75fr)]">
        <div className="rounded-md border border-border/80 bg-background/40 p-3">
          <div className="h-[360px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <RechartsBarChart
                data={chartData}
                margin={{ top: 16, right: 16, bottom: 18, left: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.35} />
                <XAxis
                  type="number"
                  dataKey="chart_price"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(value) => `₹${formatCompact(Number(value))}`}
                  tick={{ fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                  minTickGap={24}
                />
                <YAxis
                  tickFormatter={(value) => `${Number(value).toFixed(0)}%`}
                  tick={{ fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                  width={42}
                />
                <Tooltip
                  cursor={{ fill: "var(--muted)", opacity: 0.45 }}
                  labelFormatter={(_, payload) =>
                    payload?.[0]?.payload?.label ?? "Price range"
                  }
                  formatter={(value) => [
                    `${Number(value).toFixed(2)}%`,
                    "Implied probability",
                  ]}
                />
                {chain.underlying_value != null && (
                  <ReferenceLine
                    x={chain.underlying_value}
                    stroke="var(--foreground)"
                    strokeDasharray="5 4"
                    label={{
                      value: `Spot ₹${formatNumber(chain.underlying_value, 0)}`,
                      position: "insideTopRight",
                      fontSize: 10,
                      fill: "var(--foreground)",
                    }}
                  />
                )}
                <Bar
                  dataKey="probability_percent"
                  name="Implied probability"
                  fill="var(--chart-1)"
                  radius={[3, 3, 0, 0]}
                  maxBarSize={52}
                  isAnimationActive={false}
                />
              </RechartsBarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="grid grid-cols-2 overflow-hidden rounded-md border border-border/80 bg-border">
          {[
            ["Most likely range", distribution.most_likely_range ?? "—"],
            ["Median expiry price", `₹${formatNumber(distribution.median_price)}`],
            [
              "50% implied range",
              `₹${formatNumber(distribution.range_50_low, 0)}–₹${formatNumber(distribution.range_50_high, 0)}`,
            ],
            [
              "80% implied range",
              `₹${formatNumber(distribution.range_80_low, 0)}–₹${formatNumber(distribution.range_80_high, 0)}`,
            ],
            [
              "Above current spot",
              formatPercent((distribution.probability_above_spot ?? 0) * 100),
            ],
            [
              "Below current spot",
              formatPercent((distribution.probability_below_spot ?? 0) * 100),
            ],
          ].map(([label, value]) => (
            <div key={label} className="bg-card p-4">
              <p className="terminal-label">{label}</p>
              <p className="mt-2 font-mono text-sm font-semibold tabular-nums">
                {value}
              </p>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-md border border-border/80 bg-background/40 p-3">
        <div className="px-1 pb-2">
          <p className="text-sm font-medium">Expiry-price exceedance curve</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            At each price K, the curve shows the modeled probability P(Sₜ ≥ K) of
            expiring at or above that level. Hover anywhere between strikes for the
            monotone-interpolated probability.
          </p>
        </div>
        <div
          className="h-[340px] w-full"
          role="img"
          aria-label={`Probability of expiring at or above each price for ${chain.selected_expiry}`}
        >
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={exceedanceData}
              margin={{ top: 16, right: 18, bottom: 18, left: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.35} />
              <XAxis
                type="number"
                dataKey="price"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(value) => `₹${formatCompact(Number(value))}`}
                tick={{ fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                minTickGap={24}
              />
              <YAxis
                domain={[0, 100]}
                tickFormatter={(value) => `${Number(value).toFixed(0)}%`}
                tick={{ fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                width={42}
              />
              <Tooltip
                labelFormatter={(value) => `Expiry price ₹${formatNumber(Number(value), 2)}`}
                formatter={(value) => [
                  `${Number(value).toFixed(2)}%`,
                  "Probability at or above",
                ]}
              />
              <ReferenceLine
                y={50}
                stroke="var(--muted-foreground)"
                strokeDasharray="3 4"
                label={{
                  value: "50%",
                  position: "insideLeft",
                  fontSize: 10,
                  fill: "var(--muted-foreground)",
                }}
              />
              {chain.underlying_value != null && (
                <ReferenceLine
                  x={chain.underlying_value}
                  stroke="var(--foreground)"
                  strokeDasharray="5 4"
                  label={{
                    value: `Spot ₹${formatNumber(chain.underlying_value, 0)}`,
                    position: "insideTopRight",
                    fontSize: 10,
                    fill: "var(--foreground)",
                  }}
                />
              )}
              {distribution.median_price != null && (
                <ReferenceLine
                  x={distribution.median_price}
                  stroke="var(--chart-2)"
                  strokeDasharray="2 3"
                  label={{
                    value: `Median ₹${formatNumber(distribution.median_price, 0)}`,
                    position: "insideBottomRight",
                    fontSize: 10,
                    fill: "var(--muted-foreground)",
                  }}
                />
              )}
              <Line
                type="linear"
                dataKey="probability_at_or_above_percent"
                stroke="var(--chart-1)"
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 4 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="overflow-hidden rounded-md border border-border/80">
          <div className="border-b border-border/70 bg-muted/35 px-4 py-3">
            <p className="text-sm font-medium">Exact probability buckets</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Adjacent monotonic exceedance probabilities are differenced into bars.
            </p>
          </div>
          <div className="max-h-[340px] overflow-auto">
            <table className="data-table">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th>Expiry price range</th>
                  <th className="text-right">Probability</th>
                </tr>
              </thead>
              <tbody>
                {distribution.buckets.map((bucket) => (
                  <tr key={bucket.label}>
                    <td className="font-mono text-xs">{bucket.label}</td>
                    <td className="text-right font-mono font-semibold tabular-nums">
                      {(bucket.probability * 100).toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-md border border-border/80 bg-muted/20 p-4">
          <p className="text-sm font-medium">Quality diagnostics</p>
          <div className="mt-4 space-y-3 text-xs">
            {[
              ["Usable IV coverage", distribution.valid_iv_coverage_percent],
              ["Active-contract coverage", distribution.active_contract_coverage_percent],
              ["Median bid–ask spread", distribution.median_relative_spread_percent],
            ].map(([label, value]) => (
              <div key={label as string}>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">{label}</span>
                  <span className="font-mono tabular-nums">
                    {formatPercent(value as number | null)}
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-emerald-600"
                    style={{ width: `${Math.max(0, Math.min(Number(value) || 0, 100))}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 space-y-1 border-t border-border/70 pt-3 font-mono text-[10px] text-muted-foreground">
            <p>{distribution.strikes_used} of {distribution.total_strikes} strikes used</p>
            <p>{distribution.monotonic_adjustments} probability points adjusted</p>
            <p>{distribution.method}</p>
          </div>
        </div>
      </div>

      <p className="text-[11px] leading-5 text-muted-foreground">
        {distribution.limitation}
      </p>
    </section>
  );
}

function OptionsTable({
  chain,
}: {
  chain: OptionsChain;
}) {
  return (
    <Card className="gap-0 overflow-hidden py-0">
      <CardHeader className="border-b border-border/70 py-5">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart3 className="size-4 text-emerald-700 dark:text-emerald-400" />
              NSE options chain
            </CardTitle>
            <CardDescription className="mt-1">
              Calls and puts centered around the current underlying price.
            </CardDescription>
          </div>
        </div>
        {chain.available && (
          <div className="mt-3 flex flex-wrap gap-2">
            <Badge variant="secondary">
              Spot ₹{formatNumber(chain.underlying_value)}
            </Badge>
            <Badge variant="outline">As of {chain.exchange_timestamp ?? "NSE snapshot"}</Badge>
            <Badge variant="outline">
              Greeks: {chain.greeks_model} · r {formatPercent(chain.risk_free_rate_percent)}
            </Badge>
          </div>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {!chain.available ? (
          <div className="p-8 text-center">
            <p className="text-sm font-medium">No listed stock-option chain found</p>
            <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              {chain.limitation ?? "This stock may not be in NSE's equity derivatives segment."}
            </p>
            <a
              href={chain.source_url}
              target="_blank"
              rel="noreferrer"
              className="mt-4 inline-flex items-center gap-1 text-xs font-medium text-emerald-700 hover:underline dark:text-emerald-400"
            >
              Check NSE directly <ExternalLink className="size-3" />
            </a>
          </div>
        ) : (
          <div>
            <ProbabilityDistributionView chain={chain} />
            <div className="border-b border-border/70 bg-muted/20 px-4 py-3 sm:px-6">
              <p className="text-sm font-medium">Detailed option chain</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                The 25 strikes nearest spot, with exchange fields and modeled Greeks.
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1580px] text-xs">
              <thead>
                <tr className="border-b border-border/70 bg-muted/55">
                  <th colSpan={9} className="px-3 py-2.5 text-left font-mono text-[10px] uppercase tracking-[0.12em] text-emerald-700 dark:text-emerald-400">
                    Calls
                  </th>
                  <th className="border-x border-border/80 px-3 py-2.5 text-center font-mono text-[10px] uppercase tracking-[0.12em]">
                    Strike
                  </th>
                  <th colSpan={9} className="px-3 py-2.5 text-right font-mono text-[10px] uppercase tracking-[0.12em] text-rose-700 dark:text-rose-400">
                    Puts
                  </th>
                </tr>
                <tr className="border-b border-border/70 bg-muted/30 text-muted-foreground">
                  {[
                    ["OI", "Open interest"],
                    ["Volume", "Traded contracts"],
                    ["IV", "Implied volatility"],
                    ["Δ", "Delta"],
                    ["Γ", "Gamma"],
                    ["Θ", "Theta per calendar day"],
                    ["Vega", "Vega per 1 volatility point"],
                    ["Rho", "Rho per 1 interest-rate point"],
                    ["LTP", "Last traded price"],
                    ["₹", "Strike price"],
                    ["LTP", "Last traded price"],
                    ["Δ", "Delta"],
                    ["Γ", "Gamma"],
                    ["Θ", "Theta per calendar day"],
                    ["Vega", "Vega per 1 volatility point"],
                    ["Rho", "Rho per 1 interest-rate point"],
                    ["IV", "Implied volatility"],
                    ["Volume", "Traded contracts"],
                    ["OI", "Open interest"],
                  ].map(([label, title], index) => (
                    <th
                      key={`${label}-${index}`}
                      title={title}
                      className="px-3 py-2 text-center font-mono text-[10px] font-medium uppercase"
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {chain.strikes.map((row) => {
                  const isAtMoney =
                    chain.underlying_value != null &&
                    Math.abs(row.strike_price - chain.underlying_value) ===
                      Math.min(...chain.strikes.map((item) => Math.abs(item.strike_price - (chain.underlying_value ?? 0))));
                  return (
                    <tr
                      key={row.strike_price}
                      className={`border-b border-border/60 last:border-b-0 hover:bg-muted/30 ${isAtMoney ? "bg-emerald-50/60 dark:bg-emerald-950/25" : ""}`}
                    >
                      <td className="px-3 py-2 text-center"><OptionValue value={row.call?.open_interest} /></td>
                      <td className="px-3 py-2 text-center"><OptionValue value={row.call?.volume} /></td>
                      <td className="px-3 py-2 text-center"><OptionValue value={row.call?.implied_volatility} percent /></td>
                      <td className="px-3 py-2 text-center"><GreekValue value={row.call?.delta} /></td>
                      <td className="px-3 py-2 text-center"><GreekValue value={row.call?.gamma} digits={4} /></td>
                      <td className="px-3 py-2 text-center"><GreekValue value={row.call?.theta} /></td>
                      <td className="px-3 py-2 text-center"><GreekValue value={row.call?.vega} /></td>
                      <td className="px-3 py-2 text-center"><GreekValue value={row.call?.rho} /></td>
                      <td className="px-3 py-2 text-center"><OptionValue value={row.call?.last_price} /></td>
                      <td className="border-x border-border/80 bg-muted/25 px-3 py-2 text-center font-mono font-semibold tabular-nums">
                        {formatNumber(row.strike_price, 0)}
                      </td>
                      <td className="px-3 py-2 text-center"><OptionValue value={row.put?.last_price} /></td>
                      <td className="px-3 py-2 text-center"><GreekValue value={row.put?.delta} /></td>
                      <td className="px-3 py-2 text-center"><GreekValue value={row.put?.gamma} digits={4} /></td>
                      <td className="px-3 py-2 text-center"><GreekValue value={row.put?.theta} /></td>
                      <td className="px-3 py-2 text-center"><GreekValue value={row.put?.vega} /></td>
                      <td className="px-3 py-2 text-center"><GreekValue value={row.put?.rho} /></td>
                      <td className="px-3 py-2 text-center"><OptionValue value={row.put?.implied_volatility} percent /></td>
                      <td className="px-3 py-2 text-center"><OptionValue value={row.put?.volume} /></td>
                      <td className="px-3 py-2 text-center"><OptionValue value={row.put?.open_interest} /></td>
                    </tr>
                  );
                })}
              </tbody>
              </table>
              <div className="border-t border-border/70 bg-muted/25 px-4 py-3 text-[11px] leading-5 text-muted-foreground">
                Δ Delta · Γ Gamma · Θ daily Theta · Vega per 1 percentage-point IV move ·
                Rho per 1 percentage-point rate move. Greeks are modeled from NSE spot,
                strike, expiry and IV using {chain.greeks_model}, with a{" "}
                {formatPercent(chain.risk_free_rate_percent)} risk-free rate and{" "}
                {formatPercent(chain.dividend_yield_percent)} dividend-yield assumption.
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function StockMarketWorkspace({
  ticker,
  livePrice,
  liveEventTime,
}: {
  ticker: string;
  livePrice?: number;
  liveEventTime?: string;
}) {
  const [forceFallbackChart, setForceFallbackChart] = useState(false);
  const [range, setRange] = useState<PriceRange>("1Y");
  const tradingViewAvailability = useQuery({
    queryKey: ["tradingview-bse-symbol", normalizeTradingViewTicker(ticker)],
    queryFn: () => hasTradingViewBseSymbol(ticker),
    staleTime: 24 * 60 * 60 * 1000,
    retry: 1,
  });
  const useFallbackChart =
    forceFallbackChart || tradingViewAvailability.data === false;
  const history = useQuery({
    queryKey: ["company-price-history", ticker, range],
    queryFn: () => api.getCompanyPriceHistory(ticker, range),
    staleTime: 30 * 60 * 1000,
    enabled: useFallbackChart,
  });
  const ratios = useQuery({
    queryKey: ["company-trading-ratios", ticker],
    queryFn: () => api.getCompanyTradingRatios(ticker),
    staleTime: 30 * 60 * 1000,
  });
  const latestMove = useMemo(() => {
    const current = livePrice ?? ratios.data?.current_price;
    const previous = ratios.data?.previous_close;
    if (current == null || previous == null || previous === 0) return null;
    return {
      value: current - previous,
      percent: ((current - previous) / previous) * 100,
    };
  }, [livePrice, ratios.data]);
  const handleTradingViewUnavailable = useCallback(
    () => setForceFallbackChart(true),
    []
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="page-eyebrow">NSE market workspace</p>
          <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em]">
            Price action, valuation and derivatives
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            TradingView technical analysis, company ratios, and listed NSE options.
          </p>
        </div>
        {livePrice != null ? (
          <div className="text-left sm:text-right">
            <p className="terminal-label">Live Yahoo quote</p>
            <p className="mt-1 font-mono text-lg font-semibold text-emerald-700 dark:text-emerald-400">
              ₹{formatNumber(livePrice)}
            </p>
            {liveEventTime && (
              <p className="text-[10px] text-muted-foreground">
                {new Date(liveEventTime).toLocaleTimeString()}
              </p>
            )}
          </div>
        ) : latestMove ? (
          <div className="text-left sm:text-right">
            <p className="terminal-label">Latest close move</p>
            <p className={`mt-1 font-mono text-lg font-semibold ${ratioTone(latestMove.value)}`}>
              {latestMove.value >= 0 ? "+" : ""}₹{formatNumber(latestMove.value)}{" "}
              <span className="text-sm">({latestMove.percent >= 0 ? "+" : ""}{latestMove.percent.toFixed(2)}%)</span>
            </p>
          </div>
        ) : null}
      </div>

      <Card className="gap-4">
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <CandlestickChart className="size-4 text-emerald-700 dark:text-emerald-400" />
              {ticker} · {useFallbackChart ? "NSE price chart" : "TradingView Advanced Chart"}
            </CardTitle>
            <CardDescription className="mt-1">
              {useFallbackChart
                ? "Drag to pan, scroll or pinch to zoom, and hover to inspect OHLCV."
                : "BSE EOD mirror · add indicators from the top toolbar and annotate with the drawing tools on the left."}
            </CardDescription>
          </div>
          {useFallbackChart ? (
            <div className="flex flex-wrap gap-1 rounded-lg bg-muted p-1">
              {PRICE_RANGES.map((item) => (
                <Button
                  key={item}
                  size="sm"
                  variant={range === item ? "default" : "ghost"}
                  className="h-7 px-2.5 font-mono text-[11px]"
                  onClick={() => setRange(item)}
                >
                  {item}
                </Button>
              ))}
            </div>
          ) : (
            <a
              href={tradingViewNseUrl(ticker)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              Open the NSE chart on TradingView
              <ExternalLink className="size-3.5" />
            </a>
          )}
        </CardHeader>
        <CardContent>
          {tradingViewAvailability.isLoading ? (
            <Skeleton className="h-[640px] w-full" />
          ) : useFallbackChart ? (
            history.isLoading ? (
              <Skeleton className="h-[555px] w-full" />
            ) : history.isError ||
              !history.data ||
              history.data.candles.length === 0 ? (
              <div className="grid h-96 place-items-center text-sm text-muted-foreground">
                Price history is temporarily unavailable.
              </div>
            ) : (
              <TradingChart
                history={history.data}
                livePrice={livePrice}
                liveEventTime={liveEventTime}
              />
            )
          ) : (
            <TradingViewAdvancedChart
              ticker={ticker}
              onUnavailable={handleTradingViewUnavailable}
            />
          )}
        </CardContent>
      </Card>

      {ratios.isLoading ? (
        <Skeleton className="h-[420px] w-full" />
      ) : ratios.isError || !ratios.data ? (
        <Card>
          <CardContent className="py-8 text-sm text-muted-foreground">
            Valuation ratios are temporarily unavailable.
          </CardContent>
        </Card>
      ) : (
        <RatioDashboard data={ratios.data} livePrice={livePrice} />
      )}

      <div className="flex flex-col gap-2 rounded-md border border-border/70 bg-muted/25 px-4 py-3 text-[11px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span className="inline-flex items-center gap-1.5">
          <Activity className="size-3.5" />
          {livePrice != null
            ? "Headline price is live; ratios and chart history update on their normal cache schedule."
            : "Market data can be delayed. Ratios are reported values, not AI-generated estimates."}
        </span>
        <span>
          Chart: {useFallbackChart ? "Yahoo Finance NSE history" : "TradingView"} · Ratios: Yahoo Finance · Not investment advice
        </span>
      </div>
    </div>
  );
}

function ivStatusLabel(status: IVSurfaceForecast["overall_status"]) {
  if (status === "cheap") return "Options look cheap";
  if (status === "expensive") return "Options look expensive";
  if (status === "in_line") return "No material gap";
  return "Model unavailable";
}

function IVStrategyPayoffPanel({
  strategy,
  onTrack,
  isTracking,
  isTracked,
  trackingAllowed = true,
}: {
  strategy: IVStrategy;
  onTrack: (strategy: IVStrategy) => void;
  isTracking: boolean;
  isTracked: boolean;
  trackingAllowed?: boolean;
}) {
  if (!strategy.available) {
    return (
      <div className="rounded-md border border-border/70 bg-muted/20 px-4 py-4">
        <p className="terminal-label">What could a user do with this?</p>
        <p className="mt-2 text-sm font-medium">{strategy.strategy_name}</p>
        <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">
          {strategy.rationale}
        </p>
      </div>
    );
  }

  const isDebit = strategy.entry_premium_type === "debit";
  const payoffData = strategy.payoff_points.map((point) => ({
    price: point.underlying_price,
    expiryPnl: point.pnl_per_lot,
    nextSessionPnl: point.next_session_pnl_per_lot,
  }));
  const breakEvens = [strategy.lower_break_even, strategy.upper_break_even].filter(
    (value): value is number => value != null
  );

  return (
    <section className="overflow-hidden rounded-md border border-border/70">
      <div className="border-b border-border/70 bg-muted/20 px-4 py-4">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
          <div>
            <p className="terminal-label">
              {strategy.source_buckets.length > 0
                ? `Signal: ${strategy.source_buckets.join(" + ")}`
                : "Illustrative way to express the IV view"}
            </p>
            <h3 className="mt-1 text-base font-semibold">{strategy.strategy_name}</h3>
            <p className="mt-1 max-w-4xl text-xs leading-5 text-muted-foreground">
              {strategy.rationale}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">
              {strategy.signal === "long_volatility"
                ? "Long volatility"
                : strategy.signal === "short_volatility_defined_risk"
                  ? "Defined-risk short volatility"
                  : "Directional · defined risk"}
            </Badge>
            <Button
              size="sm"
              onClick={() => onTrack(strategy)}
              disabled={isTracking || isTracked || !trackingAllowed}
            >
              <Plus className="size-3.5" />
              {!trackingAllowed
                ? "Published scenario"
                : isTracking
                ? "Saving…"
                : isTracked
                  ? "Paper trade tracked"
                  : "Track one lot"}
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-0 lg:grid-cols-[0.9fr_1.4fr]">
        <div className="border-b border-border/70 p-4 lg:border-b-0 lg:border-r">
          <p className="terminal-label">One-lot order example</p>
          <div className="mt-3 space-y-2">
            {strategy.legs.map((leg, index) => (
              <div
                key={`${leg.action}-${leg.option_type}-${leg.strike_price}-${index}`}
                className="flex items-center justify-between gap-3 rounded-md bg-muted/30 px-3 py-2 text-xs"
              >
                <div>
                  <span
                    className={
                      leg.action === "buy"
                        ? "font-semibold text-emerald-700 dark:text-emerald-400"
                        : "font-semibold text-rose-700 dark:text-rose-400"
                    }
                  >
                    {leg.action.toUpperCase()}
                  </span>{" "}
                  {leg.quantity_lots} lot · ₹{formatNumber(leg.strike_price, 0)}{" "}
                  {leg.option_type}
                </div>
                <div className="text-right font-mono tabular-nums">
                  ₹{formatNumber(leg.premium_per_unit)}
                  <span className="ml-1 text-[10px] text-muted-foreground">
                    {leg.price_source}
                  </span>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-md border border-border/60 px-3 py-2">
              <p className="text-muted-foreground">
                {isDebit ? "Debit per lot" : "Credit per lot"}
              </p>
              <p className="mt-1 font-mono font-semibold">
                ₹{formatNumber(strategy.entry_cash_flow_per_lot)}
              </p>
            </div>
            <div className="rounded-md border border-border/60 px-3 py-2">
              <p className="text-muted-foreground">NSE lot size</p>
              <p className="mt-1 font-mono font-semibold">
                {formatNumber(strategy.lot_size, 0)} units
              </p>
            </div>
            <div className="rounded-md border border-border/60 px-3 py-2">
              <p className="text-muted-foreground">Maximum expiry loss</p>
              <p className="mt-1 font-mono font-semibold text-rose-700 dark:text-rose-400">
                ₹{formatNumber(strategy.maximum_loss_per_lot)}
              </p>
            </div>
            <div className="rounded-md border border-border/60 px-3 py-2">
              <p className="text-muted-foreground">Maximum expiry profit</p>
              <p className="mt-1 font-mono font-semibold text-emerald-700 dark:text-emerald-400">
                {strategy.maximum_profit_per_lot == null
                  ? "Not capped"
                  : `₹${formatNumber(strategy.maximum_profit_per_lot)}`}
              </p>
            </div>
          </div>
          {breakEvens.length > 0 && (
            <p className="mt-3 text-[11px] leading-5 text-muted-foreground">
              Expiry break-even{breakEvens.length > 1 ? "s" : ""}:{" "}
              {breakEvens.map((value) => `₹${formatNumber(value)}`).join(" and ")}.
            </p>
          )}
        </div>

        <div className="p-4">
          <div className="flex flex-col justify-between gap-1 sm:flex-row sm:items-center">
            <p className="terminal-label">One-lot P&amp;L across price scenarios</p>
            <p className="text-[10px] text-muted-foreground">
              Excludes brokerage, taxes and slippage
            </p>
          </div>
          <div className="mt-3 h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={payoffData}
                margin={{ top: 8, right: 18, left: 8, bottom: 8 }}
              >
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="price"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tick={{ fontSize: 10 }}
                  tickFormatter={(value) => `₹${formatCompact(Number(value))}`}
                />
                <YAxis
                  tick={{ fontSize: 10 }}
                  width={64}
                  tickFormatter={(value) => `₹${formatCompact(Number(value))}`}
                />
                <Tooltip
                  formatter={(value, name) => [
                    `₹${formatNumber(Number(value))}`,
                    String(name),
                  ]}
                  labelFormatter={(value) =>
                    `Underlying at expiry: ₹${formatNumber(Number(value))}`
                  }
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <ReferenceLine y={0} stroke="currentColor" strokeOpacity={0.45} />
                {strategy.underlying_value != null && (
                  <ReferenceLine
                    x={strategy.underlying_value}
                    stroke="#64748b"
                    strokeDasharray="4 4"
                    label={{ value: "Spot", fontSize: 10 }}
                  />
                )}
                {strategy.lower_break_even != null && (
                  <ReferenceLine
                    x={strategy.lower_break_even}
                    stroke="#d97706"
                    strokeDasharray="3 3"
                  />
                )}
                {strategy.upper_break_even != null && (
                  <ReferenceLine
                    x={strategy.upper_break_even}
                    stroke="#d97706"
                    strokeDasharray="3 3"
                  />
                )}
                <Line
                  type="linear"
                  dataKey="nextSessionPnl"
                  name="Next session at predicted IV"
                  stroke="#059669"
                  strokeWidth={2.5}
                  dot={false}
                />
                <Line
                  type="linear"
                  dataKey="expiryPnl"
                  name="At expiry"
                  stroke="#d97706"
                  strokeWidth={2}
                  strokeDasharray="5 4"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="border-t border-border/70 bg-muted/15 px-4 py-3 text-[11px] leading-5 text-muted-foreground">
        {strategy.limitations.join(" ")} This is an educational scenario, not a
        personalized recommendation or executable order.
      </div>
    </section>
  );
}

function IVSurfaceForecastCard({
  forecast,
  isLoading,
  isError,
  onTrack,
  trackingStrategyId,
  isTracked,
}: {
  forecast?: IVSurfaceForecast;
  isLoading: boolean;
  isError: boolean;
  onTrack: (strategy: IVStrategy) => void;
  trackingStrategyId?: string;
  isTracked: (strategy: IVStrategy) => boolean;
}) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BrainCircuit className="size-4 text-emerald-700 dark:text-emerald-400" />
            Predicted IV versus the option market
          </CardTitle>
          <CardDescription>
            Building the stock&apos;s historical IV surfaces from official NSE daily
            derivatives files. The first uncached run can take about half a minute.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-7 w-2/3" />
          <Skeleton className="h-64 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (isError || !forecast) {
    return (
      <Card>
        <CardContent className="flex items-start gap-3 py-6 text-sm text-muted-foreground">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
          The IV-surface forecast is temporarily unavailable. The live chain remains
          available in the separate Options chain tab.
        </CardContent>
      </Card>
    );
  }

  if (!forecast.available) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BrainCircuit className="size-4 text-emerald-700 dark:text-emerald-400" />
            Predicted IV versus the option market
          </CardTitle>
          <CardDescription>{forecast.summary}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border border-amber-500/30 bg-amber-50/60 px-4 py-3 text-sm leading-6 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
            {forecast.limitation}
          </div>
        </CardContent>
      </Card>
    );
  }

  const isPathDependent = forecast.model_family === "path_dependent_ssvi";

  const chartData = forecast.comparisons.map((item) => ({
    bucket: item.label,
    market: item.market_iv_percent,
    marketCall: item.call_market_iv_percent ?? null,
    marketPut: item.put_market_iv_percent ?? null,
    predicted: item.predicted_iv_percent,
  }));
  const chartValues = chartData
    .flatMap((item) => [item.market, item.marketCall, item.marketPut, item.predicted])
    .filter((value): value is number => value != null);
  const chartMinimum = Math.max(0, Math.floor(Math.min(...chartValues) - 2));
  const chartMaximum = Math.ceil(Math.max(...chartValues) + 2);
  const statusTone =
    forecast.overall_status === "cheap"
      ? "border-sky-500/30 bg-sky-50 text-sky-900 dark:bg-sky-950/25 dark:text-sky-100"
      : forecast.overall_status === "expensive"
        ? "border-amber-500/30 bg-amber-50 text-amber-950 dark:bg-amber-950/25 dark:text-amber-100"
        : "border-emerald-500/30 bg-emerald-50 text-emerald-950 dark:bg-emerald-950/25 dark:text-emerald-100";

  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b border-border/70">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <BrainCircuit className="size-4 text-emerald-700 dark:text-emerald-400" />
              {isPathDependent
                ? "Path-dependent SSVI versus the option market"
                : "FPCA–VAR versus the option market"}
            </CardTitle>
            <CardDescription className="mt-1">
              {forecast.is_carried_forward
                ? `Published ${formatDateTime(forecast.generated_at)} and retained for follow-through to ${forecast.selected_expiry}.`
                : `A next-session ${isPathDependent ? "path-dependent SSVI" : "FPCA–VAR"} forecast compared with the latest market IV for ${forecast.selected_expiry}.`}
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">{ivStatusLabel(forecast.overall_status)}</Badge>
            {forecast.is_carried_forward ? (
              <Badge variant="outline">Refresh pending · forecast preserved</Badge>
            ) : null}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5 pt-5">
        {forecast.is_carried_forward ? (
          <div className="rounded-md border border-amber-500/30 bg-amber-50/60 px-4 py-3 text-xs leading-5 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
            The latest model refresh could not be completed, so this page is preserving
            the last successfully published forecast instead of making it disappear. Its
            IV comparison, premiums and payoff inputs are the original publication
            snapshot—not current entry prices. Existing paper trades below continue to
            use current option marks through expiry.
            {forecast.refresh_limitation ? ` Refresh detail: ${forecast.refresh_limitation}` : ""}
          </div>
        ) : null}
        <div className={`rounded-md border px-4 py-3 text-sm leading-6 ${statusTone}`}>
          {forecast.summary}
        </div>

        {forecast.strategies.length > 0 ? (
          <div className="space-y-4">
            <div className="flex flex-col justify-between gap-1 sm:flex-row sm:items-end">
              <div>
                <p className="terminal-label">
                  {forecast.is_carried_forward
                    ? "Published strategy ideas from the full IV smile"
                    : "Strategy ideas from the full IV smile"}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  Ranked structures using material ATM and OTM mispricing. Every short
                  option has a defined-risk hedge.
                </p>
              </div>
              <Badge variant="outline">
                {forecast.strategies.length} idea{forecast.strategies.length === 1 ? "" : "s"}
              </Badge>
            </div>
            {forecast.strategies.map((candidate) => (
              <IVStrategyPayoffPanel
                key={candidate.strategy_id ?? candidate.strategy_name}
                strategy={candidate}
                onTrack={onTrack}
                isTracking={trackingStrategyId === candidate.strategy_id}
                isTracked={isTracked(candidate)}
                trackingAllowed={!forecast.is_carried_forward}
              />
            ))}
          </div>
        ) : (
          <IVStrategyPayoffPanel
            strategy={forecast.strategy}
            onTrack={onTrack}
            isTracking={false}
            isTracked={false}
            trackingAllowed={!forecast.is_carried_forward}
          />
        )}

        <div className="grid gap-4 lg:grid-cols-[1.35fr_1fr]">
          <div className="rounded-md border border-border/70 p-3">
            <p className="terminal-label mb-3">IV smile comparison</p>
            <div className="h-80 sm:h-96">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 8, right: 28, left: 4, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="bucket" tick={{ fontSize: 10 }} interval={0} />
                  <YAxis
                    domain={[chartMinimum, chartMaximum]}
                    tick={{ fontSize: 10 }}
                    tickFormatter={(value) => `${Number(value).toFixed(0)}%`}
                    width={42}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(value) => [`${Number(value).toFixed(2)}%`]}
                    labelStyle={{ color: "var(--foreground)" }}
                  />
                  <Line
                    type="monotone"
                    dataKey="market"
                    name={forecast.is_carried_forward ? "Market IV at publication" : "Market IV now (ATM average)"}
                    stroke="#d97706"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="marketCall"
                    name="ATM call IV"
                    stroke="#2563eb"
                    strokeWidth={0}
                    dot={{ r: 5, fill: "#2563eb" }}
                    activeDot={{ r: 6 }}
                    connectNulls={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="marketPut"
                    name="ATM put IV"
                    stroke="#be123c"
                    strokeWidth={0}
                    dot={{ r: 5, fill: "#be123c" }}
                    activeDot={{ r: 6 }}
                    connectNulls={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="predicted"
                    name={forecast.is_carried_forward ? "Published next-session IV" : "Predicted next-session IV"}
                    stroke="#047857"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="overflow-hidden rounded-md border border-border/70">
            <div className="border-b border-border/70 bg-muted/25 px-4 py-3">
              <p className="terminal-label">
                {forecast.is_carried_forward
                  ? "Contract-level reading at publication"
                  : "Contract-level reading"}
              </p>
            </div>
            <div className="divide-y divide-border/60">
              {forecast.comparisons.map((item) => (
                <div key={item.label} className="grid grid-cols-[1fr_auto] gap-3 px-4 py-3 text-xs">
                  <div>
                    <p className="font-medium">
                      {item.label} · ₹{formatNumber(item.strike_price, 0)}{" "}
                      {item.side === "call_put" ? "call + put" : item.side}
                    </p>
                    <p className="mt-1 text-muted-foreground">
                      {item.side === "call_put" ? (
                        <>
                          Call {formatPercent(item.call_market_iv_percent)} · put{" "}
                          {formatPercent(item.put_market_iv_percent)} · combined{" "}
                          {formatPercent(item.market_iv_percent)} · forecast{" "}
                          {formatPercent(item.predicted_iv_percent)}
                        </>
                      ) : (
                        <>
                          Market {formatPercent(item.market_iv_percent)} · forecast{" "}
                          {formatPercent(item.predicted_iv_percent)}
                        </>
                      )}
                    </p>
                    <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
                      Forecast error {item.model_error_vol_points.toFixed(2)} pts · required gap{" "}
                      {item.material_threshold_vol_points.toFixed(2)} pts
                      {item.standardized_gap != null
                        ? ` · z ${item.standardized_gap >= 0 ? "+" : ""}${item.standardized_gap.toFixed(2)}`
                        : ""}
                    </p>
                    <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
                      {item.explanation}
                    </p>
                  </div>
                  <div className="text-right">
                    <p
                      className={
                        item.status === "in_line"
                          ? "text-muted-foreground"
                          : item.status === "cheap"
                            ? "text-sky-700 dark:text-sky-400"
                            : "text-amber-700 dark:text-amber-400"
                      }
                    >
                      {item.status === "in_line"
                        ? "In line"
                        : item.status === "cheap"
                          ? "Looks cheap"
                          : "Looks expensive"}
                    </p>
                    <p className="mt-1 font-mono text-muted-foreground">
                      {item.difference_vol_points >= 0 ? "+" : ""}
                      {item.difference_vol_points.toFixed(2)} vol pts
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="grid gap-3 text-[11px] leading-5 text-muted-foreground sm:grid-cols-3">
          <div className="rounded-md bg-muted/30 px-3 py-2">
            <span className="font-medium text-foreground">Training</span>
            <br />
            {forecast.observations} daily surfaces · {forecast.fit_start} to{" "}
            {forecast.fit_end}
          </div>
          <div className="rounded-md bg-muted/30 px-3 py-2">
            <span className="font-medium text-foreground">
              {isPathDependent ? "Four-parameter SSVI" : "FPCA coverage"}
            </span>
            <br />
            {isPathDependent && forecast.ssvi_parameters ? (
              <>
                a {forecast.ssvi_parameters.a.toFixed(4)} · p {forecast.ssvi_parameters.p.toFixed(3)} · ρ {forecast.ssvi_parameters.rho.toFixed(3)} · η {forecast.ssvi_parameters.eta.toFixed(3)}
                <span className="mt-1 block text-[10px] leading-4">
                  {forecast.static_arbitrage_checks?.passed
                    ? "Static-arbitrage checks passed. "
                    : "Static-arbitrage checks require review. "}
                  {forecast.component_selection_note}
                </span>
              </>
            ) : (
              <>
                {forecast.principal_components} components explain{" "}
                {formatPercent(forecast.explained_variance_percent)}
                <span className="mt-1 block text-[10px] leading-4">
                  {forecast.component_selection_note}
                </span>
              </>
            )}
          </div>
          <div className="rounded-md bg-muted/30 px-3 py-2">
            <span className="font-medium text-foreground">Signal rule</span>
            <br />
            A gap must exceed 2 vol points and {isPathDependent ? "1.96×" : "1.5×"} the error from{" "}
            {forecast.validation_sessions} expanding one-session tests.
          </div>
        </div>

        <div className="border-t border-border/70 pt-4 text-[11px] leading-5 text-muted-foreground">
          <p>
            {forecast.method_note} “Cheap” or “expensive” describes a statistical
            difference, not a guaranteed trade or arbitrage.
          </p>
          <p className="mt-1">{forecast.adaptation_note}</p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            <a
              href={forecast.paper_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 font-medium text-emerald-700 hover:underline dark:text-emerald-400"
            >
              Read the {isPathDependent ? "path-dependent SSVI" : "FPCA"} paper <ExternalLink className="size-3" />
            </a>
            <a
              href={forecast.source_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 font-medium text-emerald-700 hover:underline dark:text-emerald-400"
            >
              Open NSE chain <ExternalLink className="size-3" />
            </a>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function PaperIVTradeTracker({
  trades,
  isLoading,
  isError,
  isRefreshing,
  closingTradeId,
  onRefresh,
  onClose,
  title = "Paper strategy tracker",
  description = "Save a suggestion without placing an order. The tracker records what the position cost and what its legs could be closed for later.",
  showCompany = false,
  emptyTitle = "No paper strategies tracked yet",
  emptyDescription = "When a strategy is available above, select “Track one lot.” Its exact expiry, strikes, lot size, model prediction and entry premiums will be saved for comparison on future visits.",
}: {
  trades?: PaperIVTrade[];
  isLoading: boolean;
  isError: boolean;
  isRefreshing: boolean;
  closingTradeId?: string;
  onRefresh: () => void;
  onClose: (tradeId: string) => void;
  title?: string;
  description?: string;
  showCompany?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b border-border/70">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Wallet className="size-4 text-emerald-700 dark:text-emerald-400" />
              {title}
            </CardTitle>
            <CardDescription className="mt-1 max-w-3xl">
              {description}
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={onRefresh}
            disabled={isRefreshing}
          >
            <RefreshCw className={isRefreshing ? "size-3.5 animate-spin" : "size-3.5"} />
            Refresh values
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-5">
        {isLoading ? (
          <Skeleton className="h-52 w-full" />
        ) : isError ? (
          <div className="rounded-md border border-amber-500/30 bg-amber-50/60 px-4 py-3 text-sm text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
            Saved paper positions could not be loaded right now.
          </div>
        ) : !trades?.length ? (
          <div className="rounded-md border border-dashed border-border px-5 py-8 text-center">
            <p className="text-sm font-medium">{emptyTitle}</p>
            <p className="mx-auto mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">
              {emptyDescription}
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {trades.map((trade) => {
              const mark = trade.latest_mark;
              const pnl = mark?.pnl;
              const closeValue = mark ? Math.abs(mark.close_cash_flow) : null;
              const isDebit = trade.entry_premium_type === "debit";
              const history = trade.marks.map((item) => ({
                time: formatDateTime(item.source_timestamp ?? item.created_at),
                pnl: item.pnl,
                closeValue: Math.abs(item.close_cash_flow),
              }));
              const ivHistory = trade.marks
                .filter((item) => item.current_market_iv_percent != null)
                .map((item) => ({
                  time: formatDateTime(item.source_timestamp ?? item.created_at),
                  marketIv: item.current_market_iv_percent,
                  pnlPercent: item.pnl_percent,
                }));
              const entryIv = trade.entry_market_iv_percent;
              const predictedIv = trade.entry_predicted_iv_percent;
              const latestIv = mark?.current_market_iv_percent;
              const expectedIvMove =
                entryIv != null && predictedIv != null ? predictedIv - entryIv : null;
              const observedIvMove =
                entryIv != null && latestIv != null ? latestIv - entryIv : null;
              const targetProgress =
                expectedIvMove != null &&
                observedIvMove != null &&
                Math.abs(expectedIvMove) > 0.01
                  ? (observedIvMove / expectedIvMove) * 100
                  : null;
              const movedTowardTarget =
                entryIv != null &&
                predictedIv != null &&
                latestIv != null &&
                Math.abs(latestIv - predictedIv) < Math.abs(entryIv - predictedIv);
              const targetPredatesEntry = Boolean(
                trade.forecast_for_date &&
                  trade.forecast_for_date < indiaDateKey(trade.created_at)
              );
              return (
                <section
                  key={trade.id}
                  className="overflow-hidden rounded-md border border-border/70"
                >
                  <div className="flex flex-col justify-between gap-3 border-b border-border/70 bg-muted/20 px-4 py-3 sm:flex-row sm:items-start">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        {showCompany && (
                          <Link
                            href={`/company/${encodeURIComponent(trade.ticker)}`}
                            className="font-mono text-xs font-semibold text-emerald-700 hover:underline dark:text-emerald-400"
                          >
                            {trade.ticker}
                          </Link>
                        )}
                        <p className="text-sm font-semibold">{trade.strategy_name}</p>
                        <Badge variant="outline">
                          {trade.status === "open" ? "Open paper trade" : "Closed"}
                        </Badge>
                        {mark?.price_quality === "estimated" && (
                          <Badge variant="outline">Contains last-traded price</Badge>
                        )}
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        Entered {formatDateTime(trade.created_at)} · expiry{" "}
                        {trade.expiry} · {trade.quantity_lots} lot ·{" "}
                        {formatNumber(trade.lot_size * trade.quantity_lots, 0)} units
                      </p>
                      {trade.forecast_generated_at ? (
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          Forecast published {formatDateTime(trade.forecast_generated_at)}
                          {trade.forecast_for_date
                            ? ` · next-session target ${trade.forecast_for_date}`
                            : ""}
                        </p>
                      ) : null}
                    </div>
                    {trade.status === "open" && (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={
                          !mark ||
                          Boolean(trade.valuation_limitation) ||
                          closingTradeId === trade.id
                        }
                        onClick={() => onClose(trade.id)}
                      >
                        {closingTradeId === trade.id
                          ? "Recording exit…"
                          : "Close paper position"}
                      </Button>
                    )}
                  </div>

                  <div className="grid gap-0 xl:grid-cols-[0.9fr_1.25fr]">
                    <div className="border-b border-border/70 p-4 xl:border-b-0 xl:border-r">
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-muted-foreground">
                            {isDebit ? "Total premium paid" : "Entry credit received"}
                          </p>
                          <p className="mt-1 font-mono font-semibold">
                            ₹{formatNumber(Math.abs(trade.entry_cash_flow))}
                          </p>
                        </div>
                        <div className="rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-muted-foreground">
                            {isDebit ? "Current sell value" : "Current buyback cost"}
                          </p>
                          <p className="mt-1 font-mono font-semibold">
                            {closeValue == null ? "—" : `₹${formatNumber(closeValue)}`}
                          </p>
                        </div>
                        <div className="rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-muted-foreground">
                            {trade.status === "closed" ? "Realized P&L" : "P&L if closed now"}
                          </p>
                          <p
                            className={`mt-1 font-mono font-semibold ${
                              pnl == null
                                ? ""
                                : pnl >= 0
                                  ? "text-emerald-700 dark:text-emerald-400"
                                  : "text-rose-700 dark:text-rose-400"
                            }`}
                          >
                            {pnl == null
                              ? "—"
                              : `${pnl >= 0 ? "+" : "−"}₹${formatNumber(Math.abs(pnl))}`}
                          </p>
                        </div>
                        <div className="rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-muted-foreground">Return on capital at risk</p>
                          <p
                            className={`mt-1 font-mono font-semibold ${
                              (mark?.pnl_percent ?? 0) >= 0
                                ? "text-emerald-700 dark:text-emerald-400"
                                : "text-rose-700 dark:text-rose-400"
                            }`}
                          >
                            {mark
                              ? `${mark.pnl_percent >= 0 ? "+" : ""}${formatPercent(mark.pnl_percent)}`
                              : "—"}
                          </p>
                        </div>
                        <div className="rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-muted-foreground">Market IV when published</p>
                          <p className="mt-1 font-mono font-semibold">
                            {formatPercent(trade.entry_market_iv_percent)}
                          </p>
                        </div>
                        <div className="rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-muted-foreground">Published predicted IV</p>
                          <p className="mt-1 font-mono font-semibold">
                            {formatPercent(trade.entry_predicted_iv_percent)}
                          </p>
                        </div>
                        <div className="col-span-2 rounded-md bg-muted/30 px-3 py-2">
                          <p className="text-muted-foreground">Current mean leg IV</p>
                          <p className="mt-1 font-mono font-semibold">
                            {formatPercent(mark?.current_market_iv_percent)}
                          </p>
                        </div>
                      </div>

                      <div className="mt-4 space-y-2">
                        {trade.legs.map((leg, index) => {
                          const currentLeg = mark?.leg_marks[index];
                          return (
                            <div
                              key={`${trade.id}-${leg.option_type}-${leg.strike_price}-${index}`}
                              className="grid grid-cols-[1fr_auto] gap-3 rounded-md border border-border/60 px-3 py-2 text-xs"
                            >
                              <div>
                                <span className="font-semibold">
                                  {leg.action.toUpperCase()}
                                </span>{" "}
                                ₹{formatNumber(leg.strike_price, 0)} {leg.option_type}
                                <p className="mt-0.5 text-[10px] text-muted-foreground">
                                  {currentLeg?.quantity_units ??
                                    trade.lot_size * trade.quantity_lots}{" "}
                                  units
                                </p>
                              </div>
                              <div className="text-right font-mono">
                                <p>Entry ₹{formatNumber(leg.premium_per_unit)}</p>
                                <p className="mt-0.5 text-[10px] text-muted-foreground">
                                  Close{" "}
                                  {currentLeg
                                    ? `₹${formatNumber(currentLeg.close_price_per_unit)} ${currentLeg.close_price_source}`
                                    : "—"}
                                </p>
                                {currentLeg?.current_iv_percent != null ? (
                                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                                    Current IV {formatPercent(currentLeg.current_iv_percent)}
                                  </p>
                                ) : null}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    <div className="p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="terminal-label">Recorded value over time</p>
                        <p className="text-[10px] text-muted-foreground">
                          Latest underlying: ₹{formatNumber(mark?.underlying_value)}
                        </p>
                      </div>
                      {history.length ? (
                        <div className="mt-3 h-64">
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart
                              data={history}
                              margin={{ top: 8, right: 18, left: 8, bottom: 8 }}
                            >
                              <CartesianGrid strokeDasharray="3 3" vertical={false} />
                              <XAxis dataKey="time" tick={{ fontSize: 9 }} />
                              <YAxis
                                tick={{ fontSize: 10 }}
                                width={64}
                                tickFormatter={(value) =>
                                  `₹${formatCompact(Number(value))}`
                                }
                              />
                              <Tooltip
                                formatter={(value, name) => [
                                  `₹${formatNumber(Number(value))}`,
                                  String(name),
                                ]}
                              />
                              <Legend wrapperStyle={{ fontSize: 11 }} />
                              <ReferenceLine
                                y={0}
                                stroke="currentColor"
                                strokeOpacity={0.4}
                              />
                              <Line
                                type="monotone"
                                dataKey="closeValue"
                                name={isDebit ? "Sell value" : "Buyback cost"}
                                stroke="#64748b"
                                strokeWidth={2}
                                dot={{ r: 2.5 }}
                              />
                              <Line
                                type="monotone"
                                dataKey="pnl"
                                name="P&L"
                                stroke="#059669"
                                strokeWidth={2.5}
                                dot={{ r: 3 }}
                              />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      ) : (
                        <div className="mt-3 rounded-md bg-muted/25 px-4 py-8 text-center text-xs text-muted-foreground">
                          No usable close-price mark is available yet.
                        </div>
                      )}
                      {ivHistory.length ? (
                        <div className="mt-5">
                          <div className="flex flex-col justify-between gap-1 sm:flex-row sm:items-center">
                            <p className="terminal-label">IV follow-through</p>
                            <p className="text-[10px] text-muted-foreground">
                              Published next-session target versus each saved market observation
                            </p>
                          </div>
                          {entryIv != null && predictedIv != null && latestIv != null ? (
                            <div className="mt-3 rounded-md border border-border/70 bg-muted/20 p-3">
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge
                                  variant="outline"
                                  className={
                                    movedTowardTarget
                                      ? "border-emerald-500/40 text-emerald-700 dark:text-emerald-400"
                                      : "border-rose-500/40 text-rose-700 dark:text-rose-400"
                                  }
                                >
                                  {movedTowardTarget
                                    ? "IV moved toward forecast"
                                    : "IV moved away from forecast"}
                                </Badge>
                                <span className="font-mono text-[10px] text-muted-foreground">
                                  Target progress {targetProgress == null ? "—" : `${targetProgress >= 0 ? "+" : ""}${targetProgress.toFixed(1)}%`}
                                </span>
                              </div>
                              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                                The model expected IV to {expectedIvMove! >= 0 ? "rise" : "fall"}{" "}
                                {Math.abs(expectedIvMove!).toFixed(2)} points from {entryIv.toFixed(2)}%
                                to {predictedIv.toFixed(2)}%. The latest saved observation is{" "}
                                {latestIv.toFixed(2)}%, a {Math.abs(observedIvMove!).toFixed(2)}-point{" "}
                                {observedIvMove! >= 0 ? "increase" : "decrease"} from entry.
                              </p>
                              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                                {movedTowardTarget
                                  ? mark && mark.pnl < 0
                                    ? "The broad IV path supported the forecast, but the trade still lost money. Underlying-price movement, strike-specific skew, time decay and bid–ask changes outweighed that IV move."
                                    : "The IV path moved in the forecast direction and is consistent with the trade outcome, although option P&L also includes spot movement, time decay, skew and bid–ask changes."
                                  : mark && mark.pnl < 0
                                    ? `IV moved ${expectedIvMove! >= 0 ? "down when the forecast required a rise" : "up when the forecast required a fall"}; that was a direct headwind for this trade. Spot movement, time decay, skew and bid–ask changes also affect the loss.`
                                    : "IV did not move toward the forecast, so any positive P&L came from other option-price effects such as the underlying move, time decay, skew or execution quotes."}
                              </p>
                              {targetPredatesEntry ? (
                                <p className="mt-2 rounded border border-amber-500/30 bg-amber-50/60 px-2.5 py-2 text-[11px] leading-4 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
                                  Important: this next-session forecast targeted {trade.forecast_for_date},
                                  which was already before the paper-trade entry. Treat it as a stale model
                                  snapshot, not a fresh forecast made for the entry session.
                                </p>
                              ) : null}
                            </div>
                          ) : null}
                          <div className="mt-2 h-48">
                            <ResponsiveContainer width="100%" height="100%">
                              <LineChart
                                data={ivHistory}
                                margin={{ top: 8, right: 18, left: 8, bottom: 8 }}
                              >
                                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                <XAxis dataKey="time" tick={{ fontSize: 9 }} />
                                <YAxis
                                  tick={{ fontSize: 10 }}
                                  width={48}
                                  tickFormatter={(value) => `${Number(value).toFixed(1)}%`}
                                  domain={["auto", "auto"]}
                                />
                                <Tooltip
                                  formatter={(value) => [
                                    `${Number(value).toFixed(2)}%`,
                                    "Current mean leg IV",
                                  ]}
                                />
                                {trade.entry_market_iv_percent != null ? (
                                  <ReferenceLine
                                    y={trade.entry_market_iv_percent}
                                    stroke="#d97706"
                                    strokeDasharray="4 4"
                                    label={{ value: "Entry market IV", fontSize: 9 }}
                                  />
                                ) : null}
                                {trade.entry_predicted_iv_percent != null ? (
                                  <ReferenceLine
                                    y={trade.entry_predicted_iv_percent}
                                    stroke="#047857"
                                    strokeDasharray="4 4"
                                    label={{ value: "Predicted IV", fontSize: 9 }}
                                  />
                                ) : null}
                                <Line
                                  type="monotone"
                                  dataKey="marketIv"
                                  name="Observed mean leg IV"
                                  stroke="#2563eb"
                                  strokeWidth={2.5}
                                  dot={{ r: 2.5 }}
                                />
                              </LineChart>
                            </ResponsiveContainer>
                          </div>
                          <div className="mt-3 max-h-56 overflow-auto rounded-md border border-border/70">
                            <table className="w-full min-w-[560px] text-left text-[11px]">
                              <thead className="sticky top-0 bg-muted/90 text-muted-foreground backdrop-blur">
                                <tr>
                                  <th className="px-3 py-2 font-medium">Observation</th>
                                  <th className="px-3 py-2 font-medium">Observed IV</th>
                                  <th className="px-3 py-2 font-medium">Move from entry</th>
                                  <th className="px-3 py-2 font-medium">Gap to target</th>
                                  <th className="px-3 py-2 font-medium">Trade P&amp;L</th>
                                </tr>
                              </thead>
                              <tbody>
                                {ivHistory.map((point, index) => (
                                  <tr key={`${trade.id}-iv-${point.time}-${index}`} className="border-t border-border/60">
                                    <td className="px-3 py-2">{point.time}</td>
                                    <td className="px-3 py-2 font-mono">{Number(point.marketIv).toFixed(2)}%</td>
                                    <td className="px-3 py-2 font-mono">
                                      {entryIv == null
                                        ? "—"
                                        : `${Number(point.marketIv) - entryIv >= 0 ? "+" : ""}${(Number(point.marketIv) - entryIv).toFixed(2)} pts`}
                                    </td>
                                    <td className="px-3 py-2 font-mono">
                                      {predictedIv == null
                                        ? "—"
                                        : `${Number(point.marketIv) - predictedIv >= 0 ? "+" : ""}${(Number(point.marketIv) - predictedIv).toFixed(2)} pts`}
                                    </td>
                                    <td className={`px-3 py-2 font-mono ${point.pnlPercent >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400"}`}>
                                      {point.pnlPercent >= 0 ? "+" : ""}{point.pnlPercent.toFixed(2)}%
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          <p className="mt-2 text-[10px] leading-4 text-muted-foreground">
                            Older observations are reconstructed from the underlying and executable
                            close-out quotes saved at that time; later observations retain NSE-reported
                            IV when available. The published value is a one-session forecast, so later
                            points measure follow-through rather than extending its original horizon.
                          </p>
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div className="border-t border-border/70 bg-muted/15 px-4 py-3 text-[11px] leading-5 text-muted-foreground">
                    {trade.valuation_limitation ? (
                      <span className="text-amber-700 dark:text-amber-400">
                        {trade.valuation_limitation}
                      </span>
                    ) : mark?.price_quality === "executable" ? (
                      "Current value uses bids to sell owned options and asks to buy back short options."
                    ) : (
                      "At least one live exit quote was unavailable, so its last-traded price is used and the mark is only an estimate."
                    )}{" "}
                    Brokerage, taxes, slippage and margin changes are excluded.
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function IVPredictionWorkspace({ ticker }: { ticker: string }) {
  const [expiry, setExpiry] = useState("");
  const [portfolioId, setPortfolioId] = useState<string>();
  const queryClient = useQueryClient();
  useEffect(() => {
    const storageKey = "easy-invest-paper-portfolio-id";
    const existing = window.localStorage.getItem(storageKey);
    let resolved = existing;
    if (!resolved) {
      resolved = window.crypto.randomUUID();
      window.localStorage.setItem(storageKey, resolved);
    }
    const frame = window.requestAnimationFrame(() => setPortfolioId(resolved));
    return () => window.cancelAnimationFrame(frame);
  }, []);
  const options = useQuery({
    queryKey: ["company-options-chain", ticker, expiry],
    queryFn: () => api.getCompanyOptionsChain(ticker, expiry || undefined),
    staleTime: 5 * 60 * 1000,
  });
  const selectedPrimaryExpiry = options.data?.selected_expiry ?? expiry;
  const ivForecast = useQuery({
    queryKey: ["company-iv-surface-forecast", ticker, selectedPrimaryExpiry],
    queryFn: () =>
      api.getCompanyIVSurfaceForecast(ticker, selectedPrimaryExpiry || undefined),
    staleTime: 5 * 60 * 1000,
    enabled: Boolean(options.data?.available && selectedPrimaryExpiry),
  });
  const pathDependentForecast = useQuery({
    queryKey: ["company-path-dependent-iv-surface-forecast", ticker, selectedPrimaryExpiry],
    queryFn: () =>
      api.getCompanyPathDependentIVSurfaceForecast(
        ticker,
        selectedPrimaryExpiry || undefined
      ),
    staleTime: 5 * 60 * 1000,
    enabled: Boolean(options.data?.available && selectedPrimaryExpiry),
  });
  const paperTrades = useQuery({
    queryKey: ["company-paper-iv-trades", ticker, portfolioId],
    queryFn: () => api.listCompanyPaperIVTrades(ticker, portfolioId!),
    enabled: Boolean(portfolioId),
    staleTime: 60 * 1000,
    refetchOnWindowFocus: true,
  });
  const createPaperTrade = useMutation({
    mutationFn: ({
      tradeExpiry,
      strategyId,
      modelFamily,
    }: {
      tradeExpiry: string;
      strategyId: string;
      modelFamily: "fpca_var" | "path_dependent_ssvi";
    }) =>
      api.createCompanyPaperIVTrade(
        ticker,
        portfolioId!,
        tradeExpiry,
        strategyId,
        1,
        modelFamily
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["company-paper-iv-trades", ticker, portfolioId],
      }),
  });
  const closePaperTrade = useMutation({
    mutationFn: (tradeId: string) =>
      api.closeCompanyPaperIVTrade(ticker, portfolioId!, tradeId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["company-paper-iv-trades", ticker, portfolioId],
      }),
  });
  const isStrategyTracked = (strategy: IVStrategy) =>
    Boolean(
      strategy.available &&
        paperTrades.data?.some(
          (trade) =>
            trade.status === "open" &&
            trade.expiry === strategy.expiry &&
            trade.strategy_name === strategy.strategy_name
        )
    );
  const trackingError =
    createPaperTrade.error instanceof Error
      ? createPaperTrade.error.message
      : closePaperTrade.error instanceof Error
        ? closePaperTrade.error.message
        : null;

  return (
    <div className="space-y-5">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <p className="page-eyebrow">Volatility research</p>
          <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em]">
            IV prediction and strategy scenarios
          </h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
            Compare the option market&apos;s current IV with both the existing FPCA–VAR
            forecast and the paper&apos;s path-dependent SSVI challenger. Material ATM and OTM differences are translated into ranked,
            defined-risk structures with one-lot expiry P&amp;L scenarios. Once
            published, a forecast is retained through the selected expiry even if a
            later model refresh cannot be completed.
          </p>
        </div>
        {options.data && options.data.expiry_dates.length > 0 && (
          <div className="flex flex-wrap gap-3 rounded-md border border-border bg-card p-3">
            <label className="space-y-1 text-xs text-muted-foreground">
              <span className="block font-medium text-foreground">Primary expiry</span>
              <select
                value={selectedPrimaryExpiry || ""}
                onChange={(event) => setExpiry(event.target.value)}
                className="h-9 min-w-36 rounded-md border border-input bg-background px-3 font-mono text-xs text-foreground shadow-xs outline-none focus:border-ring"
              >
                {options.data.expiry_dates.map((date) => (
                  <option key={date} value={date}>{date}</option>
                ))}
              </select>
            </label>
          </div>
        )}
      </div>

      {options.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : options.isError || !options.data ? (
        <Card>
          <CardContent className="py-8 text-sm text-muted-foreground">
            The IV prediction workspace is temporarily unavailable.
          </CardContent>
        </Card>
      ) : (
        <IVSurfaceForecastCard
          forecast={ivForecast.data}
          isLoading={ivForecast.isLoading && ivForecast.fetchStatus !== "idle"}
          isError={ivForecast.isError}
          onTrack={(candidate) => {
            if (candidate.expiry && candidate.strategy_id && portfolioId) {
              createPaperTrade.mutate({
                tradeExpiry: candidate.expiry,
                strategyId: candidate.strategy_id,
                modelFamily: "fpca_var",
              });
            }
          }}
          trackingStrategyId={
            createPaperTrade.isPending
              ? createPaperTrade.variables?.strategyId
              : undefined
          }
          isTracked={isStrategyTracked}
        />
      )}

      {options.data?.available ? (
        <IVSurfaceForecastCard
          forecast={pathDependentForecast.data}
          isLoading={
            pathDependentForecast.isLoading &&
            pathDependentForecast.fetchStatus !== "idle"
          }
          isError={pathDependentForecast.isError}
          onTrack={(candidate) => {
            if (candidate.expiry && candidate.strategy_id && portfolioId) {
              createPaperTrade.mutate({
                tradeExpiry: candidate.expiry,
                strategyId: candidate.strategy_id,
                modelFamily: "path_dependent_ssvi",
              });
            }
          }}
          trackingStrategyId={
            createPaperTrade.isPending
              ? createPaperTrade.variables?.strategyId
              : undefined
          }
          isTracked={isStrategyTracked}
        />
      ) : null}

      {trackingError && (
        <div className="rounded-md border border-amber-500/30 bg-amber-50/60 px-4 py-3 text-xs leading-5 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
          The paper position could not be updated. {trackingError}
        </div>
      )}

      <PaperIVTradeTracker
        trades={paperTrades.data}
        isLoading={!portfolioId || paperTrades.isLoading}
        isError={paperTrades.isError}
        isRefreshing={paperTrades.isFetching}
        closingTradeId={
          closePaperTrade.isPending ? closePaperTrade.variables : undefined
        }
        onRefresh={() => paperTrades.refetch()}
        onClose={(tradeId) => closePaperTrade.mutate(tradeId)}
      />

      <div className="flex flex-col gap-2 rounded-md border border-border/70 bg-muted/25 px-4 py-3 text-[11px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span className="inline-flex items-center gap-1.5">
          <Activity className="size-3.5" />
          Both surface forecasts are statistical next-session scenarios; payoff charts
          show expiry outcomes using the displayed publication premiums. Saved paper
          positions are followed using current close-out quotes through expiry. NSE
          stock options are physically settled.
        </span>
        <span>Source: NSE India · Educational research only</span>
      </div>
    </div>
  );
}

export function OptionsChainWorkspace({ ticker }: { ticker: string }) {
  const [expiry, setExpiry] = useState("");
  const options = useQuery({
    queryKey: ["company-options-chain", ticker, expiry],
    queryFn: () => api.getCompanyOptionsChain(ticker, expiry || undefined),
    staleTime: 5 * 60 * 1000,
  });
  const selectedPrimaryExpiry = options.data?.selected_expiry ?? expiry;

  return (
    <div className="space-y-5">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <p className="page-eyebrow">NSE derivatives</p>
          <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em]">
            Listed stock options
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Inspect the option chain and implied terminal-price distribution for one expiry.
          </p>
        </div>
        {options.data && options.data.expiry_dates.length > 0 && (
          <div className="flex flex-wrap gap-3 rounded-md border border-border bg-card p-3">
            <label className="space-y-1 text-xs text-muted-foreground">
              <span className="block font-medium text-foreground">Primary expiry</span>
              <select
                value={selectedPrimaryExpiry || ""}
                onChange={(event) => setExpiry(event.target.value)}
                className="h-9 min-w-36 rounded-md border border-input bg-background px-3 font-mono text-xs text-foreground shadow-xs outline-none focus:border-ring"
              >
                {options.data.expiry_dates.map((date) => (
                  <option key={date} value={date}>{date}</option>
                ))}
              </select>
            </label>
          </div>
        )}
      </div>

      {options.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : options.isError || !options.data ? (
        <Card>
          <CardContent className="py-8 text-sm text-muted-foreground">
            The NSE option-chain feed is temporarily unavailable.
          </CardContent>
        </Card>
      ) : (
        <OptionsTable chain={options.data} />
      )}

      <div className="flex flex-col gap-2 rounded-md border border-border/70 bg-muted/25 px-4 py-3 text-[11px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span className="inline-flex items-center gap-1.5">
          <Activity className="size-3.5" />
          Options data can be delayed and appears only for NSE-listed derivatives.
        </span>
        <span>Source: NSE India · Not investment advice</span>
      </div>
    </div>
  );
}
