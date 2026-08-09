"use client";

import { CitationList } from "@/components/citation-list";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  api,
  type Citation,
  type CompanyChatResponse,
} from "@/lib/api";
import { useMutation } from "@tanstack/react-query";
import {
  BarChart3,
  BrainCircuit,
  Loader2,
  MessageSquareText,
  SendHorizonal,
  Sparkles,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

type ChatTurn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  result?: CompanyChatResponse;
};

const SUGGESTIONS = [
  {
    label: "Valuation",
    question: "Explain this company’s valuation and profitability ratios.",
  },
  {
    label: "Technicals",
    question: "What do the daily RSI, MACD, momentum and trend indicators say right now?",
  },
  {
    label: "Options",
    question: "Summarize the nearest options expiry, open interest and implied price distribution.",
  },
  {
    label: "Deep research",
    question: "What recent developments could materially affect this business? Include the counter-case.",
  },
  {
    label: "Balanced view",
    question:
      "I’m considering buying this stock. Give me a balanced short- and medium-term evidence assessment and confidence rating.",
  },
];

function viewClasses(view: string | null | undefined) {
  if (view === "positive") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700";
  if (view === "negative") return "border-rose-500/30 bg-rose-500/10 text-rose-700";
  return "border-amber-500/30 bg-amber-500/10 text-amber-700";
}

export function CompanyChat({
  ticker,
  companyName,
}: {
  ticker: string;
  companyName: string;
}) {
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  const send = useMutation({
    mutationFn: (question: string) =>
      api.chatAboutCompany(
        ticker,
        question,
        turns.map(({ role, content }) => ({ role, content }))
      ),
    onMutate: (question) => {
      setTurns((current) => [
        ...current,
        {
          id: `user-${Date.now()}`,
          role: "user",
          content: question,
        },
      ]);
      setMessage("");
    },
    onSuccess: (result) => {
      setTurns((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: result.answer,
          result,
        },
      ]);
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns.length, send.isPending]);

  const submit = (question: string) => {
    const clean = question.trim();
    if (clean && !send.isPending) send.mutate(clean);
  };

  return (
    <section id="company-research-chat" className="overflow-hidden rounded-lg border bg-card">
      <div className="grid border-b border-border/80 lg:grid-cols-[1fr_auto]">
        <div className="p-5 sm:p-6">
          <div className="flex items-center gap-2">
            <span className="grid size-9 place-items-center rounded-md bg-primary text-primary-foreground">
              <BrainCircuit className="size-4" />
            </span>
            <div>
              <p className="page-eyebrow">Company research assistant</p>
              <h2 className="mt-0.5 text-lg font-semibold tracking-[-0.025em]">
                Ask about {ticker}
              </h2>
            </div>
          </div>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
            Llama answers only about {companyName}, using calculated ratios,
            technical indicators, NSE options, statistical scenarios, verified
            filings, and Tavily-backed current research when relevant.
          </p>
        </div>
        <div className="flex items-center gap-2 border-t border-border/80 bg-muted/30 px-5 py-4 lg:border-l lg:border-t-0">
          <Sparkles className="size-4 text-emerald-700" />
          <div>
            <p className="text-xs font-medium">Grounded responses</p>
            <p className="text-[11px] text-muted-foreground">
              Sources and limitations included
            </p>
          </div>
        </div>
      </div>

      <div className="grid min-h-[520px] lg:grid-cols-[260px_1fr]">
        <aside className="border-b border-border/80 bg-muted/20 p-4 lg:border-b-0 lg:border-r">
          <p className="terminal-label mb-3">Suggested questions</p>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion.label}
                type="button"
                disabled={send.isPending}
                onClick={() => setMessage(suggestion.question)}
                className="rounded-md border bg-card p-3 text-left transition-colors hover:border-input hover:bg-muted/50 disabled:opacity-50"
              >
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-emerald-700">
                  {suggestion.label}
                </span>
                <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                  {suggestion.question}
                </span>
              </button>
            ))}
          </div>
        </aside>

        <div className="flex min-h-0 flex-col p-4 sm:p-5">
          <div className="max-h-[560px] min-h-[340px] flex-1 space-y-3 overflow-y-auto pr-1">
            {turns.length === 0 && !send.isPending && (
              <div className="grid min-h-[320px] place-items-center rounded-lg border border-dashed bg-muted/15 p-8 text-center">
                <div className="max-w-md">
                  <span className="mx-auto grid size-11 place-items-center rounded-full bg-secondary">
                    <MessageSquareText className="size-5" />
                  </span>
                  <p className="mt-4 text-sm font-medium">
                    Start with a preset or ask your own question
                  </p>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    For technical questions, include a timeframe if you want
                    something other than the default daily view.
                  </p>
                </div>
              </div>
            )}

            {turns.map((turn) => (
              <div
                key={turn.id}
                className={`rounded-lg p-3.5 text-sm ${
                  turn.role === "user"
                    ? "ml-8 rounded-br-sm bg-primary text-primary-foreground"
                    : "mr-3 rounded-bl-sm border bg-muted/45"
                }`}
              >
                {turn.role === "assistant" && turn.result && (
                  <div className="mb-2 flex flex-wrap items-center gap-1.5">
                    <Badge variant="outline" className="capitalize">
                      {turn.result.intent.replace(/_/g, " ")}
                    </Badge>
                    {turn.result.short_term_view && (
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold capitalize ${viewClasses(
                          turn.result.short_term_view
                        )}`}
                      >
                        Short term: {turn.result.short_term_view}
                      </span>
                    )}
                    {turn.result.medium_term_view && (
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold capitalize ${viewClasses(
                          turn.result.medium_term_view
                        )}`}
                      >
                        Medium term: {turn.result.medium_term_view}
                      </span>
                    )}
                    {turn.result.confidence_percent != null && (
                      <span className="text-[10px] text-muted-foreground">
                        {turn.result.confidence_label} confidence ·{" "}
                        {turn.result.confidence_percent}%
                      </span>
                    )}
                  </div>
                )}
                <p className="whitespace-pre-wrap leading-6">{turn.content}</p>
                {turn.result?.citations.length ? (
                  <details className="mt-3 border-t border-current/10 pt-2">
                    <summary className="cursor-pointer text-xs opacity-70">
                      {turn.result.citations.length} source
                      {turn.result.citations.length === 1 ? "" : "s"}
                    </summary>
                    <CitationList
                      citations={turn.result.citations as Citation[]}
                    />
                  </details>
                ) : null}
                {turn.result?.data_used.length ? (
                  <p className="mt-2 text-[11px] opacity-60">
                    Used: {turn.result.data_used.join(" · ")}
                  </p>
                ) : null}
                {turn.result?.limitations.length ? (
                  <details className="mt-1 text-[11px] opacity-60">
                    <summary className="cursor-pointer">
                      {turn.result.limitations.length} limitation
                      {turn.result.limitations.length === 1 ? "" : "s"}
                    </summary>
                    <ul className="mt-1 list-disc space-y-1 pl-4">
                      {turn.result.limitations.map((limitation) => (
                        <li key={limitation}>{limitation}</li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </div>
            ))}

            {send.isPending && (
              <div className="mr-3 flex items-center gap-2 rounded-lg rounded-bl-sm border bg-muted/45 p-3.5 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Calculating the relevant company evidence and asking Llama…
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <form
            className="mt-4 flex gap-2 border-t pt-4"
            onSubmit={(event) => {
              event.preventDefault();
              submit(message);
            }}
          >
            <Textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder={`Ask a question about ${ticker}…`}
              className="max-h-32 min-h-11 resize-none bg-background"
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  submit(message);
                }
              }}
            />
            <Button
              type="submit"
              size="icon"
              className="size-11 shrink-0"
              disabled={!message.trim() || send.isPending}
              aria-label="Send company question"
            >
              <SendHorizonal className="size-4" />
            </Button>
          </form>
          {send.isError && (
            <p className="mt-2 text-xs text-destructive">
              {String(send.error)}
            </p>
          )}
          <div className="mt-2 flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <BarChart3 className="size-3" />
            Research information only — not investment advice.
          </div>
        </div>
      </div>
    </section>
  );
}
