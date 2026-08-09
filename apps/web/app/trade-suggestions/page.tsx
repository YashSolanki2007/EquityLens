import type { Metadata } from "next";
import { headers } from "next/headers";

import { TradeSuggestionsView } from "@/components/trade-suggestions-view";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host");
  const protocol = requestHeaders.get("x-forwarded-proto") ?? "http";
  const image = host
    ? `${protocol}://${host}/trade-suggestions-og.png`
    : "/trade-suggestions-og.png";
  const title = "Trade suggestions";
  const description =
    "Statistically screened NSE F&O pair-trade ideas with visual relationship and spread diagnostics.";

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      images: [{ url: image, width: 1733, height: 908, alt: title }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [image],
    },
  };
}

export default function TradeSuggestionsPage() {
  return <TradeSuggestionsView />;
}
