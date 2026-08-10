import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { RobustSignalView } from "@/components/robust-signal-view";
import report from "@/data/robust-signal.json";
import { FEATURE_AVAILABILITY } from "@/lib/feature-availability";

export const metadata: Metadata = {
  title: "Robust signal audit",
  description: "Selection-aware audit of a risk-budgeted NIFTY 50 trend experiment.",
  robots: { index: false, follow: false },
};

export default function RobustSignalPage() {
  if (!FEATURE_AVAILABILITY.robustSignal) notFound();

  return <RobustSignalView report={report} />;
}
