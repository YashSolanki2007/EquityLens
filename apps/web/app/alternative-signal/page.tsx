import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AlternativeSignalView } from "@/components/alternative-signal-view";
import report from "@/data/alternative-signal.json";
import { FEATURE_AVAILABILITY } from "@/lib/feature-availability";

export const metadata: Metadata = {
  title: "Alternative signal",
  description: "Frozen 21/63 EMA regime backtest for the Indian market.",
  robots: { index: false, follow: false },
};

export default function AlternativeSignalPage() {
  if (!FEATURE_AVAILABILITY.alternativeSignal) notFound();

  return <AlternativeSignalView report={report} />;
}
