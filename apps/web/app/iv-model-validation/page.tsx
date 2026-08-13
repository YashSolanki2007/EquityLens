import type { Metadata } from "next";

import { IVModelValidationView } from "@/components/iv-model-validation-view";

export const metadata: Metadata = {
  title: "IV surface model validation",
  description: "Causal next-session validation for FPCA-VAR and path-dependent SSVI volatility-surface models.",
  robots: { index: false, follow: false },
};

export default function IVModelValidationPage() {
  return <IVModelValidationView />;
}
