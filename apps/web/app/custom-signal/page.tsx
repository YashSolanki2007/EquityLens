import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CustomSignalView } from "@/components/custom-signal-view";
import { EnsembleSignalExperiment } from "@/components/ensemble-signal-experiment";
import report from "@/data/custom-signal.json";
import ensembleReport from "@/data/ensemble-signal.json";
import { FEATURE_AVAILABILITY } from "@/lib/feature-availability";

export const metadata: Metadata = {
  title: "Custom signal",
  description: "Walk-forward conditional tail-probability signal for the NIFTY 50.",
  robots: { index: false, follow: false },
};

export default function CustomSignalPage() {
  if (!FEATURE_AVAILABILITY.customSignal) notFound();

  return (
    <>
      <CustomSignalView report={report} />
      <EnsembleSignalExperiment report={ensembleReport} />
    </>
  );
}
