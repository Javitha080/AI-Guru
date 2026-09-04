'use client';

import React, { useRef } from 'react';

/**
 * Apple-Grade Liquid Glass Card
 * Features:
 * - 28px blur with 190% saturation boost (vibrant chromatic underlying colors)
 * - 1px top specular key-light bevel (inset highlight)
 * - Translucent perimeter lens rim
 * - Dynamic cursor-tracking glare spotlight (visionOS hover reflection)
 */
export function AppleGlassCard({
  children,
  className = '',
  enableGlare = true,
  onClick,
}: {
  children: React.ReactNode;
  className?: string;
  enableGlare?: boolean;
  onClick?: () => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!enableGlare) return;
    const el = cardRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    el.style.setProperty('--glare-x', `${x}px`);
    el.style.setProperty('--glare-y', `${y}px`);
  };

  return (
    <div
      ref={cardRef}
      onPointerMove={handlePointerMove}
      onClick={onClick}
      className={`group relative overflow-hidden rounded-3xl border border-white/10 border-t-white/25 bg-[#0C1017]/70 backdrop-blur-2xl saturate-[190%] contrast-[105%] transition-all duration-300 hover:border-white/20 hover:border-t-white/40 ${className}`}
      style={{
        boxShadow:
          '0 12px 36px -4px rgba(0, 0, 0, 0.50), 0 4px 12px -2px rgba(0, 0, 0, 0.30), inset 0 1px 1px 0 rgba(255, 255, 255, 0.22), inset 0 -1px 1px 0 rgba(0, 0, 0, 0.25)',
      }}
    >
      {/* 1. Dynamic Cursor Glare (visionOS reflection) */}
      {enableGlare && (
        <div
          className="pointer-events-none absolute -inset-px opacity-0 transition-opacity duration-300 group-hover:opacity-100"
          style={{
            background:
              'radial-gradient(450px circle at var(--glare-x, 0px) var(--glare-y, 0px), rgba(255, 255, 255, 0.12), rgba(224, 109, 68, 0.05) 40%, transparent 80%)',
          }}
          aria-hidden="true"
        />
      )}

      {/* 2. Top Specular Bevel Line */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-[1px] bg-gradient-to-r from-transparent via-white/30 to-transparent"
        aria-hidden="true"
      />

      {/* 3. Card Content */}
      <div className="relative z-10 p-6">{children}</div>
    </div>
  );
}

/**
 * Apple-Grade Liquid Glass Floating Dock / Bar
 */
export function AppleGlassDock({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`apple-glass-ultra-thin inline-flex items-center gap-2 rounded-full px-4 py-2 ${className}`}
    >
      {children}
    </div>
  );
}

/**
 * Apple-Grade Liquid Glass Pill Action Button
 */
export function AppleGlassPillButton({
  children,
  onClick,
  className = '',
}: {
  children: React.ReactNode;
  onClick?: () => void;
  className?: string;
}) {
  return (
    <button onClick={onClick} className={`apple-glass-pill ${className}`}>
      {children}
    </button>
  );
}
