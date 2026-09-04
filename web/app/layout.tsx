import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import "./motion-tokens.css";
import "./glass-surfaces.css";
import "./liquid-glass.css";
import ThemeScript from "@/components/ThemeScript";
import ToastViewport from "@/components/common/ToastViewport";
import CommandPalette from "@/components/common/CommandPalette";
import LiquidGlassDefs from "@/components/ui/LiquidGlassDefs";
import { AppShellProvider } from "@/context/AppShellContext";
import { I18nClientBridge } from "@/i18n/I18nClientBridge";

// Urbanist (geometric display) for clean modern headers and accents.
// Self-hosted via @fontsource-variable so builds work with no network egress
// (next/font/google requires fonts.googleapis.com at build time, which breaks
// the offline/local-first story and offline CI).
const fontDisplay = localFont({
  src: "../node_modules/@fontsource-variable/urbanist/files/urbanist-latin-wght-normal.woff2",
  display: "swap",
  variable: "--font-display",
  weight: "100 900",
});

// Onest (legible body) for readable UI elements and content.
const fontBody = localFont({
  src: "../node_modules/@fontsource-variable/onest/files/onest-latin-wght-normal.woff2",
  display: "swap",
  variable: "--font-body",
  weight: "100 900",
});

export const metadata: Metadata = {
  title: "AI Guru",
  description: "Agent-native intelligent learning companion — AI Guru",
  icons: {
    icon: [
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
    ],
    apple: "/apple-touch-icon.png",
  },
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
      data-scroll-behavior="smooth"
      className={`${fontDisplay.variable} ${fontBody.variable}`}
    >
      <head>
        <ThemeScript />
      </head>
      <body
        className="font-body bg-[var(--background)] text-[var(--foreground)]"
        suppressHydrationWarning
      >
        {/* SVG filter defs for the liquid-glass tier. Renders nothing. */}
        <LiquidGlassDefs />
        <AppShellProvider>
          <I18nClientBridge>{children}</I18nClientBridge>
          <ToastViewport />
          <CommandPalette />
        </AppShellProvider>
      </body>
    </html>
  );
}
