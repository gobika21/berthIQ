import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import { Header } from "@/components/Header";
import { LocaleProvider } from "@/components/LocaleProvider";
import { PortBackground } from "@/components/PortBackground";
import { SkipLink } from "@/components/SkipLink";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

// Cloudflare Web Analytics: cookie-free visitor counts. The token is a public site ID,
// not a secret. Only loaded in production builds, so local runs don't count as visits.
const CF_ANALYTICS_TOKEN = "534e3f73fb5b47d3b20ebc3634e515c6";

export const metadata: Metadata = {
  title: "BerthIQ — Port Traffic Reports",
  description: "See which major ports are backed up right now, and get plain-English advice on what to do about it.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr" className={inter.variable} suppressHydrationWarning>
      <body className="min-h-screen bg-canvas font-sans text-ink antialiased">
        <PortBackground />
        <LocaleProvider>
          <SkipLink />
          <Header />
          <main id="main-content" tabIndex={-1} className="focus:outline-none">
            {children}
          </main>
        </LocaleProvider>
        {process.env.NODE_ENV === "production" && (
          <Script
            src="https://static.cloudflareinsights.com/beacon.min.js"
            data-cf-beacon={JSON.stringify({ token: CF_ANALYTICS_TOKEN })}
            strategy="afterInteractive"
          />
        )}
      </body>
    </html>
  );
}
