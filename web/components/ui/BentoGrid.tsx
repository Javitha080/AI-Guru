"use client";

import { type ReactNode } from "react";

interface BentoGridProps {
  children: ReactNode;
  className?: string;
}

export function BentoGrid({ children, className = "" }: BentoGridProps) {
  return (
    <div className={`grid grid-cols-1 md:grid-cols-6 lg:grid-cols-12 gap-4 ${className}`}>
      {children}
    </div>
  );
}

interface BentoCardProps {
  children: ReactNode;
  className?: string;
  /** Glass surface tier: 1 = base, 2 = elevated with sheen */
  tier?: 1 | 2;
}

export function BentoCard({ children, className = "", tier = 1 }: BentoCardProps) {
  const surfaceClass = tier === 2 ? "surface-glass-elevated liquid-sheen" : "surface-glass-base";
  return (
    <div className={`${surfaceClass} p-5 ${className}`}>
      {children}
    </div>
  );
}
