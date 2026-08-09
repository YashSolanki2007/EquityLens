import type { Metadata } from "next";

import { BetaR2BacktestView } from "@/components/beta-r2-backtest-view";
import report from "@/data/beta-r2-backtest.json";

export const metadata: Metadata = {
  title: "Beta × R² backtest",
  description: "A reproducible NIFTY 50 price-trend backtest for the beta × R² momentum score.",
  robots: { index: false, follow: false },
};

export default function BetaR2BacktestPage() {
  return <BetaR2BacktestView report={report} />;
}
