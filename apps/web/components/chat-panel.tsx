"use client";

import { api, type ChatMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { CitationList } from "@/components/citation-list";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, SendHorizonal, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const SUGGESTIONS = [
  "Why did the first company rank above the second?",
  "Which of these companies has discussed customer concentration?",
  "Could the first result be affected by a recent geopolitical conflict? Research the latest evidence and counter-case.",
  "Increase the market-cap tolerance to 70%.",
  "Exclude the last company from the results.",
];

export function ChatPanel({ searchId }: { searchId: string }) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const messages = useQuery({
    queryKey: ["messages", searchId],
    queryFn: () => api.getMessages(searchId),
  });

  const send = useMutation({
    mutationFn: (text: string) => api.followUp(searchId, text),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["messages", searchId] });
      queryClient.invalidateQueries({ queryKey: ["search", searchId] });
      setMessage("");
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.data?.length, send.isPending]);

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex-1 space-y-3 overflow-y-auto pr-1">
        {(messages.data ?? []).map((m: ChatMessage) => (
          <div
            key={m.id}
            className={`rounded-lg p-3.5 text-sm ${
              m.role === "user"
                ? "ml-8 rounded-br-md bg-primary text-primary-foreground"
                : "mr-3 rounded-bl-md border border-border/70 bg-muted/65"
            }`}
          >
            {m.intent && m.role === "assistant" && (
              <p className="text-[10px] uppercase tracking-wide opacity-60 mb-1">
                {m.intent.replace(/_/g, " ")}
              </p>
            )}
            <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
            {m.citations?.length > 0 && (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs opacity-70">
                  {m.citations.length} citation(s)
                </summary>
                <div className="mt-1">
                  <CitationList citations={m.citations} />
                </div>
              </details>
            )}
            {m.limitations?.length > 0 && (
              <p className="mt-1 text-xs opacity-60">
                Limitations: {m.limitations.join("; ")}
              </p>
            )}
          </div>
        ))}
        {send.isPending && (
          <div className="mr-3 flex items-center gap-2 rounded-lg rounded-bl-sm border border-border bg-muted/65 p-3.5 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Researching filings, current news, and
            counterevidence…
          </div>
        )}
        {messages.data?.length === 0 && !send.isPending && (
          <div className="space-y-3 text-xs text-muted-foreground">
            <div className="grid size-9 place-items-center rounded-md bg-secondary text-secondary-foreground">
              <Sparkles className="size-4" />
            </div>
            <p className="leading-5">
              Ask grounded follow-up questions, run deep research on current events, or modify
              the search conversationally.
            </p>
            <div className="flex flex-col items-start gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => setMessage(s)}
                  className="w-full rounded-md border border-border bg-card px-3 py-2 text-left leading-4 transition-colors hover:border-input hover:bg-muted/60 hover:text-foreground"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <form
        className="mt-3 flex gap-2 border-t border-border/70 pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (message.trim() && !send.isPending) send.mutate(message.trim());
        }}
      >
        <Textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Ask about these results…"
          className="max-h-32 min-h-10 resize-none bg-card"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (message.trim() && !send.isPending) send.mutate(message.trim());
            }
          }}
        />
        <Button type="submit" size="icon" disabled={!message.trim() || send.isPending}>
          <SendHorizonal className="size-4" />
        </Button>
      </form>
      {send.isError && (
        <p className="mt-1 text-xs text-destructive">{String(send.error)}</p>
      )}
    </div>
  );
}
