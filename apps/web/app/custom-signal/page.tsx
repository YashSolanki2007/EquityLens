import type { Metadata } from "next";

import { CustomSignalView } from "@/components/custom-signal-view";
import report from "@/data/custom-signal.json";

export const metadata: Metadata = {
  title: "Custom signal",
  description: "Walk-forward conditional tail-probability signal for the NIFTY 50.",
  robots: { index: false, follow: false },
};

export default function CustomSignalPage() {
  return <CustomSignalView report={report} />;
}
