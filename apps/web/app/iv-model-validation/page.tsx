import type { Metadata } from "next";

import { IVModelValidationView } from "@/components/iv-model-validation-view";

export const metadata: Metadata = {
  title: "IV model validation",
  description: "Genuine next-session walk-forward validation for the FPCA-VAR IV model.",
  robots: { index: false, follow: false },
};

export default function IVModelValidationPage() {
  return <IVModelValidationView />;
}
