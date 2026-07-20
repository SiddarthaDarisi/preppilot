import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import Topbar from "@/components/Topbar";
import { ThemeProvider } from "@/lib/theme";
import { HealthProvider } from "@/lib/health";

// Self-hosted at build time (next/font downloads + inlines the woff2 into the
// static export — no runtime CDN request, which the project forbids).
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const jbMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jbmono", display: "swap" });

export const metadata: Metadata = {
  title: "PrepPilot — Mock Interview",
  description: "AI mock-interview tutor with live coaching.",
};

// Sets data-theme on <html> before first paint. Light is the app default
// regardless of OS preference — the user explicitly prefers the light look
// ("white mode is good, dark mode is meh"); dark stays one toggle away.
// Not a CDN script (that's disallowed) — inline, same-document snippet.
const THEME_INIT_SCRIPT = `
(function () {
  try {
    document.documentElement.dataset.theme = "light";
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} ${jbMono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <ThemeProvider>
          <HealthProvider>
            <div className="container">
              <Topbar />
              {children}
            </div>
          </HealthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
