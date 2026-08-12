"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, FlaskConical, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";

function metric(value?: number | null, suffix = "", digits = 2) {
  return value == null || !Number.isFinite(value)
    ? "—"
    : `${value.toFixed(digits)}${suffix}`;
}

function dateTime(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  }).format(new Date(value));
}

export function IVModelValidationView() {
  const queryClient = useQueryClient();
  const report = useQuery({
    queryKey: ["iv-model-evaluation"],
    queryFn: api.getIVModelEvaluation,
    refetchInterval: 60_000,
  });
  const run = useMutation({
    mutationFn: () => api.runIVModelEvaluation(30),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["iv-model-evaluation"] }),
  });

  if (report.isLoading) {
    return <div className="mx-auto max-w-[1500px] p-6"><Skeleton className="h-[620px] w-full" /></div>;
  }
  if (report.isError || !report.data) {
    return (
      <div className="mx-auto max-w-[1500px] p-6">
        <div className="rounded-md border border-amber-500/30 bg-amber-50/60 p-4 text-sm text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
          The IV validation report could not be loaded. Check the API and database migration.
        </div>
      </div>
    );
  }

  const data = report.data;
  const progress = Math.min(100, data.scored_forecasts / data.evidence_target * 100);
  const fpcaHealthy = (data.average_explained_variance_percent ?? 0) >= data.thresholds.fpca_explained_variance_healthy_percent;
  const varBeatsBaseline = (data.improvement_over_baseline_percent ?? -Infinity) > 0;
  const historical = data.historical_backtest;
  const collection = run.data?.collection;

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <section className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="flex flex-col justify-between gap-4 border-b border-border/70 px-5 py-5 lg:flex-row lg:items-end">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <p className="page-eyebrow">System · model governance</p>
              <Badge variant="outline"><FlaskConical className="mr-1 size-3" /> Forward test</Badge>
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">FPCA–VAR validation lab</h1>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">
              Each forecast is frozen before its NSE target session opens, then compared with the official next-session IV surface and a no-change forecast. These results diagnose whether surface compression or score forecasting needs to change.
            </p>
          </div>
          <Button onClick={() => run.mutate()} disabled={run.isPending}>
            <RefreshCw className={run.isPending ? "size-4 animate-spin" : "size-4"} />
            {run.isPending ? "Collecting eligible surfaces…" : "Run collection and scoring"}
          </Button>
        </div>
        <div className="grid gap-px bg-border/70 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Clean forecasts scored", `${data.scored_forecasts}/${data.evidence_target}`],
            ["Pending next session", String(data.pending_forecasts)],
            ["Stocks represented", String(data.covered_symbols)],
            ["Model win rate", metric(data.model_win_rate_percent, "%")],
          ].map(([label, value]) => (
            <div key={label} className="bg-card px-5 py-4">
              <p className="terminal-label">{label}</p>
              <p className="mt-2 font-mono text-xl font-semibold">{value}</p>
            </div>
          ))}
        </div>
      </section>

      <Card>
        <CardHeader className="border-b border-border/70">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2 text-base"><Activity className="size-4 text-emerald-600" /> Evidence progress</CardTitle>
            <Badge variant="outline">{data.verdict}</Badge>
          </div>
        </CardHeader>
        <CardContent className="pt-5">
          <div className="h-3 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-emerald-600 transition-[width]" style={{ width: `${progress}%` }} />
          </div>
          <div className="mt-2 flex justify-between font-mono text-[10px] text-muted-foreground"><span>{data.scored_forecasts} scored</span><span>{data.evidence_target} minimum</span></div>
          <p className="mt-4 text-sm leading-6">{data.verdict_detail}</p>
          {collection ? (
            <p className="mt-3 rounded-md bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              Latest run: {collection.created} new forecasts recorded, {collection.skipped} skipped from {collection.attempted} attempted. A skipped forecast is never backdated after its session begins.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="text-base">1. Does FPCA represent the surface?</CardTitle></CardHeader>
          <CardContent className="space-y-4 pt-5">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Variance retained</p><p className="mt-2 font-mono text-xl font-semibold">{metric(data.average_explained_variance_percent, "%")}</p></div>
              <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Reconstruction RMSE</p><p className="mt-2 font-mono text-xl font-semibold">{metric(data.average_reconstruction_rmse, " pts")}</p></div>
            </div>
            <div className="flex gap-2 text-sm">
              {fpcaHealthy ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />}
              <p className="leading-5 text-muted-foreground">Healthy band: at least {data.thresholds.fpca_explained_variance_healthy_percent}% retained variance. Below this level, test more components, a richer surface grid, or a different smoother before changing VAR.</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border/70"><CardTitle className="text-base">2. Does VAR beat doing nothing?</CardTitle></CardHeader>
          <CardContent className="space-y-4 pt-5">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">FPCA–VAR RMSE</p><p className="mt-2 font-mono font-semibold">{metric(data.model_rmse)}</p></div>
              <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">No-change RMSE</p><p className="mt-2 font-mono font-semibold">{metric(data.baseline_rmse)}</p></div>
              <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Improvement</p><p className="mt-2 font-mono font-semibold">{metric(data.improvement_over_baseline_percent, "%")}</p></div>
              <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Direction</p><p className="mt-2 font-mono font-semibold">{metric(data.directional_accuracy_percent, "%")}</p></div>
            </div>
            <div className="flex gap-2 text-sm">
              {varBeatsBaseline ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />}
              <p className="leading-5 text-muted-foreground">Decision band: at least {data.thresholds.minimum_rmse_improvement_percent}% lower RMSE than no-change and at least {data.thresholds.minimum_directional_accuracy_percent}% directional accuracy. If FPCA is healthy but this fails after {data.evidence_target} forecasts, change the VAR dynamics.</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="border-b border-border/70">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="text-base">Historical option-surface walk-forward test</CardTitle>
            <Badge variant="outline">{historical.verdict}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-5 pt-5">
          <p className="text-sm leading-6 text-muted-foreground">{historical.verdict_detail}</p>
          {historical.available ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Out-of-sample forecasts</p><p className="mt-2 font-mono text-xl font-semibold">{historical.observations}</p><p className="mt-1 text-[10px] text-muted-foreground">{historical.symbols} stocks · {historical.target_sessions} sessions</p></div>
                <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">FPCA–VAR RMSE</p><p className="mt-2 font-mono text-xl font-semibold">{metric(historical.model_rmse)}</p></div>
                <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">No-change RMSE</p><p className="mt-2 font-mono text-xl font-semibold">{metric(historical.baseline_rmse)}</p></div>
                <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">RMSE improvement</p><p className="mt-2 font-mono text-xl font-semibold">{metric(historical.improvement_over_baseline_percent, "%")}</p><p className="mt-1 text-[10px] text-muted-foreground">95% CI {metric(historical.improvement_confidence_interval_95?.[0], "%")} to {metric(historical.improvement_confidence_interval_95?.[1], "%")}</p></div>
                <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Forecast win rate</p><p className="mt-2 font-mono text-xl font-semibold">{metric(historical.model_win_rate_percent, "%")}</p></div>
                <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Direction accuracy</p><p className="mt-2 font-mono text-xl font-semibold">{metric(historical.directional_accuracy_percent, "%")}</p><p className="mt-1 text-[10px] text-muted-foreground">{historical.meaningful_directional_cells} grid-cell moves</p></div>
                <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Variance retained</p><p className="mt-2 font-mono text-xl font-semibold">{metric(historical.average_explained_variance_percent, "%")}</p></div>
                <div className="rounded-md bg-muted/30 p-3"><p className="terminal-label">Bootstrap P(model wins)</p><p className="mt-2 font-mono text-xl font-semibold">{metric(historical.bootstrap_probability_model_beats_baseline_percent, "%")}</p></div>
              </div>
              <div className="max-h-[360px] overflow-auto rounded-md border border-border/70">
                <table className="w-full min-w-[760px] text-left text-[11px]">
                  <thead className="sticky top-0 bg-muted/95 text-muted-foreground backdrop-blur">
                    <tr>{["Stock", "Tests", "Model RMSE", "No-change RMSE", "Improvement", "Win rate", "Direction"].map((item) => <th key={item} className="px-3 py-2 font-medium">{item}</th>)}</tr>
                  </thead>
                  <tbody>
                    {(historical.per_symbol ?? []).map((item) => (
                      <tr key={item.ticker} className="border-t border-border/60">
                        <td className="px-3 py-2 font-mono font-semibold">{item.ticker}</td>
                        <td className="px-3 py-2 font-mono">{item.observations}</td>
                        <td className="px-3 py-2 font-mono">{metric(item.model_rmse)}</td>
                        <td className="px-3 py-2 font-mono">{metric(item.baseline_rmse)}</td>
                        <td className="px-3 py-2 font-mono">{metric(item.improvement_over_baseline_percent, "%")}</td>
                        <td className="px-3 py-2 font-mono">{metric(item.model_win_rate_percent, "%")}</td>
                        <td className="px-3 py-2 font-mono">{metric(item.directional_accuracy_percent, "%")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-[10px] leading-4 text-muted-foreground">
                {historical.methodology} Data: {historical.source}. {historical.excluded_for_gaps} candidate forecasts were excluded because their history contained gaps longer than four calendar days. {historical.limitation}
              </p>
            </>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-border/70"><CardTitle className="text-base">Forecast audit trail</CardTitle></CardHeader>
        <CardContent className="pt-5">
          {!data.records.length ? (
            <div className="rounded-md border border-dashed border-border px-5 py-10 text-center">
              <p className="text-sm font-medium">No eligible forward forecasts recorded yet</p>
              <p className="mt-1 text-xs text-muted-foreground">The collector waits for a fresh official surface and refuses to backdate a forecast after the target session opens.</p>
            </div>
          ) : (
            <div className="max-h-[560px] overflow-auto rounded-md border border-border/70">
              <table className="w-full min-w-[1050px] text-left text-[11px]">
                <thead className="sticky top-0 bg-muted/95 text-muted-foreground backdrop-blur">
                  <tr>{["Stock", "Generated", "Target", "State", "PCs", "Variance", "Reconstruction", "Training vs baseline", "Live model RMSE", "Live baseline RMSE", "Live improvement", "Direction"].map((item) => <th key={item} className="px-3 py-2 font-medium">{item}</th>)}</tr>
                </thead>
                <tbody>
                  {data.records.map((item) => (
                    <tr key={item.id} className="border-t border-border/60">
                      <td className="px-3 py-2 font-mono font-semibold">{item.ticker}</td>
                      <td className="px-3 py-2">{dateTime(item.generated_at)}</td>
                      <td className="px-3 py-2 font-mono">{item.target_date}</td>
                      <td className="px-3 py-2"><Badge variant="outline">{item.status}</Badge></td>
                      <td className="px-3 py-2 font-mono">{item.component_count}</td>
                      <td className="px-3 py-2 font-mono">{metric(item.explained_variance_percent, "%")}</td>
                      <td className="px-3 py-2 font-mono">{metric(item.reconstruction_rmse)}</td>
                      <td className="px-3 py-2 font-mono">{metric(item.validation_improvement_percent, "%")}</td>
                      <td className="px-3 py-2 font-mono">{metric(item.model_rmse)}</td>
                      <td className="px-3 py-2 font-mono">{metric(item.baseline_rmse)}</td>
                      <td className="px-3 py-2 font-mono">{metric(item.improvement_over_baseline_percent, "%")}</td>
                      <td className="px-3 py-2 font-mono">{metric(item.directional_accuracy_percent, "%")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-3 text-[10px] leading-4 text-muted-foreground">The no-change baseline predicts that the next session’s entire IV surface equals the latest observed surface. Internal expanding-window metrics are shown for context but do not count toward the 100 live forward observations.</p>
        </CardContent>
      </Card>
    </div>
  );
}
