import type { Metadata } from "next";

import { AlternativeSignalView } from "@/components/alternative-signal-view";
import report from "@/data/alternative-signal.json";

export const metadata: Metadata = {
  title: "Alternative signal",
  description: "Frozen 21/63 EMA regime backtest for the Indian market.",
  robots: { index: false, follow: false },
};

export default function AlternativeSignalPage() {
  return <AlternativeSignalView report={report} />;
}
