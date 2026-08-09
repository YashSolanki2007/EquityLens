import type { Metadata } from "next";
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

export const metadata: Metadata = {
  title: {
    default: "EquityLens",
    template: "%s · EquityLens",
  },
  description:
    "Source-grounded semantic equity research across business exposure, financial performance, and current market events.",
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
          <main className="flex-1 pb-8 pt-28 md:ml-56 md:pt-[76px]">
            <div className="page-shell">{children}</div>
          </main>
          <footer className="mt-8 border-t border-border bg-card md:ml-56">
            <div className="page-shell flex flex-col gap-2 py-5 text-[11px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
              <span>NSE filings · delayed market data · source-linked news</span>
              <span>
                Research and information retrieval only — not investment advice.
              </span>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
