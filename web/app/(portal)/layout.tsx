import React from "react";

/**
 * Standalone Parent Portal chrome — deliberately OUTSIDE the (workspace)
 * group so students never see it and parents never see student UI
 * (no sidebar, no FloatingGuru, no FirstRunGate wizard popping over).
 * Ember Glass canvas: OLED black / porcelain white with drifting embers.
 */
export default function PortalLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="min-h-screen bg-[var(--background)] text-[var(--foreground)] relative">
      {/* Drifting ember backdrop */}
      <div className="aurora-stage" aria-hidden>
        <div
          className="aurora-blob"
          style={
            {
              "--x": "14%",
              "--y": "-6%",
              "--size": "640px",
              "--blob-opacity": "0.5",
              "--drift-dur": "34s",
            } as React.CSSProperties
          }
        />
        <div
          className="aurora-blob"
          style={
            {
              "--x": "92%",
              "--y": "30%",
              "--size": "520px",
              "--blob-color": "var(--amber-glow)",
              "--blob-opacity": "0.4",
              "--drift-dur": "42s",
              "--drift-delay": "-12s",
            } as React.CSSProperties
          }
        />
        <div
          className="aurora-blob"
          style={
            {
              "--x": "30%",
              "--y": "110%",
              "--size": "560px",
              "--blob-opacity": "0.35",
              "--drift-dur": "38s",
              "--drift-delay": "-20s",
            } as React.CSSProperties
          }
        />
      </div>
      {/* Global CSS locks html/body with overflow:hidden, so this group must own
          its scroll container — without it the PIN lock, wizard and long tabs
          are clipped below the fold with no way to reach them. */}
      <div className="h-screen overflow-y-auto [scrollbar-gutter:stable] relative z-10">
        {children}
      </div>
    </div>
  );
}
