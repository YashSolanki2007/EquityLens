import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PairMethodLabView } from "@/components/pair-method-lab-view";

export const metadata: Metadata = {
  title: "Dynamic pairs-method lab",
  description: "Development-only comparison of alternative cointegration pair-selection methods.",
  robots: { index: false, follow: false },
};

export default function PairMethodLabPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <PairMethodLabView />;
}
