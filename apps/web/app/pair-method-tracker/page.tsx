import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PairLabPaperTracker } from "@/components/pair-lab-paper-tracker";

export const metadata: Metadata = {
  title: "Paper method P&L tracker",
  description: "Development-only P&L tracking for strict dual-test pair observations.",
  robots: { index: false, follow: false },
};

export default function PairMethodTrackerPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <PairLabPaperTracker />;
}
