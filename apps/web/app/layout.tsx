import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { SiteHeader } from "@/components/site-header";
import { Providers } from "./providers";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host");
  const protocol = requestHeaders.get("x-forwarded-proto") ?? "http";
  const metadataBase = host ? new URL(`${protocol}://${host}`) : undefined;

  return {
    metadataBase,
    title: {
      default: "EquityLens",
      template: "%s · EquityLens",
    },
    description:
      "Institutional-grade Indian equity research across company fundamentals, primary filings, market events, and quantitative signals.",
    openGraph: {
      title: "EquityLens · India Equity Intelligence",
      description: "Move from market question to defensible evidence.",
      images: [{ url: "/og.png", width: 1734, height: 907, alt: "EquityLens India equity intelligence workspace" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "EquityLens · India Equity Intelligence",
      description: "Move from market question to defensible evidence.",
      images: ["/og.png"],
    },
  };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f6f2" },
    { media: "(prefers-color-scheme: dark)", color: "#171814" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var t=localStorage.getItem('equitylens-theme');var d=t==='dark';document.documentElement.classList.toggle('dark',d);document.documentElement.style.colorScheme=d?'dark':'light'}catch(e){}",
          }}
        />
      </head>
      <body className="flex min-h-full flex-col">
        <Providers>
          <SiteHeader />
          <main className="flex-1 pb-5 pt-[72px] lg:ml-[228px]">
            <div className="page-shell">{children}</div>
          </main>
          <footer className="mt-4 border-t border-border bg-card lg:ml-[228px]">
            <div className="page-shell flex flex-col gap-2 py-4 font-mono text-[8px] uppercase tracking-[0.08em] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
              <span>NSE filings · Delayed market data · Source-linked news</span>
              <span>
                Research and information retrieval only · Not investment advice
              </span>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
