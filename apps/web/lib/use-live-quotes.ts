"use client";

import { technicalQuoteStreamUrl } from "@/lib/api";
import { useEffect, useState } from "react";

export type LiveQuote = {
  ticker: string;
  symbol: string;
  price: number;
  event_time: string;
  received_at: string;
  market_hours: number | null;
};

export function useLiveQuotes(tickers: string[], enabled = true) {
  const [quotes, setQuotes] = useState<Record<string, LiveQuote>>({});
  const tickerKey = [...new Set(tickers.map((ticker) => ticker.trim().toUpperCase()))]
    .filter(Boolean)
    .sort()
    .join(",");

  useEffect(() => {
    if (!enabled || !tickerKey) return;
    const activeTickers = tickerKey.split(",");
    const tickerShards = Array.from(
      { length: Math.ceil(activeTickers.length / 50) },
      (_, index) => activeTickers.slice(index * 50, (index + 1) * 50)
    );
    const sockets = new Set<WebSocket>();
    const reconnectTimers = new Set<ReturnType<typeof setTimeout>>();
    let stopped = false;

    const connect = (tickers: string[]) => {
      const socket = new WebSocket(technicalQuoteStreamUrl(tickers));
      sockets.add(socket);
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { type: string; quotes: LiveQuote[] };
          if (payload.type !== "quotes") return;
          setQuotes((current) => {
            const next = { ...current };
            let changed = false;
            for (const quote of payload.quotes) {
              if (current[quote.ticker]?.received_at !== quote.received_at) {
                next[quote.ticker] = quote;
                changed = true;
              }
            }
            return changed ? next : current;
          });
        } catch {
          // Keep the last valid quote when a best-effort message is malformed.
        }
      };
      socket.onclose = () => {
        sockets.delete(socket);
        if (!stopped) {
          const timer = setTimeout(() => {
            reconnectTimers.delete(timer);
            connect(tickers);
          }, 1_000);
          reconnectTimers.add(timer);
        }
      };
    };

    tickerShards.forEach(connect);
    return () => {
      stopped = true;
      reconnectTimers.forEach(clearTimeout);
      sockets.forEach((socket) => socket.close());
    };
  }, [enabled, tickerKey]);

  return quotes;
}
