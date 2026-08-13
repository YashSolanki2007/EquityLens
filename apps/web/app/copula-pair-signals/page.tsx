import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CopulaPairSignalsView } from "@/components/copula-pair-signals-view";

export const metadata: Metadata = {
  title: "Copula pair signals",
  description: "Development-only copula entry and exit signals for strict pair candidates.",
  robots: { index: false, follow: false },
};

export default function CopulaPairSignalsPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <CopulaPairSignalsView />;
}
