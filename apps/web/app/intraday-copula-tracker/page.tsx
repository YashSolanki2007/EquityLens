import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { IntradayCopulaTrackerView } from "@/components/intraday-copula-tracker-view";

export const metadata: Metadata = {
  title: "Intraday copula tracker",
  description: "Development-only five-minute cash-equity copula pair tracker.",
  robots: { index: false, follow: false },
};

export default function IntradayCopulaTrackerPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <IntradayCopulaTrackerView />;
}
