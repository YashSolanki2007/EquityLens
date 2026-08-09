import type { Metadata } from "next";

import { TradeTrackerView } from "@/components/trade-tracker-view";

export const metadata: Metadata = {
  title: "Trade tracker",
  description: "Development tracker for options paper trades.",
};

export default function TradeTrackerPage() {
  return <TradeTrackerView />;
}
