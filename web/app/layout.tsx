import type { Metadata } from "next";
import { Urbanist, Onest } from "next/font/google";
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

// Urbanist (geometric display) for clean modern headers and accents
const fontDisplay = Urbanist({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-display",
  weight: ["300", "400", "500", "600", "700", "800"],
});

// Onest (legible body) for readable UI elements and content
const fontBody = Onest({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-body",
  weight: ["300", "400", "500", "600", "700"],
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
