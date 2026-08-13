import type { Metadata } from "next";

import { PairPortfolioView } from "@/components/pair-portfolio-view";

export const metadata: Metadata = {
  title: "Pair portfolio",
  description:
    "Construct and track a low-overlap paper portfolio from statistically screened NSE pair trades.",
};

export default function PairPortfolioPage() {
  return <PairPortfolioView />;
}
